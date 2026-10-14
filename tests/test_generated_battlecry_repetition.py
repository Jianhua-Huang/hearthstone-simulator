"""Actual generated BC max plans, shared finite budgets and original windows."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, GainArmor, RequestChoice, Silence, Summon
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded, SnapshotError
from hs_sim.engine.generated_battlecry_repeats import PROFILE
from hs_sim.engine.model import BattlecryRepeatSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE as LEGACY_PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from tests.test_whole_card_physical_runtime import registry as original_registry, mechanics, PhysicalDeliberateFailure


def registry():
    r = original_registry()
    def repeat(c, profile=PROFILE, player=None, choices='player'):
        return (ReplayWholeCards(c.player_id if player is None else player, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1,
                kinds=(CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO)),
            physical_profile=profile, choices=choices),)
    for name, callback in (('repeat', repeat), ('legacy_repeat', lambda c: repeat(c, LEGACY_PROFILE)),
            ('other_repeat', lambda c: repeat(c, player=2)), ('random_repeat', lambda c: repeat(c, choices='random'))):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=2, on_play=name))
    for name, value, uses, kinds, player in (
            ('policy2', 2, 3, (CardType.MINION, CardType.WEAPON, CardType.HERO), None),
            ('policy3', 3, 3, (CardType.MINION, CardType.WEAPON, CardType.HERO), None),
            ('weapon_policy', 4, 2, (CardType.WEAPON,), None),
            ('unlimited', 3, None, (CardType.MINION, CardType.WEAPON, CardType.HERO), None),
            ('other_policy', 3, 2, (CardType.MINION,), 2),
            ('huge_policy', 1000000, 1, (CardType.MINION,), None)):
        r.register_behavior(name, lambda c, v=value, u=uses, k=kinds, p=player:
            (AddBattlecryRepeatModifier(c.player_id if p is None else p,
                BattlecryRepeatSpec(v, k), source_id=c.source_id, uses=u),))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('policies', lambda c: (
        AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(2), c.source_id, uses=1),
        AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(3), c.source_id, uses=2),
        AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(2), c.source_id)))
    r.register_card(CardDefinition('policies', 'Policies', CardType.SPELL, on_play='policies'))
    for value in (2, 4):
        r.register_card(CardDefinition('aura' + str(value), 'Aura', CardType.MINION, health=5,
            battlecry_repeats=(BattlecryRepeatSpec(value),)))
    def probe(c):
        if c.physical is None: return (GainArmor(c.player_id, 1),)
        if c.play is not None or c.generated_activation is None or c.battlecry.origin != 'effect':
            raise ValueError('Generated repetition lost its independent actual origin')
        if c.generated_activation.profile_id != PROFILE or c.battlecry.id not in c.physical.battlecry_ids:
            raise ValueError('Generated repetition lost its actual accepted identity')
        return (GainArmor(c.player_id, 2),)
    r.register_behavior('probe_bc', probe)
    r.register_card(CardDefinition('probecry', 'Probe cry', CardType.MINION, health=4, battlecry='probe_bc'))
    def remove_aura(c):
        if c.physical is None: return ()
        return tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id.startswith('aura'))
    r.register_behavior('remove_aura', remove_aura)
    r.register_card(CardDefinition('removecry', 'Remove cry', CardType.MINION, health=4, battlecry='remove_aura'))
    r.register_behavior('self_silence', lambda c: (Silence(c.source_id),) if c.physical is not None else ())
    r.register_card(CardDefinition('silencecry', 'Silence cry', CardType.MINION, health=4, battlecry='self_silence'))
    r.register_behavior('grant_on_play', lambda c: (AddBattlecryRepeatModifier(c.player_id,
        BattlecryRepeatSpec(4), c.source_id, uses=2),) if c.physical is not None else ())
    r.register_card(CardDefinition('grantcry', 'Grant cry', CardType.MINION, health=4,
        on_play='grant_on_play', battlecry='bc'))
    r.register_behavior('kill_target', lambda c: (Destroy(c.target_id, c.source_id),) if c.physical is not None else ())
    r.register_card(CardDefinition('targetcry', 'Target cry', CardType.MINION, health=4, battlecry='kill_target',
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')))
    r.register_behavior('fail_bc', lambda c: (PhysicalDeliberateFailure(c.source_id),) if c.physical is not None else ())
    r.register_card(CardDefinition('failcry', 'Fail cry', CardType.MINION, health=4, battlecry='fail_bc'))
    r.register_behavior('lethal_bc', lambda c: (Damage(c.state.players[2].hero_id, 100, c.source_id),)
        if c.physical is not None else ())
    r.register_card(CardDefinition('lethalcry', 'Lethal cry', CardType.MINION, health=4, battlecry='lethal_bc'))
    r.register_behavior('summon_only', lambda c: (Summon(c.player_id, 'minion'),))
    r.register_card(CardDefinition('summon_only', 'Summon only', CardType.SPELL, on_play='summon_only'))
    def listener(c):
        ledger = c.state.whole_card_replay_ledger
        if not ledger.stack: return ()
        p = ledger.children[-1].physical
        if p is None or p.phase != 'running': return ()
        if c.event.kind.startswith('battlecry_') and c.event.kind != 'battlecry_modifier_used':
            b = c.state.battlecry_history[-1]
            if b.origin != 'effect': return ()
            if p.active_battlecry_id != b.id or p.battlecry_ids[-1] != b.id:
                raise ValueError('Start/finish listener captured an unbound actual BC')
        return (RequestChoice(c.player_id, (ChoiceOption('a', 'Continue', ()),), source_id=c.source_id),)
    r.register_behavior('listener', listener)
    for suffix, event in (('start', 'battlecry_started'), ('finish', 'battlecry_finished'),
            ('used', 'battlecry_modifier_used')):
        r.register_card(CardDefinition('watch_' + suffix, 'Watcher', CardType.MINION, health=5,
            triggers=(TriggerSpec(event, 'listener'),)))
    return r


class GeneratedBattlecryRepetitionTests(unittest.TestCase):
    def game(self, hand=('minion', 'policy3', 'repeat'), board=(), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('plain',) * 8, max_mana=10, mana=10, hero_power_card_id='power'),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 8, max_mana=10, mana=10,
                hero_power_card_id='power')), seed=236), registry(), mechanics=mechanics())

    def play(self, g, name, target=None):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, source, target_id=target))

    def populated(self, name='minion', policy='policy3', repeater='repeat', **kw):
        names = (name, policy, repeater) if policy else (name, repeater)
        g = self.game(names, **kw)
        for cid in names: self.play(g, cid)
        return g

    def progress(self, g, index=0): return g.state.whole_card_replay_ledger.children[index].physical
    def mods(self, g, player=1): return g.state.players[player].battlecry_modifiers

    def raw(self, g, label):
        directory = os.environ.get('GENERATED_BC_REPEAT_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(), 'snapshot': g.snapshot(),
                    'replay': build_replay(g), 'actual_generated_battlecry_repetition': True}, f, ensure_ascii=False)

    def portable(self, g, label):
        snapshot = json.loads(json.dumps(g.snapshot()))
        branches = (Game.from_snapshot(snapshot, registry(), mechanics()), g.clone(), replay(build_replay(g), registry(), mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(branch.observe(player), g.observe(player))
                self.assertEqual(branch.player_events(player), g.player_events(player))
                self.assertEqual(branch.for_player(player).legal_actions(), g.for_player(player).legal_actions())
        self.raw(g, label); return branches

    def completed(self, name):
        g = self.populated(name); p = self.progress(g)
        self.assertEqual(p.battlecry_repeat_acceptance.plan.repetitions, 3)
        self.assertEqual(len(p.battlecry_ids), 3); self.assertEqual(p.phase, 'completed')
        self.assertEqual(self.mods(g)[0].uses_remaining, 2)
        self.assertEqual(len(g.state.play_history), 3); self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(p.activation.owner_clocks, (1, 0))
        self.assertEqual(len(g.state.owner_turn_history), 1)
        records = [g.state.battlecry_history[i - 1] for i in p.battlecry_ids]
        self.assertTrue(all(b.origin == 'effect' and b.play_id is None and b.completed for b in records))
        self.assertEqual(len({b.id for b in records}), 3); self.raw(g, 'completed'); return g

    def waiting(self, board=(), name='minion_wait'):
        g = self.populated(name, board=board); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.mods(g)[0].uses_remaining, 2)
        return g

    @staticmethod
    def rehash(snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def negative(self, mutate):
        g = self.waiting(); snapshot = deepcopy(g.snapshot()); mutate(snapshot); self.rehash(snapshot)
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(snapshot, registry(), mechanics())
        self.assertNotIn('digest mismatch', str(error.exception)); self.raw(g, 'negative-origin')

    @staticmethod
    def acceptance(s): return s['state']['whole_card_replay_ledger']['children'][0]['physical']['battlecry_repeat_acceptance']

    def test_minion_repeats_with_actual_independent_ids(self): self.completed('minion')
    def test_weapon_repeats_without_another_equipment_payment(self): self.completed('weapon')
    def test_hero_repeats_without_another_replacement(self): self.completed('herocard')
    def test_location_has_no_battlecry_acceptance_or_use(self):
        g = self.populated('location'); self.assertIsNone(self.progress(g).battlecry_repeat_acceptance)
        self.assertEqual(self.mods(g)[0].uses_remaining, 3); self.assertEqual(g.state.battlecry_policy_uses, [])
        self.raw(g, 'location-empty')
    def test_max_all_contributors_and_all_finite_once(self):
        g = self.populated(policy='policies', board=('aura2',)); accepted = self.progress(g).battlecry_repeat_acceptance
        self.assertEqual(accepted.plan.repetitions, 3); self.assertEqual(len(accepted.plan.contributors), 4)
        self.assertEqual(len(accepted.plan.consumable_ids), 2); self.assertEqual(len(accepted.modifiers), 3)
        self.assertEqual([m.uses_remaining for m in self.mods(g)], [1, None])
        self.assertEqual(sum(e.kind == 'battlecry_modifier_used' for e in g.events), 2)
        self.portable(g, 'max-all-policies')
    def test_same_family_budgets_continue_across_hand_generated_hand(self):
        g = self.game(('policy3', 'minion', 'repeat', 'minion'))
        for name in ('policy3', 'minion', 'repeat', 'minion'): self.play(g, name)
        uses = g.state.battlecry_policy_uses
        self.assertEqual(tuple(u.origin for u in uses), ('paid_hand', 'generated_body', 'paid_hand'))
        self.assertEqual(tuple(u.modifiers[0].uses_remaining for u in uses), (3, 2, 1))
        self.assertEqual(self.mods(g), []); self.assertEqual(sum(e.kind == 'battlecry_modifier_used' for e in g.events), 3)
        self.portable(g, 'shared-three-origin-transitions')
    def test_lower_policy_consumes_even_when_board_max_wins(self):
        g = self.populated(policy='policy2', board=('aura4',)); p = self.progress(g)
        self.assertEqual(p.battlecry_repeat_acceptance.plan.repetitions, 4)
        self.assertEqual(self.mods(g)[0].uses_remaining, 2); self.assertEqual(len(p.battlecry_ids), 4)
    def test_enemy_aura_does_not_contribute(self):
        g = self.populated(policy=None, enemy=('aura4',)); self.assertEqual(len(self.progress(g).battlecry_ids), 1)
        self.assertEqual(self.progress(g).battlecry_repeat_acceptance.plan.contributors, ())
    def test_nonmatching_type_policy_keeps_its_budget(self):
        g = self.populated(policy='weapon_policy'); self.assertEqual(len(self.progress(g).battlecry_ids), 1)
        self.assertEqual(self.mods(g)[0].uses_remaining, 2); self.assertEqual(self.progress(g).battlecry_repeat_acceptance.modifiers, ())
    def test_unlimited_policy_is_captured_without_consumption_event(self):
        g = self.populated(policy='unlimited'); a = self.progress(g).battlecry_repeat_acceptance
        self.assertEqual(a.plan.repetitions, 3); self.assertEqual(a.plan.consumable_ids, ())
        self.assertEqual(len(a.modifiers), 1); self.assertFalse(any(e.kind == 'battlecry_modifier_used' for e in g.events))
    def test_original_legacy_profile_keeps_single_indirect_battlecry(self):
        g = self.populated(repeater='legacy_repeat'); p = self.progress(g)
        self.assertIsNone(p.battlecry_repeat_acceptance); self.assertEqual(len(p.battlecry_ids), 1)
        self.assertEqual(self.mods(g)[0].uses_remaining, 3); self.raw(g, 'legacy-bounded')
    def test_plain_summon_does_not_accept_or_consume_battlecries(self):
        g = self.game(('policy3', 'summon_only'))
        self.play(g, 'policy3'); self.play(g, 'summon_only')
        self.assertEqual(self.mods(g)[0].uses_remaining, 3); self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.battlecry_policy_uses); self.assertFalse(g.state.whole_card_replay_ledger.children)
    def test_quantity_extras_do_not_create_extra_family_uses(self):
        g = self.populated(board=('quantity',)); p = self.progress(g)
        self.assertEqual(g.state.card_summon_history[p.summon_root_id - 1].plan.total, 2)
        self.assertEqual(len(p.battlecry_ids), 3)
        self.assertEqual(sum(u.origin == 'generated_body' for u in g.state.battlecry_policy_uses), 1)
    def test_on_play_grants_apply_only_to_the_next_acceptance(self):
        g = self.game(('grantcry', 'repeat', 'repeat'))
        for name in ('grantcry', 'repeat', 'repeat'): self.play(g, name)
        self.assertEqual(tuple(c.physical.battlecry_repeat_acceptance.plan.repetitions
            for c in g.state.whole_card_replay_ledger.children), (1, 4))
        self.assertEqual(tuple(len(c.physical.battlecry_ids) for c in g.state.whole_card_replay_ledger.children), (1, 4))
        self.assertEqual([m.uses_remaining for m in self.mods(g)], [1, 2]); self.raw(g, 'later-root-new-plan')
    def test_removed_aura_keeps_accepted_count_but_later_root_recaptures(self):
        g = self.game(('removecry', 'repeat', 'repeat'), board=('aura4',))
        for name in ('removecry', 'repeat', 'repeat'): self.play(g, name)
        self.assertEqual(tuple(len(c.physical.battlecry_ids) for c in g.state.whole_card_replay_ledger.children), (4, 1))
        self.portable(g, 'removed-original-aura')
    def test_source_silence_keeps_accepted_payload_and_count(self):
        g = self.populated('silencecry'); p = self.progress(g)
        self.assertEqual(len(p.battlecry_ids), 3); self.assertTrue(g.state.entities[p.source.entity_id].silenced)
        self.portable(g, 'silenced-primary')
    def test_each_callback_reads_own_actual_record_and_same_acceptance(self):
        g = self.populated('probecry'); self.assertEqual(len(self.progress(g).battlecry_ids), 3)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)
    def test_other_executor_uses_its_own_policy_and_has_no_paid_record(self):
        g = self.populated(policy='other_policy', repeater='other_repeat'); p = self.progress(g)
        self.assertEqual(p.player_id, 2); self.assertEqual(p.battlecry_repeat_acceptance.plan.repetitions, 3)
        self.assertEqual(self.mods(g, 2)[0].uses_remaining, 1); self.assertEqual(self.mods(g, 1), [])
        self.assertEqual(g.state.players[2].mana, 10); self.assertFalse(p.combo); self.raw(g, 'other-executor')
    def test_lost_target_is_retained_without_reselection(self):
        g = self.game(('targetcry', 'policy3', 'repeat'), enemy=('plain',))
        self.play(g, 'targetcry', g.state.players[2].board[0]); self.play(g, 'policy3'); self.play(g, 'repeat')
        p = self.progress(g); records = [g.state.battlecry_history[i - 1] for i in p.battlecry_ids]
        self.assertEqual(len(records), 3); self.assertEqual(len({b.target_id for b in records}), 1)
        self.assertIsNone(records[0].failure); self.assertTrue(all(b.failure == 'invalid_target' for b in records[1:]))
        self.assertTrue(all(b.completed for b in records)); self.portable(g, 'retained-stale-target')
    def test_first_start_listener_capture_is_bound_before_wait(self):
        g = self.waiting(board=('watch_start',), name='minion'); self.assertIsNotNone(self.progress(g).active_battlecry_id)
        branches = self.portable(g, 'first-start-wait')
        for _ in range(3):
            for branch in (g, *branches):
                c = branch.state.pending_choice; self.assertIsNotNone(c)
                branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
            for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(self.progress(g).battlecry_ids), 3)
        self.assertEqual(self.mods(g)[0].uses_remaining, 2); self.raw(g, 'all-start-waits-completed')
    def test_consumption_wait_precedes_first_body_and_consumes_once(self):
        g = self.waiting(board=('watch_used',), name='minion')
        self.assertEqual(self.progress(g).battlecry_ids, ()); branches = self.portable(g, 'consumption-wait')
        for branch in (g, *branches):
            c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(len(self.progress(g).battlecry_ids), 3); self.assertEqual(self.mods(g)[0].uses_remaining, 2)
    def test_each_body_choice_resumes_without_extra_policy_use(self):
        g = self.waiting(name='minion_bcwait'); branches = self.portable(g, 'first-body-wait')
        for _ in range(3):
            for branch in (g, *branches):
                c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
            for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(len(self.progress(g).battlecry_ids), 3); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(u.origin == 'generated_body' for u in g.state.battlecry_policy_uses), 1)
    def test_finish_listener_wait_preserves_completed_child_and_owed_next_repeat(self):
        g = self.waiting(board=('watch_finish',), name='minion'); branches = self.portable(g, 'first-finish-wait')
        self.assertTrue(g.state.battlecry_history[self.progress(g).active_battlecry_id - 1].completed)
        for _ in range(3):
            for branch in (g, *branches):
                c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
            for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(self.progress(g).battlecry_ids), 3)
        self.assertEqual(self.mods(g)[0].uses_remaining, 2)
    def test_random_body_choices_have_no_wait_and_independent_actual_records(self):
        g = self.populated('minion_bcwait', repeater='random_repeat')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(len(self.progress(g).battlecry_ids), 3)
        self.portable(g, 'random-repeated-choices')
    def test_body_exception_rolls_back_installation_rng_payment_and_use(self):
        g = self.game(('failcry', 'policy3', 'repeat')); self.play(g, 'failcry'); self.play(g, 'policy3')
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'repeat')
        self.assertEqual(g.snapshot(), before); self.raw(g, 'rolled-back-body')
    def test_resolution_budget_failure_is_atomic_without_large_expansion(self):
        g = self.game(('minion', 'huge_policy', 'repeat')); self.play(g, 'minion'); self.play(g, 'huge_policy')
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.play(g, 'repeat')
        self.assertEqual(g.snapshot(), before); self.raw(g, 'budget-rollback')
    def test_lethal_interrupts_remaining_repeats_without_fake_activations(self):
        g = self.populated('lethalcry'); self.assertEqual(g.state.status, 'finished')
        self.assertEqual(len(self.progress(g).battlecry_ids), 1); self.assertEqual(self.mods(g)[0].uses_remaining, 2)
        self.portable(g, 'lethal-interruption')
    def test_players_do_not_receive_acceptances_full_policies_or_use_ids(self):
        g = self.waiting()
        for player in (1, 2):
            view = json.dumps((g.observe(player), g.player_events(player), g.for_player(player).legal_actions()))
            for word in ('battlecry_policy_uses', 'battlecry_repeat_acceptance', 'consumable_ids', 'contributors', 'use_id', 'modifiers'):
                if word == 'modifiers': continue
                self.assertNotIn(word, view)
        self.raw(g, 'both-player-privacy')
    def test_rehashed_missing_generated_consumption_is_rejected(self):
        self.negative(lambda s: s['state']['battlecry_policy_uses'].pop())
    def test_rehashed_wrong_origin_cannot_borrow_paid_acceptance(self):
        self.negative(lambda s: s['state']['battlecry_policy_uses'][-1].update(origin='paid_hand', origin_id=1))
    def test_rehashed_surviving_budget_cannot_undo_consumption(self):
        self.negative(lambda s: s['state']['players']['1']['battlecry_modifiers'][0].update(uses_remaining=3))
    def test_rehashed_shrunken_original_max_plan_is_rejected(self):
        self.negative(lambda s: self.acceptance(s)['plan'].update(repetitions=2))
    def test_rehashed_missing_full_policy_capture_is_rejected(self):
        self.negative(lambda s: self.acceptance(s).update(modifiers=[]))
    def test_new_schema116_is_explicitly_rejected(self):
        g = self.populated(); s = g.snapshot(); s['schema_version'] = 116
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot schema version'): Game.from_snapshot(s, registry(), mechanics())
        self.raw(g, 'old-schema-negative')
    def test_empty_minion_payload_does_not_query_or_consume_repeat_policies(self):
        g = self.populated('plain'); self.assertIsNone(self.progress(g).battlecry_repeat_acceptance)
        self.assertEqual(self.mods(g)[0].uses_remaining, 3); self.assertFalse(g.state.battlecry_policy_uses)
    def test_full_board_failed_installation_does_not_consume_player_policy(self):
        g = self.populated(board=('plain',) * 6); self.assertEqual(self.progress(g).failure, 'board_full')
        self.assertIsNone(self.progress(g).battlecry_repeat_acceptance); self.assertEqual(self.mods(g)[0].uses_remaining, 3)
        self.raw(g, 'full-board-no-use')
    def test_entry_removal_prevents_body_acceptance_and_policy_use(self):
        g = self.populated(board=('killer',)); self.assertEqual(self.progress(g).failure, 'stale_installation')
        self.assertIsNone(self.progress(g).battlecry_repeat_acceptance); self.assertEqual(self.mods(g)[0].uses_remaining, 3)
        self.raw(g, 'stale-entry-no-use')


if __name__ == '__main__': unittest.main()
