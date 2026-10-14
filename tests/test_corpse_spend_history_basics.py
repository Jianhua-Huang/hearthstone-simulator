"""Persistent actual corpse units; no native price adapter or new executor."""
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError, replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CorpseSpendRecord, CostSpec, EndTurn,
    Game, IllegalAction, PaymentType, PlayerSetup, PlayCard, ResolutionError, Resource,
    Scenario, SelectChoice, SnapshotError, SpendUpToResource, TriggerSpec, UseHeroPower,
    corpse_spends, spent_corpses, resource_result)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage, Effect,
    GainArmor, GainResource, InvokeBehavior, RequestChoice, SpendResource)
from hs_sim.engine.resources import corpse_spend_from_event, validate_corpse_boundary
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from opening_fixtures import metadata, registry as opening_registry
import test_v142_capped_resource as capped
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


@dataclass(frozen=True)
class SavedCorpseRow(Effect):
    row: CorpseSpendRecord

    def __post_init__(self):
        if type(self.row) is not CorpseSpendRecord:
            raise ValueError('Expected one complete original debit row')
        self.row.__post_init__()


@dataclass(frozen=True)
class PretendCorpseDebit(Effect):
    pass


def typed_mechanics():
    return default_mechanics('b71-corpse-typed-test').register(SavedCorpseRow,
        lambda r, work: (GainArmor(r.state.players[work.row.player_id].hero_id, work.row.amount),)).register(
        PretendCorpseDebit, lambda r, work: r.emit('corpses_spent', player_id=1, amount=9))


