"""Real generated body acceptances, distinct origins and frozen prerequisites."""
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.errors import SnapshotError
from hs_sim.engine.generated_activation_receipts import GeneratedActivationReceipt
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from tests.test_whole_card_physical_runtime import registry as original_registry, mechanics


def registry():
    r = original_registry()
    def probe(c):
        if c.physical is None:
            if c.generated_activation is not None: raise ValueError('Paid body borrowed generated provenance')
            return ()
        receipt = c.generated_activation
        if (type(receipt) is not GeneratedActivationReceipt or receipt.source.entity_id != c.source_id
                or receipt.player_id != c.player_id or receipt.combo != c.spell_conditions.combo):
            raise ValueError('Body lost its exact independent receipt')
        return (GainArmor(c.player_id, 16),)
    r.register_behavior('probe', probe)
    r.register_card(CardDefinition('probe', 'Probe', CardType.MINION, health=4, on_play='probe'))
    r.register_card(CardDefinition('thirst', 'Thirst', CardType.MINION, health=4, on_play='probe',
        manathirst=7, keywords=(Keyword.MANATHIRST,)))
    def nested(c):
        if c.physical is None: return ()
        return (ReplayWholeCards(c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=(CardType.LOCATION,)),
            physical_profile=PROFILE),)
    r.register_behavior('nested', nested)
    r.register_card(CardDefinition('nested', 'Nested', CardType.MINION, health=4, on_play='nested'))
    return r


