"""All-game manual power uses priced from existing physical activation roots."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CostSpec, EndTurn,
    Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction, InteractableSpec,
    PaymentType, PlayCard, PlayerSetup, PlayerHeroPowerCountCostSpec, PlayerSpellCountCostSpec,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec,
    TriggerHeroPower, UseHeroPower, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    InvokeBehavior, ModifyCost, RefreshHeroPower, ReplaceHeroPower, RequestChoice,
    ReturnToHand, SetHeroPowerUses, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

FROST = 'AT_120'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-hero-power-count-cost-basics.json'
PIN = 'f273dea38f98d7cd4d3d41021f04ac2bd3da97632700d0c6cdd1e205c71c79b6'

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Personal power evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Personal power full raw changed')
    return {row['id']: row['data'] for row in support['records']}

def registry():
    r = opening_registry()
    raw = evidence()[FROST]
    r.register_card(CardDefinition(FROST, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata(rarity=Rarity.EPIC), player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()))
    r.register_behavior('power.count.noop', lambda c: ())
    r.register_card(CardDefinition('power.count.spell', 'Nonpower fixture', CardType.SPELL,
        on_play='power.count.noop'))
    r.register_behavior('power.count.wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('continue', 'Complete activation', ()),), c.source_id),))
    for cid, behavior, targeting, passive in (
            ('power.count.basic', 'power.count.noop', None, False),
            ('power.count.new', 'power.count.noop', None, False),
            ('power.count.choice', 'power.count.wait', None, False),
            ('power.count.targeted', 'power.count.noop', TargetSpec(relation='enemy',
                zones=(Zone.BOARD,), kinds=(CardType.MINION,)), False),
            ('power.count.passive', None, None, True)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, on_use=behavior,
            targeting=targeting, passive_hero_power=passive,
            triggers=(TriggerSpec('card_played', 'power.count.noop'),) if passive else ()))

    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == FROST)
    def first(c):
        return c.state.players[c.player_id].board[0]
    def power_cost(c, spec):
        return ModifyCost(c.state.players[c.player_id].hero_power_id, spec)
    scripts = {
        'power.count.limit': lambda c: (SetHeroPowerUses(c.player_id, 12),),
        'power.count.refresh': lambda c: (RefreshHeroPower(c.player_id),),
        'power.count.replace': lambda c: (ReplaceHeroPower(c.player_id, 'power.count.new'),),
        'power.count.acquire': lambda c: (AddToHand(c.player_id, FROST),),
        'power.count.auto': lambda c: (TriggerHeroPower(c.player_id, c.source_id, choices='player'),),
        'power.count.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'power.count.silence': lambda c: (Silence(first(c)),),
        'power.count.bounce': lambda c: (ReturnToHand(first(c)),),
        'power.count.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-3)),),
        'power.count.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(FROST,))),),
        'power.count.paid': lambda c: (power_cost(c, CostSpec(set_to=2, card_types=(CardType.HERO_POWER,))),),
        'power.count.health': lambda c: (power_cost(c, CostSpec(set_to=2,
            payment=PaymentType.HEALTH, card_types=(CardType.HERO_POWER,))),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid))
    r.register_behavior('power.count.fail', lambda c: (AddToHand(c.player_id, 'power.count.spell'),
        AddToHand(c.player_id, 'unknown.power.count')))
    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id != FROST:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Complete paid play', ()),
            ChoiceOption('fault', 'Delayed error', (InvokeBehavior('power.count.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('power.count.paid.wait', paid_wait)
    r.register_card(CardDefinition('power.count.watch', 'Paid completion observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_played', 'power.count.paid.wait'),)))
    return r

def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved

class PlayerHeroPowerCountCostTests(unittest.TestCase):
    def game(self, hand=(FROST,), *, board=(), enemy_hand=(), power='power.count.basic', mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*3,
                hero_power_card_id=power, mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=('card.1',)*3,
                hero_power_card_id='power.count.basic', mana=10, max_mana=10)), seed=18), registry())
    def source(self, g, cid=FROST, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
    def fact(self, g, cid=FROST, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))
    def price(self, g, player=1):
        return self.fact(g, player=player).amount
    def play(self, g, cid=FROST):
        eid = self.source(g, cid).id
        g.apply(PlayCard(g.state.active_player, eid))
        return eid
    def use(self, g, player=None):
        player = g.state.active_player if player is None else player
        g.apply(UseHeroPower(player, g.state.players[player].hero_power_id))
    def choose(self, g, option='continue'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def twice(self, *, extras=(), board=(), mana=10):
        g = self.game(hand=(FROST, 'power.count.limit', *extras), board=board, mana=mana)
        self.play(g, 'power.count.limit')
        self.use(g)
        self.use(g)
        return g
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(restored.observe(player), g.observe(player))
        return saved

    def test_full_frost_raw_and_hero_power_text_are_pinned(self):
        row = evidence()[FROST]
        original = {v['id']: v for v in json.loads((PATH.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(row, original[FROST])
        self.assertEqual((row['cost'], row['attack'], row['health']), (10, 8, 8))
        self.assertIn('used your Hero Power this game', row['text_en'])

    def test_finite_profile_and_one_ordinary_minion_quantity(self):
        for profile in (None, True, 'all.automatic', 'formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                PlayerHeroPowerCountCostSpec(profile)
        r = registry()
        for changes in ({'kind': CardType.SPELL, 'health': 0}, {'player_hero_power_count_cost': 'expression'},
                {'interactable': InteractableSpec('power.count.noop')}, {'board_minion_cost': BoardMinionCostSpec()},
                {'hand_count_cost': HandCountCostSpec()}, {'hero_missing_health_cost': HeroMissingHealthCostSpec()},
                {'player_spell_count_cost': PlayerSpellCountCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(FROST), id='bad.power.price', **changes))

    def test_empty_game_has_printed_ten_and_zero_complete_prefix(self):
        g = self.game(enemy_hand=(FROST,))
        self.assertEqual((self.price(g), self.price(g, 2)), (10, 10))
        f = self.fact(g).intrinsic.player_hero_powers
        self.assertEqual((f.rows, f.hero_power_history_length, f.quantity, f.after), ((), 0, 0, 10))
        self.portable(g)

    def test_each_real_manual_root_counts_once_with_same_physical_power(self):
        g = self.twice()
        f = self.fact(g).intrinsic.player_hero_powers
        self.assertEqual((self.price(g), f.quantity, f.hero_power_history_length), (8, 2, 2))
        self.assertEqual(f.rows[0].source_id, f.rows[1].source_id)
        self.assertEqual([row.id for row in f.rows], [1, 2])
        self.assertEqual([row.uses_before for row in f.rows], [0, 1])
        self.portable(g)

    def test_manual_uses_before_acquisition_are_not_hand_age_progress(self):
        g = self.game(hand=('power.count.limit', 'power.count.acquire'))
        self.play(g, 'power.count.limit')
        self.use(g)
        self.use(g)
        self.play(g, 'power.count.acquire')
        self.assertEqual(self.price(g), 8)
        self.assertEqual(self.source(g).abilities, [])
        self.portable(g)

    def test_actual_payer_excludes_opponent_uses(self):
        g = self.twice(extras=())
        # Both actual players hold their own physically acquired copy.
        other = self.game(enemy_hand=(FROST,))
        self.use(other)
        other.apply(EndTurn(1))
        self.use(other)
        self.assertEqual((self.price(other), self.price(other, 2)), (9, 9))
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_hero_powers.quantity), (8, 2))
        self.portable(other)

    def test_turn_reset_keeps_all_game_count_and_new_use_adds_one(self):
        g = self.game()
        self.use(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0)
        self.assertEqual(self.price(g), 9)
        self.use(g)
        self.assertEqual(self.price(g), 8)
        self.portable(g)

    def test_replacing_power_keeps_old_physical_use_history(self):
        g = self.game(hand=(FROST, 'power.count.replace'))
        old = g.state.players[1].hero_power_id
        self.use(g)
        self.play(g, 'power.count.replace')
        self.assertEqual(self.price(g), 9)
        self.use(g)
        f = self.fact(g).intrinsic.player_hero_powers
        self.assertEqual((self.price(g), g.state.entities[old].zone), (8, Zone.GRAVEYARD))
        self.assertEqual([row.card_id for row in f.rows], ['power.count.basic', 'power.count.new'])
        self.assertNotEqual(f.rows[0].source_id, f.rows[1].source_id)
        self.portable(g)

    def test_refresh_changes_allowance_without_erasing_accepted_uses(self):
        g = self.game(hand=(FROST, 'power.count.refresh'))
        self.use(g)
        with self.assertRaises(IllegalAction):
            self.use(g)
        self.play(g, 'power.count.refresh')
        self.assertEqual(self.price(g), 9)
        self.use(g)
        self.assertEqual(self.price(g), 8)
        self.assertEqual([row.uses_before for row in self.fact(g).intrinsic.player_hero_powers.rows], [0, 0])
        self.portable(g)

    def test_spells_and_minion_plays_are_not_hero_power_uses(self):
        g = self.game(hand=(FROST, 'power.count.spell', 'card.1'))
        self.play(g, 'power.count.spell')
        self.play(g, 'card.1')
        self.assertEqual((self.price(g), len(g.state.hero_power_history)), (10, 0))
        self.portable(g)

    def test_effect_activation_is_saved_but_not_a_manual_use(self):
        g = self.game(hand=(FROST, 'power.count.auto'))
        self.play(g, 'power.count.auto')
        f = self.fact(g).intrinsic.player_hero_powers
        self.assertEqual((self.price(g), f.hero_power_history_length, f.quantity), (10, 1, 0))
        self.assertEqual((f.rows[0].origin, f.rows[0].cost, f.rows[0].payment), ('effect', None, None))
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0)
        self.portable(g)

    def test_failed_automatic_and_passive_attempts_keep_zero_quantity(self):
        for power, reason in (('power.count.targeted', 'no_target'), ('power.count.passive', 'passive')):
            with self.subTest(power=power):
                g = self.game(hand=(FROST, 'power.count.auto'), power=power)
                self.play(g, 'power.count.auto')
                f = self.fact(g).intrinsic.player_hero_powers
                self.assertEqual((self.price(g), f.quantity, f.rows[0].failure), (10, 0, reason))
                self.portable(g)

    def test_illegal_manual_target_rolls_back_without_a_count(self):
        g = self.game(power='power.count.targeted')
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.use(g)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.price(g), 10)

    def test_use_counts_do_not_follow_payment_amount_or_account(self):
        for cid, account in (('power.count.paid', PaymentType.MANA), ('power.count.health', PaymentType.HEALTH)):
            with self.subTest(account=account):
                g = self.game(hand=(FROST, cid))
                self.play(g, cid)
                self.use(g)
                f = self.fact(g).intrinsic.player_hero_powers
                self.assertEqual((self.price(g), f.quantity, f.rows[0].cost, f.rows[0].payment), (9, 1, 2, account))
                self.portable(g)

    def test_manual_accepted_choice_counts_before_completion_and_restores(self):
        g = self.game(power='power.count.choice')
        self.use(g)
        self.assertFalse(g.state.hero_power_history[0].completed)
        stage = self.fact(g).intrinsic
        self.assertEqual((self.price(g), stage.player_hero_powers.quantity), (9, 1))
        restored = Game.from_snapshot(self.portable(g), registry())
        for current in (g, restored):
            self.choose(current)
            validate_intrinsic_history_prefix(stage, current.state, current.registry)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.price(g), 9)
        self.portable(g)

    def test_effect_choice_progress_keeps_original_zero_count(self):
        g = self.game(hand=(FROST, 'power.count.auto'), power='power.count.choice')
        self.play(g, 'power.count.auto')
        stage = self.fact(g).intrinsic
        self.assertEqual((stage.player_hero_powers.quantity, self.price(g)), (0, 10))
        restored = Game.from_snapshot(self.portable(g), registry())
        for current in (g, restored):
            self.choose(current)
            validate_intrinsic_history_prefix(stage, current.state, current.registry)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.portable(g)

    def test_ten_real_uses_floor_at_zero_and_allow_zero_mana_payment(self):
        g = self.twice(mana=0)
        for _ in range(9):
            self.use(g)
        f = self.fact(g).intrinsic.player_hero_powers
        self.assertEqual((f.quantity, self.price(g)), (11, 0))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 0))
        self.portable(g)

    def test_physical_generated_and_player_queries_are_pure(self):
        g = self.twice()
        before = g.snapshot()
        for _ in range(3):
            f = capture_generated_quote_fact(g.state, g.registry, 1, FROST)
            self.assertEqual(f.intrinsic.player_hero_powers, self.fact(g).intrinsic.player_hero_powers)
            validate_generated_quote_fact(g.registry, f)
            self.assertEqual((f.amount, self.price(g)), (8, 8))
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)
        self.assertEqual((self.source(g).base_cost, self.source(g).enchantments), (10, []))

    def test_local_external_layer_order_and_one_payment(self):
        g = self.twice(extras=('power.count.local', 'power.count.external'))
        self.play(g, 'power.count.local')
        self.play(g, 'power.count.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.base_cost, f.intrinsic.amount, f.local_amount, f.amount), (10, 8, 5, 3))
        self.play(g)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (3, 7))
        self.portable(g)

    def test_generated_initial_external_and_minimum_keep_existing_order(self):
        g = self.twice(extras=('power.count.external',))
        self.play(g, 'power.count.external')
        f = capture_generated_quote_fact(g.state, g.registry, 1, FROST, cost=CostSpec(delta=-3))
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (8, 5, 3))
        validate_generated_quote_fact(g.registry, f)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, FROST, cost=CostSpec(set_to=0), minimum_cost=1).amount, 1)

    def test_display_legal_validation_and_actual_payment_share_the_prefix(self):
        g = self.twice()
        source = self.source(g)
        g.validate(PlayCard(1, source.id))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = g.observe(1)['players'][0]['hand'][0]['ref']
        action = next(v for v in dto['actions'] if v.get('card') == ref)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'], 8)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (8, 2))
        self.portable(g)

    def test_insufficient_payment_preserves_history_hand_allocator_and_rng(self):
        g = self.twice(mana=7)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_original_prefix_is_frozen_after_later_real_manual_use(self):
        g = self.twice()
        stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        self.use(g)
        self.assertEqual((stage.player_hero_powers.quantity, self.price(g)), (2, 7))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)

    def test_base_copy_silence_bounce_keep_printed_price_and_game_count(self):
        g = self.game(hand=('power.count.limit', 'power.count.copy', 'power.count.silence', 'power.count.bounce'), board=(FROST,))
        self.play(g, 'power.count.limit')
        self.use(g)
        self.use(g)
        for cid in ('power.count.copy', 'power.count.silence', 'power.count.bounce'):
            self.play(g, cid)
        self.assertEqual((self.source(g).base_cost, self.price(g)), (10, 8))
        copied = next(g.state.entities[eid] for eid in g.state.players[1].board if g.state.entities[eid].card_id == FROST)
        self.assertEqual((copied.base_cost, quote_cost(g.state, g.registry, copied).amount), (10, 8))
        self.portable(g)

    def test_paid_completion_wait_freezes_price_across_later_manual_use(self):
        g = self.twice(board=('power.count.watch',))
        source = self.play(g)
        receipt = g.state.play_history[-1].submitted_cost
        restored = Game.from_snapshot(self.portable(g), registry())
        for current in (g, restored):
            self.choose(current)
            self.use(current)
        self.assertEqual(g.snapshot(), restored.snapshot())
        root = next(row for row in g.state.play_history if row.source_id == source)
        self.assertEqual((root.cost, root.submitted_cost, g.state.players[1].mana), (8, receipt, 2))
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[source]).amount, 7)
        self.portable(g)

    def test_delayed_failure_rolls_back_acquisition_and_paid_root(self):
        g = self.twice(board=('power.count.watch',))
        self.play(g)
        before = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'unknown.power.count'):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_rows_reject_invalid_origin_payment_nesting_boolean_and_manual_failure(self):
        row = self.fact(self.twice()).intrinsic.player_hero_powers.rows[0]
        for changes in ({'origin': 'fake'}, {'origin': True}, {'id': True}, {'player_id': False},
                {'cost': None}, {'cost': True}, {'payment': 'mana'}, {'failure': 'no_target'},
                {'parent_id': 1}, {'activator_id': row.source_id}, {'uses_before': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(row, **changes)
        self.assertTrue(row.counts_for(1))
        self.assertFalse(row.counts_for(2))

    def test_fact_rejects_incomplete_reordered_future_and_false_count_operands(self):
        f = self.fact(self.twice()).intrinsic.player_hero_powers
        for changes in ({'rows': f.rows[:1]}, {'rows': f.rows[::-1]}, {'rows': list(f.rows)},
                {'rows': (replace(f.rows[0], source_id=f.next_entity_id), f.rows[1])},
                {'quantity': True}, {'quantity': 3}, {'hero_power_history_length': True},
                {'hero_power_history_length': 3}, {'player_id': True}, {'after': 9}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(f, **changes)

    def test_stage_validates_every_face_original_payer_base_and_time(self):
        g = self.twice()
        stage = self.fact(g).intrinsic
        f = stage.player_hero_powers
        for face in ('card.1', 'unknown.power.count', 'power.count.passive'):
            bad = replace(stage, player_hero_powers=replace(f, rows=(replace(f.rows[0], card_id=face), f.rows[1])))
            with self.subTest(face=face), self.assertRaises(ValueError):
                validate_intrinsic_stage_fact(g.registry, bad)
        with self.assertRaises(ValueError):
            replace(stage, player_hero_powers=replace(f, player_id=2, quantity=0, after=10))
        with self.assertRaises(ValueError):
            replace(stage, player_hero_powers=replace(f, before=9, after=7))
        with self.assertRaises(ValueError):
            replace(stage, player_hero_powers=replace(f, rows=(f.rows[0], replace(f.rows[1], action=stage.boundary.action+1))))
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, replace(stage, player_hero_powers=None, amount=10))

    def test_compact_prefix_cannot_borrow_the_other_physical_activation(self):
        g = self.game(hand=(FROST, 'power.count.replace'))
        self.use(g)
        self.play(g, 'power.count.replace')
        self.use(g)
        stage = self.fact(g).intrinsic
        f = stage.player_hero_powers
        bad = replace(stage, player_hero_powers=replace(f, rows=(replace(f.rows[0], source_id=f.rows[1].source_id), f.rows[1])))
        with self.assertRaisesRegex(ValueError, 'original physical activation prefix'):
            validate_intrinsic_history_prefix(bad, g.state, g.registry)
        with self.assertRaisesRegex(ValueError, 'newer than its captured allocator'):
            replace(self.fact(g), quote_input=replace(self.fact(g).quote_input, source_id=f.next_entity_id))

    def test_unknown_excluded_effect_row_is_not_hidden_by_zero_quantity(self):
        g = self.game(hand=(FROST, 'power.count.auto'))
        self.play(g, 'power.count.auto')
        state = g.state
        state.hero_power_history[0] = replace(state.hero_power_history[0], card_id='unknown.power.count')
        with self.assertRaisesRegex(ValueError, 'unknown.power.count'):
            capture_quote_fact(state, g.registry, capture_cost_input(state.entities[self.source(g).id]))

    def test_rehashed_wire_rejects_missing_extra_and_rewritten_original_prefix(self):
        g = self.twice(extras=('power.count.auto',))
        self.play(g, 'power.count.auto')
        self.play(g)
        saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'drop_excluded', 'cursor', 'source', 'face', 'payment', 'boolean'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            power = stage['player_hero_powers']
            if edit == 'quantity': power['quantity'] += 1
            elif edit == 'missing_field': del stage['player_hero_powers']
            elif edit == 'missing_fact': stage['player_hero_powers'] = None
            elif edit == 'extra': power['invented'] = 1
            elif edit == 'drop_excluded': power['rows'] = power['rows'][:-1]
            elif edit == 'cursor': power['hero_power_history_length'] += 1
            elif edit == 'source': power['rows'][0]['source_id'] = g.state.hero_power_history[-1].activator_id
            elif edit == 'face': power['rows'][-1]['card_id'] = 'card.1'
            elif edit == 'payment': power['rows'][0]['payment'] = None
            else: power['rows'][0]['uses_before'] = True
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_prices_hide_original_prefix_and_opponent_hand(self):
        g = self.game(enemy_hand=(FROST, 'card.1'))
        self.use(g)
        own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 9)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('player_hero_powers', 'hero_power_history_length', 'next_entity_id', 'payment_state', 'submitted_cost'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_strict_current_schema_and_existing_public_protocols(self):
        g = self.game(hand=('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.player_hero_powers)
        self.play(g, 'card.1')
        saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            ('player-view-v122', 'player-actions-v13'))
        for version in (1, 173, 174, 217, True, '175'):
            bad = deepcopy(saved)
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())

if __name__ == '__main__':
    unittest.main()
