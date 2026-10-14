"""Finite Thing from Below price using the original success and payment paths."""
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    ChangeMinionTribes, CostSpec, EndTurn, Game, IllegalAction, IntrinsicCostSpec,
    Keyword, PlayerDrawCountCostSpec, PlayerSetup, PlayerSummonCountCostFact,
    PlayerSummonCountCostSpec, PlayCard, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, SuccessfulSummonRecord, TriggerSpec, TribeChangeSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, capture_quote_fact
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption,
    Destroy, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_summon_count_costs import validate_definition, validate_prefix
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import _intrinsic_stage_from_dict, canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'OG_028'
SUPPORT = Path(__file__).resolve().parents[1]/'data/support/player-summon-count-cost-basics.json'
PIN = '2d0d6538374a6d2b91cd2c47e6aff0f1d4934ab97551290f0116007cf6ffe9e8'


def evidence():
    value = json.loads(SUPPORT.read_bytes())
    if canonical_digest(value) != PIN:
        raise ValueError('Successful Totem price complete evidence changed')
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Successful Totem price raw row changed')
    return value['records'][0]['data']


def meta(tribes):
    return CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)


def registry():
    r = Registry('successful-totem-price-basics-v1')
    raw = evidence()
    r.register_card(CardDefinition('hero', 'Fixture hero', CardType.HERO, health=30,
        metadata=CardMetadata(False, (CardClass.SHAMAN,), None)))
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.TAUNT,),
        metadata=CardMetadata(True, (CardClass.SHAMAN,), Rarity.RARE, tribes=()),
        player_summon_count_cost=PlayerSummonCountCostSpec()))
    for name, tribes in (('t.totem', ('TOTEM',)), ('t.other', ('BEAST',)),
            ('t.all', ('all',)), ('t.empty', ()), ('t.unknown', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=3, metadata=meta(tribes)))

    def held(c):
        return next(c.state.entities[e] for e in c.state.players[c.player_id].hand
            if c.state.entities[e].card_id == NATIVE)

    def first(c):
        return c.state.players[c.player_id].board[0]

    def native_body(c):
        return next(e for e in c.state.players[c.player_id].board if c.state.entities[e].card_id == NATIVE)

    def change_hand(c):
        entity = next(c.state.entities[e] for e in c.state.players[c.player_id].hand
            if c.state.entities[e].card_id == 't.totem')
        return (ChangeMinionTribes(CardReference.capture(entity), TribeChangeSpec('set', ('BEAST',)), c.source_id),)

    bodies = {
        't.make': lambda c: (Summon(c.player_id, 't.totem'),),
        't.six': lambda c: tuple(Summon(c.player_id, 't.totem') for _ in range(6)),
        't.enemy': lambda c: (Summon(3-c.player_id, 't.totem'),),
        't.acquire': lambda c: (AddToHand(c.player_id, NATIVE),),
        't.kill': lambda c: (Destroy(first(c), c.source_id),),
        't.bounce': lambda c: (ReturnToHand(first(c)),),
        't.shape': lambda c: (Transform(first(c), 't.other'),),
        't.control': lambda c: (ChangeControl(first(c), 3-c.player_id),),
        't.change.hand': change_hand,
        't.copy.enemy': lambda c: (CopyCard(CardReference.capture(held(c)), 3-c.player_id, mode='base'),),
        't.local': lambda c: (ModifyCost(held(c).id, CostSpec(set_to=4)),),
        't.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(NATIVE,))),),
        't.silence.native': lambda c: (Silence(native_body(c)),),
        't.bounce.native': lambda c: (ReturnToHand(native_body(c)),),
        't.fail': lambda c: (Summon(c.player_id, 't.totem'), AddToHand(c.player_id, 'unknown.summon.price')),
    }
    for name, fn in bodies.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != NATIVE:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('more', 'New success for future quote', (Summon(c.player_id, 't.totem'),
                AddToHand(c.player_id, NATIVE))),
            ChoiceOption('fault', 'Original rollback probe', (InvokeBehavior('t.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('t.pause', pause)
    for name, event in (('t.committed.watch', 'card_committed'), ('t.completed.watch', 'card_played')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=3, metadata=meta(()),
            triggers=(TriggerSpec(event, 't.pause'),)))
    r.register_behavior('t.late.fail', lambda c: (AddToHand(c.player_id, 'unknown.summon.price'),)
        if c.state.entities[c.event.source_id].card_id == NATIVE else ())
    r.register_card(CardDefinition('t.fail.watch', 'Original failure listener', CardType.MINION,
        health=3, metadata=meta(()), triggers=(TriggerSpec('card_played', 't.late.fail'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k:v for k,v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class PlayerSummonCountCostTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), *, board=(), enemy_board=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('t.empty',)*6, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, deck=('t.empty',)*6,
                mana=10, max_mana=10)), seed=51), registry())

    def source(self, g, name=NATIVE, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand if g.state.entities[e].card_id == name)

    def play(self, g, name=NATIVE):
        player = g.state.active_player
        g.apply(PlayCard(player, self.source(g, name, player).id))

    def fact(self, g, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, player=player)))

    def price(self, g, player=1):
        return self.fact(g, player).amount

    def one(self, extras=(), *, board=()):
        g = self.game((NATIVE, 't.make', *extras), board=board)
        self.play(g, 't.make')
        return g

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return saved

    def typed(self, g, stage):
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        wire = json.loads(json.dumps(asdict(stage)))
        self.assertEqual(_intrinsic_stage_from_dict(wire), stage)

    def test_complete_native_raw_pin_and_isolated_six_five_five_rare_taunt(self):
        raw = evidence(); rows = json.loads(SUPPORT.read_bytes())['records']
        self.assertEqual([r['id'] for r in rows], [NATIVE, 'CORE_OG_028'])
        self.assertEqual((raw['dbf_id'], raw['cost'], raw['attack'], raw['health']), (38267, 6, 5, 5))
        card = registry().card(NATIVE)
        self.assertEqual((card.keywords, card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            ((Keyword.TAUNT,), (CardClass.SHAMAN,), Rarity.RARE, ()))
        self.assertIsNone(card.on_play); self.assertIsNone(card.battlecry); self.assertIsNone(card.deathrattle)

    def test_initial_board_totems_do_not_fabricate_past_summons(self):
        g = self.game(board=('t.totem',)); f = self.fact(g).intrinsic.player_summons
        self.assertEqual((f.records, f.selected_ids, f.quantity, self.price(g)), ((), (), 0, 6))
        self.typed(g, self.fact(g).intrinsic); self.check(g)

    def test_ordinary_totem_hand_play_reduces_price_once(self):
        g = self.game((NATIVE, 't.totem')); self.play(g, 't.totem')
        f = self.fact(g).intrinsic.player_summons
        self.assertEqual((f.selected_ids, f.quantity, f.before, f.after, self.price(g)), ((1,), 1, 6, 5, 5))
        self.assertEqual(g.state.card_summon_history, [])
        self.typed(g, self.fact(g).intrinsic); self.check(g)

    def test_plain_effect_success_is_not_lost_without_a_producer_root(self):
        g = self.one(); f = self.fact(g).intrinsic.player_summons
        self.assertEqual((self.price(g), f.records, g.state.card_summon_history),
            (5, tuple(g.state.successful_summon_history), []))
        self.check(g)

    def test_nonmatching_and_opponent_rows_are_in_complete_prefix(self):
        g = self.one(('t.other', 't.enemy')); self.play(g, 't.other'); self.play(g, 't.enemy')
        f = self.fact(g).intrinsic.player_summons
        self.assertEqual((len(f.records), f.selected_ids, f.quantity, self.price(g)), (3, (1,), 1, 5))
        self.assertEqual([r.player_id for r in f.records], [1, 1, 2])
        self.check(g)

    def test_count_before_acquisition_reduces_new_native_price(self):
        g = self.game(('t.make', 't.acquire')); self.play(g, 't.make'); self.play(g, 't.acquire')
        self.assertEqual(self.price(g), 5); self.check(g)

    def test_six_successes_floor_price_at_zero_and_native_does_not_count_itself(self):
        g = self.game((NATIVE, 't.six')); self.play(g, 't.six')
        self.assertEqual(self.price(g), 0); self.play(g)
        record = g.state.play_history[-1]
        self.assertEqual((record.cost, g.state.players[1].mana,
            record.submitted_cost.quote.intrinsic.player_summons.quantity), (0, 10, 6))
        self.assertEqual(len(g.state.successful_summon_history), 7)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual((generated.amount, generated.intrinsic.player_summons.quantity), (0, 6))
        self.check(g)

    def test_full_board_failed_summon_does_not_reduce_price(self):
        g = self.game((NATIVE, 't.make'), board=('t.empty',)*7); self.play(g, 't.make')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.records), (6, ()))
        self.check(g)

    def test_death_and_transform_cannot_reclassify_old_totem_success(self):
        for operation in ('t.kill', 't.shape'):
            with self.subTest(operation=operation):
                g = self.one((operation,)); before = self.fact(g).intrinsic.player_summons.records
                self.play(g, operation)
                self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.records), (5, before))
                self.check(g)

    def test_bounce_and_replay_same_entity_counts_two_successes(self):
        g = self.one(('t.bounce',)); original = g.state.players[1].board[0]
        self.play(g, 't.bounce'); self.assertEqual(self.price(g), 5)
        self.play(g, 't.totem')
        f = self.fact(g).intrinsic.player_summons
        self.assertEqual((self.price(g), [r.entity_id for r in f.records]), (4, [original, original]))
        self.check(g)

    def test_control_transfer_retains_original_player_count(self):
        g = self.one(('t.control',)); self.play(g, 't.control')
        self.assertEqual(self.price(g), 5)
        enemy = capture_generated_quote_fact(g.state, g.registry, 2, NATIVE)
        self.assertEqual(enemy.amount, 6)
        self.check(g)

    def test_all_tribes_is_one_matching_success(self):
        g = self.game((NATIVE, 't.all')); self.play(g, 't.all')
        f = self.fact(g).intrinsic.player_summons
        self.assertEqual((f.selected_ids, f.quantity, self.price(g)), ((1,), 1, 5))
        self.check(g)

    def test_original_current_tribes_are_used_instead_of_printed_or_later_hand(self):
        g = self.game((NATIVE, 't.totem', 't.change.hand', 't.bounce'))
        self.play(g, 't.change.hand'); self.play(g, 't.totem')
        f = self.fact(g).intrinsic.player_summons
        self.assertEqual((f.records[0].printed_tribes.members, f.records[0].tribes.members), (('TOTEM',), ('BEAST',)))
        self.assertEqual((f.selected_ids, self.price(g)), ((), 6))
        self.play(g, 't.bounce'); self.assertEqual(self.price(g), 6)
        self.check(g)

    def test_unknown_selected_player_tribes_error_explicitly(self):
        g = self.game((NATIVE, 't.unknown')); self.play(g, 't.unknown')
        with self.assertRaises(UnsupportedDefinitionError): self.price(g)
        with self.assertRaises(UnsupportedDefinitionError): capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.check(g)

    def test_opponent_unknown_tribes_are_preserved_without_poisoning_payer(self):
        g = self.game((NATIVE,), enemy_hand=('t.unknown',)); g.apply(EndTurn(1)); self.play(g, 't.unknown')
        self.assertEqual((self.price(g), len(self.fact(g).intrinsic.player_summons.records)), (6, 1))
        self.check(g)

    def test_history_is_all_game_after_genuine_turns(self):
        g = self.one(); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_summons.records[0].turn), (5, 1))
        self.check(g)

    def test_printed_copy_quotes_the_new_payers_original_history(self):
        g = self.one(('t.copy.enemy',)); self.play(g, 't.copy.enemy')
        self.assertEqual((self.price(g), self.price(g, 2)), (5, 6))
        self.check(g)

    def test_physical_generated_and_minimum_quotes_share_the_same_quantity(self):
        g = self.one(); physical = self.fact(g); generated = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual((physical.amount, generated.amount), (5, 5))
        self.assertEqual(physical.intrinsic.player_summons, generated.intrinsic.player_summons)
        minimum = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE, minimum_cost=7)
        self.assertEqual((minimum.intrinsic.amount, minimum.amount), (5, 7))
        validate_generated_quote_fact(g.registry, minimum)
        self.typed(g, generated.intrinsic)

    def test_original_local_then_external_layers_follow_intrinsic_price(self):
        g = self.one(('t.local', 't.external')); self.play(g, 't.local'); self.play(g, 't.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (5, 4, 2))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (2, 8))
        self.check(g)

    def test_player_command_quotes_and_pays_once_through_original_api(self):
        g = self.one(); port = g.for_player(1); dto = port.legal_actions()
        row = next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == NATIVE)
        action = next(a for a in dto['actions'] if a.get('card') == row['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (5, 5))
        self.check(g)

    def test_native_taunt_uses_the_original_combat_target_rule(self):
        g = self.game(enemy_board=('t.other',)); self.play(g); native = g.state.players[1].board[0]
        g.apply(EndTurn(1)); enemy = g.state.players[2].board[0]
        with self.assertRaises(IllegalAction): g.apply(Attack(2, enemy, g.state.players[1].hero_id))
        g.apply(Attack(2, enemy, native))
        self.assertEqual(g.state.entities[native].health, 4)
        self.check(g)

    def test_silence_then_bounce_restores_printed_declaration_without_rewriting_history(self):
        g = self.game((NATIVE, 't.silence.native', 't.bounce.native')); self.play(g)
        self.play(g, 't.silence.native'); self.play(g, 't.bounce.native')
        self.assertEqual((self.price(g), self.source(g).base_cost), (6, 6))
        self.check(g)

    def waiting(self, watcher, completed):
        g = self.one(board=(watcher,)); self.play(g)
        record = g.state.play_history[-1]; old = record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost, record.completed, old.player_summons.quantity), (5, completed, 1))
        saved = self.check(g); self.typed(g, old)
        copies = (Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry()))
        action = SelectChoice(1, g.state.pending_choice.id, ('more',))
        g.apply(action)
        for other in copies:
            other.apply(action); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana, self.price(g)), (5, 5, 4))
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        self.assertEqual(old.player_summons.quantity, 1)
        self.check(g)

    def test_committed_window_wait_restores_frozen_payment_and_new_success(self):
        self.waiting('t.committed.watch', False)

    def test_completed_window_wait_restores_frozen_payment_and_new_success(self):
        self.waiting('t.completed.watch', True)

    def test_failed_choice_restores_price_histories_wait_and_cursor(self):
        g = self.one(board=('t.completed.watch',)); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1, g.state.pending_choice.id, ('fault',)))
        self.assertEqual(g.snapshot(), before); self.check(g)

    def test_late_listener_failure_rolls_back_native_payment_and_own_entry(self):
        g = self.one(board=('t.fail.watch',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.price(g), 5)

    def test_frozen_prefix_accepts_only_exact_retained_rows_and_later_append(self):
        g = self.one(('t.make',)); old = self.fact(g).intrinsic
        self.play(g, 't.make'); self.assertEqual(self.price(g), 4)
        validate_prefix(old.player_summons, g.state, g.registry)
        validate_intrinsic_history_prefix(old, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(old, g.state, g.registry)
        row = old.player_summons.records[0]
        changed = replace(old.player_summons, records=(replace(row, event_sequence=row.event_sequence+1),))
        with self.assertRaises(ValueError): validate_prefix(changed, g.state, g.registry)

    def test_exact_origin_rejects_omitted_nonmatch_even_when_price_unchanged(self):
        g = self.one(('t.other',)); self.play(g, 't.other'); stage = self.fact(g).intrinsic
        fact = stage.player_summons
        shorter = replace(fact, records=fact.records[:1], next_successful_summon_id=2)
        changed = replace(stage, player_summons=shorter)
        validate_intrinsic_stage_fact(g.registry, changed)
        self.assertEqual(changed.amount, stage.amount)
        with self.assertRaises(ValueError): validate_intrinsic_origin(changed, g.state, g.registry)

    def test_finite_declarations_reject_unknown_types_and_unreviewed_formulas(self):
        for value in ('cost.any-history-expression', True):
            with self.assertRaises(ValueError): PlayerSummonCountCostSpec(value)
        card = registry().card(NATIVE)
        for changed in (replace(card, kind=CardType.SPELL), replace(card, choice_only=True),
                replace(card, player_summon_count_cost=True),
                replace(card, player_draw_count_cost=PlayerDrawCountCostSpec()),
                replace(card, intrinsic_costs=(IntrinsicCostSpec(delta=-1),))):
            with self.assertRaises(ValueError): validate_definition(changed)

    def test_fact_types_cursor_selection_and_formula_are_strict(self):
        g = self.one(); f = self.fact(g).intrinsic.player_summons
        self.assertIs(type(f), PlayerSummonCountCostFact)
        self.assertIs(type(f.records[0]), SuccessfulSummonRecord)
        for changed in ({'player_id': True}, {'quantity': 1.0}, {'records': []},
                {'next_successful_summon_id': 1}, {'selected_ids': (True,)},
                {'selected_ids': ()}, {'after': 6}, {'next_entity_id': 1}):
            with self.subTest(changed=changed), self.assertRaises(ValueError): replace(f, **changed)
        with self.assertRaises(FrozenInstanceError): f.quantity = 9

    def test_physical_quote_subject_must_preexist_original_allocator(self):
        g = self.game(); full = self.fact(g); source = self.source(g)
        f = replace(full.intrinsic.player_summons, next_entity_id=source.id)
        stage = replace(full.intrinsic, player_summons=f)
        with self.assertRaises(ValueError): replace(full, intrinsic=stage)

    def test_saved_finite_price_cannot_drop_or_change_original_required_fields(self):
        g = self.one(); self.play(g); saved = self.check(g)
        def operand(s): return s['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['player_summons']
        for field, value in (('quantity', True), ('selected_ids', []), ('next_successful_summon_id', 1),
                ('records', []), ('extra', 1)):
            bad = deepcopy(saved); operand(bad)[field] = value
            with self.subTest(field=field), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        bad = deepcopy(saved); del operand(bad)['records']
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())

    def test_ordinary_none_leaf_is_required_in_dictionary_and_typed_frame(self):
        g = self.game(('t.other',)); self.play(g, 't.other')
        stage = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.assertIsNone(stage.player_summons)
        codec = FrameCodec(g.mechanics, g.registry)
        wire = codec.encode(stage); del wire['fields']['player_summons']
        with self.assertRaises(ValueError): codec.decode(wire)
        raw = json.loads(json.dumps(asdict(stage))); del raw['player_summons']
        with self.assertRaises(ValueError): _intrinsic_stage_from_dict(raw)

    def test_nested_record_typed_codec_remains_allowlisted_and_strict(self):
        g = self.one(); stage = self.fact(g).intrinsic; codec = FrameCodec(g.mechanics, g.registry)
        self.typed(g, stage)
        wire = codec.encode(stage)
        row = wire['fields']['player_summons']['fields']['records']['tuple'][0]
        self.assertEqual(row['type'], 'hs_sim.engine.successful_summons.SuccessfulSummonRecord')
        del row['fields']['minion']
        with self.assertRaises(ValueError): codec.decode(wire)

    def test_current_schema_explicitly_rejects_all_old_future_and_boolean_versions(self):
        g = self.game(); saved = g.snapshot()
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        for value in (*range(1, 218), True, 206.0, 217):
            bad = deepcopy(saved); bad['schema_version'] = value
            with self.subTest(value=value), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_quotes_are_pure_and_player_views_never_receive_the_private_prefix(self):
        g = self.one(); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(self.price(g), 5)
            for player in (1, 2):
                for dto in (g.observe(player), g.for_player(player).legal_actions()):
                    text = json.dumps(dto)
                    for hidden in ('player_summons', 'successful_summon_history', 'selected_ids', 'submitted_cost'):
                        self.assertNotIn(hidden, text)
        self.assertEqual(g.snapshot(), before)