class GeneratedActivationReceiptTests(unittest.TestCase):
    def game(self, hand=('minion', 'rerun'), board=(), enemy=(), max_mana=10):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('plain',) * 8, max_mana=max_mana, mana=max_mana, hero_power_card_id='power'),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 8, max_mana=10, mana=10,
                hero_power_card_id='power')), seed=235), registry(), mechanics=mechanics())

    def play(self, g, name, target=None):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, source, target_id=target))

    def populated(self, name='minion', **kw):
        g = self.game((name, 'rerun'), **kw); self.play(g, name); self.play(g, 'rerun'); return g

    def progress(self, g, index=0): return g.state.whole_card_replay_ledger.children[index].physical
    def receipt(self, g, index=0): return self.progress(g, index).activation

    def portable(self, g, label='accepted'):
        snapshot = json.loads(json.dumps(g.snapshot())); payload = build_replay(g)
        branches = (Game.from_snapshot(snapshot, registry(), mechanics()), g.clone(), replay(payload, registry(), mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(branch.observe(player), g.observe(player))
                self.assertEqual(branch.player_events(player), g.player_events(player))
                self.assertEqual(branch.for_player(player).legal_actions(), g.for_player(player).legal_actions())
        directory = os.environ.get('GENERATED_ACTIVATION_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(), 'snapshot': snapshot,
                    'replay': payload, 'actual_generated_acceptance': True}, f, ensure_ascii=False)
        return branches

    def accepted(self, name):
        g = self.populated(name); receipt = self.receipt(g); child = g.state.whole_card_replay_ledger.children[0]
        root = g.state.whole_card_replay_ledger.roots[0]
        self.assertEqual(receipt.key, ('whole_card_history', root.id, child.id))
        self.assertEqual(receipt.profile_id, PROFILE); self.assertEqual(receipt.occurrence_id, 1)
        self.assertEqual(receipt.source, self.progress(g).source); self.assertEqual(receipt.issuer, root.caster)
        self.assertNotEqual(receipt.source.entity_id, g.state.play_history[0].source_id)
        self.assertEqual(receipt.before_play_id, 3); self.assertEqual(receipt.combo_play_ids, (1, 2))
        self.assertEqual(receipt.owner_clocks, (1, 0)); self.assertEqual(receipt.owner_turn_id, 1)
        self.assertEqual(receipt.action, 2); self.assertEqual(len(g.state.play_history), 2)
        self.portable(g); return g

    @staticmethod
    def rehash(snapshot):
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def negative(self, mutate, name='minion_wait'):
        g = self.populated(name); bad = deepcopy(g.snapshot()); mutate(bad); self.rehash(bad)
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(bad, registry(), mechanics())
        self.assertNotIn('digest mismatch', str(error.exception)); self.portable(g, 'valid-negative-origin')

    @staticmethod
    def wire(s): return s['state']['whole_card_replay_ledger']['children'][0]['physical']['activation']

    def test_minion_acceptance_has_original_source_and_history(self): self.accepted('minion')
    def test_weapon_acceptance_has_actual_equipped_source(self): self.accepted('weapon')
    def test_location_acceptance_does_not_use_location(self):
        g = self.accepted('location'); self.assertEqual(g.state.entities[self.receipt(g).source.entity_id].uses_this_turn, 0)
    def test_hero_acceptance_has_actual_replaced_source(self): self.accepted('herocard')
    def test_trusted_behavior_reads_receipt_without_hand_play(self):
        g = self.accepted('probe'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 16)
    def test_other_executor_has_empty_combo_prefix(self):
        g = self.game(('minion', 'other')); self.play(g, 'minion'); self.play(g, 'other')
        receipt = self.receipt(g)
        self.assertEqual(receipt.player_id, 2); self.assertEqual(receipt.issuer.controller, 1)
        self.assertEqual(receipt.source.controller, 2); self.assertFalse(receipt.combo)
        self.assertEqual(receipt.combo_play_ids, ()); self.assertEqual(receipt.owner_turn_id, 1)
        self.assertEqual(self.progress(g).combos, ()); self.portable(g)
    def test_other_executor_manathirst_uses_its_own_maximum(self):
        g = self.game(('thirst', 'other'), max_mana=4); self.play(g, 'thirst'); self.play(g, 'other')
        self.assertEqual(self.receipt(g).max_mana, 10); self.assertTrue(self.receipt(g).manathirst); self.portable(g)
    def test_manathirst_preserves_accepted_maximum_mana(self):
        g = self.populated('thirst', max_mana=6)
        self.assertEqual(self.receipt(g).max_mana, 6); self.assertFalse(self.receipt(g).manathirst); self.portable(g)
    def test_real_new_owner_interval_and_clocks(self):
        g = self.game(('minion', 'rerun')); self.play(g, 'minion')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'rerun')
        receipt = self.receipt(g)
        self.assertEqual(receipt.owner_turn_id, 3); self.assertEqual(receipt.owner_clocks, (2, 1))
        self.assertEqual(receipt.combo_play_ids, (2,)); self.assertEqual(receipt.turn, 3); self.portable(g)
    def test_later_paid_play_does_not_rewrite_old_prefix(self):
        g = self.game(('minion', 'rerun', 'plain')); self.play(g, 'minion'); self.play(g, 'rerun')
        receipt = self.receipt(g); self.play(g, 'plain')
        self.assertEqual(self.receipt(g), receipt); self.assertEqual(receipt.before_play_id, 3); self.portable(g)
    def test_same_card_occurrences_have_independent_acceptances(self):
        g = self.game(('minion', 'minion', 'rerun'))
        for name in ('minion', 'minion', 'rerun'): self.play(g, name)
        receipts = (self.receipt(g, 0), self.receipt(g, 1))
        self.assertNotEqual(receipts[0].key, receipts[1].key)
        self.assertNotEqual(receipts[0].source.entity_id, receipts[1].source.entity_id)
        self.assertEqual(tuple(r.occurrence_id for r in receipts), (1, 2)); self.portable(g)
    def test_later_replay_root_recaptures_paid_frontier(self):
        g = self.game(('minion', 'rerun', 'rerun')); self.play(g, 'minion'); self.play(g, 'rerun'); self.play(g, 'rerun')
        first, second = self.receipt(g, 0), self.receipt(g, 1)
        self.assertEqual((first.root_id, second.root_id), (1, 2))
        self.assertEqual((first.before_play_id, second.before_play_id), (3, 4)); self.portable(g)
    def test_nested_actual_child_keeps_separate_parent_and_issuer(self):
        g = self.game(('location', 'nested', 'rerun'))
        for name in ('location', 'nested', 'rerun'): self.play(g, name)
        ledger = g.state.whole_card_replay_ledger; nested = ledger.roots[1]
        child = ledger.children[-1]; receipt = child.physical.activation
        self.assertEqual(receipt.root_id, nested.id); self.assertEqual(receipt.parent_child_id, 2)
        self.assertEqual(receipt.issuer.entity_id, ledger.children[1].physical.source.entity_id)
        self.assertEqual(len(g.state.play_history), 3); self.portable(g)
    def test_quantity_extras_do_not_allocate_extra_body_receipts(self):
        g = self.populated(board=('quantity',)); p = self.progress(g)
        self.assertEqual(g.state.card_summon_history[p.summon_root_id - 1].plan.total, 2)
        self.assertEqual(len(g.state.whole_card_replay_ledger.children), 1)
        self.assertEqual(self.receipt(g).source, g.state.card_summon_history[p.summon_root_id - 1].deliveries[0].entity)
        self.portable(g)
    def test_entry_wait_has_no_body_acceptance_until_actual_window(self):
        g = self.populated(board=('watcher',)); self.assertIsNone(self.receipt(g))
        branches = self.portable(g, 'before-acceptance')
        for branch in (g, *branches):
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('a',)))
        self.assertEqual(self.receipt(g).action, 3)
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.portable(g, 'after-acceptance')
    def test_body_wait_resume_retains_original_receipt(self):
        g = self.populated('minion_wait'); receipt = self.receipt(g); branches = self.portable(g, 'body-wait')
        for branch in (g, *branches):
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('a',)))
        self.assertEqual(self.receipt(g), receipt)
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.portable(g, 'body-resumed')
    def test_battlecry_wait_owns_same_generated_acceptance(self):
        g = self.populated('minion_bcwait'); receipt = self.receipt(g)
        self.assertIsNotNone(self.progress(g).active_battlecry_id); branches = self.portable(g, 'battlecry-wait')
        for branch in (g, *branches):
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('a',)))
        self.assertEqual(self.receipt(g), receipt)
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.portable(g, 'battlecry-resumed')
    def test_stale_installation_never_fabricates_acceptance(self):
        g = self.populated(board=('killer',)); self.assertIsNone(self.receipt(g))
        self.assertEqual(self.progress(g).failure, 'stale_installation'); self.portable(g)
    def test_full_board_never_fabricates_acceptance(self):
        g = self.populated(board=('plain',) * 6); self.assertIsNone(self.receipt(g))
        self.assertEqual(self.progress(g).failure, 'board_full'); self.portable(g)
    def test_receipts_stay_private_to_both_player_ports(self):
        g = self.populated('minion_wait')
        for player in (1, 2):
            view = json.dumps((g.observe(player), g.player_events(player), g.for_player(player).legal_actions()))
            for key in ('GeneratedActivationReceipt', 'combo_play_ids', 'before_play_id', 'owner_clocks', 'issuer', 'profile_id'):
                self.assertNotIn(key, view)
        self.portable(g)
    def test_missing_independent_receipt_is_rejected(self):
        self.negative(lambda s: s['state']['whole_card_replay_ledger']['children'][0]['physical'].update(activation=None))
    def test_borrowed_child_identity_is_rejected(self): self.negative(lambda s: self.wire(s).update(child_id=999))
    def test_borrowed_root_identity_is_rejected(self): self.negative(lambda s: self.wire(s).update(root_id=999))
    def test_borrowed_occurrence_is_rejected(self): self.negative(lambda s: self.wire(s).update(occurrence_id=2))
    def test_fabricated_paid_origin_is_rejected(self): self.negative(lambda s: self.wire(s).update(origin='paid_hand'))
    def test_unknown_origin_profile_is_rejected(self): self.negative(lambda s: self.wire(s).update(profile_id='unknown'))
    def test_other_executor_is_rejected(self): self.negative(lambda s: self.wire(s).update(player_id=2))
    def test_erased_prerequisite_is_rejected(self): self.negative(lambda s: self.wire(s).update(combo_play_ids=[1]))
    def test_future_prerequisite_is_rejected(self): self.negative(lambda s: self.wire(s).update(combo_play_ids=[1, 2, 3]))
    def test_shortened_history_frontier_is_rejected(self): self.negative(lambda s: self.wire(s).update(before_play_id=2, combo_play_ids=[1]))
    def test_future_owner_interval_is_rejected(self): self.negative(lambda s: self.wire(s).update(owner_turn_id=2))
    def test_borrowed_owner_clocks_is_rejected(self): self.negative(lambda s: self.wire(s).update(owner_clocks=[1, 1]))
    def test_future_acceptance_action_is_rejected(self): self.negative(lambda s: self.wire(s).update(action=999))
    def test_substituted_issuer_is_rejected(self):
        self.negative(lambda s: self.wire(s)['issuer'].update(entity_id=self.wire(s)['source']['entity_id']))
    def test_missing_wire_field_is_rejected(self): self.negative(lambda s: self.wire(s).pop('max_mana'))
    def test_finished_receipt_cannot_borrow_later_paid_root(self):
        g = self.game(('minion', 'rerun', 'plain')); self.play(g, 'minion'); self.play(g, 'rerun'); self.play(g, 'plain')
        bad = deepcopy(g.snapshot()); self.wire(bad).update(combo_play_ids=[1, 2, 3], before_play_id=4)
        self.rehash(bad)
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry(), mechanics())
        self.portable(g)
    def test_previous_schema115_cannot_infer_receipts(self):
        g = self.populated(); bad = g.snapshot(); bad['schema_version'] = 115
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot schema version'): Game.from_snapshot(bad, registry(), mechanics())
        self.portable(g)
