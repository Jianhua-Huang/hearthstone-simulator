"""The real Ooze suffix uses existing end-window acceptance and expiry.

Selected activation spells are diagnostic producers, not new real cards.
These tests establish internal policy, not CN calibration or a curated pool.
"""
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_discovery_copy_count_fragments import load_batch
from hs_sim.cards.hand_shuffle_turn_copy_cards import OOZE, PREFIX
from hs_sim.cards.native_assemble_entry_cards import SHAPER, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardClass, CardMetadata, DamageKind,
    EndTurnRepeatSpec, EndTurnRequest, EndTurnSelector, Rarity, TargetSpec)
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from tools import card_batch as batch

BASE, OTHER, COIN = 'BE_152', 'CORE_GIL_622', 'GAME_005'
CID = AssembleRecipe(BASE, OOZE, 'bottom').card_id
CTX = GenerationContext('k518-real-ooze-diagnostic-domain', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON)
P = 'fixture.ooze_end_turn.'
ACTIVATE, GROW, WOUND, MUTE, BOUNCE, KILL, GIVE = (
    P+s for s in ('activate', 'grow', 'wound', 'mute', 'bounce', 'kill', 'give'))
WATCH, FAIL, FILL, REPEAT = (P+s for s in ('watch', 'fail', 'fill', 'repeat'))


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    r = build_registry()
    r._version += '.k518.'+mode

    def activate(c):
        target = c.state.entities[c.target_id]
        return (TriggerEndTurnEffects(c.player_id, EndTurnRequest(
            EndTurnSelector('selected', (target.controller,), ('minion',),
                (target.id,))), c.source_id),)

    bodies = {
        ACTIVATE: activate,
        GROW: lambda c: (Buff(c.target_id, 2, 3, c.source_id),),
        WOUND: lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),),
        MUTE: lambda c: (Silence(c.target_id),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),),
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL,
            cost=1 if cid == ACTIVATE else 0, metadata=META, on_play=cid,
            targeting=TargetSpec(kinds=(CardType.MINION,), relation='friendly')))

    def fail(c):
        raise ResolutionError('deliberate Ooze grant-notification failure')

    def watch(c):
        if mode not in ('wait', 'fail') or c.event is None:
            return ()
        target = c.state.entities[c.event.target_id]
        if target.card_id != CID or dict(c.event.data).get('ability_kind') != 'trigger':
            return ()
        if mode == 'fail':
            return (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, attack=0,
        health=20, metadata=META, triggers=(TriggerSpec('ability_granted', WATCH),)))
    r.register_card(CardDefinition(FILL, FILL, CardType.MINION, attack=0,
        health=20, metadata=META))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, attack=0,
        health=20, metadata=META, end_turn_repeats=(EndTurnRepeatSpec(2),)))
    r.register_pool(PoolDefinition(POOL_ID, 'three-reviewed-real-faces-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (BASE, OOZE, OTHER)),
        complete=True))
    return r


