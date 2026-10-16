"""Actual Pterrordax choices and captured owner-clock grants share one lifetime."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_timed_grant_cards import PTERRORDAX, STEALTH, ELUSIVE, WINDFURY, CHOICE_ONLY, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, TimedKeywordSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference

YETI = 'CORE_CS2_182'
FIRE = 'CORE_CS2_029'
PREFIX = 'k92.'


def registry():
    r = build_registry()
    def body(c):
        return next(e for e in c.state.entities.values() if e.card_id == PTERRORDAX and e.zone == Zone.BOARD)
    scripts = {
        'copy': lambda c: (CopyMinion(BoardPresenceReference.capture(c.state, body(c).id), 2),),
        'control': lambda c: (ChangeControl(body(c).id, 2),),
        'silence': lambda c: (Silence(body(c).id),),
        'bounce': lambda c: (ReturnToHand(body(c).id),),
        'transform': lambda c: (Transform(body(c).id, YETI),),
        'summon': lambda c: (Summon(c.player_id, PTERRORDAX),),
        'permanent': lambda c: (GrantKeyword(body(c).id, Keyword.STEALTH),),
    }
    r.register_behavior(PREFIX+'fail', lambda c: (AddToHand(c.player_id, 'unknown.k92'),))
    def resummon(c):
        e = next(e for e in c.state.entities.values() if e.card_id == PTERRORDAX and e.zone == Zone.HAND)
        return (SummonStoredCard(CardReference.capture(e), 1),)
    r.register_behavior(PREFIX+'resummon', resummon)
    def defer(c):
        e = body(c)
        grant = GrantCapturedKeyword(MinionReference.capture(e), Keyword.STEALTH, c.source_id,
                                     duration=TimedKeywordSpec(Keyword.STEALTH))
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (grant,)),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(PREFIX+'fail', c.source_id, c.player_id), grant)),
            ChoiceOption('cycle', 'Reenter', (ReturnToHand(e.id), InvokeBehavior(PREFIX+'resummon', c.source_id, c.player_id), grant)),
            ChoiceOption('transform', 'Transform', (Transform(e.id, YETI), grant)),
            ChoiceOption('control', 'Transfer', (ChangeControl(e.id, 2), grant)),
            ChoiceOption('kill', 'Destroy', (Destroy(e.id, c.source_id), grant)),
        ), source_id=c.source_id),)
    scripts['defer'] = defer
    for name, fn in scripts.items():
        r.register_behavior(PREFIX+name, fn)
        r.register_card(CardDefinition(PREFIX+name, name, CardType.SPELL, on_play=PREFIX+name))
    def wait(c):
        e = c.state.entities.get(c.event.target_id)
        if e is None or e.card_id != PTERRORDAX:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', ()),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(PREFIX+'fail', c.source_id, c.player_id),)),
        ), source_id=c.source_id),)
    r.register_behavior(PREFIX+'wait', wait)
    r.register_card(CardDefinition(PREFIX+'watch', 'Grant observer', CardType.MINION, health=10,
                                   triggers=(TriggerSpec('ability_granted', PREFIX+'wait'),)))
    return r


class NativeTimedGrantCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = registry()

    def game(self, hand=(PTERRORDAX,), board=(), enemy=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(YETI,)*8, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy, deck=(YETI,)*8, mana=20, max_mana=20, mana_cap=20),
        ), seed=92), self.r)

    def play(self, g, cid=PTERRORDAX, target=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(p, i, target, position=len(g.state.players[p].board) if cid == PTERRORDAX else None))
        return i

    def choose(self, g, cid=STEALTH):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (cid,)))

    def turn(self, g):
        g.apply(EndTurn(g.state.active_player))

    def timed(self, g, i):
        return [a for a in g.state.entities[i].abilities if a.timed_keyword is not None]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in ('MinionReference', 'GrantCapturedKeyword', 'resolution_frame', 'rng_state', 'keyword_expiry'):
                self.assertNotIn(hidden, public)
        return other

    def reject(self, s):
        s['state_hash'] = canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_complete_actual_face_and_three_real_nonphysical_options(self):
        data = load_batch(); card = self.r.card(PTERRORDAX)
        self.assertEqual((data['cards'][0]['record']['dbf_id'], card.cost, card.attack, card.health), (118232, 4, 4, 4))
        self.assertIsNotNone(card.battlecry)
        self.assertIsNone(card.choose_one)
        self.assertEqual(len(data['official_observations']), 8)
        self.assertEqual([row['record']['dbf_id'] for row in data['dependencies']], [41054, 41060, 41062])
        for cid in CHOICE_ONLY:
            option = self.r.card(cid)
            self.assertTrue(option.choice_only)
            self.assertIsNone(option.on_play)
            self.assertEqual(option.cost, 0)

    def test_actual_battlecry_three_choices_original_payment_and_one_keyword(self):
        g = self.game(); i = self.play(g); q = g.state.pending_choice
        self.assertEqual((q.min_count, q.max_count), (1, 1))
        self.assertEqual(tuple(x.card_id for x in q.options), CHOICE_ONLY)
        self.assertFalse(g.state.entities[i].keywords)
        self.choose(g, ELUSIVE)
        self.assertEqual(g.state.entities[i].keywords, {Keyword.ELUSIVE})
        self.assertEqual(g.state.players[1].mana, 16)
        self.assertEqual(len(g.state.battlecry_history), 1)

    def test_invalid_or_multiple_selection_preserves_original_waiting_action(self):
        g = self.game(); self.play(g); s = g.snapshot(); q = g.state.pending_choice
        for choices in ((), (STEALTH, WINDFURY), ('unknown.k92',)):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                g.apply(SelectChoice(1, q.id, choices))
            self.assertEqual(g.snapshot(), s)

    def test_pending_actual_choice_restores_clones_replays_and_keeps_duration_codec(self):
        g = self.game(); i = self.play(g); other = self.portable(g)
        self.assertIn('GrantCapturedKeyword', str(g.snapshot()))
        self.assertIn('TimedKeywordSpec', str(g.snapshot()))
        for current in (g, other):
            self.choose(current)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.timed(g, i)[0].keyword_expiry.player_id, 1)
        self.portable(g)

    def test_stealth_survives_opponent_turn_then_expires_at_own_next_start(self):
        g = self.game(); i = self.play(g); self.choose(g)
        expiry = self.timed(g, i)[0].keyword_expiry
        self.assertEqual((expiry.player_id, expiry.owner_turn_index, expiry.boundary), (1, 2, 'turn_started'))
        self.turn(g); self.assertIn(Keyword.STEALTH, g.state.entities[i].keywords)
        self.turn(g); self.assertNotIn(Keyword.STEALTH, g.state.entities[i].keywords)
        self.assertFalse(self.timed(g, i)); self.portable(g)

    def test_elusive_is_permanent_and_blocks_actual_enemy_spell_target(self):
        g = self.game(enemy_hand=(FIRE,)); i = self.play(g); self.choose(g, ELUSIVE); self.turn(g)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, FIRE, i)
        self.assertEqual(g.snapshot(), before)
        self.turn(g)
        self.assertIn(Keyword.ELUSIVE, g.state.entities[i].keywords)
        self.assertFalse(self.timed(g, i))

    def test_windfury_is_permanent_and_uses_existing_two_attack_budget(self):
        g = self.game(); i = self.play(g); self.choose(g, WINDFURY)
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, i, g.state.players[2].hero_id))
        self.turn(g); self.turn(g)
        for _ in range(2):
            g.apply(Attack(1, i, g.state.players[2].hero_id))
        with self.assertRaises(IllegalAction):
            g.apply(Attack(1, i, g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 22)
        self.assertIn(Keyword.WINDFURY, g.state.entities[i].keywords)

    def test_direct_summon_and_initial_board_do_not_execute_battlecry(self):
        g = self.game(hand=(PREFIX+'summon',), board=(PTERRORDAX,)); self.play(g, PREFIX+'summon')
        self.assertIsNone(g.state.pending_choice)
        self.assertFalse(g.state.battlecry_history)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertTrue(all(not g.state.entities[i].keywords for i in g.state.players[1].board))

    def test_current_enemy_copy_keeps_original_owner_deadline(self):
        g = self.game(hand=(PTERRORDAX, PREFIX+'copy')); i = self.play(g); self.choose(g)
        expiry = self.timed(g, i)[0].keyword_expiry; self.play(g, PREFIX+'copy')
        copy, = g.state.players[2].board
        self.assertEqual(self.timed(g, copy)[0].keyword_expiry, expiry)
        self.turn(g); self.assertIn(Keyword.STEALTH, g.state.entities[copy].keywords)
        self.turn(g); self.assertFalse(self.timed(g, copy)); self.portable(g)

    def test_control_after_grant_does_not_rebind_clock(self):
        g = self.game(hand=(PTERRORDAX, PREFIX+'control')); i = self.play(g); self.choose(g)
        expiry = self.timed(g, i)[0].keyword_expiry; self.play(g, PREFIX+'control')
        self.assertEqual(g.state.entities[i].controller, 2)
        self.assertEqual(self.timed(g, i)[0].keyword_expiry, expiry)
        self.turn(g); self.assertIn(Keyword.STEALTH, g.state.entities[i].keywords)
        self.turn(g); self.assertFalse(self.timed(g, i))

    def test_bounce_resets_grant_and_actual_replay_pays_and_chooses_again(self):
        g = self.game(hand=(PTERRORDAX, PREFIX+'bounce')); i = self.play(g); self.choose(g)
        self.play(g, PREFIX+'bounce'); self.assertFalse(self.timed(g, i))
        self.assertEqual(self.play(g), i); self.assertIsNotNone(g.state.pending_choice)
        self.choose(g, WINDFURY)
        self.assertEqual(g.state.entities[i].keywords, {Keyword.WINDFURY})
        self.assertEqual(g.state.players[1].mana, 12)

    def test_silence_and_transform_remove_timed_attachment(self):
        for action in ('silence', 'transform'):
            with self.subTest(action=action):
                g = self.game(hand=(PTERRORDAX, PREFIX+action)); i = self.play(g); self.choose(g)
                self.play(g, PREFIX+action)
                self.assertFalse(self.timed(g, i)); self.assertFalse(g.state.entities[i].keywords)

    def test_permanent_stealth_is_not_removed_with_one_timed_attachment(self):
        g = self.game(hand=(PTERRORDAX, PREFIX+'permanent')); i = self.play(g); self.choose(g)
        self.play(g, PREFIX+'permanent'); self.turn(g); self.turn(g)
        self.assertIn(Keyword.STEALTH, g.state.entities[i].keywords)
        self.assertFalse(self.timed(g, i))

    def test_captured_pending_duration_and_failure_restore_original_frame(self):
        g = self.game(hand=(PREFIX+'defer',), board=(PTERRORDAX,)); i = g.state.players[1].board[0]
        self.play(g, PREFIX+'defer'); before = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        for current in (g, other):
            self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.timed(g, i)[0].keyword_expiry.owner_turn_index, 2)

    def test_captured_grant_does_not_rebind_same_id_reentry_control_transform_or_death(self):
        for key in ('cycle', 'control', 'transform', 'kill'):
            with self.subTest(key=key):
                g = self.game(hand=(PREFIX+'defer',), board=(PTERRORDAX,)); i = g.state.players[1].board[0]
                old = MinionReference.capture(g.state.entities[i]); self.play(g, PREFIX+'defer')
                self.choose(g, key)
                self.assertNotEqual(MinionReference.capture(g.state.entities[i]) if g.state.entities[i].zone == Zone.BOARD else None, old)
                self.assertFalse(self.timed(g, i))
                self.assertNotIn(Keyword.STEALTH, g.state.entities[i].keywords)

    def test_actual_grant_wait_failure_rolls_back_selection_only_and_no_double_payment(self):
        g = self.game(board=(PREFIX+'watch',)); i = self.play(g); self.choose(g)
        self.assertIsNotNone(g.state.pending_choice); before = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        for current in (g, other):
            self.choose(current, 'ok')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g.state.players[1].mana, 16)
        self.assertEqual(len(self.timed(g, i)), 1); self.portable(g)

    def test_duration_keyword_mismatch_dual_expiry_and_invalid_type_reject(self):
        g = self.game(hand=(), board=(PTERRORDAX,)); ref = MinionReference.capture(g.state.entities[g.state.players[1].board[0]])
        for kwargs in (dict(duration=TimedKeywordSpec(Keyword.TAUNT)),
                       dict(duration=TimedKeywordSpec(Keyword.STEALTH), expires_turn=3),
                       dict(duration={'keyword': 'stealth'})):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GrantCapturedKeyword(ref, Keyword.STEALTH, **kwargs)

    def test_rehashed_corrupt_granted_deadline_rejects_after_real_choice(self):
        g = self.game(); i = self.play(g); self.choose(g)
        for field, value in (('owner_turn_index', 9), ('created_turn', 9), ('player_id', True)):
            s = deepcopy(g.snapshot())
            granted = next(a for a in s['state']['entities'][str(i)]['abilities'] if a['timed_keyword'] is not None)
            granted['keyword_expiry'][field] = value
            with self.subTest(field=field):
                self.reject(s)


if __name__ == '__main__':
    unittest.main()
