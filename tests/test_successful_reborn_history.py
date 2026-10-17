"""Actual Reborn success belongs to immutable native entry history."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Registry, RewindSpec, Scenario, SelectChoice, SnapshotError, TargetSpec,
    successful_reborns, summoned_minions, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.successful_summons import record_from_dict, validate_state
from hs_sim.engine.summon_sources import ResurrectMinion

P = 'k165a.'
HERO, NORMAL, FULL, BLOCKED, PLAIN, WATCH = (P + x for x in ('hero', 'normal', 'full', 'blocked', 'plain', 'watch'))
KILL, COPY, RES, BUFF, TAKE, GIVE, CHANGE, BOUNCE, SILENCE, REWIND = (
    P + x for x in ('kill', 'copy', 'res', 'buff', 'take', 'give', 'change', 'bounce', 'silence', 'rewind'))


@lru_cache(maxsize=None)
def registry(mode=None, role='writer'):
    if role not in ('writer', 'reader'): raise AssertionError('Independent registry role required')
    r = Registry('successful-reborn-' + str(mode))
    r.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30))
    r.register_card(CardDefinition(PLAIN, PLAIN, CardType.MINION, attack=1, health=4))
    r.register_card(CardDefinition(NORMAL, NORMAL, CardType.MINION, cost=2, attack=3, health=2, keywords=(Keyword.REBORN,)))
    r.register_card(CardDefinition(FULL, FULL, CardType.MINION, cost=3, attack=3, health=2,
        keywords=(Keyword.REBORN,), reborn_policy='full_health_enchantments'))
    r.register_behavior(P + 'fill', lambda c: (Summon(c.player_id, PLAIN),))
    r.register_card(CardDefinition(BLOCKED, BLOCKED, CardType.MINION, health=2,
        keywords=(Keyword.REBORN,), deathrattle=P + 'fill'))
    def resurrect(c):
        death = next(d for d in c.state.death_history if d.card_id == NORMAL)
        return (ResurrectMinion(c.player_id, death.id, source_id=c.source_id),)
    bodies = {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),), RES: resurrect,
        BUFF: lambda c: (Buff(c.target_id, 4, 5, c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, c.player_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3 - c.player_id),),
        CHANGE: lambda c: (Transform(c.target_id, PLAIN),),
        BOUNCE: lambda c: (ReturnToHand(c.target_id),), SILENCE: lambda c: (Silence(c.target_id),),
        REWIND: lambda c: (Destroy(c.target_id, c.source_id),)}
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        extra = dict(keywords=(Keyword.REWIND,), rewind=RewindSpec()) if cid == REWIND else {}
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid != RES else None, **extra))
    def fail(c): raise ResolutionError('K165-A deliberate failure after actual Reborn')
    r.register_behavior(P + 'fail', fail)
    if mode:
        def eligible(c): return 'reborn_from' in dict(c.event.data)
        def watch(c):
            rows = successful_reborns(c.state, c.event.player_id)
            assert rows and rows[-1].event_sequence == c.event.sequence
            assert rows[-1].reborn_death_id == dict(c.event.data)['death_id']
            if mode == 'fail': return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),)
            if mode == 'kill': return (Destroy(c.event.target_id, c.source_id),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('bad', 'Rollback', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_trigger_condition(P + 'eligible', eligible); r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec('minion_summoned', P + 'watch', condition_id=P + 'eligible'),)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class SuccessfulRebornHistoryTests(unittest.TestCase):
    def game(self, hand=(KILL,), board=(NORMAL,), enemy=(), enemy_hand=(), mode=None):
        self.mode = mode
        if mode: board = (WATCH,) + tuple(board)
        return Game.from_scenario(Scenario((PlayerSetup(HERO, hand=hand, board=board, deck=(PLAIN,) * 8,
            mana=30, max_mana=30, mana_cap=30), PlayerSetup(HERO, hand=enemy_hand, board=enemy, deck=(PLAIN,) * 8,
            mana=30, max_mana=30, mana_cap=30)), seed=165), registry(mode))
    def first(self, g, cid, zone='board', pid=1):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid], zone) if g.state.entities[i].card_id == cid)
    def play(self, g, cid, target=None, pid=1):
        e = self.first(g, cid, 'hand', pid); g.apply(PlayCard(pid, e.id, target_id=target,
            position=len(g.state.players[pid].board) if e.kind == CardType.MINION else None)); return e.id
    def choose(self, g, key='ok'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(self.mode, 'reader')
        self.assertIsNot(g.registry, reader); self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved); self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('reborn_death_id', 'successful_summon_history', 'death_history', 'rng_state', 'resolution_frame'):
                self.assertNotIn('"' + key + '"', public)
    def reborn(self, g): return successful_reborns(g.state, 1)
    def corrupt(self, g, edit):
        bad = deepcopy(g.snapshot()); edit(bad)
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry(self.mode, 'reader'))

    def test_a0_played_reborn_keyword_is_not_success_until_original_return(self):
        g = self.game((NORMAL, KILL), board=()); self.play(g, NORMAL)
        self.assertEqual(self.reborn(g), ()); old = self.first(g, NORMAL).id; self.play(g, KILL, old)
        row, = self.reborn(g); death, = g.state.death_history
        self.assertEqual((row.reborn_death_id, row.card_id, row.player_id), (death.id, NORMAL, 1))
        self.assertNotEqual(row.entity_id, old); self.assertEqual(g.state.entities[row.entity_id].health, 1)
        self.assertNotIn(Keyword.REBORN, g.state.entities[row.entity_id].keywords); self.portable(g)

    def test_a1_death_with_reborn_but_full_board_failed_return_does_not_count(self):
        g = self.game(board=(BLOCKED,) + (PLAIN,) * 6); target = self.first(g, BLOCKED).id; self.play(g, KILL, target)
        self.assertIn(Keyword.REBORN, g.state.death_history[0].keywords)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(self.reborn(g), ())
        self.assertTrue(any(e.kind == 'reborn_failed' for e in g.events)); self.portable(g)

    def test_a2_ordinary_copy_and_resurrection_are_not_additional_reborns(self):
        g = self.game((KILL, COPY, RES)); self.play(g, KILL, self.first(g, NORMAL).id)
        self.play(g, COPY, self.first(g, NORMAL).id); self.play(g, RES)
        self.assertEqual(len(summoned_minions(g.state, 1)), 3); self.assertEqual(len(self.reborn(g)), 1)
        self.assertEqual([r.reborn_death_id for r in summoned_minions(g.state, 1)], [g.state.death_history[0].id, None, None]); self.portable(g)

    def test_a3_later_controller_face_and_death_do_not_rewrite_original_receiver(self):
        g = self.game((KILL, GIVE, CHANGE, KILL)); self.play(g, KILL, self.first(g, NORMAL).id)
        row, = self.reborn(g); self.play(g, GIVE, row.entity_id); self.play(g, CHANGE, row.entity_id); self.play(g, KILL, row.entity_id)
        self.assertEqual(self.reborn(g), (row,)); self.assertEqual(successful_reborns(g.state, 2), ()); self.portable(g)

    def test_a4_opponent_kill_does_not_change_actual_reborn_receiver(self):
        g = self.game(hand=(), enemy_hand=(KILL,)); target = self.first(g, NORMAL).id
        g.apply(EndTurn(1)); self.play(g, KILL, target, pid=2)
        row, = self.reborn(g); self.assertEqual((row.player_id, row.active_player), (1, 2))
        self.assertFalse(successful_reborns(g.state, 2)); self.portable(g)

    def test_a5_stolen_original_reborn_creates_a_new_body_owned_by_death_controller(self):
        g = self.game((TAKE, KILL), board=(), enemy=(NORMAL,)); old = self.first(g, NORMAL, pid=2).id
        self.play(g, TAKE, old); self.play(g, KILL, old); row, = self.reborn(g)
        self.assertEqual((g.state.death_history[0].owner, row.minion.owner, row.player_id), (2, 1, 1)); self.portable(g)

    def test_a6_full_health_enchantments_reborn_counts_without_one_health_inference(self):
        g = self.game((BUFF, KILL), board=(FULL,)); old = self.first(g, FULL).id
        self.play(g, BUFF, old); self.play(g, KILL, old); row, = self.reborn(g)
        self.assertEqual((g.state.entities[row.entity_id].attack, g.state.entities[row.entity_id].health), (7, 7)); self.portable(g)

    def test_a7_silenced_reborn_keyword_never_fabricates_success(self):
        g = self.game((SILENCE, KILL)); target = self.first(g, NORMAL).id
        self.play(g, SILENCE, target); self.play(g, KILL, target); self.assertEqual(self.reborn(g), ()); self.portable(g)

    def test_b0_first_summon_listener_sees_complete_success_and_wait_restores(self):
        g = self.game(mode='wait'); self.play(g, KILL, self.first(g, NORMAL).id)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.reborn(g)), 1); self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.portable(g)

    def test_b1_failure_after_native_reborn_rolls_back_entry_history_and_original_death(self):
        g = self.game(mode='fail'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, KILL, self.first(g, NORMAL).id)
        self.assertEqual(g.snapshot(), saved)

    def test_b2_immediate_death_of_returned_body_does_not_erase_success(self):
        g = self.game(mode='kill'); self.play(g, KILL, self.first(g, NORMAL).id); row, = self.reborn(g)
        self.assertEqual(g.state.entities[row.entity_id].zone, Zone.GRAVEYARD); self.assertEqual(len(g.state.death_history), 2); self.portable(g)

    def test_b3_real_rewind_retires_old_reborn_pair_and_accepts_sparse_death_id(self):
        g = self.game((REWIND,)); self.play(g, REWIND, self.first(g, NORMAL).id); old = self.reborn(g)[0].entity_id
        self.portable(g); self.choose(g, 'retry'); row, = self.reborn(g)
        self.assertNotEqual(row.entity_id, old); self.assertGreater(row.reborn_death_id, len(g.state.death_history))
        self.assertEqual(len(g.state.successful_summon_history), 1); self.assertEqual(g.state.players[1].mana, 29); self.portable(g)

    def test_b4_bounced_returned_minion_can_reborn_again_as_independent_occurrence(self):
        g = self.game((KILL, BOUNCE, KILL)); self.play(g, KILL, self.first(g, NORMAL).id); first, = self.reborn(g)
        self.play(g, BOUNCE, first.entity_id); self.play(g, NORMAL); self.play(g, KILL, first.entity_id)
        rows = self.reborn(g); self.assertEqual(len(rows), 2); self.assertNotEqual(rows[0].reborn_death_id, rows[1].reborn_death_id); self.portable(g)

    def test_c0_query_is_pure_frozen_and_keeps_unknown_tribes_without_filter(self):
        g = self.game(); self.play(g, KILL, self.first(g, NORMAL).id); before = g.snapshot(); rng = g._rng.getstate()
        row, = self.reborn(g); self.assertIsNone(row.tribes)
        with self.assertRaises(FrozenInstanceError): row.reborn_death_id = 9
        for bad in (True, 0, 3, '1'):
            with self.assertRaises(ValueError): successful_reborns(g.state, bad)
        for bad in (True, 0, -1, '1'):
            with self.assertRaises(ValueError): replace(row, reborn_death_id=bad)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g._rng.getstate(), rng)

    def test_c1_typed_record_and_new_strict_dictionary_require_original_link_field(self):
        g = self.game(); self.play(g, KILL, self.first(g, NORMAL).id); row, = self.reborn(g)
        codec = FrameCodec(g.mechanics, g.registry); self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(row)))), row)
        raw = json.loads(json.dumps(asdict(row))); raw.pop('reborn_death_id')
        with self.assertRaises(ValueError): record_from_dict(raw)
        state = g.state; state.successful_summon_history[0] = replace(row, reborn_death_id=999)
        with self.assertRaises(ValueError): validate_state(state)

    def test_c2_rehashed_deleted_or_replaced_reborn_classification_is_rejected(self):
        g = self.game(); self.play(g, KILL, self.first(g, NORMAL).id)
        for value in (None, True, 999):
            self.corrupt(g, lambda s, value=value: s['state']['successful_summon_history'][0].update(reborn_death_id=value))
        self.portable(g)

    def test_c3_removing_entry_marker_and_classification_still_loses_paired_reborn_event(self):
        g = self.game(); self.play(g, KILL, self.first(g, NORMAL).id)
        def edit(saved):
            saved['state']['successful_summon_history'][0]['reborn_death_id'] = None
            event = next(e for e in saved['events'] if e['kind'] == 'minion_summoned')
            event['data'].pop('reborn_from'); event['data'].pop('death_id')
        self.corrupt(g, edit)

    def test_c4_rehashed_ordinary_copy_cannot_claim_an_existing_actual_reborn_death(self):
        g = self.game((KILL, COPY)); self.play(g, KILL, self.first(g, NORMAL).id); self.play(g, COPY, self.first(g, NORMAL).id)
        def edit(saved): saved['state']['successful_summon_history'][1]['reborn_death_id'] = g.state.death_history[0].id
        self.corrupt(g, edit); self.portable(g)


if __name__ == '__main__': unittest.main()