class OozeEndTurnContextTests(unittest.TestCase):
    def game(self, extra=(), board=(), *, actor=1, mode='normal'):
        self.mode = mode
        return Game.from_scenario(Scenario(tuple(PlayerSetup('HERO_04',
            hand=(SHAPER, *extra) if p == actor else (),
            board=board if p == actor else (), deck=(COIN,)*12,
            mana=20, max_mana=20, mana_cap=30) for p in (1, 2)),
            active_player=actor, seed=518, generation_context=CTX), fixture(mode))

    def play(self, g, cid, target=None):
        actor = g.state.active_player
        eid = next(i for i in g.state.players[actor].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(actor, eid, target_id=target))
        return eid

    def manufacture(self, g):
        self.play(g, SHAPER)
        q = g.state.pending_choice
        option = next(o for o in q.options if o.card_id == CID)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        return self.play(g, CID)

    def copies(self, g, actor):
        return [g.state.entities[i] for i in g.state.players[actor].board
            if g.state.entities[i].card_id == CID]

    def delayed(self, g, eid):
        return [a for a in g.state.entities[eid].abilities
            if a.kind == 'trigger' and a.behavior_id == PREFIX+'copy']

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(self.mode, 'reader')
        self.assertIsNot(reader, g.registry)
        restored = Game.from_snapshot(saved, reader)
        clone = g.clone()
        replayed = replay(build_replay(g), reader)
        for other in (restored, clone, replayed):
            self.assertEqual(other.snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for field in ('"rng_state"', '"resolution_frame"', '"end_turn_batches"'):
                self.assertNotIn(field, public)
        return restored, clone, replayed

    def test_complete_source_faces_and_pending_natural_death_remain_explicit(self):
        data = load_batch()
        row = next(x for x in data['existing_dependencies'] if x['record']['id'] == OOZE)
        self.assertEqual(batch.canonical(row['record']), row['record_sha256'])
        self.assertEqual(batch.canonical(asdict(fixture().card(OOZE))), row['definition_sha256'])
        for obs in (o for o in data['official_observations'] if o['card_id'] == OOZE):
            path = Path(obs['response_file'])
            self.assertEqual(batch.sha(path), obs['response_sha256'])
            body = json.loads(path.read_text(encoding='utf-8-sig'))
            self.assertEqual([x for x in body['cards'] if x['id'] == row['record']['dbf_id']], [obs['face']])
            batch.check_face(row['record'], obs['face'], obs['locale'])
        suffix = fixture().assemble_templates[OOZE].suffix
        self.assertEqual(suffix.allowed_timings, ('battlecry', 'start_turn', 'end_turn'))
        self.assertEqual(suffix.pending_timings, ('deathrattle',))
        self.assertIn('Natural death', data['pending_contexts'][OOZE])
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'explicitly unimplemented'):
            fixture().card(AssembleRecipe('CORE_EX1_096', OOZE, 'bottom').card_id)

    def test_actual_shaper_two_players_late_grant_never_enters_accepted_window(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game(actor=actor)
                eid = self.manufacture(g)
                self.assertEqual(g.state.players[actor].mana, 16)
                self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].max_health), (2, 3))
                self.assertEqual(len(g.state.battlecry_history), 1)
                rng = g.snapshot()['rng_state']
                g.apply(EndTurn(actor))
                self.assertEqual([e.id for e in self.copies(g, actor)], [eid])
                self.assertFalse(self.delayed(g, eid))
                group = g.state.end_turn_batches[-1]
                self.assertEqual(len(group.subjects), 1)
                self.assertNotEqual(group.subjects[0].ability.behavior_id, PREFIX+'copy')
                self.assertTrue(group.completed)
                self.assertEqual(g.snapshot()['rng_state'], rng)
                g.apply(EndTurn(3-actor)); g.apply(EndTurn(actor))
                self.assertEqual([e.id for e in self.copies(g, actor)], [eid])
                self.assertFalse(self.delayed(g, eid))

    def test_selected_activation_installs_then_natural_end_copies_current_material(self):
        for actor in (1, 2):
            with self.subTest(actor=actor):
                g = self.game((ACTIVATE, GROW, WOUND), actor=actor)
                eid = self.manufacture(g)
                self.play(g, GROW, eid); self.play(g, WOUND, eid)
                clocks = (g.state.turn, g.state.active_player)
                self.play(g, ACTIVATE, eid)
                self.assertEqual((g.state.turn, g.state.active_player), clocks)
                self.assertEqual(g.state.players[actor].mana, 15)
                old = self.delayed(g, eid)
                self.assertEqual(len(old), 1)
                self.assertEqual(old[0].expires_turn, g.state.turn)
                self.assertEqual(len(self.copies(g, actor)), 1)
                g.apply(EndTurn(actor))
                copies = self.copies(g, actor)
                self.assertEqual(len(copies), 2)
                self.assertEqual({(e.attack, e.max_health, e.damage) for e in copies}, {(4, 6, 1)})
                self.assertEqual(len({e.id for e in copies}), 2)
                self.assertFalse(any(self.delayed(g, e.id) for e in copies))
                self.assertEqual(len(g.state.battlecry_history), 1)
                accepted = g.state.end_turn_batches[-1].subjects
                self.assertEqual([s.ability.id for s in accepted if s.ability.behavior_id == PREFIX+'copy'], [old[0].id])

    def test_independent_active_windows_preserve_each_old_grant_without_same_window_recursion(self):
        g = self.game((ACTIVATE, ACTIVATE))
        eid = self.manufacture(g)
        self.play(g, ACTIVATE, eid)
        self.play(g, ACTIVATE, eid)
        # The second active window accepts the first delayed subject too.
        self.assertEqual(len(self.copies(g, 1)), 2)
        self.assertEqual(len(self.delayed(g, eid)), 2)
        g.apply(EndTurn(1))
        self.assertEqual(len(self.copies(g, 1)), 6)
        self.assertFalse(any(self.delayed(g, e.id) for e in self.copies(g, 1)))
        g.apply(EndTurn(2)); g.apply(EndTurn(1))
        self.assertEqual(len(self.copies(g, 1)), 6)

    def test_pending_grant_wait_restore_clone_and_replay_really_finish_the_same_window(self):
        g = self.game(board=(WATCH,), mode='wait')
        eid = self.manufacture(g)
        g.apply(EndTurn(1))
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.delayed(g, eid)), 1)
        self.assertFalse(g.state.end_turn_batches[-1].completed)
        self.assertEqual(len(g.state.end_turn_batches[-1].subjects), 1)
        legs = (g, *self.portable(g))
        for other in legs:
            self.choose(other)
            self.assertFalse(self.delayed(other, eid))
            self.assertEqual([e.id for e in self.copies(other, 1)], [eid])
        self.assertTrue(all(other.snapshot() == g.snapshot() for other in legs))

    def test_late_grant_bad_choice_rolls_back_choice_then_good_choice_expires_normally(self):
        g = self.game(board=(WATCH,), mode='wait')
        eid = self.manufacture(g)
        g.apply(EndTurn(1))
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate Ooze'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.assertFalse(self.delayed(g, eid))
        self.assertEqual(len(self.copies(g, 1)), 1)

    def test_notification_failure_rolls_back_whole_natural_end(self):
        g = self.game(board=(WATCH,), mode='fail')
        eid = self.manufacture(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate Ooze'):
            g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), saved)
        self.assertFalse(self.delayed(g, eid))
        self.assertFalse(g.state.end_turn_batches)

    def test_removal_silence_and_reentry_cancel_preaccepted_delayed_copy(self):
        for spell in (MUTE, BOUNCE, KILL):
            with self.subTest(spell=spell):
                g = self.game((ACTIVATE, spell))
                eid = self.manufacture(g)
                self.play(g, ACTIVATE, eid)
                self.play(g, spell, eid)
                if spell == BOUNCE:
                    self.assertEqual(g.state.entities[eid].zone, Zone.HAND)
                    self.assertEqual(self.play(g, CID), eid)
                g.apply(EndTurn(1))
                self.assertLessEqual(len(self.copies(g, 1)), 1)
                self.assertFalse(self.delayed(g, eid))

    def test_full_board_expires_the_accepted_copy_without_deferred_delivery(self):
        g = self.game((ACTIVATE, KILL), board=(FILL,)*5)
        eid = self.manufacture(g)
        self.play(g, ACTIVATE, eid)
        g.apply(EndTurn(1))
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(len(self.copies(g, 1)), 1)
        self.assertFalse(self.delayed(g, eid))
        g.apply(EndTurn(2))
        self.play(g, KILL, g.state.players[1].board[0])
        g.apply(EndTurn(1))
        self.assertEqual(len(self.copies(g, 1)), 1)

    def test_control_transfer_uses_current_controller_and_either_turn_of_old_grant(self):
        g = self.game((ACTIVATE, GIVE))
        eid = self.manufacture(g)
        self.play(g, ACTIVATE, eid)
        self.play(g, GIVE, eid)
        self.assertEqual(g.state.entities[eid].controller, 2)
        g.apply(EndTurn(1))
        self.assertFalse(self.copies(g, 1))
        self.assertEqual(len(self.copies(g, 2)), 2)
        self.assertTrue(all(e.owner == 2 for e in self.copies(g, 2) if e.id != eid))
        self.assertFalse(any(self.delayed(g, e.id) for e in self.copies(g, 2)))

    def test_repeated_end_body_grants_stay_outside_its_fixed_natural_window(self):
        g = self.game(board=(REPEAT,))
        eid = self.manufacture(g)
        start = len(g.events)
        g.apply(EndTurn(1))
        grants = [e for e in g.events[start:] if e.kind == 'ability_granted' and e.target_id == eid]
        self.assertEqual(len(grants), 2)
        self.assertEqual(len(g.state.end_turn_batches[-1].subjects), 1)
        self.assertEqual(len(self.copies(g, 1)), 1)
        self.assertFalse(self.delayed(g, eid))


if __name__ == '__main__':
    unittest.main()