def registry():
    r = opening_registry()
    r.register_behavior('debit.noop', lambda c: ())

    def choice(c):
        row = corpse_spends(c.state, c.player_id)[-1]
        return (RequestChoice(c.player_id, (
            ChoiceOption('done', 'Apply original saved units', (SavedCorpseRow(row),)),
            ChoiceOption('fault', 'Fail after original debit', (InvokeBehavior('debit.fault', c.source_id, c.player_id),)),
        ), c.source_id),)

    scripts = {
        'debit.fixed': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 2),),
        'debit.cap': lambda c: (SpendUpToResource(c.player_id, Resource.CORPSES, 3, c.source_id),),
        'debit.sourceless': lambda c: (SpendUpToResource(c.player_id, Resource.CORPSES, 3),),
        'debit.cap.zero': lambda c: (SpendUpToResource(c.player_id, Resource.CORPSES, 0),),
        'debit.fixed.zero': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 0),),
        'debit.skip': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 99),),
        'debit.required': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 99, required=True),),
        'debit.gain': lambda c: (GainResource(c.player_id, Resource.CORPSES, 4),),
        'debit.mode': lambda c: (AddCostModifier(c.player_id, CostSpec(payment=PaymentType.CORPSES,
            card_types=(CardType.SPELL, CardType.HERO_POWER),
            card_ids=('debit.paid', 'debit.power', 'debit.paid.zero'))),),
        'debit.fault': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 1),
            AddToHand(c.player_id, 'unknown.corpse.rollback')),
        'debit.fixed.wait': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 2,
            on_success=(InvokeBehavior('debit.choose', c.source_id, c.player_id),)),),
        'debit.cap.wait': lambda c: (SpendUpToResource(c.player_id, Resource.CORPSES, 3, c.source_id, 'debit.choose'),),
        'debit.terminal': lambda c: (SpendResource(c.player_id, Resource.CORPSES, 2,
            on_success=(Damage(c.state.players[3-c.player_id].hero_id, 30, c.source_id),)),),
        'debit.fake': lambda c: (PretendCorpseDebit(),),
    }
    scripts['debit.choose'] = choice
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        if cid != 'debit.choose':
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    for cid, cost in (('debit.paid', 3), ('debit.paid.zero', 0)):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=cost, on_play='debit.noop', metadata=metadata()))
    r.register_card(CardDefinition('debit.power', 'Corpse account power', CardType.HERO_POWER,
        cost=2, on_use='debit.noop', metadata=metadata(collectible=False)))
    r.register_behavior('debit.observe', lambda c: (GainArmor(c.state.players[c.player_id].hero_id,
        spent_corpses(c.state, c.player_id)),))
    r.register_card(CardDefinition('debit.watch', 'Original spending observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('resource_spent', 'debit.observe'),), metadata=metadata()))
    r.register_behavior('debit.paid.wait', lambda c: choice(c) if c.event.player_id == c.player_id else ())
    r.register_card(CardDefinition('debit.paid.watch', 'Original corpse payment observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('corpses_spent', 'debit.paid.wait'),), metadata=metadata()))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class CorpseSpendHistoryTests(unittest.TestCase):
    def game(self, hand=(), *, corpses=8, enemy_corpses=5, enemy_hand=(), board=(), power=None, typed=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, corpses=corpses, mana=10, max_mana=10,
                        deck=('card.1',)*2, hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, corpses=enemy_corpses,
                        mana=10, max_mana=10, deck=('card.1',)*2)), seed=22), registry(),
            mechanics=typed_mechanics() if typed else None)

    def play(self, g, cid):
        player = g.state.active_player
        eid = next(eid for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
        g.apply(PlayCard(player, eid))
        return eid

    def choose(self, g, option='done'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g, *, typed=False):
        saved = json.loads(json.dumps(g.snapshot()))
        mechanics = typed_mechanics() if typed else None
        restored = Game.from_snapshot(saved, registry(), mechanics)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(), mechanics=typed_mechanics() if typed else None).snapshot(), saved)
        for player in (1, 2): self.assertEqual(restored.observe(player), g.observe(player))
        return restored

    def test_empty_original_bank_is_not_spending_and_query_is_pure(self):
        g = self.game(corpses=20)
        saved = g.snapshot()
        self.assertEqual((corpse_spends(g.state, 1), spent_corpses(g.state, 1)), ((), 0))
        self.assertEqual(g.snapshot(), saved)

    def test_fixed_capped_and_currency_payments_form_one_complete_unit_prefix(self):
        g = self.game(('debit.fixed', 'debit.cap', 'debit.mode', 'debit.paid'))
        for cid in ('debit.fixed', 'debit.cap', 'debit.mode', 'debit.paid'): self.play(g, cid)
        rows = corpse_spends(g.state, 1)
        self.assertEqual([(r.id, r.origin, r.amount, r.balance_before, r.balance_after) for r in rows],
                         [(1, 'fixed', 2, 8, 6), (2, 'capped', 3, 6, 3), (3, 'payment', 3, 3, 0)])
        self.assertEqual(spent_corpses(g.state, 1), 8)
        self.assertEqual(len(g.state.resource_operations), 0)
        self.assertEqual((rows[0].source_id, rows[1].operation_id), (None, 1))
        self.portable(g)

    def test_capped_amount_is_actual_units_not_requested_cap_or_operation_count(self):
        g = self.game(('debit.cap',), corpses=1)
        self.play(g, 'debit.cap')
        row = g.state.corpse_spend_history[0]
        event = next(e for e in g.events if e.kind == 'resource_spent')
        result = resource_result(event)
        self.assertEqual((spent_corpses(g.state, 1), row.amount, result.cap, result.actual_amount), (1, 1, 3, 1))
        self.assertEqual(corpse_spend_from_event(event), row)
        self.assertEqual(row.operation_id, result.operation_id)

    def test_completed_capped_result_leaves_persistent_debit_after_pending_finishes(self):
        g = self.game(('debit.cap',))
        self.play(g, 'debit.cap')
        self.assertEqual((g.state.resource_operations, len(g.state.corpse_spend_history), spent_corpses(g.state, 1)), ([], 1, 3))
        self.portable(g)

    def test_source_less_capped_result_keeps_explicit_none_source(self):
        g = self.game(('debit.sourceless',))
        self.play(g, 'debit.sourceless')
        row = corpse_spends(g.state, 1)[0]
        self.assertEqual((row.source_id, row.source_card_id, row.origin, row.amount), (None, None, 'capped', 3))
        self.portable(g)

    def test_zero_fixed_capped_and_currency_debits_keep_complete_zero_rows(self):
        g = self.game(('debit.fixed.zero', 'debit.cap.zero', 'debit.mode', 'debit.paid.zero'), corpses=0)
        for cid in ('debit.fixed.zero', 'debit.cap.zero', 'debit.mode', 'debit.paid.zero'): self.play(g, cid)
        self.assertEqual([r.origin for r in g.state.corpse_spend_history], ['fixed', 'capped', 'payment'])
        self.assertEqual([r.amount for r in g.state.corpse_spend_history], [0, 0, 0])
        self.assertEqual(spent_corpses(g.state, 1), 0)
        self.portable(g)

    def test_skip_gain_and_mana_payment_do_not_add_a_corpse_debit(self):
        g = self.game(('debit.skip', 'debit.gain', 'coin'), corpses=0)
        for cid in ('debit.skip', 'debit.gain', 'coin'): self.play(g, cid)
        self.assertEqual((g.state.players[1].resources[Resource.CORPSES], g.state.corpse_spend_history), (4, []))
        self.assertTrue(any(e.kind == 'resource_payment_skipped' for e in g.events))

    def test_required_insufficiency_rolls_back_every_original_root_and_event(self):
        g = self.game(('debit.required',), corpses=1)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'debit.required')
        self.assertEqual(g.snapshot(), saved)

    def test_partial_debit_then_body_failure_restores_balance_prefix_and_ids(self):
        g = self.game(('debit.fixed', 'debit.fault'))
        self.play(g, 'debit.fixed')
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'debit.fault')
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(spent_corpses(g.state, 1), 2)

    def test_resource_reaction_queries_see_original_debit_before_later_payload(self):
        g = self.game(('debit.fixed', 'debit.cap'), board=('debit.watch',))
        self.play(g, 'debit.fixed')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.play(g, 'debit.cap')
        self.assertEqual((spent_corpses(g.state, 1), g.state.entities[g.state.players[1].hero_id].armor), (5, 7))

    def test_actual_other_player_and_current_turn_queries_are_independent(self):
        g = self.game(('debit.fixed',), enemy_hand=('debit.cap',))
        self.play(g, 'debit.fixed')
        g.apply(EndTurn(1)); self.play(g, 'debit.cap')
        self.assertEqual((spent_corpses(g.state, 1), spent_corpses(g.state, 2)), (2, 3))
        self.assertEqual((spent_corpses(g.state, 1, turn=2), spent_corpses(g.state, 2, turn=2)), (0, 3))
        self.assertEqual(spent_corpses(g.state, 1, before_id=2), 2)
        self.portable(g)

    def test_hero_power_currency_payment_uses_same_persistent_account_fact(self):
        g = self.game(('debit.mode',), power='debit.power')
        self.play(g, 'debit.mode')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        row = corpse_spends(g.state, 1)[0]
        self.assertEqual((row.origin, row.source_card_id, row.amount, spent_corpses(g.state, 1)), ('payment', 'debit.power', 2, 2))
        self.portable(g)

    def test_insufficient_currency_payment_cannot_leave_a_nominal_debit(self):
        g = self.game(('debit.mode', 'debit.paid'), corpses=2)
        self.play(g, 'debit.mode')
        saved = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, 'debit.paid')
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(spent_corpses(g.state, 1), 0)

    def test_fixed_waiting_saved_row_typed_frame_restores_and_resumes(self):
        g = self.game(('debit.fixed.wait',), typed=True)
        self.play(g, 'debit.fixed.wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(spent_corpses(g.state, 1), 2)
        restored = self.portable(g, typed=True)
        self.choose(restored); self.choose(g)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(len(g.state.corpse_spend_history), 1)

    def test_capped_waiting_retains_original_result_and_one_saved_history_row(self):
        g = self.game(('debit.cap.wait',), typed=True)
        self.play(g, 'debit.cap.wait')
        self.assertEqual((len(g.state.resource_operations), spent_corpses(g.state, 1)), (1, 3))
        restored = self.portable(g, typed=True)
        self.choose(restored); self.choose(g)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((len(g.state.resource_operations), len(g.state.corpse_spend_history), spent_corpses(g.state, 1)), (0, 1, 3))

    def test_paid_waiting_original_payment_projection_keeps_exact_debit(self):
        g = self.game(('debit.mode', 'debit.paid'), board=('debit.paid.watch',), typed=True)
        self.play(g, 'debit.mode'); self.play(g, 'debit.paid')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(spent_corpses(g.state, 1), 3)
        restored = self.portable(g, typed=True)
        self.choose(restored); self.choose(g)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((spent_corpses(g.state, 1), g.state.play_history[-1].cost), (3, 3))

    def test_waiting_fault_rolls_back_to_saved_committed_debit_boundary(self):
        g = self.game(('debit.cap.wait',), typed=True)
        self.play(g, 'debit.cap.wait')
        saved = self.portable(g, typed=True).snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(spent_corpses(g.state, 1), 3)

    def test_terminal_payload_preserves_accepted_actual_debit(self):
        g = self.game(('debit.terminal',))
        self.play(g, 'debit.terminal')
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual((spent_corpses(g.state, 1), len(g.state.corpse_spend_history)), (2, 1))
        self.portable(g)

    def test_pretend_spending_event_cannot_create_a_resource_fact(self):
        g = self.game(('debit.fake',), typed=True)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'debit.fake')
        self.assertEqual(g.snapshot(), saved)

    def test_query_filters_and_player_types_are_strict_and_read_only(self):
        g = self.game(('debit.fixed',)); self.play(g, 'debit.fixed')
        saved = g.snapshot()
        for player, args in ((True, {}), (0, {}), (1, {'turn': True}), (1, {'turn': 0}),
                             (1, {'before_id': True}), (1, {'before_id': 0})):
            with self.subTest(player=player, args=args), self.assertRaises(ValueError):
                corpse_spends(g.state, player, **args)
        self.assertEqual(spent_corpses(g.state, 1, before_id=1), 0)
        self.assertEqual(g.snapshot(), saved)

    def test_records_are_frozen_and_reject_unknown_or_inconsistent_debits(self):
        g = self.game(('debit.fixed',)); self.play(g, 'debit.fixed')
        row = corpse_spends(g.state, 1)[0]
        with self.assertRaises(FrozenInstanceError): row.amount = 7
        for changes in (dict(id=True), dict(player_id=True), dict(turn=0), dict(action=True), dict(amount=-1),
                        dict(origin='unknown'), dict(balance_after=1), dict(source_id=5, source_card_id='coin'),
                        dict(operation_id=1), dict(origin='payment')):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(row, **changes)

    def test_rehashed_wire_rejects_missing_extra_reordered_truncated_and_future_rows(self):
        g = self.game(('debit.fixed', 'debit.cap')); self.play(g, 'debit.fixed'); self.play(g, 'debit.cap')
        saved = g.snapshot()
        for mode in ('missing', 'extra', 'truncate', 'reverse', 'id', 'amount', 'player', 'turn', 'action', 'source', 'operation'):
            bad = deepcopy(saved); rows = bad['state']['corpse_spend_history']
            if mode == 'missing': del bad['state']['corpse_spend_history']
            elif mode == 'extra': rows[0]['invented'] = True
            elif mode == 'truncate': rows.pop()
            elif mode == 'reverse': rows.reverse()
            elif mode == 'id': rows[0]['id'] = 2
            elif mode == 'amount': rows[0]['amount'] = True
            elif mode == 'player': rows[0]['player_id'] = 2
            elif mode == 'turn': rows[0]['turn'] = 2
            elif mode == 'action': rows[0]['action'] += 1
            elif mode == 'source': rows[1]['source_card_id'] = 'unknown.original.corpse'
            else: rows[1]['operation_id'] += 1
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_rehashed_event_cannot_drop_or_rewrite_original_debit_envelope(self):
        g = self.game(('debit.fixed',)); self.play(g, 'debit.fixed')
        saved = g.snapshot()
        index = next(i for i, event in enumerate(saved['events']) if event['kind'] == 'resource_spent')
        for mode in ('missing', 'amount', 'player', 'payload', 'extra'):
            bad = deepcopy(saved); event = bad['events'][index]
            if mode == 'missing': del event['data']['corpse_spend']
            elif mode == 'amount': event['amount'] += 1
            elif mode == 'player': event['player_id'] = 2
            elif mode == 'payload': event['data']['corpse_spend'] = []
            else: event['data']['corpse_spend'].append(['invented', 1])
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_views_do_not_export_internal_history_or_debit_payload(self):
        g = self.game(('debit.fixed',), enemy_hand=('debit.cap',)); self.play(g, 'debit.fixed')
        for player in (1, 2):
            text = json.dumps(g.for_player(player).observe())
            for private in ('corpse_spend_history', 'corpse_spend', 'balance_before', 'source_card_id', 'operation_id'):
                self.assertNotIn(private, text)
        self.assertNotIn('debit.cap', json.dumps(g.observe(1)))
        self.portable(g)

    def test_real_rewind_retires_attempted_debits_and_keeps_only_original_state_prefix(self):
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('retry',), corpses=5, mana=10, max_mana=10),
                                         PlayerSetup('hero', mana=10, max_mana=10))), capped.registry(), mechanics=capped.mechanics())
        eid = next(iter(g.state.players[1].hand))
        g.apply(PlayCard(1, eid))
        for attempt in (1, 2, 3):
            saved = json.loads(json.dumps(g.snapshot()))
            restored = Game.from_snapshot(saved, capped.registry(), mechanics=capped.mechanics())
            self.assertEqual(restored.snapshot(), saved)
            self.assertEqual(replay(build_replay(g), capped.registry(), mechanics=capped.mechanics()).snapshot(), saved)
            rows = corpse_spends(g.state, 1)
            self.assertEqual([(row.id, row.amount, row.operation_id) for row in rows], [(1, 3, attempt)])
            self.choose(g, 'good')
            if attempt < 3:
                self.choose(g, 'retry')
        validate_corpse_boundary(g)
        self.assertEqual((spent_corpses(g.state, 1), g.state.players[1].resources[Resource.CORPSES],
                          g.state.next_resource_operation_id), (3, 2, 4))
        self.assertEqual(len(g.state.corpse_spend_history), 1)
        self.assertTrue(any(event.kind == 'timeline_rewound' for event in g.events))

    def test_actual_refund_changes_bank_without_erasing_successful_units(self):
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('produce',), board=('refund',),
            corpses=5, mana=10, max_mana=10), PlayerSetup('hero', mana=10, max_mana=10))),
            capped.registry(), mechanics=capped.mechanics())
        g.apply(PlayCard(1, g.state.players[1].hand[0]))
        self.assertEqual((spent_corpses(g.state, 1), g.state.players[1].resources[Resource.CORPSES]), (3, 12))
        self.choose(g, 'good')
        self.assertEqual(spent_corpses(g.state, 1), 3)
        self.assertEqual(len(g.state.corpse_spend_history), 1)
        validate_corpse_boundary(g)

    def test_schema209_new_field_and_previous_hosts_are_explicitly_incompatible(self):
        g = self.game(('debit.fixed',)); self.play(g, 'debit.fixed')
        saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, g.mechanics.version),
                         (265, 'prototype-v302', CORE_EFFECTS_VERSION))
        for version in (1, 208, 217, True, 216.0):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        self.portable(g)


if __name__ == '__main__': unittest.main()
