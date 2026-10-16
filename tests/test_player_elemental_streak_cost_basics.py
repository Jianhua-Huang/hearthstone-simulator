"""Finite Azerite Giant price using original owner/physical-play facts."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import asdict, FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

import test_owner_turn_type_history_basics as fixtures
import test_m5_owner_turn_opening as opening_fixtures
import test_m5_owner_turn_startup as startup_fixtures
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    IntrinsicCostSpec, PlayerDrawCountCostSpec, PlayerElementalStreakCostSpec,
    PlayerElementalStreakCostFact, PlayCard, QueueTurns, Rarity, ResolutionError,
    SelectChoice, SkipTurns, SnapshotError, TriggerSpec, UseHeroPower,
    consecutive_elemental_turn_count)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    GainArmor, InvokeBehavior, RequestChoice, Summon, Transform)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.player_elemental_streak_costs import capture, validate_definition, validate_prefix
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.serialization import _intrinsic_stage_from_dict
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'WW_025'
ELEMENTAL = fixtures.NATIVE
SUPPORT = Path(__file__).resolve().parents[1]/'data/support/player-elemental-streak-cost-basics.json'
PIN = '53a1b2b5556cc547824a7812f356e7ca6b7425e4a39b6b4c64ba3dae1e8a8ceb'


def evidence():
    support = json.loads(SUPPORT.read_bytes())
    if canonical_digest(support) != PIN:
        raise ValueError('Complete consecutive Elemental evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original streak card changed')
    return {row['id']: row['data'] for row in support['records']}


def native_definition():
    raw = evidence()[NATIVE]
    return CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'],
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.EPIC, tribes=('elemental',)),
        player_elemental_streak_cost=PlayerElementalStreakCostSpec())


class PlayerElementalStreakCostTests(unittest.TestCase):
    game = fixtures.OwnerTurnTypeHistoryTests.game
    play = fixtures.OwnerTurnTypeHistoryTests.play
    end = fixtures.OwnerTurnTypeHistoryTests.end
    choose = fixtures.OwnerTurnTypeHistoryTests.choose
    script = fixtures.OwnerTurnTypeHistoryTests.script
    fresh_registry = fixtures.OwnerTurnTypeHistoryTests.fresh_registry
    next_own = fixtures.OwnerTurnTypeHistoryTests.next_own

    def setUp(self):
        fixtures.OwnerTurnTypeHistoryTests.setUp(self)
        self.r.register_card(native_definition())

    def source(self, g, player=1):
        return next(g.state.entities[e] for e in g.state.players[player].hand
            if g.state.entities[e].card_id == NATIVE)

    def fact(self, g, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, player)))

    def quantity(self, g, player=1):
        return self.fact(g, player).intrinsic.player_elemental_streak.quantity

    def one(self, extras=(), *, board=()):
        g = self.game((NATIVE, ELEMENTAL, *extras), board=board)
        self.play(g, ELEMENTAL)
        return g

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        for other in (Game.from_snapshot(saved, self.fresh_registry(), mechanics=g.mechanics),
                g.clone(), replay(build_replay(g), self.fresh_registry(), mechanics=g.mechanics)):
            self.assertEqual(other.snapshot(), saved)
        return saved

    def typed(self, g, stage):
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(stage)), stage)
        self.assertEqual(_intrinsic_stage_from_dict(json.loads(json.dumps(asdict(stage)))), stage)

    def test_complete_raw_pin_and_isolated_eight_eight_eight_epic_elemental(self):
        raw = evidence()[NATIVE]; card = self.r.card(NATIVE)
        self.assertEqual((raw['dbf_id'], card.cost, card.attack, card.health), (100234, 8, 8, 8))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            ((CardClass.NEUTRAL,), Rarity.EPIC, ('elemental',)))
        self.assertIsNone(card.on_play); self.assertIsNone(card.battlecry); self.assertIsNone(card.deathrattle)
        self.assertEqual(card.keywords, ())
        self.assertNotIn('TRL_313', self.r.cards)

    def test_initial_board_does_not_fabricate_an_elemental_submission(self):
        g = self.game((NATIVE,), board=(ELEMENTAL,)); f = self.fact(g).intrinsic.player_elemental_streak
        self.assertEqual((f.rows, f.selected_interval_ids, f.quantity, f.after), ((), (), 0, 8))
        self.assertEqual(len(f.owner_turns), 1); self.typed(g, self.fact(g).intrinsic); self.check(g)

    def test_first_native_quotes_before_its_own_commit_and_pays_once(self):
        g = self.game((NATIVE,)); self.assertEqual(self.fact(g).amount, 8)
        self.play(g, NATIVE); record = g.state.play_history[-1]
        self.assertEqual((record.cost, record.submitted_cost.quote.intrinsic.player_elemental_streak.quantity,
            consecutive_elemental_turn_count(g.state, 1), g.state.players[1].mana), (8, 0, 1, 2))
        self.check(g)

    def test_multiple_elementals_in_one_own_interval_count_once(self):
        g = self.one((ELEMENTAL,)); self.play(g, ELEMENTAL)
        f = self.fact(g).intrinsic.player_elemental_streak
        self.assertEqual((f.quantity, f.selected_interval_ids, len(f.rows), f.after), (1, (1,), 2, 7))
        self.typed(g, self.fact(g).intrinsic); self.check(g)

    def test_open_empty_current_interval_preserves_previous_closed_streak(self):
        g = self.one(); self.next_own(g)
        f = self.fact(g).intrinsic.player_elemental_streak
        self.assertEqual((f.quantity, f.selected_interval_ids, f.after), (1, (1,), 7))
        self.assertFalse(f.owner_turns[-1].closed)
        self.assertEqual(f.owner_turns[-1].player_id, 1); self.check(g)

    def test_closed_empty_own_interval_breaks_streak(self):
        g = self.one(); self.next_own(g); self.end(g)
        self.assertEqual((self.quantity(g), self.fact(g).amount), (0, 8))
        self.end(g); self.assertEqual(self.quantity(g), 0); self.check(g)

    def test_current_nonmatching_minion_or_spell_does_not_break_before_close(self):
        g = self.one(('empty', 'arcane')); self.next_own(g)
        self.play(g, 'empty'); self.play(g, 'arcane')
        self.assertEqual(self.quantity(g), 1); self.end(g)
        self.assertEqual(self.quantity(g), 0)
        self.assertEqual(len(self.fact(g).intrinsic.player_elemental_streak.rows), 3)
        self.check(g)

    def test_new_current_elemental_extends_distinct_own_intervals(self):
        g = self.one((ELEMENTAL, ELEMENTAL)); self.next_own(g); self.play(g, ELEMENTAL)
        self.assertEqual(self.quantity(g), 2); self.next_own(g)
        self.assertEqual(self.quantity(g), 2); self.play(g, ELEMENTAL)
        self.assertEqual((self.quantity(g), self.fact(g).amount), (3, 5))
        self.assertEqual(self.fact(g).intrinsic.player_elemental_streak.selected_interval_ids, (1, 3, 5))
        self.check(g)

    def test_closed_break_does_not_recover_older_matches_after_new_elemental(self):
        g = self.one((ELEMENTAL,)); self.next_own(g); self.next_own(g); self.play(g, ELEMENTAL)
        self.assertEqual(self.fact(g).intrinsic.player_elemental_streak.selected_interval_ids, (5,))
        self.assertEqual(self.fact(g).amount, 7); self.check(g)

    def test_actual_extra_same_player_turns_are_distinct_own_intervals(self):
        self.script('extra', lambda c: [QueueTurns((c.player_id,))])
        g = self.one(('extra', ELEMENTAL)); self.play(g, 'extra'); self.end(g)
        self.assertEqual(g.state.active_player, 1); self.play(g, ELEMENTAL)
        self.assertEqual(self.fact(g).intrinsic.player_elemental_streak.selected_interval_ids, (1, 2))
        self.assertEqual(self.quantity(g), 2); self.check(g)

    def test_skipped_opportunity_does_not_fabricate_an_empty_own_interval(self):
        self.script('skip', lambda c: [SkipTurns(3-c.player_id, 1)])
        g = self.one(('skip', ELEMENTAL)); self.play(g, 'skip'); self.end(g)
        self.assertEqual(g.state.active_player, 1); self.assertEqual(self.quantity(g), 1)
        self.play(g, ELEMENTAL); self.assertEqual(self.quantity(g), 2); self.check(g)

    def test_other_players_elemental_and_unknown_keep_complete_prefix(self):
        g = self.game((NATIVE,), enemy_hand=(ELEMENTAL, 'unknown'))
        self.end(g); self.play(g, ELEMENTAL); self.play(g, 'unknown')
        f = self.fact(g).intrinsic.player_elemental_streak
        self.assertEqual((f.quantity, len(f.rows), f.after), (0, 2, 8))
        self.assertIsNone(f.rows[-1].face.metadata.tribes); self.check(g)

    def test_outside_own_interval_submission_never_becomes_own_match(self):
        self.r.register_behavior('offturn', lambda c: [PlayFromHand(PlayCard(2,
            c.state.players[2].hand[0], position=0))])
        self.r.register_card(CardDefinition('offturn-power', 'offturn-power', CardType.HERO_POWER,
            on_use='offturn', metadata=fixtures.fixtures.metadata(card_class=CardClass.MAGE, collectible=False)))
        g = self.game(enemy_hand=(ELEMENTAL, NATIVE), power='offturn-power')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        f = self.fact(g, 2).intrinsic.player_elemental_streak
        self.assertEqual((f.quantity, len(f.rows), f.rows[0].face.owner_turn_id), (0, 1, 1))
        self.end(g); self.assertEqual(self.quantity(g, 2), 0); self.check(g)

    def test_unknown_own_row_is_rejected_even_after_older_break(self):
        g = self.game(('unknown',)); self.play(g, 'unknown'); self.next_own(g); self.next_own(g)
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'):
            capture(g.state, g.registry, 1, native_definition(), 8)

    def test_all_tribes_matches_known_empty_does_not(self):
        g = self.game((NATIVE, 'empty', 'all')); self.play(g, 'empty')
        self.assertEqual(self.quantity(g), 0); self.play(g, 'all')
        self.assertEqual(self.quantity(g), 1); self.check(g)

    def test_printed_frozen_face_survives_transform_death_and_control(self):
        self.script('shape', lambda c: [Transform(c.state.players[1].board[0], 'empty')])
        self.script('transfer', lambda c: [ChangeControl(c.state.players[1].board[0], 2)])
        self.script('kill', lambda c: [Destroy(c.state.players[2].board[0], c.source_id)])
        g = self.one(('shape', 'transfer', 'kill')); original = g.state.play_history[0].played_face
        for card in ('shape', 'transfer', 'kill'): self.play(g, card)
        self.assertEqual((self.quantity(g), g.state.play_history[0].played_face), (1, original)); self.check(g)

    def test_elemental_summon_does_not_count_as_a_hand_play(self):
        self.script('make', lambda c: [Summon(c.player_id, ELEMENTAL)])
        g = self.game((NATIVE, 'make')); self.play(g, 'make')
        self.assertEqual((self.quantity(g), len(g.state.successful_summon_history)), (0, 1)); self.check(g)

    def test_preacquisition_streak_prices_new_native_from_player_history(self):
        self.script('acquire', lambda c: [AddToHand(c.player_id, NATIVE)])
        g = self.game((ELEMENTAL, 'acquire')); self.play(g, ELEMENTAL); self.next_own(g)
        self.play(g, 'acquire'); self.assertEqual((self.quantity(g), self.fact(g).amount), (1, 7)); self.check(g)

    def test_generated_quote_uses_same_quantity_without_fabricating_history(self):
        g = self.game((ELEMENTAL,)); self.play(g, ELEMENTAL); before = g.snapshot()
        f = capture_generated_quote_fact(g.state, g.registry, 1, NATIVE)
        self.assertEqual((f.amount, f.intrinsic.player_elemental_streak.quantity), (7, 1))
        validate_generated_quote_fact(g.registry, f); self.typed(g, f.intrinsic)
        self.assertEqual(g.snapshot(), before)

    def test_read_only_quantity_and_quote_leave_snapshot_rng_and_allocators_unchanged(self):
        g = self.one(); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(consecutive_elemental_turn_count(g.state, 1), 1); self.assertEqual(self.fact(g).amount, 7)
        self.assertEqual(g.snapshot(), before)
        for player in (True, 0, 3, '1'):
            with self.assertRaises(ValueError): consecutive_elemental_turn_count(g.state, player)

    def watcher(self, event):
        self.r.register_behavior('streak-wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('ok', 'ok', (GainArmor(c.player_id, 1),)),
             ChoiceOption('bad', 'bad', (InvokeBehavior('failure', c.source_id, c.player_id),))),
            source_id=c.source_id)] if c.play is not None and c.play.card_id == NATIVE else [])
        self.r.register_card(CardDefinition('streak-watcher', 'streak-watcher', CardType.MINION,
            health=5, metadata=fixtures.fixtures.metadata(), triggers=(TriggerSpec(event, 'streak-wait'),)))

    def waiting(self, event, completed):
        self.watcher(event); g = self.game((NATIVE,), board=('streak-watcher',)); self.play(g, NATIVE)
        record = g.state.play_history[-1]; stage = record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost, record.completed, stage.player_elemental_streak.quantity), (8, completed, 0))
        self.assertEqual(consecutive_elemental_turn_count(g.state, 1), 1)
        saved = self.check(g); self.typed(g, stage)
        copies = (Game.from_snapshot(saved, self.fresh_registry(), mechanics=g.mechanics),
            g.clone(), replay(build_replay(g), self.fresh_registry(), mechanics=g.mechanics))
        self.choose(g)
        for other in copies:
            self.choose(other); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (8, 2))
        validate_intrinsic_history_prefix(stage, g.state, g.registry); self.check(g)
        return g

    def test_committed_wait_keeps_precommit_price_restores_and_pays_once(self):
        self.waiting('card_committed', False)

    def test_completed_wait_keeps_precommit_price_restores_and_pays_once(self):
        self.waiting('card_played', True)

    def test_failed_choice_rolls_back_wait_payment_and_both_histories(self):
        self.watcher('card_committed'); g = self.game((NATIVE,), board=('streak-watcher',)); self.play(g, NATIVE)
        before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g); self.check(g)

    def test_failed_submit_rolls_back_no_elemental_or_price_cache(self):
        self.script('fail', lambda c: [InvokeBehavior('failure', c.source_id, c.player_id)])
        g = self.one(('fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.assertEqual(self.quantity(g), 1)

    def test_old_quote_remains_frozen_across_close_publish_and_new_match(self):
        g = self.one((ELEMENTAL,)); stage = self.fact(g).intrinsic
        self.next_own(g); self.play(g, ELEMENTAL)
        self.assertEqual((stage.player_elemental_streak.quantity, self.quantity(g)), (1, 2))
        validate_intrinsic_history_prefix(stage, g.state, g.registry); self.typed(g, stage); self.check(g)

    def test_compact_prefix_rejects_rewritten_empty_owner_interval(self):
        g = self.one(); self.next_own(g); stage = self.fact(g).intrinsic
        bad = deepcopy(g.state); bad.owner_turn_history[1] = replace(bad.owner_turn_history[1], player_id=1)
        with self.assertRaises(ValueError): validate_intrinsic_history_prefix(stage, bad, g.registry)

    def test_same_price_shorter_complete_false_tail_requires_exact_origin(self):
        g = self.one(('empty',)); self.play(g, 'empty'); stage = self.fact(g).intrinsic
        f = stage.player_elemental_streak; boundary = replace(f.boundary, play_history_length=1)
        short = replace(f, rows=f.rows[:1], boundary=boundary)
        changed = replace(stage, boundary=boundary, player_elemental_streak=short)
        validate_intrinsic_stage_fact(g.registry, changed); self.assertEqual(changed.amount, stage.amount)
        with self.assertRaises(ValueError): validate_intrinsic_origin(changed, g.state, g.registry)

    def test_fact_rejects_omitted_middle_nonmatch_duplicate_ids_and_wrong_quantity(self):
        g = self.one(('empty', ELEMENTAL)); self.play(g, 'empty'); self.play(g, ELEMENTAL)
        f = self.fact(g).intrinsic.player_elemental_streak
        for change in ({'rows': (f.rows[0], f.rows[2])}, {'owner_turns': ()},
                {'selected_interval_ids': (True,)}, {'selected_interval_ids': (1,1)},
                {'quantity': 2}, {'after': 6}, {'player_id': True}, {'next_entity_id': f.rows[-1].face.source_id}):
            with self.subTest(change=change), self.assertRaises(ValueError): replace(f, **change)
        with self.assertRaises(FrozenInstanceError): f.quantity = 0

    def test_stage_and_subject_binding_reject_foreign_payer_window_and_allocator(self):
        g = self.one(); q = self.fact(g); stage = q.intrinsic; f = stage.player_elemental_streak
        with self.assertRaises(ValueError): replace(stage, player_id=2)
        with self.assertRaises(ValueError): replace(stage, boundary=replace(stage.boundary, action=stage.boundary.action+1))
        with self.assertRaises(ValueError): replace(q, quote_input=replace(q.quote_input, source_id=f.next_entity_id))

    def test_finite_declaration_rejects_unreviewed_formulas_and_unknown_profiles(self):
        for value in (True, 'cost.any-history-expression'):
            with self.assertRaises(ValueError): PlayerElementalStreakCostSpec(value)
        card = native_definition()
        for changed in (replace(card, kind=CardType.SPELL), replace(card, choice_only=True),
                replace(card, player_elemental_streak_cost=True),
                replace(card, intrinsic_costs=(IntrinsicCostSpec(delta=-1),)),
                replace(card, player_draw_count_cost=PlayerDrawCountCostSpec())):
            with self.assertRaises(ValueError): validate_definition(changed)

    def test_player_action_quotes_and_pays_through_original_opaque_command(self):
        g = self.one(); self.next_own(g); port = g.for_player(1); dto = port.legal_actions()
        row = next(r for r in g.observe(1)['players'][0]['hand'] if r['card_id'] == NATIVE)
        action = next(a for a in dto['actions'] if a.get('card') == row['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        record = g.state.play_history[-1]
        self.assertEqual((record.cost, g.state.players[1].mana,
            record.submitted_cost.quote.intrinsic.player_elemental_streak.quantity), (7, 3, 1)); self.check(g)

    def test_player_observation_and_events_do_not_expose_price_operand(self):
        g = self.one(); self.next_own(g)
        for player in (1,2):
            data = json.dumps((g.observe(player), g.for_player(player).observe(), g.for_player(player).legal_actions()))
            for key in ('selected_interval_ids', 'owner_turns', 'player_elemental_streak', 'played_face', 'hand_entry_id'):
                self.assertNotIn(key, data)
        self.check(g)

    def test_nullable_leaf_has_strict_dictionary_and_typed_roundtrips(self):
        g = self.one(); stage = self.fact(g).intrinsic; self.typed(g, stage)
        for mutation in ('missing', 'extra', 'boolean_quantity', 'wrong_pin'):
            data = json.loads(json.dumps(asdict(stage)))
            if mutation == 'missing': del data['player_elemental_streak']
            elif mutation == 'extra': data['player_elemental_streak']['secret'] = 1
            elif mutation == 'boolean_quantity': data['player_elemental_streak']['quantity'] = True
            else: data['player_elemental_streak']['rows'][0]['face']['metadata']['tribes'] = ['BEAST']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): _intrinsic_stage_from_dict(data)
        other = self.game(('empty',))
        ordinary = capture_quote_fact(other.state, other.registry, capture_cost_input(other.state.entities[other.state.players[1].hand[0]]))
        self.assertIsNone(ordinary.intrinsic.player_elemental_streak)
        self.typed(other, ordinary.intrinsic)

    def test_current_schema_rejects_all_old_future_boolean_and_old_rule_effect_ids(self):
        g = self.game((NATIVE,)); snap = g.snapshot()
        self.assertEqual((g.ruleset.id, g.mechanics.version, snap['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        for version in (*range(1,218), True, 207.0, 217):
            bad = deepcopy(snap); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, self.fresh_registry())
        for key, subkey, version in (('ruleset','id','prototype-v221'), ('mechanics_version','version','core-effects-v215')):
            bad = deepcopy(snap); bad[key][subkey] = version
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad, self.fresh_registry())

    def test_pre_first_original_play_remains_outside_finite_elemental_count(self):
        fixture = opening_fixtures.OpeningPaidPhaseTests(); fixture.setUp(); g = fixture.opening()
        f = capture(g.state, g.registry, 1, native_definition(), 8)
        self.assertEqual((f.quantity, len(f.rows), f.rows[0].face.owner_turn_id), (0, 1, None))
        self.assertEqual(f.rows[0].face.opening_stage, 'starting')

    def test_pending_genuine_start_price_keeps_original_unpublished_interval(self):
        fixture = startup_fixtures.StartExpiryIntervalTests(); fixture.setUp(); g = fixture.startup_paid_game('choice')
        f = capture(g.state, g.registry, 1, native_definition(), 8)
        self.assertIsNone(f.owner_turns[-1].publication_event)
        self.assertEqual(f.quantity, 0)
        fixture.choose(g); fixture.choose(g)
        validate_prefix(f, g.state, g.registry)

