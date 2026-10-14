"""Real generated Combo records, family plans and shared policy budgets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor,
    RandomDamage, RequestChoice, Summon)
from hs_sim.engine.errors import SnapshotError, ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.model import BattlecryRepeatSpec, ComboRepeatSpec
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.generated_combo_repeats import PROFILE
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE as LEGACY
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from tests.test_m5_combo_matching import fixture_registry, metadata, specification


def registry():
    r = fixture_registry()
    def probe(c):
        if c.physical is not None and c.physical.activation.profile_id == PROFILE and (c.play is not None or c.combo is None
                or c.combo.play_id is not None or c.combo.batch_id is not None
                or c.combo.physical_child_id != c.physical.child_id
                or c.combo.id not in c.physical.combo_ids or c.physical.active_combo_id != c.combo.id):
            raise ValueError('Generated Combo lost its actual independent execution identity')
        return (GainArmor(c.player_id, 1),)
    r.register_behavior('gen.probe', probe)
    r.register_behavior('gen.wait_body', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),), source_id=c.source_id),))
    r.register_behavior('gen.remove', lambda c: (Destroy(c.source_id),)
        if c.physical is not None and c.combo.repeat_index == 1 else (GainArmor(c.player_id, 1),))
    r.register_behavior('gen.fail_body', lambda c: (RandomDamage((c.state.players[2].hero_id,), 1),
        Summon(c.player_id, 'unregistered.generated.body')) if c.physical is not None else ())
    r.register_behavior('gen.lethal_body', lambda c: (Damage(c.state.players[2].hero_id, 100),)
        if c.physical is not None else ())
    for name, behavior, meta in (('gen.minion', 'gen.probe', metadata(('dragon',))),
            ('gen.wait', 'gen.wait_body', metadata(('dragon',))),
            ('gen.remove_source', 'gen.remove', metadata(('dragon',))),
            ('gen.fail', 'gen.fail_body', metadata(('dragon',))),
            ('gen.lethal', 'gen.lethal_body', metadata(('dragon',))),
            ('gen.empty', 'empty', metadata(('dragon',))), ('gen.unknown', 'gen.probe', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=1, health=6,
            combo=behavior, keywords=(Keyword.COMBO,), metadata=meta))
    r.register_card(CardDefinition('gen.weapon', 'Weapon', CardType.WEAPON, cost=1, attack=2,
        durability=3, combo='gen.probe', keywords=(Keyword.COMBO,)))
    r.register_card(CardDefinition('gen.hero', 'Hero card', CardType.HERO, cost=1, health=30,
        hero_card=True, initial_hero_power='power', combo='gen.probe', keywords=(Keyword.COMBO,)))
    r.register_card(CardDefinition('gen.location', 'Location', CardType.LOCATION, cost=1,
        durability=3, on_use='armor'))
    r.register_card(CardDefinition('gen.blank', 'Blank', CardType.MINION, cost=1, health=6))
    r.register_card(CardDefinition('gen.mixed', 'Mixed', CardType.MINION, cost=1, health=6,
        battlecry='armor', combo='gen.probe', keywords=(Keyword.COMBO,), metadata=metadata()))
    all_kinds = (CardType.MINION, CardType.WEAPON, CardType.HERO)
    for name, callback in (
            ('gen.policy', lambda c: (AddComboRepeatModifier(c.player_id, ComboRepeatSpec(3, all_kinds),
                c.source_id, uses=3, trigger='activation'),)),
            ('gen.both', lambda c: (AddComboRepeatModifier(c.player_id, ComboRepeatSpec(7, all_kinds),
                c.source_id, uses=3, trigger='play'), AddComboRepeatModifier(c.player_id,
                ComboRepeatSpec(3, all_kinds), c.source_id, uses=3, trigger='activation'))),
            ('gen.all', lambda c: (AddComboRepeatModifier(c.player_id, ComboRepeatSpec(2, all_kinds),
                c.source_id, uses=1, trigger='activation'), AddComboRepeatModifier(c.player_id,
                ComboRepeatSpec(3, all_kinds), c.source_id, uses=2, trigger='activation'),
                AddComboRepeatModifier(c.player_id, ComboRepeatSpec(2, all_kinds), c.source_id,
                    trigger='activation'))),
            ('gen.tribal', lambda c: (AddComboRepeatModifier(c.player_id,
                specification(3, tribes=('dragon',)), c.source_id, uses=2, trigger='activation'),)),
            ('gen.huge', lambda c: (AddComboRepeatModifier(c.player_id, ComboRepeatSpec(1000000),
                c.source_id, uses=1, trigger='activation'),)),
            ('gen.mixed_policy', lambda c: (AddBattlecryRepeatModifier(c.player_id,
                BattlecryRepeatSpec(2, all_kinds), c.source_id, uses=2),
                AddComboRepeatModifier(c.player_id, ComboRepeatSpec(3, all_kinds), c.source_id,
                    uses=2, trigger='activation')))):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    def repeated(c, profile=PROFILE, player=None):
        return (ReplayWholeCards(c.player_id if player is None else player, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1,
                kinds=(CardType.MINION, CardType.WEAPON, CardType.HERO, CardType.LOCATION)),
            physical_profile=profile, choices='player'),)
    for name, callback in (('gen.repeat', repeated), ('gen.legacy', lambda c: repeated(c, LEGACY)),
            ('gen.other', lambda c: repeated(c, player=2))):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, on_play=name))
    def watch(c):
        ledger = c.state.whole_card_replay_ledger
        if not ledger.stack:
            return ()
        root = ledger.roots[ledger.stack[-1] - 1]
        if root.active_child_id is None:
            return ()
        progress = ledger.children[root.active_child_id - 1].physical
        if c.event.kind in ('combo_started', 'combo_finished'):
            if dict(c.event.data).get('play_id') is not None:
                return ()
            if c.combo is None or progress is None or c.combo.id != progress.active_combo_id:
                raise ValueError('Generated start/finish context captured an unbound Combo identity')
        return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', ()),), source_id=c.source_id),)
    r.register_behavior('gen.watch', watch)
    for name, event in (('gen.watch_start', 'combo_started'), ('gen.watch_finish', 'combo_finished'),
            ('gen.watch_use', 'combo_modifier_used')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            triggers=(TriggerSpec(event, 'gen.watch'),)))
    return r


class GeneratedComboRepetitionTests(unittest.TestCase):
    def game(self, hand=('gen.minion', 'gen.policy', 'gen.repeat'), board=(), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            max_mana=10, mana=10, deck=('plain',) * 6, hero_power_card_id='power'),
            PlayerSetup('hero', board=enemy, max_mana=10, mana=10, deck=('plain',) * 6,
                hero_power_card_id='power')), seed=238), registry())

    def play(self, g, name):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, source))

    def populated(self, name='gen.minion', policy='gen.policy', repeater='gen.repeat', **kw):
        names = (name, policy, repeater)
        g = self.game(names, **kw)
        for cid in names:
            self.play(g, cid)
        return g

    def progress(self, g):
        return g.state.whole_card_replay_ledger.children[0].physical

    def raw(self, g, label):
        directory = os.environ.get('GENERATED_COMBO_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(),
                    'snapshot': g.snapshot(), 'replay': build_replay(g),
                    'actual_generated_combo_repetition': True}, f, ensure_ascii=False)

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        copies = (Game.from_snapshot(snapshot, registry()), g.clone(), replay(build_replay(g), registry()))
        for branch in copies:
            self.assertEqual(branch.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(branch.observe(player), g.observe(player))
                self.assertEqual(branch.for_player(player).legal_actions(), g.for_player(player).legal_actions())
        self.raw(g, 'portable')
        return copies

    def complete(self, name):
        g = self.populated(name)
        p = self.progress(g)
        self.assertEqual(p.combo_repeat_acceptance.plan.repetitions, 3)
        self.assertEqual(len(p.combo_ids), 3)
        self.assertEqual(p.phase, 'completed')
        self.assertEqual(len(g.state.play_history), 3)
        self.assertTrue(all(r.play_id is None and r.batch_id is None and r.completed
            and r.physical_child_id == p.child_id for r in g.state.combo_history))
        self.assertEqual([r.repeat_index for r in g.state.combo_history], [1, 2, 3])
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 2)
        self.raw(g, 'completed')
        return g

    def test_generated_minion_has_actual_ids_and_one_use(self): self.complete('gen.minion')
    def test_generated_weapon_has_actual_ids_without_paid_play(self): self.complete('gen.weapon')
    def test_generated_hero_has_actual_ids_without_paid_replacement(self): self.complete('gen.hero')

    def test_generated_policy_excludes_larger_play_window(self):
        g = self.populated(policy='gen.both')
        self.assertEqual(self.progress(g).combo_repeat_acceptance.plan.repetitions, 3)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [3, 2])
        self.raw(g, 'activation-only')

    def test_complete_max_consumes_lower_finite_and_keeps_unlimited(self):
        g = self.populated(policy='gen.all', board=('friendly.5',))
        accepted = self.progress(g).combo_repeat_acceptance
        self.assertEqual(accepted.plan.repetitions, 5)
        self.assertEqual(len(accepted.plan.contributors), 4)
        self.assertEqual(len(accepted.plan.consumable_ids), 2)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [1, None])
        self.assertEqual(len(self.progress(g).combo_ids), 5)
        self.raw(g, 'complete-max')

    def test_enemy_repeat_source_does_not_enter_plan(self):
        g = self.populated(enemy=('friendly.5',))
        self.assertEqual(self.progress(g).combo_repeat_acceptance.plan.repetitions, 3)
        self.raw(g, 'enemy-source')

    def test_paid_generated_paid_share_exact_activation_budget(self):
        g = self.game(('gen.both', 'gen.minion', 'gen.repeat', 'gen.minion'))
        for name in ('gen.both', 'gen.minion', 'gen.repeat', 'gen.minion'):
            self.play(g, name)
        self.assertEqual([r.repeat_index for r in g.state.combo_history],
            list(range(1, 8)) + [1, 2, 3] + list(range(1, 8)))
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [1])
        self.assertEqual(len(g.state.combo_batches), 2)
        self.assertEqual(len(g.state.play_history), 4)
        self.assertEqual(sum(r.origin == 'generated_body' for r in g.state.combo_policy_receipts), 1)
        self.portable(g)

    def test_battlecry_and_combo_have_separate_max_and_uses(self):
        g = self.populated('gen.mixed', policy='gen.mixed_policy')
        p = self.progress(g)
        self.assertEqual(len(p.battlecry_ids), 2)
        self.assertEqual(len(p.combo_ids), 3)
        self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining, 1)
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 1)
        self.raw(g, 'mixed-family')

    def test_single_profile_records_combo_without_consuming_repeat_policy(self):
        g = self.populated(repeater='gen.legacy')
        p = self.progress(g)
        self.assertEqual(p.combo_repeat_acceptance.plan.repetitions, 1)
        self.assertEqual(p.combo_repeat_acceptance.plan.contributors, ())
        self.assertEqual(p.combo_repeat_acceptance.plan.consumable_ids, ())
        self.assertEqual(len(p.combo_ids), 1)
        self.assertTrue(g.state.combo_history[p.combo_ids[0] - 1].completed)
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 3)
        self.raw(g, 'single-actual-combo')

    def test_location_does_not_fabricate_combo_family(self):
        g = self.populated('gen.location')
        self.assertIsNone(self.progress(g).combo_repeat_acceptance)
        self.assertEqual(g.state.combo_history, [])
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 3)
        self.raw(g, 'location')

    def test_empty_declaration_retains_explicit_no_payload(self):
        g = self.populated('gen.blank')
        self.assertEqual(self.progress(g).combo_repeat_acceptance.status, 'no_payload')
        self.assertEqual(g.state.combo_history, [])
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 3)
        self.raw(g, 'no-payload')

    def test_empty_effect_still_has_actual_completed_invocations(self): self.complete('gen.empty')

    def test_consumption_start_body_and_finish_waits_restore(self):
        for board, name in ((('gen.watch_use',), 'gen.minion'), (('gen.watch_start',), 'gen.minion'),
                ((), 'gen.wait'), (('gen.watch_finish',), 'gen.minion')):
            g = self.populated(name, board=board)
            self.assertIsNotNone(g.state.pending_choice)
            self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 2)
            branches = (g, *self.portable(g))
            while g.state.pending_choice is not None:
                action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
                for branch in branches:
                    branch.apply(action)
                self.assertTrue(all(branch.snapshot() == g.snapshot() for branch in branches))
            self.assertEqual(len(self.progress(g).combo_ids), 3)
            self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 2)
            self.raw(g, 'all-waits-completed')

    def test_accepted_source_removal_preserves_later_repetitions(self):
        g = self.complete('gen.remove_source')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.portable(g)

    def test_lethal_stops_unstarted_repetitions_without_invented_ids(self):
        g = self.populated('gen.lethal')
        self.assertNotEqual(g.state.status, 'playing')
        self.assertEqual(len(g.state.combo_history), 1)
        self.assertTrue(g.state.combo_history[0].interrupted)
        self.assertEqual(self.progress(g).combo_repeat_acceptance.plan.repetitions, 3)
        self.portable(g)

    def test_body_failure_rolls_back_payment_history_uses_and_rng(self):
        g = self.game(('gen.fail', 'gen.policy', 'gen.repeat'))
        self.play(g, 'gen.fail'); self.play(g, 'gen.policy')
        before = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)):
            self.play(g, 'gen.repeat')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'rollback')

    def test_huge_plan_budget_error_is_atomic(self):
        g = self.game(('gen.minion', 'gen.huge', 'gen.repeat'))
        self.play(g, 'gen.minion'); self.play(g, 'gen.huge')
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(g, 'gen.repeat')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'budget')

    def test_needed_unknown_metadata_rejects_without_deleting_candidate(self):
        g = self.game(('gen.unknown', 'gen.tribal', 'gen.repeat'))
        self.play(g, 'gen.unknown'); self.play(g, 'gen.tribal')
        before = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)):
            self.play(g, 'gen.repeat')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'unknown')

    def test_other_executor_disabled_gate_has_no_policy_or_invocation(self):
        g = self.populated(repeater='gen.other')
        p = self.progress(g)
        self.assertEqual(p.player_id, 2)
        self.assertEqual(p.combo_repeat_acceptance.status, 'disabled')
        self.assertIsNone(p.combo_repeat_acceptance.plan)
        self.assertEqual(p.combo_ids, ())
        self.raw(g, 'other-executor')

    def test_rehashed_waiting_records_and_policy_cannot_borrow_paid_identity(self):
        g = self.populated('gen.wait')
        original = g.snapshot()
        def record_paid(s): s['state']['combo_history'][-1]['play_id'] = 1
        def record_child(s): s['state']['combo_history'][-1]['physical_child_id'] += 1
        def no_use(s): s['state']['combo_policy_receipts'][-1]['consumption_applied'] = False
        def trim_ids(s): s['state']['whole_card_replay_ledger']['children'][0]['physical']['combo_ids'] = []
        for mutate in (record_paid, record_child, no_use, trim_ids):
            snapshot = deepcopy(original); mutate(snapshot)
            snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError) as error:
                Game.from_snapshot(snapshot, registry())
            self.assertNotIn('digest mismatch', str(error.exception))
        self.raw(g, 'negative-origins')
