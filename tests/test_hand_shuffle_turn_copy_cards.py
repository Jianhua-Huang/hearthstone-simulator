"""Real hand-arrow and expiring end-copy consumers, without a second executor."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.hand_shuffle_turn_copy_cards import OOZE, WRIGGLER, load_batch
from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, Zone
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, Destroy, Draw, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, DamageKind, EndTurnSpec, TargetMode, TargetSpec, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import check_face

P = 'fixture.hand_shuffle_turn_copy.'
PLAIN, SPELL, WEAPON, LOCATION, DRAW, OLD_COST, BOOST, KILL, SILENCE, BOUNCE, WATCH, DRAW_WATCH, EARLY = (
    P+x for x in ('plain', 'spell', 'weapon', 'location', 'draw', 'old_cost', 'boost', 'kill', 'silence', 'bounce',
        'watch', 'draw_watch', 'early'))
COIN = 'GAME_005'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent fixture registries required')
    r = build_registry()
    r.register_behavior(P+'noop', lambda c: ())
    def fail(c):
        raise ResolutionError('Explicit physical shuffle/copy choice failure')
    r.register_behavior(P+'fail', fail)
    def wait(c):
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(P+'wait', wait)
    def early(c):
        ids = [i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == OOZE]
        return (Buff(ids[0], 2, 3, c.source_id), *wait(c)) if ids else ()
    r.register_behavior(P+'early', early)
    bodies = {
        SPELL: lambda c: (), DRAW: lambda c: (Draw(c.player_id, 1),),
        OLD_COST: lambda c: (ModifyCost(c.target_id, CostSpec(delta=-2), c.source_id),),
        BOOST: lambda c: (Buff(c.target_id, 2, 3, c.source_id), GrantKeyword(c.target_id, Keyword.TAUNT, c.source_id),
            Damage(c.target_id, 1, c.source_id, DamageKind.SPELL)),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        SILENCE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        fields = {}
        if cid in (BOOST, KILL, SILENCE, BOUNCE):
            fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid == OLD_COST:
            fields['targeting'] = TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly')
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=4 if cid == SPELL else 0,
            on_play=cid, metadata=META, **fields))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, cost=5, attack=4, health=6, metadata=META))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, cost=4, attack=2, durability=2, metadata=META))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, cost=4, durability=2, on_use=P+'noop', metadata=META))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, attack=0, health=5,
        triggers=(TriggerSpec('card_shuffled', P+'wait'),), metadata=META))
    r.register_card(CardDefinition(DRAW_WATCH, DRAW_WATCH, CardType.MINION, attack=0, health=5,
        triggers=(TriggerSpec('card_shuffled', DRAW),), metadata=META))
    r.register_card(CardDefinition(EARLY, EARLY, CardType.MINION, attack=0, health=5,
        triggers=(TriggerSpec('turn_ended', P+'early', EndTurnSpec()),), metadata=META))
    return r


class HandShuffleTurnCopyTests(unittest.TestCase):
    def game(self, hand, board=(), enemy=(), deck=(), mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=mana, max_mana=10), PlayerSetup('HERO_01', board=enemy, deck=(COIN,)*8,
                mana=10, max_mana=10)), seed=4), fixture())

    def first(self, g, cid, zone='hand', player=1):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None, position=None):
        eid = self.first(g, cid)
        g.apply(PlayCard(1, eid, target_id=target, position=position))
        return eid

    def oozes(self, g):
        return [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == OOZE]

    def quote(self, g, eid):
        # Stored-deck prices are internal assertions; the player API correctly
        # limits quotes to the active hand and installed Hero powers.
        return quote_cost(g.state, g.registry, g.state.entities[eid])

    def portable(self, g):
        saved = g.snapshot(); reader = fixture('reader')
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), reader).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe())+json.dumps(g.player_events(player))
            for field in ('"rng_state"', '"resolution_frame"', '"deck_shuffle_history"', '"end_turn_batches"'):
                self.assertNotIn(field, public)

    def test_complete_two_roots_and_four_primary_faces_keep_actual_stats_and_tribes(self):
        data = load_batch()
        self.assertEqual(len(data['cards']), 2); self.assertEqual(len(data['official_observations']), 4)
        by_id = {row['record']['id']: row['record'] for row in data['cards']}
        for observation in data['official_observations']:
            face = observation['face']
            raw = next(x for x in by_id.values() if x['dbf_id'] == face['id'])
            check_face(raw, face, observation['locale'])
        self.assertEqual((fixture().card(WRIGGLER).cost, fixture().card(WRIGGLER).attack, fixture().card(WRIGGLER).health), (1, 3, 3))
        self.assertEqual((fixture().card(OOZE).cost, fixture().card(OOZE).attack, fixture().card(OOZE).health), (4, 3, 2))
        self.assertIn('beast', fixture().card(WRIGGLER).metadata.tribes)
        self.assertEqual(fixture().card(WRIGGLER).targeting.mode, TargetMode.IF_AVAILABLE)
        self.assertEqual(len(fixture().card(WRIGGLER).targeting.kinds), 5)

    def test_hand_arrow_shuffles_original_minion_spell_weapon_and_location(self):
        for cid in (PLAIN, SPELL, WEAPON, LOCATION):
            with self.subTest(cid=cid):
                g = self.game((WRIGGLER, cid)); target = self.first(g, cid); old = g.state.entities[target]
                self.play(g, WRIGGLER, target)
                entity = g.state.entities[target]
                self.assertEqual((entity.zone, entity.zone_epoch), (Zone.DECK, old.zone_epoch+1))
                self.assertEqual(g.state.players[1].deck, [target])
                self.assertEqual(self.quote(g, target).amount, fixture().card(cid).cost-1)
                self.assertEqual(len(g.state.deck_shuffle_history), 1)
                self.assertEqual(g.state.players[1].mana, 9)

    def test_duplicate_faces_are_distinct_physical_targets(self):
        g = self.game((WRIGGLER, PLAIN, PLAIN)); first, second = g.state.players[1].hand[1:]
        self.play(g, WRIGGLER, second)
        self.assertEqual(g.state.players[1].hand, [first])
        self.assertEqual((self.quote(g, first).amount, self.quote(g, second).amount), (5, 4))

    def test_empty_remaining_hand_has_no_target_choice_or_shuffle_and_does_not_draw_randomness(self):
        g = self.game((WRIGGLER,)); rng = g.snapshot()['rng_state']; self.play(g, WRIGGLER)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.deck_shuffle_history)
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_missing_enemy_or_board_target_rejects_before_payment(self):
        g = self.game((WRIGGLER, PLAIN), board=(PLAIN,), enemy=(PLAIN,)); saved = g.snapshot()
        for target in (None, g.state.players[1].board[0], g.state.players[2].board[0]):
            with self.subTest(target=target), self.assertRaises(IllegalAction):
                self.play(g, WRIGGLER, target)
            self.assertEqual(g.snapshot(), saved)

    def test_shuffle_resets_old_cost_then_new_discount_survives_redraw_and_actual_payment(self):
        g = self.game((OLD_COST, WRIGGLER, PLAIN, DRAW)); target = self.first(g, PLAIN)
        self.play(g, OLD_COST, target); self.assertEqual(self.quote(g, target).amount, 3)
        self.play(g, WRIGGLER, target); self.assertEqual(self.quote(g, target).amount, 4)
        self.play(g, DRAW); self.assertEqual(g.state.players[1].hand, [target])
        self.play(g, PLAIN)
        self.assertEqual(g.state.players[1].mana, 5); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.portable(g)

    def test_zero_cost_stays_zero_and_shuffle_does_not_copy_the_card(self):
        g = self.game((WRIGGLER, COIN)); target = self.first(g, COIN)
        self.play(g, WRIGGLER, target)
        self.assertEqual(self.quote(g, target).amount, 0)
        self.assertEqual(len([e for e in g.state.entities.values() if e.card_id == COIN]), 9)

    def test_original_shuffled_card_drawn_by_reaction_still_gets_its_discount(self):
        g = self.game((WRIGGLER, PLAIN), board=(DRAW_WATCH,)); target = self.first(g, PLAIN)
        self.play(g, WRIGGLER, target)
        self.assertEqual((g.state.entities[target].zone, self.quote(g, target).amount), (Zone.HAND, 4))

    def test_shuffle_reaction_wait_preserves_original_target_and_late_failure_boundary(self):
        g = self.game((WRIGGLER, PLAIN), board=(WATCH,)); target = self.first(g, PLAIN)
        self.play(g, WRIGGLER, target); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.quote(g, target).amount, 5); self.portable(g)
        saved = g.snapshot(); choice = g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError, 'Explicit physical'):
            g.apply(SelectChoice(1, choice.id, ('fail',)))
        self.assertEqual(g.snapshot(), saved)
        g.apply(SelectChoice(1, choice.id, ('continue',)))
        self.assertEqual(self.quote(g, target).amount, 4); self.portable(g)

    def test_ooze_waits_for_end_and_copies_current_buff_keywords_and_damage(self):
        g = self.game((OOZE, BOOST)); source = self.play(g, OOZE)
        self.assertEqual(len(self.oozes(g)), 1); self.play(g, BOOST, source)
        g.apply(EndTurn(1)); bodies = self.oozes(g)
        self.assertEqual([(e.attack, e.health, e.damage, e.max_health) for e in bodies], [(5, 4, 1, 5), (5, 4, 1, 5)])
        self.assertTrue(all(Keyword.TAUNT in e.keywords for e in bodies))
        self.assertFalse(any(a.kind == 'trigger' and a.behavior_id.endswith('.copy') for e in bodies for a in e.abilities))
        self.portable(g)

    def test_copy_is_inserted_next_to_current_source_and_does_not_play_battlecry(self):
        g = self.game((OOZE,), board=(PLAIN, PLAIN)); source = self.play(g, OOZE, position=1)
        g.apply(EndTurn(1)); board = g.state.players[1].board
        self.assertEqual([g.state.entities[i].card_id for i in board], [PLAIN, OOZE, OOZE, PLAIN])
        self.assertEqual(board[1], source)
        self.assertEqual(len([x for x in g.state.play_history if x.card_id == OOZE]), 1)

    def test_silenced_killed_or_returned_source_does_not_copy(self):
        for effect in (SILENCE, KILL, BOUNCE):
            with self.subTest(effect=effect):
                g = self.game((OOZE, effect)); source = self.play(g, OOZE)
                self.play(g, effect, source); g.apply(EndTurn(1))
                self.assertEqual(len(self.oozes(g)), 1 if effect == SILENCE else 0)

    def test_multiple_original_oozes_copy_once_each_and_expire_before_later_turns(self):
        g = self.game((OOZE, OOZE), deck=(COIN,)*8)
        self.play(g, OOZE); self.play(g, OOZE); g.apply(EndTurn(1))
        self.assertEqual(len(self.oozes(g)), 4)
        g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual(len(self.oozes(g)), 4)

    def test_full_board_failure_does_not_defer_copy_to_a_later_turn(self):
        g = self.game((OOZE, KILL), board=(PLAIN,)*6, deck=(COIN,)*8)
        self.play(g, OOZE); g.apply(EndTurn(1)); self.assertEqual(len(self.oozes(g)), 1)
        g.apply(EndTurn(2)); self.play(g, KILL, g.state.players[1].board[0]); g.apply(EndTurn(1))
        self.assertEqual(len(self.oozes(g)), 1)

    def test_earlier_end_subject_changes_current_copy_and_wait_restores_without_extra_copy(self):
        g = self.game((OOZE,), board=(EARLY,)); self.play(g, OOZE); g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.oozes(g)), 1)
        self.portable(g); saved = g.snapshot(); choice = g.state.pending_choice
        with self.assertRaisesRegex(ResolutionError, 'Explicit physical'):
            g.apply(SelectChoice(1, choice.id, ('fail',)))
        self.assertEqual(g.snapshot(), saved)
        g.apply(SelectChoice(1, choice.id, ('continue',)))
        self.assertEqual([(e.attack, e.health) for e in self.oozes(g)], [(5, 5), (5, 5)])
        self.portable(g)

    def test_illegal_mana_does_not_install_grant_shuffle_or_discount(self):
        for cid, mana in ((WRIGGLER, 0), (OOZE, 3)):
            with self.subTest(cid=cid):
                g = self.game((cid, PLAIN), mana=mana); saved = g.snapshot()
                with self.assertRaises(IllegalAction):
                    self.play(g, cid, self.first(g, PLAIN) if cid == WRIGGLER else None)
                self.assertEqual(g.snapshot(), saved)
