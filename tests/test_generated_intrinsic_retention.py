"""Execute actual intrinsic generated results, not an outer paid repetition."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import CardDefinition, CardType, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, GainArmor, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import ComboRepeatSpec, RewindSpec
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.generated_retained_outcomes import PROFILE
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from tests.test_generated_combo_repetition import registry as base_registry
from tests.test_m5_combo_matching import metadata


def registry():
    r = base_registry()
    r.register_card(CardDefinition('intr.holder', 'Holder', CardType.MINION, health=6, retain_rewind_outcomes=True))
    def check(c, family):
        if c.physical is None:
            return
        p = c.physical
        if p.activation.profile_id != PROFILE or p.retained_acceptance is None or c.play is not None or c.cast is not None:
            raise ValueError('Intrinsic result borrowed another real activation origin')
        if p.outcome_id is not None:
            record = c.state.rewind_outcomes[p.outcome_id - 1]
            if not record.running or record.physical_child_id != p.child_id or c.rewind_attempt != record.completed:
                raise ValueError('Intrinsic result lost its running real physical identity')
            if family is not None:
                actual = c.battlecry if family == 'bc' else c.combo
                if actual is None or (actual.physical_child_id, actual.outcome_id, actual.iteration) != (p.child_id, record.id, record.completed + 1):
                    raise ValueError('Actual generated family lost its result iteration')
    def body(c):
        check(c, None)
        if c.physical is None:
            return (GainArmor(c.player_id, 1),)
        mode = c.physical.card_id
        if mode == 'intr.lethal':
            return (Damage(c.state.players[2].hero_id, 100),)
        if mode == 'intr.remove' and c.rewind_attempt == 0:
            return (*tuple(Destroy(i) for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == 'intr.holder'), GainArmor(c.player_id, 1))
        if mode == 'intr.wait':
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),), source_id=c.source_id),)
        if mode == 'intr.future' and c.rewind_attempt == 0:
            return (AddComboRepeatModifier(c.player_id, ComboRepeatSpec(9), c.source_id, uses=3, trigger='activation'), GainArmor(c.player_id, 1))
        if mode == 'intr.fail' and c.rewind_attempt == 1:
            return (Summon(c.player_id, 'unregistered.intrinsic.result'),)
        return (GainArmor(c.player_id, 1),)
    def bc(c):
        check(c, 'bc')
        return (GainArmor(c.player_id, 2),)
    def combo(c):
        check(c, 'combo')
        return (GainArmor(c.player_id, 1),)
    r.register_behavior('intr.body', body)
    r.register_behavior('intr.bc', bc)
    r.register_behavior('intr.combo', combo)
    for name in ('intr.normal', 'intr.wait', 'intr.remove', 'intr.lethal', 'intr.future', 'intr.fail'):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=1, health=6, on_play='intr.body',
            battlecry='intr.bc', combo='intr.combo', keywords=(Keyword.COMBO, Keyword.REWIND), rewind=RewindSpec(), metadata=metadata()))
    for name, spec in (('intr.face2', RewindSpec(2, 'intr.face1')), ('intr.face1', RewindSpec(1, 'intr.face0')), ('intr.face0', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=1, health=6, on_play='intr.body',
            battlecry='intr.bc', combo='intr.combo', keywords=(Keyword.COMBO, Keyword.REWIND) if spec else (Keyword.COMBO,),
            rewind=spec, metadata=metadata()))
    for name, count in (('intr.one', 1), ('intr.two', 2)):
        r.register_behavior(name, lambda c, n=count: tuple(Summon(c.player_id, 'intr.holder') for _ in range(n)))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('intr.replay', lambda c: (ReplayWholeCards(c.player_id, c.source_id,
        WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.MINION,)),
        physical_profile=PROFILE, choices='player'),))
    r.register_card(CardDefinition('intr.replay', 'Replay', CardType.SPELL, cost=1, on_play='intr.replay'))
    return r


class GeneratedIntrinsicRetentionTests(unittest.TestCase):
    def prepared_game(self, name='intr.normal', holders=1, board=()):
        hand = (name, 'gen.mixed_policy') + (('intr.two' if holders == 2 else 'intr.one',) if holders else ()) + ('intr.replay',)
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, max_mana=10, mana=10,
            deck=('plain',) * 6, hero_power_card_id='power'), PlayerSetup('hero', max_mana=10, mana=10,
            deck=('plain',) * 6, hero_power_card_id='power')), seed=242), registry())
        for cid in hand[:-1]:
            self.play(g, cid)
            if cid == name and g.state.pending_choice is not None:
                g.apply(SelectChoice(1, g.state.pending_choice.id, ('keep',)))
        return g

    def play(self, g, cid):
        identity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(1, identity))

    def populated(self, **kw):
        g = self.prepared_game(**kw)
        self.play(g, 'intr.replay')
        return g

    def progress(self, g): return g.state.whole_card_replay_ledger.children[0].physical

    def raw(self, g, label):
        directory = os.environ.get('INTRINSIC_RETENTION_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            path = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'actual_intrinsic_physical_results': True,
                    'method_id': self.id(), 'snapshot': g.snapshot(), 'replay': build_replay(g)}, f, ensure_ascii=False)

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        copies = (Game.from_snapshot(snapshot, registry()), g.clone(), replay(build_replay(g), registry()))
        self.assertTrue(all(copy.snapshot() == snapshot for copy in copies))
        for player in (1, 2):
            self.assertTrue(all(copy.observe(player) == g.observe(player) for copy in copies))
        self.raw(g, 'portable')
        return copies

    def test_two_real_results_have_one_install_and_independent_actual_family_ids(self):
        g = self.populated()
        p = self.progress(g)
        self.assertEqual((p.phase, p.cursor, p.retained_acceptance.total), ('completed', 12, 2))
        self.assertEqual(len(g.state.rewind_outcomes), 1)
        outcome = g.state.rewind_outcomes[0]
        self.assertEqual((outcome.physical_child_id, outcome.play_id, outcome.cast_id, outcome.power_id), (p.child_id, None, None, None))
        self.assertEqual((outcome.completed, outcome.finished), (2, True))
        bc = [b for b in g.state.battlecry_history if b.physical_child_id == p.child_id]
        combos = [c for c in g.state.combo_history if c.physical_child_id == p.child_id]
        self.assertEqual([b.iteration for b in bc], [1, 1, 2, 2])
        self.assertEqual([b.repeat_index for b in bc], [1, 2, 1, 2])
        self.assertEqual([c.iteration for c in combos], [1, 1, 1, 2, 2, 2])
        self.assertEqual([c.repeat_index for c in combos], [1, 2, 3, 1, 2, 3])
        self.assertEqual(len(g.state.play_history), 4)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 19)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].battlecry_modifiers], [1])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [1])
        self.raw(g, 'completed')

    def test_absent_holder_uses_declared_profile_without_fabricating_outcome(self):
        g = self.populated(holders=0)
        p = self.progress(g)
        self.assertEqual((p.retained_acceptance.status, p.retained_acceptance.total), ('no_holder', 1))
        self.assertIsNone(p.outcome_id)
        self.assertEqual(g.state.rewind_outcomes, [])
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (2, 3))
        self.raw(g, 'no-holder')

    def test_two_holders_do_not_stack_and_removal_keeps_accepted_second_result(self):
        g = self.populated(name='intr.remove', holders=2)
        p = self.progress(g)
        self.assertEqual((len(p.retained_acceptance.holders), p.retained_acceptance.total), (2, 2))
        self.assertFalse(any(g.state.entities[i].card_id == 'intr.holder' for i in g.state.players[1].board))
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (4, 6))
        self.raw(g, 'removed-holders')

    def test_consumption_and_each_result_wait_restore_clone_and_replay(self):
        g = self.populated(name='intr.wait', board=('gen.watch_use',))
        boundaries = 0
        while g.state.pending_choice is not None:
            boundaries += 1
            copies = self.portable(g)
            action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
            g.apply(action)
            for copy in copies:
                copy.apply(action)
                self.assertEqual(copy.snapshot(), g.snapshot())
        self.assertEqual(boundaries, 3)
        self.assertEqual(self.progress(g).cursor, 12)
        self.assertEqual(g.state.rewind_outcomes[0].completed, 2)
        self.raw(g, 'all-waits-completed')

    def test_new_policy_in_first_result_does_not_replace_frozen_family_plan(self):
        g = self.populated(name='intr.future')
        p = self.progress(g)
        self.assertEqual(p.retained_acceptance.combo_plan.repetitions, 3)
        self.assertEqual(len(p.combo_ids), 6)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].combo_modifiers], [1, 3])
        self.raw(g, 'future-policy')

    def test_persistent_faces_advance_one_source_with_three_actual_result_groups(self):
        g = self.populated(name='intr.face2')
        p = self.progress(g)
        self.assertEqual((p.card_id, g.state.entities[p.source.entity_id].card_id), ('intr.face2', 'intr.face0'))
        self.assertEqual((g.state.rewind_outcomes[0].total, g.state.rewind_outcomes[0].completed), (3, 3))
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (6, 9))
        self.portable(g)

    def test_lethal_first_result_interrupts_without_inventing_later_family_ids(self):
        g = self.populated(name='intr.lethal')
        p = self.progress(g)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertTrue(g.state.rewind_outcomes[0].interrupted)
        self.assertEqual((g.state.rewind_outcomes[0].completed, p.cursor, p.battlecry_ids, p.combo_ids), (0, 1, (), ()))
        self.portable(g)

    def test_second_result_error_rolls_back_payment_accepted_uses_first_result_and_rng(self):
        g = self.prepared_game(name='intr.fail')
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unregistered.intrinsic.result'):
            self.play(g, 'intr.replay')
        self.assertEqual(g.snapshot(), before)
        self.raw(g, 'rolled-back')

    def test_rehashed_result_origin_iteration_cursor_and_group_finish_are_rejected(self):
        g = self.populated(name='intr.wait')
        original = g.snapshot()
        def paid(s): s['state']['rewind_outcomes'][-1]['play_id'] = 1
        def child(s): s['state']['rewind_outcomes'][-1]['physical_child_id'] += 1
        def cursor(s): s['state']['whole_card_replay_ledger']['children'][0]['physical']['cursor'] += 6
        def iteration(s): s['state']['rewind_outcomes'][-1]['completed'] += 1
        def quota(s): s['state']['whole_card_replay_ledger']['children'][0]['physical']['retained_acceptance']['total'] = 3
        def finish(s):
            frame = s['resolution_frame']['fields']
            removed = 0
            for field in ('prefix', 'continuation'):
                rows = frame[field]['tuple']
                kept = [row for row in rows if row.get('type') != 'hs_sim.engine.rewind_outcomes.FinishRewindOutcomes']
                removed += len(rows) - len(kept)
                frame[field]['tuple'] = kept
            self.assertEqual(removed, 1)
        for mutate in (paid, child, cursor, iteration, quota, finish):
            snapshot = deepcopy(original); mutate(snapshot)
            snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError) as error:
                Game.from_snapshot(snapshot, registry())
            self.assertNotIn('digest mismatch', str(error.exception))
        self.raw(g, 'negative-actual-origins')

    def test_players_do_not_receive_intrinsic_origin_or_acceptance_proofs(self):
        g = self.populated(name='intr.wait')
        for player in (1, 2):
            payload = json.dumps(g.for_player(player).observe(), ensure_ascii=False)
            for forbidden in ('rewind_outcomes', 'retained_acceptance', 'physical_child_id', 'before_outcome_id', 'ability_ids'):
                self.assertNotIn(forbidden, payload)
        self.raw(g, 'masked-players')
