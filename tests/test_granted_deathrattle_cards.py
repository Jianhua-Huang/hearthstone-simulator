"""Real Steed grants keep ordinary physical attachments and complete summons."""
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.granted_deathrattle_cards import load_batch, PAYLOAD, STEED, STEGODON
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup,
                          Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest

YETI = 'CORE_CS2_182'
SQUIRE = 'CORE_EX1_008'


def registry(mode=None):
    result = build_registry()
    scripts = dict(kill=lambda c: (Destroy(c.target_id, c.source_id),),
        silence=lambda c: (Silence(c.target_id),), bounce=lambda c: (ReturnToHand(c.target_id),),
        copy=lambda c: (CopyMinion(c.target_id, c.player_id),),
        base_copy=lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),),
        steal=lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        trigger=lambda c: (TriggerDeathrattles(c.target_id, c.source_id),))
    for key, body in scripts.items():
        result.register_behavior('k35.'+key, body)
        result.register_card(CardDefinition('k35.'+key, key, CardType.SPELL, on_play='k35.'+key,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def watch(context):
        event = context.event
        if mode == 'fail':
            if event.kind != 'ability_granted' or dict(event.data).get('ability_kind') != 'deathrattle':
                return ()
            return (AddToHand(context.player_id, 'unknown.k35'),)
        if event.kind != 'minion_summoned' or context.state.entities[event.target_id].card_id != STEGODON:
            return ()
        return (RequestChoice(context.player_id, (ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('fail', 'Fail', (InvokeBehavior('k35.fail', context.source_id, context.player_id),))), context.source_id),)
    if mode:
        result.register_behavior('k35.fail', lambda c: (AddToHand(c.player_id, 'unknown.k35'),))
        result.register_behavior('k35.watch', watch)
        result.register_card(CardDefinition('k35.watch', 'Watcher', CardType.MINION, health=8,
            triggers=(TriggerSpec('ability_granted' if mode == 'fail' else 'minion_summoned', 'k35.watch'),)))
    return result


class GrantedDeathrattleCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.r = registry()
    def game(self, hand=(), board=(YETI,), enemy=(), mode=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*8, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', board=enemy, deck=(YETI,)*8)), seed=437), registry(mode) if mode else self.r)
    def play(self, game, cid, target=None):
        entity = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(1, entity, target, len(game.state.players[1].board)
                            if game.registry.card(cid).kind == CardType.MINION else None))
        return entity
    def board(self, game, player=1):
        return [game.state.entities[i].card_id for i in game.state.players[player].board]
    def grants(self, game, target):
        return [a for a in game.state.entities[target].abilities if a.kind == 'deathrattle' and a.behavior_id == PAYLOAD]
    def portable(self, game, mode=None):
        saved = json.loads(json.dumps(game.snapshot()))
        other = Game.from_snapshot(saved, registry(mode))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry(mode)).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.observe(player))+json.dumps(game.player_events(player))+json.dumps(game.for_player(player).legal_actions())
            for key in ('resolution_frame', 'deathrattle_history', 'deathrattle_batches', 'card_summon_history', 'rng_state'):
                self.assertNotIn('"'+key+'"', public)
        return other

    def test_complete_current_faces_and_explicit_cross_set_collectible_dependency(self):
        batch = load_batch()
        self.assertEqual(len(batch['cards']), 4)
        for row in batch['cards']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        source, dep = (next(r['record'] for r in batch['cards'] if r['record']['id'] == cid) for cid in (STEED, STEGODON))
        self.assertEqual(source['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], dep['dbf_id'])
        self.assertEqual(dep['dbf_id'], 41324)
        self.assertEqual((self.r.card(STEED).cost, self.r.card(STEED).metadata.deck_identity), (5, 'UNG_952'))
        card = self.r.card(STEGODON)
        self.assertEqual((card.cost, card.attack, card.health, card.keywords), (4, 2, 6, (Keyword.TAUNT,)))
        self.assertTrue(card.metadata.collectible)
        self.assertEqual(card.metadata.tribes, ('beast',))

    def test_paid_spell_grants_stats_taunt_and_deathrattle_then_complete_replacement_at_death_position(self):
        game = self.game((STEED, 'k35.kill'), (SQUIRE, YETI, SQUIRE))
        target = game.state.players[1].board[1]
        source = self.play(game, STEED, target)
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.max_health, game.state.players[1].mana), (6, 11, 35))
        self.assertIn(Keyword.TAUNT, entity.keywords)
        grant = self.grants(game, target)[0]
        self.assertEqual((grant.source_id, grant.deathrattle_grant_card_id, grant.origin), (source, STEED, 'granted'))
        self.play(game, 'k35.kill', target)
        self.assertEqual(self.board(game), [SQUIRE, STEGODON, SQUIRE])
        child = game.state.entities[game.state.players[1].board[1]]
        self.assertEqual((child.attack, child.health), (2, 6))
        self.assertIn(Keyword.TAUNT, child.keywords)
        self.assertFalse(self.grants(game, child.id))
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.portable(game)

    def test_enemy_recipient_death_summons_for_its_controller(self):
        game = self.game((STEED, 'k35.kill'), (), (YETI,))
        target = game.state.players[2].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.kill', target)
        self.assertEqual(self.board(game), [])
        self.assertEqual(self.board(game, 2), [STEGODON])

    def test_missing_target_and_hero_target_reject_before_payment_or_grants(self):
        game = self.game((STEED,))
        for target in (None, game.state.players[1].hero_id, game.state.players[2].hero_id):
            with self.subTest(target=target):
                before = game.snapshot()
                with self.assertRaises(IllegalAction): self.play(game, STEED, target)
                self.assertEqual(game.snapshot(), before)

    def test_repeated_real_casts_keep_two_independent_grants_without_buffing_the_summons(self):
        game = self.game((STEED, STEED, 'k35.kill'))
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, STEED, target)
        self.assertEqual((game.state.entities[target].attack, game.state.entities[target].max_health), (8, 17))
        grants = self.grants(game, target)
        self.assertEqual(len({a.id for a in grants}), 2)
        self.assertEqual(len({a.source_id for a in grants}), 2)
        self.assertEqual(game.state.players[1].mana, 30)
        self.play(game, 'k35.kill', target)
        self.assertEqual(self.board(game), [STEGODON, STEGODON])
        self.assertTrue(all((game.state.entities[i].attack, game.state.entities[i].health) == (2, 6)
                            for i in game.state.players[1].board))

    def test_silence_removes_both_grants_and_stats_without_later_summon(self):
        game = self.game((STEED, 'k35.silence', 'k35.kill'))
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.silence', target)
        self.assertEqual((game.state.entities[target].attack, game.state.entities[target].max_health), (4, 5))
        self.assertNotIn(Keyword.TAUNT, game.state.entities[target].keywords)
        self.assertFalse(self.grants(game, target))
        self.play(game, 'k35.kill', target); self.assertFalse(game.state.players[1].board)

    def test_bounce_keeps_physical_card_but_replay_has_no_old_attachment(self):
        game = self.game((STEED, 'k35.bounce', 'k35.kill'))
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.bounce', target)
        self.assertIn(target, game.state.players[1].hand)
        self.assertFalse(self.grants(game, target))
        self.assertEqual(self.play(game, YETI), target)
        self.assertEqual((game.state.entities[target].attack, game.state.entities[target].max_health), (4, 5))
        self.play(game, 'k35.kill', target); self.assertFalse(game.state.players[1].board)

    def test_current_copy_keeps_granted_payload_but_base_copy_does_not(self):
        for copying, expected in (('k35.copy', [STEGODON]), ('k35.base_copy', [])):
            with self.subTest(copying=copying):
                game = self.game((STEED, copying, 'k35.kill'))
                target = game.state.players[1].board[0]
                self.play(game, STEED, target); self.play(game, copying, target)
                copied = game.state.players[1].board[-1]
                self.assertNotEqual(copied, target)
                self.assertEqual(bool(self.grants(game, copied)), copying == 'k35.copy')
                self.play(game, 'k35.kill', copied)
                self.assertEqual(self.board(game)[1:], expected)

    def test_changed_control_does_not_keep_caster_as_the_summon_controller(self):
        game = self.game((STEED, 'k35.steal', 'k35.kill'))
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.steal', target)
        self.play(game, 'k35.kill', target)
        self.assertEqual(self.board(game), [])
        self.assertEqual(self.board(game, 2), [STEGODON])

    def test_active_trigger_keeps_live_carrier_and_places_summon_beside_it(self):
        game = self.game((STEED, 'k35.trigger'), (YETI, SQUIRE))
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.trigger', target)
        self.assertEqual(self.board(game), [YETI, STEGODON, SQUIRE])
        self.assertEqual(len(self.grants(game, target)), 1)
        self.assertFalse(game.state.death_history)
        self.portable(game)

    def test_active_full_board_does_not_evict_cards_or_draw_randomness(self):
        game = self.game((STEED, 'k35.trigger'), (YETI,)*7)
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); rng = game.snapshot()['rng_state']
        self.play(game, 'k35.trigger', target)
        self.assertEqual(self.board(game), [YETI]*7)
        self.assertEqual(game.snapshot()['rng_state'], rng)

    def test_real_quantity_source_uses_carrier_attribution_and_complete_stegodon_material(self):
        game = self.game((STEED, 'k35.kill'), ('CORE_DAL_575', YETI))
        target = game.state.players[1].board[1]
        caster = self.play(game, STEED, target); self.play(game, 'k35.kill', target)
        self.assertEqual(self.board(game), ['CORE_DAL_575', STEGODON, STEGODON])
        cause = game.state.card_summon_history[-1].request.cause
        self.assertEqual(cause.source.entity_id, target)
        self.assertNotEqual(cause.source.entity_id, caster)
        self.assertIsNone(cause.cast_id)
        self.portable(game)

    def test_waiting_summon_restores_replays_and_bad_choice_rolls_back_without_a_second_death(self):
        game = self.game((STEED, 'k35.kill'), (YETI, 'k35.watch'), mode='wait')
        target = game.state.players[1].board[0]
        self.play(game, STEED, target); self.play(game, 'k35.kill', target)
        self.assertIsNotNone(game.state.pending_choice)
        other = self.portable(game, 'wait'); before = game.snapshot()
        pending = game.state.pending_choice
        with self.assertRaises(ResolutionError): game.apply(SelectChoice(pending.player_id, pending.id, ('fail',)))
        self.assertEqual(game.snapshot(), before)
        for instance in (game, other):
            choice = instance.state.pending_choice
            instance.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
        self.assertEqual(game.snapshot(), other.snapshot())
        self.assertEqual(len(game.state.death_history), 1)
        self.assertEqual(self.board(game).count(STEGODON), 1)
        self.portable(game, 'wait')

    def test_late_grant_reaction_failure_rolls_back_entire_paid_real_spell(self):
        game = self.game((STEED,), (YETI, 'k35.watch'), mode='fail')
        target = game.state.players[1].board[0]; before = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, STEED, target)
        self.assertEqual(game.snapshot(), before)
