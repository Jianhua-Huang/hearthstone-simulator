"""Real late-result BC and Combo start/body/finish choice boundaries."""
import json
from hs_sim.engine import CardDefinition, CardType, Game, Keyword, PlayerSetup, Scenario, SelectChoice, TriggerSpec
from hs_sim.engine.effects import ChoiceOption, GainArmor, RandomDamage, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import RewindSpec
from hs_sim.engine.replay import build_replay, replay
from tests.test_m5_combo_matching import metadata
import unittest
from tests import test_generated_intrinsic_retention as intrinsic_fixture
base_registry = intrinsic_fixture.registry


def registry():
    r = base_registry()
    def late(record, family):
        return record.iteration == 2 and record.repeat_index == (2 if family == 'bc' else 3)
    def listener(c):
        family = 'bc' if c.event.kind.startswith('battlecry_') else 'combo'
        rows = c.state.battlecry_history if family == 'bc' else c.state.combo_history
        key = 'battlecry_id' if family == 'bc' else 'combo_id'
        actual = rows[dict(c.event.data)[key] - 1]
        if actual.physical_child_id is None or not late(actual, family): return ()
        progress = c.state.whole_card_replay_ledger.children[actual.physical_child_id - 1].physical
        active = progress.active_battlecry_id if family == 'bc' else progress.active_combo_id
        if active != actual.id or actual.outcome_id != progress.outcome_id:
            raise ValueError('Late family listener lost the actual active result identity')
        return (RequestChoice(c.player_id, (ChoiceOption('ok', family, ()),), source_id=c.source_id),)
    r.register_behavior('intr.late_listener', listener)
    for name, events in (('intr.watch_late_start', ('battlecry_started', 'combo_started')),
                         ('intr.watch_late_finish', ('battlecry_finished', 'combo_finished'))):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=6,
            triggers=tuple(TriggerSpec(event, 'intr.late_listener') for event in events)))
    def body(c, family):
        effects = r.behavior('intr.bc' if family == 'bc' else 'intr.combo')(c)
        actual = c.battlecry if family == 'bc' else c.combo
        if c.physical is None or not late(actual, family): return effects
        return (RequestChoice(c.player_id, (ChoiceOption('ok', family, effects),), source_id=c.source_id),)
    r.register_behavior('intr.late_bc', lambda c: body(c, 'bc'))
    r.register_behavior('intr.late_combo', lambda c: body(c, 'combo'))
    r.register_card(CardDefinition('intr.late_body', 'Late bodies', CardType.MINION, cost=1, health=6,
        on_play='intr.body', battlecry='intr.late_bc', combo='intr.late_combo',
        keywords=(Keyword.COMBO, Keyword.REWIND), rewind=RewindSpec(), metadata=metadata()))
    def random_then_fail(c):
        if c.physical is None: return (GainArmor(c.player_id, 1),)
        p = c.physical
        outcome = c.state.rewind_outcomes[p.outcome_id - 1]
        if c.rewind_attempt == 0:
            return (RandomDamage((c.state.players[2].hero_id,), 1), GainArmor(c.player_id, 1))
        if (c.rewind_attempt, outcome.completed, p.cursor, len(p.battlecry_ids), len(p.combo_ids),
                c.state.entities[c.state.players[2].hero_id].damage) != (1, 1, 7, 2, 3, 1):
            raise ValueError('Rollback probe did not reach the second real result after first damage and families')
        return (Summon(c.player_id, 'unregistered.intrinsic.random_result'),)
    r.register_behavior('intr.random_then_fail', random_then_fail)
    r.register_card(CardDefinition('intr.random_failure', 'Random then fail', CardType.MINION, cost=1, health=6,
        on_play='intr.random_then_fail', battlecry='intr.bc', combo='intr.combo',
        keywords=(Keyword.COMBO, Keyword.REWIND), rewind=RewindSpec(), metadata=metadata()))
    return r


class GeneratedIntrinsicRetentionBoundaryTests(unittest.TestCase):
    play = intrinsic_fixture.GeneratedIntrinsicRetentionTests.play
    populated = intrinsic_fixture.GeneratedIntrinsicRetentionTests.populated
    progress = intrinsic_fixture.GeneratedIntrinsicRetentionTests.progress
    raw = intrinsic_fixture.GeneratedIntrinsicRetentionTests.raw
    def prepared_game(self, name='intr.normal', holders=1, board=()):
        hand = (name, 'gen.mixed_policy', 'intr.one', 'intr.replay')
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, max_mana=10, mana=10,
            deck=('plain',) * 6, hero_power_card_id='power'), PlayerSetup('hero', max_mana=10, mana=10,
            deck=('plain',) * 6, hero_power_card_id='power')), seed=242), registry())
        for cid in hand[:-1]:
            self.play(g, cid)
            if cid == name and g.state.pending_choice is not None:
                g.apply(SelectChoice(1, g.state.pending_choice.id, ('keep',)))
        return g

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        copies = (Game.from_snapshot(snapshot, registry()), g.clone(), replay(build_replay(g), registry()))
        self.assertTrue(all(copy.snapshot() == snapshot for copy in copies))
        for player in (1, 2):
            self.assertTrue(all(copy.observe(player) == g.observe(player) for copy in copies))
        self.raw(g, 'late-portable')
        return copies

    def late_boundaries(self, *, window, name='intr.normal', board=()):
        g = self.populated(name=name, board=board)
        for family, cursor, repeat in (('bc', 9, 2), ('combo', 12, 3)):
            self.assertIsNotNone(g.state.pending_choice)
            p = self.progress(g)
            active = p.active_battlecry_id if family == 'bc' else p.active_combo_id
            rows = g.state.battlecry_history if family == 'bc' else g.state.combo_history
            actual = rows[active - 1]
            outcome = g.state.rewind_outcomes[p.outcome_id - 1]
            self.assertEqual((p.cursor, outcome.completed, outcome.running), (cursor, 1, True))
            self.assertEqual((actual.iteration, actual.repeat_index, actual.completed), (2, repeat, window == 'finish'))
            copies = self.portable(g)
            action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
            g.apply(action)
            for copy in copies:
                copy.apply(action)
                self.assertEqual(copy.snapshot(), g.snapshot())
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((self.progress(g).phase, g.state.rewind_outcomes[0].completed), ('completed', 2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 19)
        self.raw(g, 'late-completed')

    def test_second_result_last_battlecry_and_combo_start_choices_are_portable(self):
        self.late_boundaries(window='start', board=('intr.watch_late_start',))

    def test_second_result_last_battlecry_and_combo_body_choices_are_portable(self):
        self.late_boundaries(window='body', name='intr.late_body')

    def test_second_result_last_battlecry_and_combo_finish_choices_are_portable(self):
        self.late_boundaries(window='finish', board=('intr.watch_late_finish',))

    def test_second_result_failure_after_actual_random_damage_restores_complete_transaction(self):
        g = self.prepared_game(name='intr.random_failure')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unregistered.intrinsic.random_result'):
            self.play(g, 'intr.replay')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'random-damage-rolled-back')
