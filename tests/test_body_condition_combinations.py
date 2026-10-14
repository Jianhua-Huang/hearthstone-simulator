"""Actual paid/generated body conditions composed with repeats and retained results."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (BodyReference, BodyPlayReference, IfBodyCondition,
    body_play_conditions, GrantBattlecry, GrantCombo, CardDefinition, CardType,
    Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeManaCrystals, ChoiceOption, GainArmor,
    RandomDamage, RequestChoice, Summon)
from hs_sim.engine.model import BattlecryRepeatSpec, ComboRepeatSpec, RewindSpec
from hs_sim.engine.battlecry_modifiers import AddBattlecryRepeatModifier
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.generated_retained_outcomes import PROFILE
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.registry import Registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards


def registry(mode='normal'):
    r = Registry('body-condition-combinations-' + mode + '-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, health=6))
    r.register_card(CardDefinition('holder', 'Holder', CardType.MINION, health=6,
        retain_rewind_outcomes=True))
    r.register_behavior('primary', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('unit', 'Unit', CardType.MINION, cost=1, health=6,
        on_play='primary', rewind=RewindSpec(), manathirst=3, keywords=(Keyword.REWIND, Keyword.MANATHIRST)))

    def body(c, family):
        ref = BodyPlayReference.capture(c, family)
        decision = IfBodyCondition(ref, 'manathirst',
            (GainArmor(c.player_id, 5 if family == 'battlecry' else 3),),
            (GainArmor(c.player_id, 1),))
        effects = []
        if family == 'battlecry' and ref.declaration_card_id == 'threshold5' and ref.repeat_index == 1:
            effects.append(ChangeManaCrystals(c.player_id, -5))
            if mode == 'future' and ref.iteration == 1:
                effects.extend((AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(9), c.source_id, uses=3),
                    AddComboRepeatModifier(c.player_id, ComboRepeatSpec(9), c.source_id, uses=3, trigger='activation')))
        if mode == 'fail_second' and family == 'battlecry' and ref.declaration_card_id == 'threshold9' and ref.iteration == 2 and ref.repeat_index == 2:
            return (RandomDamage((c.state.players[2].hero_id,), 1, source_id=c.source_id),
                Summon(c.player_id, 'unregistered.second.condition.result'))
        if mode == 'wait' and ((family == 'battlecry' and ref.declaration_card_id == 'threshold5' and ref.repeat_index == 2) or
                (family == 'combo' and ref.declaration_card_id == 'threshold9' and ref.repeat_index == 3)):
            effects.append(RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id))
        return (*effects, decision)

    r.register_behavior('bc', lambda c: body(c, 'battlecry'))
    r.register_behavior('combo', lambda c: body(c, 'combo'))
    for threshold in (5, 9):
        r.register_card(CardDefinition('threshold' + str(threshold), 'Threshold', CardType.MINION,
            health=6, battlecry='bc', combo='combo', manathirst=threshold,
            keywords=(Keyword.MANATHIRST, Keyword.COMBO)))

    def grants(c, entity):
        reference = BodyReference.capture(entity)
        return tuple(kind(reference, 'threshold' + str(threshold), c.source_id)
            for kind in (GrantBattlecry, GrantCombo) for threshold in (5, 9))

    def setup(c):
        result = [AddBattlecryRepeatModifier(c.player_id, BattlecryRepeatSpec(2), c.source_id, uses=2),
            AddComboRepeatModifier(c.player_id, ComboRepeatSpec(3), c.source_id, uses=2, trigger='activation'),
            Summon(c.player_id, 'holder')]
        unit = next((e for e in c.state.entities.values() if e.card_id == 'unit' and e.zone == Zone.HAND and e.controller == c.player_id), None)
        if unit is not None:
            result.extend(grants(c, unit))
        return tuple(result)

    r.register_behavior('setup', setup)
    r.register_card(CardDefinition('setup', 'Setup', CardType.SPELL, on_play='setup'))
    def watch(c):
        unit = c.state.entities[c.event.target_id]
        return grants(c, unit) if unit.card_id == 'unit' else ()
    r.register_behavior('watch', watch)
    r.register_card(CardDefinition('watcher', 'Watcher', CardType.MINION, health=6,
        triggers=(TriggerSpec('minion_summoned', 'watch'),)))
    r.register_behavior('replay', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,)),
        physical_profile=PROFILE, choices='player'),))
    r.register_card(CardDefinition('replay', 'Replay', CardType.SPELL, cost=1, on_play='replay'))
    return r


class BodyConditionCompositionTests(unittest.TestCase):
    def game(self, mode='normal', generated=True):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=('unit', 'setup', 'replay') if generated else ('setup', 'unit'),
            board=('watcher',) if generated else (), deck=('plain',) * 3, max_mana=6, mana=6),
            PlayerSetup('hero', deck=('plain',) * 3, max_mana=6, mana=6)), seed=247), registry(mode))

    def play(self, g, name):
        s = g.state
        entity_id = next(i for i in s.players[1].hand if s.entities[i].card_id == name)
        g.apply(PlayCard(1, entity_id))

    def prepared(self, mode='normal', generated=True):
        g = self.game(mode, generated)
        if generated:
            self.play(g, 'unit')
            if g.state.pending_choice:
                self.assertIn('keep', [o.id for o in g.state.pending_choice.options])
                g.apply(SelectChoice(1, g.state.pending_choice.id, ('keep',)))
        self.play(g, 'setup')
        return g

    def populated(self, mode='normal', generated=True):
        g = self.prepared(mode, generated)
        self.play(g, 'replay' if generated else 'unit')
        return g

    def portable(self, g, mode):
        snapshot = json.loads(json.dumps(g.snapshot()))
        copies = (g.clone(), Game.from_snapshot(snapshot, registry(mode)), replay(build_replay(g), registry(mode)))
        for copy in copies:
            self.assertEqual(copy.snapshot(), snapshot)
            for seat in (1, 2):
                self.assertEqual(copy.for_player(seat).observe(), g.for_player(seat).observe())
        return copies

    def raw(self, g, label):
        directory = os.environ.get('BODY_CONDITION_COMBINATION_RAW')
        if directory:
            destination = Path(directory) / self.id() / (label + '.json')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'snapshot': g.snapshot(), 'replay': build_replay(g)}, f, ensure_ascii=False)

    def assert_completed(self, g, generated):
        s = g.state
        bcs, combos = s.battlecry_history, s.combo_history
        self.assertEqual((len(bcs), len(combos)), (8, 12))
        self.assertEqual([b.iteration for b in bcs], [1] * 4 + [2] * 4)
        self.assertEqual([c.iteration for c in combos], [1] * 6 + [2] * 6)
        self.assertEqual([b.repeat_index for b in bcs], [1, 2, 1, 2] * 2)
        self.assertEqual([c.repeat_index for c in combos], [1, 2, 3, 1, 2, 3] * 2)
        self.assertEqual(s.entities[s.players[1].hero_id].armor, 51 if generated else 50)
        self.assertEqual(s.players[1].max_mana, 0)
        self.assertEqual(len(s.play_history), 3 if generated else 2)
        outcome = s.rewind_outcomes[-1]
        self.assertEqual((outcome.total, outcome.completed, outcome.finished), (2, 2, True))
        for family, records in (('battlecry', bcs), ('combo', combos)):
            for record in records:
                self.assertEqual(record.outcome_id, outcome.id)
                self.assertEqual(record.play_id is None, generated)
                self.assertEqual(record.physical_child_id is not None, generated)
                facts = body_play_conditions(s, g.registry, BodyPlayReference.from_record(record, family))
                self.assertEqual(facts.mana_crystals, 6)
                self.assertEqual(facts.manathirst, record.payload.card_id == 'threshold5')
                self.assertTrue(facts.combo)
                if generated:
                    self.assertEqual((facts.outcast, facts.finale, facts.quickdraw), (False, False, False))
        self.assertEqual([m.uses_remaining for m in s.players[1].battlecry_modifiers[:1]], [1])
        self.assertEqual([m.uses_remaining for m in s.players[1].combo_modifiers[:1]], [1])
        checks = [dict(e.data) for e in g.events if e.kind == 'body_condition_checked']
        self.assertEqual(len(checks), 20)
        self.assertEqual([e['result'] for e in checks], ([True] * 2 + [False] * 2 + [True] * 3 + [False] * 3) * 2)

    def test_actual_generated_retained_results_and_both_repeat_families_use_original_conditions(self):
        g = self.populated()
        self.assert_completed(g, True)
        self.portable(g, 'normal')
        self.raw(g, 'generated-completed')

    def test_actual_paid_retained_results_and_both_repeat_families_use_original_conditions(self):
        g = self.populated(generated=False)
        self.assert_completed(g, False)
        self.portable(g, 'normal')
        self.raw(g, 'paid-completed')

    def test_later_repeat_policies_cannot_replace_either_accepted_family_plan(self):
        g = self.populated('future')
        self.assert_completed(g, True)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].battlecry_modifiers], [1, 3])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [1, 3])
        self.portable(g, 'future')
        self.raw(g, 'new-policies-not-accepted')

    def test_four_real_repeat_result_waits_resume_restore_clone_replay_and_hide_proofs(self):
        g = self.populated('wait')
        count = 0
        while g.state.pending_choice:
            count += 1
            copies = self.portable(g, 'wait')
            for seat in (1, 2):
                wire = json.dumps(g.for_player(seat).observe()) + json.dumps(g.player_events(seat))
                for hidden in ('body_condition_checked', 'BodyPlayReference', 'physical_child_id', 'retained_acceptance', 'activation_id'):
                    self.assertNotIn(hidden, wire)
            self.raw(g, 'waiting-' + str(count))
            action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
            g.apply(action)
            for copy in copies:
                copy.apply(action)
                self.assertEqual(copy.snapshot(), g.snapshot())
        self.assertEqual(count, 4)
        self.assert_completed(g, True)
        self.portable(g, 'wait')
        self.raw(g, 'all-waits-completed')

    def test_second_result_failure_rolls_back_paid_root_first_result_uses_and_rng(self):
        g = self.prepared('fail_second')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unregistered.second.condition.result'):
            self.play(g, 'replay')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'second-result-rolled-back')

    def test_waiting_second_result_cannot_borrow_completed_first_result_condition_identity(self):
        g = self.populated('wait')
        for _ in range(2):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('ok',)))
        self.assertEqual(g.state.rewind_outcomes[-1].completed, 1)
        def references(value):
            if isinstance(value, dict):
                if value.get('type') == 'hs_sim.engine.body_conditions.BodyPlayReference':
                    yield value
                for item in value.values():
                    yield from references(item)
            elif isinstance(value, list):
                for item in value:
                    yield from references(item)
        original = g.snapshot()
        ref = next(references(original['resolution_frame']))['fields']
        self.assertEqual((ref['family'], ref['iteration'], ref['repeat_index']), ('battlecry', 2, 2))
        completed = next(b for b in g.state.battlecry_history if b.iteration == 1 and b.repeat_index == 2 and b.payload.card_id == 'threshold5')
        old = BodyPlayReference.from_record(completed, 'battlecry')
        for name, value in (('activation_id', old.activation_id), ('iteration', old.iteration), ('repeat_index', 1), ('physical_child_id', old.physical_child_id + 1)):
            bad = deepcopy(original)
            next(references(bad['resolution_frame']))['fields'][name] = value
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError) as error:
                Game.from_snapshot(bad, registry('wait'))
            self.assertNotIn('digest mismatch', str(error.exception))
        bad = deepcopy(original)
        next(references(bad['resolution_frame']))['fields'].update(vars(old))
        bad['state_hash'] = canonical_hash({k: v for k, v in bad.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad, registry('wait'))
        self.raw(g, 'second-result-condition-identities')
