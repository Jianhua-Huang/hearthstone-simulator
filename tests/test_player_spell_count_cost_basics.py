"""Personal spell roots priced from the full original game ledger, not hand age."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CastWhenDrawnSpec,
    CostSpec, EndTurn, Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction,
    InteractableSpec, Keyword, PlayCard, PlayerSetup, PlayerSpellCountCostSpec, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec,
    UseHeroPower, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    Draw, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell, CastStoredSpell, cast_spells
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


ARCANE = 'KAR_711'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-spell-count-cost-basics.json'
PIN = 'd567a39f443c09b70c2cb7a2ef065440389405e38e359a724edac69a6a0b1964'


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Personal spell evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Personal spell complete raw changed')
    return {row['id']: row['data'] for row in support['records']}


def registry():
    r = opening_registry()
    raw = evidence()[ARCANE]
    r.register_card(CardDefinition(ARCANE, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata(rarity=Rarity.EPIC), player_spell_count_cost=PlayerSpellCountCostSpec()))
    r.register_behavior('count.noop', lambda c: ())
    r.register_card(CardDefinition('count.noop', 'Empty personally played spell', CardType.SPELL,
        on_play='count.noop', metadata=metadata()))
    r.register_card(CardDefinition('count.drawn', 'Automatic draw fixture', CardType.SPELL,
        on_play='count.noop', cast_when_drawn=CastWhenDrawnSpec(replacement=False),
        keywords=(Keyword.CASTS_WHEN_DRAWN,)))
    r.register_card(CardDefinition('count.targeted', 'Automatic failure fixture', CardType.SPELL,
        on_play='count.noop', targeting=TargetSpec(relation='enemy', zones=(Zone.BOARD,), kinds=(CardType.MINION,))))

    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == ARCANE)

    def first(c):
        return c.state.players[c.player_id].board[0]

    def stored(c):
        eid = next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == 'count.noop')
        return CastStoredSpell(CardReference.capture(c.state.entities[eid]), c.player_id, c.source_id)

    # Minion drivers do not themselves increase the measured personal spell count.
    scripts = {
        'count.acquire': lambda c: (AddToHand(c.player_id, ARCANE),),
        'count.auto': lambda c: (CastSpell(c.player_id, 'count.noop', c.source_id),),
        'count.failed.auto': lambda c: (CastSpell(c.player_id, 'count.targeted', c.source_id),),
        'count.draw': lambda c: (Draw(c.player_id),),
        'count.history': lambda c: (RecastSpell(player_id=c.player_id, cast_id=c.state.cast_history[0].id, source_id=c.source_id),),
        'count.stored': lambda c: (stored(c),),
        'count.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'count.silence': lambda c: (Silence(first(c)),),
        'count.bounce': lambda c: (ReturnToHand(first(c)),),
        'count.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-3)),),
        'count.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(ARCANE,))),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid))
    r.register_behavior('count.refill', lambda c: (AddToHand(c.player_id, 'count.refill'),))
    r.register_card(CardDefinition('count.refill', 'Same-face physical root fixture', CardType.SPELL,
        on_play='count.refill'))
    r.register_behavior('count.wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('continue', 'Complete accepted cast', ()),), c.source_id),))
    r.register_card(CardDefinition('count.wait', 'Acceptance before completion fixture', CardType.SPELL,
        on_play='count.wait'))
    r.register_behavior('count.auto.wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('continue', 'Accept the pending automatic payload', ()),), c.source_id),))
    r.register_card(CardDefinition('count.auto.watch', 'Automatic start observer', CardType.MINION,
        health=2, triggers=(TriggerSpec('spell_cast_started', 'count.auto.wait'),)))
    r.register_behavior('count.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('count.counter', 'Original hand root counter fixture', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_committed', 'count.counter'),)))
    r.register_behavior('count.fail', lambda c: (AddToHand(c.player_id, 'count.noop'),
        AddToHand(c.player_id, 'unknown.personal.spell')))

    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id != ARCANE:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('acquire', 'Acquire future personally played spell', (AddToHand(c.player_id, 'count.noop'),)),
            ChoiceOption('fault', 'Delayed fixture failure', (InvokeBehavior('count.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('count.paid.wait', paid_wait)
    r.register_card(CardDefinition('count.watch', 'Paid completion observer', CardType.MINION,
        attack=1, health=3, triggers=(TriggerSpec('card_played', 'count.paid.wait'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class PlayerSpellCountCostTests(unittest.TestCase):
    def game(self, hand=(ARCANE,), *, deck=(), enemy_hand=(), board=(), enemy_board=(), mana=10, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, mana=mana, max_mana=10,
                hero_power_card_id=power),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*3, mana=10, max_mana=10)),
            seed=17), registry())

    def source(self, g, cid=ARCANE, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=ARCANE, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, cid=ARCANE, player=1):
        return self.fact(g, cid, player).amount

    def play(self, g, cid, player=None):
        player = g.state.active_player if player is None else player
        eid = self.source(g, cid, player).id
        g.apply(PlayCard(player, eid))
        return eid

    def choose(self, g, option='acquire'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(restored.observe(player), g.observe(player))
        return saved

    def two_casts(self, *, extras=(), board=(), mana=10):
        g = self.game(hand=(ARCANE, 'count.noop', 'count.noop', *extras), board=board, mana=mana)
        self.play(g, 'count.noop')
        self.play(g, 'count.noop')
        return g

    def test_complete_arcane_raw_and_all_game_personal_spell_text_are_pinned(self):
        rows = evidence()
        original = {row['id']: row for row in json.loads((PATH.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(rows, {ARCANE: original[ARCANE]})
        self.assertEqual((rows[ARCANE]['cost'], rows[ARCANE]['attack'], rows[ARCANE]['health']), (12, 8, 8))
        self.assertIn("you've cast this game", rows[ARCANE]['text_en'])

    def test_finite_policy_ordinary_minion_and_one_quantity_declaration(self):
        for profile in (None, True, 'all.attempts', 'all.automatic', 'formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                PlayerSpellCountCostSpec(profile)
        r = registry()
        for changes in ({'kind': CardType.SPELL, 'health': 0}, {'player_spell_count_cost': 'expression'},
                {'interactable': InteractableSpec('count.noop')}, {'board_minion_cost': BoardMinionCostSpec()},
                {'hand_count_cost': HandCountCostSpec()}, {'hero_missing_health_cost': HeroMissingHealthCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(ARCANE), id='bad.personal.spell', **changes))

    def test_empty_game_has_printed_price_and_zero_full_prefix_for_both_payers(self):
        g = self.game(enemy_hand=(ARCANE,))
        self.assertEqual((self.price(g), self.price(g, player=2)), (12, 12))
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.rows, f.cast_history_length, f.quantity, f.after), ((), 0, 0, 12))
        self.portable(g)

    def test_actual_personal_spells_count_each_physical_root_even_with_same_face(self):
        g = self.two_casts()
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((self.price(g), f.quantity, f.cast_history_length), (10, 2, 2))
        self.assertEqual([row.card_id for row in f.rows], ['count.noop', 'count.noop'])
        self.assertNotEqual(f.rows[0].source_id, f.rows[1].source_id)
        self.assertNotEqual(f.rows[0].play_id, f.rows[1].play_id)
        self.portable(g)

    def test_spells_before_acquisition_are_counted_without_per_hand_progress(self):
        g = self.game(hand=('count.noop', 'count.noop', 'count.acquire'))
        self.play(g, 'count.noop')
        self.play(g, 'count.noop')
        self.play(g, 'count.acquire')
        self.assertEqual(self.price(g), 10)
        self.assertEqual(self.source(g).abilities, [])
        self.portable(g)

    def test_actual_payer_counts_own_game_roots_and_not_the_opponents(self):
        g = self.game(hand=(ARCANE, 'count.noop', 'count.noop'), enemy_hand=(ARCANE, 'count.noop'))
        self.play(g, 'count.noop')
        self.play(g, 'count.noop')
        g.apply(EndTurn(1))
        self.play(g, 'count.noop')
        self.assertEqual((self.price(g), self.price(g, player=2)), (10, 11))
        self.assertEqual(len(self.fact(g).intrinsic.player_spells.rows), 3)
        self.portable(g)

    def test_minion_and_hero_power_actions_are_not_personal_spell_roots(self):
        g = self.game(hand=(ARCANE, 'card.1'), power='mage.power')
        self.play(g, 'card.1')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.assertEqual((self.price(g), len(g.state.cast_history)), (12, 0))
        self.portable(g)

    def test_countered_spell_is_saved_but_does_not_add_to_the_price_quantity(self):
        g = self.game(hand=(ARCANE, 'count.noop'), enemy_board=('count.counter',))
        self.play(g, 'count.noop')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.cast_history_length, f.quantity, self.price(g)), (1, 0, 12))
        self.assertEqual((f.rows[0].failure, f.rows[0].payload_started), ('countered', False))
        self.portable(g)

    def test_effect_cast_and_failed_automatic_attempt_are_complete_but_not_personal(self):
        g = self.game(hand=(ARCANE, 'count.auto', 'count.failed.auto'))
        self.play(g, 'count.failed.auto')
        self.play(g, 'count.auto')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.cast_history_length, f.quantity, self.price(g)), (2, 0, 12))
        self.assertEqual([row.origin for row in f.rows], ['effect', 'effect'])
        self.assertEqual([row.failure for row in f.rows], ['no_target', None])
        self.portable(g)

    def test_actual_draw_cast_is_not_counted_as_a_personal_hand_spell(self):
        g = self.game(hand=(ARCANE, 'count.draw'), deck=('count.drawn',))
        self.play(g, 'count.draw')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.cast_history_length, f.quantity, self.price(g)), (1, 0, 12))
        self.assertEqual(f.rows[0].origin, 'draw')
        self.portable(g)

    def test_historical_recast_keeps_original_personal_root_without_an_extra_count(self):
        g = self.game(hand=(ARCANE, 'count.noop', 'count.history'))
        self.play(g, 'count.noop')
        self.play(g, 'count.history')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual(([row.origin for row in f.rows], f.quantity, self.price(g)), (['hand', 'history'], 1, 11))
        self.portable(g)

    def test_effect_consuming_a_stored_hand_spell_is_still_an_automatic_source(self):
        g = self.game(hand=(ARCANE, 'count.noop', 'count.stored'))
        self.play(g, 'count.stored')
        f = self.fact(g).intrinsic.player_spells
        self.assertEqual((f.rows[0].origin, f.quantity, self.price(g)), ('effect', 0, 12))
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_accepted_inflight_hand_payload_counts_before_completion_and_restores(self):
        g = self.game(hand=(ARCANE, 'count.wait'))
        self.play(g, 'count.wait')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.cast_history[0].completed)
        self.assertEqual((len(cast_spells(g.state, 1, successful=True)), self.price(g)), (0, 11))
        stage = self.fact(g).intrinsic
        saved = self.portable(g)
        restored = Game.from_snapshot(saved, registry())
        for current in (g, restored):
            self.choose(current, 'continue')
        self.assertEqual(restored.snapshot(), g.snapshot())
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        self.assertEqual(self.price(g), 11)
        self.portable(g)

    def test_zero_floor_after_twelve_real_roots_allows_one_zero_mana_payment(self):
        g = self.game(hand=(ARCANE, 'count.refill'), mana=0)
        for _ in range(12):
            self.play(g, 'count.refill')
        self.assertEqual(self.price(g), 0)
        self.play(g, ARCANE)
        root = g.state.play_history[-1]
        self.assertEqual((root.cost, g.state.players[1].mana, root.submitted_cost.quote.intrinsic.player_spells.quantity), (0, 0, 12))
        self.portable(g)

    def test_pending_automatic_prefix_can_progress_without_adding_a_personal_root(self):
        g = self.game(hand=(ARCANE, 'count.auto'), board=('count.auto.watch',))
        self.play(g, 'count.auto')
        self.assertIsNotNone(g.state.pending_choice)
        stage = self.fact(g).intrinsic
        self.assertFalse(stage.player_spells.rows[0].payload_started)
        self.assertEqual((stage.player_spells.quantity, stage.amount), (0, 12))
        saved = self.portable(g)
        restored = Game.from_snapshot(saved, registry())
        for current in (g, restored):
            self.choose(current, 'continue')
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertTrue(g.state.cast_history[0].payload_started)
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        self.assertEqual(self.price(g), 12)
        self.portable(g)

    def test_repeated_physical_and_generated_queries_are_pure_and_use_the_same_prefix(self):
        g = self.two_casts()
        before = g.snapshot()
        for _ in range(3):
            f = capture_generated_quote_fact(g.state, g.registry, 1, ARCANE)
            self.assertEqual(f.intrinsic.player_spells, self.fact(g).intrinsic.player_spells)
            validate_generated_quote_fact(g.registry, f)
            self.assertEqual((f.amount, self.price(g)), (10, 10))
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)
        subject = self.source(g)
        self.assertEqual((subject.base_cost, subject.cost_modifier, subject.enchantments), (12, 0, []))

    def test_local_external_cost_order_reuses_original_quantity_and_pays_once(self):
        g = self.two_casts(extras=('count.local', 'count.external'))
        self.play(g, 'count.local')
        self.play(g, 'count.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.base_cost, f.intrinsic.amount, f.local_amount, f.amount), (12, 10, 7, 5))
        self.play(g, ARCANE)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (5, 5))
        self.portable(g)

    def test_generated_initial_external_and_minimum_keep_existing_layer_order(self):
        g = self.two_casts(extras=('count.external',))
        self.play(g, 'count.external')
        f = capture_generated_quote_fact(g.state, g.registry, 1, ARCANE, cost=CostSpec(delta=-3))
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (10, 7, 5))
        validate_generated_quote_fact(g.registry, f)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, ARCANE, cost=CostSpec(set_to=0), minimum_cost=1).amount, 1)

    def test_player_display_enumeration_validation_and_payment_share_original_prefix(self):
        g = self.two_casts()
        subject = self.source(g)
        g.validate(PlayCard(1, subject.id))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = g.observe(1)['players'][0]['hand'][0]['ref']
        action = next(action for action in dto['actions'] if action.get('card') == ref)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'], 10)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        root = g.state.play_history[-1]
        self.assertEqual((root.cost, g.state.players[1].mana, root.submitted_cost.quote.intrinsic.player_spells.quantity), (10, 0, 2))
        self.portable(g)

    def test_insufficient_mana_keeps_full_history_hand_allocations_and_rng_unchanged(self):
        g = self.two_casts(mana=9)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, ARCANE)
        self.assertEqual(g.snapshot(), before)

    def test_original_frozen_prefix_survives_later_real_spells_without_using_the_new_count(self):
        g = self.two_casts(extras=('count.noop',))
        stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        self.play(g, 'count.noop')
        self.assertEqual((stage.player_spells.quantity, self.price(g)), (2, 9))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)

    def test_printed_copy_silence_and_bounce_reuse_the_game_count_after_reacquisition(self):
        g = self.game(hand=('count.noop', 'count.noop', 'count.copy', 'count.silence', 'count.bounce'), board=(ARCANE,))
        for cid in ('count.noop', 'count.noop', 'count.copy', 'count.silence', 'count.bounce'):
            self.play(g, cid)
        subject = self.source(g)
        self.assertEqual((subject.base_cost, self.price(g)), (12, 10))
        self.assertEqual(g.registry.card(subject.card_id).player_spell_count_cost, PlayerSpellCountCostSpec())
        copied = next(g.state.entities[eid] for eid in g.state.players[1].board if g.state.entities[eid].card_id == ARCANE)
        self.assertEqual((copied.base_cost, quote_cost(g.state, g.registry, copied).amount), (12, 10))
        self.portable(g)

    def test_paid_completion_choice_restores_and_later_manual_spell_does_not_reprice_payment(self):
        g = self.two_casts(board=('count.watch',))
        subject = self.play(g, ARCANE)
        receipt = g.state.play_history[-1].submitted_cost
        saved = self.portable(g)
        restored = Game.from_snapshot(saved, registry())
        for current in (g, restored):
            self.choose(current)
            self.play(current, 'count.noop')
        self.assertEqual(restored.snapshot(), g.snapshot())
        root = next(row for row in g.state.play_history if row.source_id == subject)
        self.assertEqual((root.cost, root.submitted_cost, g.state.players[1].mana), (10, receipt, 0))
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[subject]).amount, 9)
        self.portable(g)

    def test_delayed_failure_rolls_back_private_acquisition_and_the_original_paid_root(self):
        g = self.two_casts(board=('count.watch',))
        self.play(g, ARCANE)
        before = self.portable(g)
        visible = g.observe(1)
        with self.assertRaisesRegex(ResolutionError, 'unknown.personal.spell'):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.observe(1), visible)
        self.portable(g)

    def test_cast_row_rejects_unknown_origins_types_and_impossible_acceptance_shapes(self):
        g = self.two_casts()
        row = self.fact(g).intrinsic.player_spells.rows[0]
        for changes in ({'origin': 'fake'}, {'origin': True}, {'id': True}, {'player_id': 0},
                {'play_id': None}, {'payload_started': False}, {'payload_started': 1},
                {'failure': 'no_target'}, {'failure': 'countered'}, {'iteration': 2}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(row, **changes)
        repeat = replace(row, origin='repeat', iteration=2)
        self.assertFalse(repeat.counts_for(1))
        self.assertTrue(row.counts_for(1))
        self.assertFalse(row.counts_for(2))

    def test_fact_rejects_reordered_missing_future_boolean_and_inconsistent_count_operands(self):
        g = self.two_casts()
        f = self.fact(g).intrinsic.player_spells
        future = replace(f.rows[0], source_id=f.next_entity_id)
        for changes in ({'rows': f.rows[::-1]}, {'rows': f.rows[:1]}, {'rows': (future, f.rows[1])},
                {'rows': list(f.rows)}, {'quantity': 3}, {'quantity': True}, {'cast_history_length': True},
                {'cast_history_length': 3}, {'player_id': True}, {'before': True}, {'after': 11}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(f, **changes)

    def test_stage_validates_every_original_face_and_original_payer_base_and_window(self):
        g = self.two_casts()
        stage = self.fact(g).intrinsic
        f = stage.player_spells
        for face in ('card.1', 'unknown.personal.spell'):
            rows = (replace(f.rows[0], card_id=face), f.rows[1])
            bad = replace(stage, player_spells=replace(f, rows=rows))
            with self.subTest(face=face), self.assertRaises(ValueError):
                validate_intrinsic_stage_fact(g.registry, bad)
        with self.assertRaises(ValueError):
            replace(stage, player_spells=replace(f, player_id=2, quantity=0, after=12))
        with self.assertRaises(ValueError):
            replace(stage, player_spells=replace(f, before=11, after=9))
        with self.assertRaises(ValueError):
            replace(stage, player_spells=replace(f, rows=(f.rows[0], replace(f.rows[1], action=stage.boundary.action + 1))))
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, replace(stage, player_spells=None, amount=12))

    def test_compact_original_prefix_cannot_borrow_a_different_physical_cast(self):
        g = self.two_casts()
        stage = self.fact(g).intrinsic
        f = stage.player_spells
        other = replace(f.rows[0], source_id=f.rows[1].source_id)
        bad = replace(stage, player_spells=replace(f, rows=(other, f.rows[1])))
        with self.assertRaisesRegex(ValueError, 'original physical cast prefix'):
            validate_intrinsic_history_prefix(bad, g.state, g.registry)
        quote = self.fact(g)
        with self.assertRaisesRegex(ValueError, 'newer than its captured allocator'):
            replace(quote, quote_input=replace(quote.quote_input, source_id=f.next_entity_id))

    def test_unknown_unselected_automatic_history_is_not_hidden_by_zero_quantity(self):
        g = self.game(hand=(ARCANE, 'count.auto'))
        self.play(g, 'count.auto')
        state = g.state
        state.cast_history[0] = replace(state.cast_history[0], card_id='unknown.personal.spell')
        with self.assertRaisesRegex(ValueError, 'unknown.personal.spell'):
            capture_quote_fact(state, g.registry, capture_cost_input(state.entities[state.players[1].hand[0]]))

    def test_rehashed_snapshots_reject_missing_extra_or_rewritten_full_count_prefix(self):
        g = self.two_casts(extras=('count.auto',))
        self.play(g, 'count.auto')
        self.play(g, ARCANE)
        saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'drop_excluded', 'cursor', 'source', 'face', 'boolean'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            personal = stage['player_spells']
            if edit == 'quantity': personal['quantity'] += 1
            elif edit == 'missing_field': del stage['player_spells']
            elif edit == 'missing_fact': stage['player_spells'] = None
            elif edit == 'extra': personal['invented'] = 1
            elif edit == 'drop_excluded': personal['rows'] = personal['rows'][:-1]
            elif edit == 'cursor': personal['cast_history_length'] += 1
            elif edit == 'source': personal['rows'][0]['source_id'] = personal['rows'][1]['source_id']
            elif edit == 'face': personal['rows'][-1]['card_id'] = 'card.1'
            else: personal['rows'][0]['payload_started'] = 1
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_prices_keep_internal_prefix_and_opponent_hand_faces_private(self):
        g = self.game(hand=(ARCANE, 'count.noop'), enemy_hand=('card.1', 'card.2'))
        self.play(g, 'count.noop')
        own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 11)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('player_spells', 'cast_history_length', 'next_entity_id', 'payment_state', 'submitted_cost'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_strict_new_wire_and_existing_public_protocols(self):
        g = self.game(hand=('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.player_spells)
        self.play(g, 'card.1')
        saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            ('player-view-v115', 'player-actions-v13'))
        for version in (1, 172, 173, 217, True, '174'):
            bad = deepcopy(saved)
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())


if __name__ == '__main__':
    unittest.main()
