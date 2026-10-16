"""Actual spell mana from committed payments, independently of hand acquisition."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CostSpec, EndTurn,
    Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction, InteractableSpec,
    PaymentType, PlayCard, PlayerSetup, PlayerHeroPowerCountCostSpec, PlayerSpellCountCostSpec,
    PlayerSpellManaCostSpec, Rarity, Resource, ResolutionError, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, UseHeroPower)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion,
    GainArmor, GainResource, GainTemporaryMana, InvokeBehavior, ModifyCost, RefreshMana,
    RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NAGA = 'TSC_829'
PATH = Path(__file__).resolve().parents[1] / 'data/support/player-spell-mana-cost-basics.json'
PIN = '1078263ea7525701589b668e95cfbd63f4ae1048d4cdefa5228f1b08d832398c'

def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Spell mana full evidence changed')
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Spell mana raw changed')
    return {row['id']: row['data'] for row in support['records']}

def registry():
    r = opening_registry()
    raw = evidence()[NAGA]
    r.register_card(CardDefinition(NAGA, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=metadata(rarity=Rarity.EPIC, tribes=('NAGA',)),
        player_spell_mana_cost=PlayerSpellManaCostSpec()))
    r.register_behavior('mana.noop', lambda c: ())
    r.register_behavior('mana.wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('continue', 'Finish spell', ()),), c.source_id),))
    for cid, amount, body in (('mana.two', 2, 'mana.noop'), ('mana.three', 3, 'mana.noop'),
            ('mana.free', 0, 'mana.noop'), ('mana.choice', 2, 'mana.wait')):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=amount, on_play=body))

    def held(c, cid=NAGA):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == cid)
    def first(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == NAGA)
    scripts = {
        'mana.acquire': lambda c: (AddToHand(c.player_id, NAGA),),
        'mana.auto': lambda c: (CastSpell(c.player_id, 'mana.three', c.source_id),),
        'mana.refresh': lambda c: (RefreshMana(c.player_id, 10),),
        'mana.refill': lambda c: (RefreshMana(c.player_id, 10), AddToHand(c.player_id, 'mana.three')),
        'mana.temporary': lambda c: (GainTemporaryMana(c.player_id, 3),),
        'mana.spell.discount': lambda c: (ModifyCost(held(c, 'mana.three'), CostSpec(delta=-2)),),
        'mana.spell.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=2, card_types=(CardType.SPELL,))),),
        'mana.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-10)),),
        'mana.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(NAGA,))),),
        'mana.zero': lambda c: (ModifyCost(held(c), CostSpec(set_to=0)),),
        'mana.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'mana.silence': lambda c: (Silence(first(c)),),
        'mana.bounce': lambda c: (ReturnToHand(first(c)),),
    }
    for cid, account in (('mana.health', PaymentType.HEALTH), ('mana.armor', PaymentType.ARMOR),
                         ('mana.corpses', PaymentType.CORPSES)):
        scripts[cid] = lambda c, p=account: (GainArmor(c.state.players[c.player_id].hero_id, 5),
            GainResource(c.player_id, Resource.CORPSES, 5),
            AddCostModifier(c.player_id, CostSpec(payment=p, card_types=(CardType.SPELL,))))
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=1, battlecry=cid))
    r.register_behavior('mana.counter', lambda c: (CounterSpell(dict(c.event.data)['window_id']),)
        if c.event.player_id != c.player_id else ())
    r.register_card(CardDefinition('mana.counter', 'Counter physical spell', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_committed', 'mana.counter'),)))
    r.register_behavior('mana.fail', lambda c: (AddToHand(c.player_id, 'mana.free'),
        AddToHand(c.player_id, 'unknown.spell.mana')))
    def paid_wait(c):
        if c.state.entities[c.event.source_id].card_id != NAGA:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Finish paid play', (RefreshMana(c.player_id, 10),
                AddToHand(c.player_id, 'mana.three'))),
            ChoiceOption('fault', 'Delayed error', (InvokeBehavior('mana.fail', c.source_id, c.player_id),)),
        ), c.source_id),)
    r.register_behavior('mana.paid.wait', paid_wait)
    r.register_card(CardDefinition('mana.watch', 'Paid completion observer', CardType.MINION,
        health=3, triggers=(TriggerSpec('card_played', 'mana.paid.wait'),)))
    return r

def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({key: value for key, value in saved.items()
        if key not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved

class PlayerSpellManaCostTests(unittest.TestCase):
    def game(self, hand=(NAGA,), *, enemy_hand=(), board=(), enemy_board=(), mana=10,
             max_mana=10, power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*3,
                hero_power_card_id=power, mana=mana, max_mana=max_mana),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.1',)*3,
                mana=10, max_mana=10)), seed=19), registry())
    def source(self, g, cid=NAGA, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)
    def fact(self, g, cid=NAGA, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))
    def price(self, g, player=1): return self.fact(g, player=player).amount
    def play(self, g, cid, player=None):
        player = g.state.active_player if player is None else player
        eid = self.source(g, cid, player).id
        g.apply(PlayCard(player, eid))
        return eid
    def choose(self, g, option='continue'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def paid(self, *, board=(), extras=()):
        g = self.game((NAGA, 'mana.two', 'mana.local', *extras), board=board)
        self.play(g, 'mana.two')
        self.play(g, 'mana.local')
        self.play(g, NAGA)
        return g
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        self.assertEqual(restored.observe(1), g.observe(1))
        self.assertEqual(restored.observe(2), g.observe(2))
        return saved

    def test_full_real_naga_raw_and_mana_text_are_pinned(self):
        raw = evidence()[NAGA]
        original = {v['id']: v for v in json.loads((PATH.parents[1] / 'extracted/cards.json').read_bytes())}
        self.assertEqual(raw, original[NAGA])
        self.assertEqual((raw['cost'], raw['attack'], raw['health']), (20, 8, 8))
        self.assertIn('Mana you\'ve spent on spells', raw['text_en'])

    def test_only_finite_independent_ordinary_minion_policy_is_registered(self):
        for profile in (None, True, 'all.accounts', 'arbitrary.formula'):
            with self.subTest(profile=profile), self.assertRaises(ValueError): PlayerSpellManaCostSpec(profile)
        r = registry()
        for changes in ({'kind': CardType.SPELL, 'health': 0}, {'player_spell_mana_cost': 'formula'},
                {'interactable': InteractableSpec('mana.noop')}, {'board_minion_cost': BoardMinionCostSpec()},
                {'hand_count_cost': HandCountCostSpec()}, {'hero_missing_health_cost': HeroMissingHealthCostSpec()},
                {'player_spell_count_cost': PlayerSpellCountCostSpec()},
                {'player_hero_power_count_cost': PlayerHeroPowerCountCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(NAGA), id='bad.mana.price', **changes))

    def test_empty_game_keeps_printed_twenty_and_empty_prefix(self):
        g = self.game(enemy_hand=(NAGA,))
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertEqual((self.price(g), self.price(g, 2)), (20, 20))
        self.assertEqual((f.rows, f.play_history_length, f.quantity, f.after), ((), 0, 0, 20))
        self.portable(g)

    def test_actual_two_and_three_payments_count_five_not_two_cards(self):
        g = self.game((NAGA, 'mana.two', 'mana.three'))
        self.play(g, 'mana.two'); self.play(g, 'mana.three')
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertEqual((self.price(g), f.quantity, f.play_history_length), (15, 5, 2))
        self.assertEqual([(r.mana_before, r.mana_after) for r in f.rows], [(10, 8), (8, 5)])
        self.portable(g)

    def test_free_spell_has_a_physical_root_but_zero_mana(self):
        g = self.game((NAGA, 'mana.free'))
        self.play(g, 'mana.free')
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertEqual((self.price(g), f.quantity, len(f.rows)), (20, 0, 1))
        self.portable(g)

    def test_local_spell_discount_uses_actual_payment_not_printed_cost(self):
        g = self.game((NAGA, 'mana.three', 'mana.spell.discount'))
        self.play(g, 'mana.spell.discount'); self.play(g, 'mana.three')
        self.assertEqual((self.price(g), g.state.play_history[-1].cost), (19, 1))
        self.portable(g)

    def test_external_spell_surcharge_uses_the_original_paid_amount(self):
        g = self.game((NAGA, 'mana.two', 'mana.spell.external'))
        self.play(g, 'mana.spell.external'); self.play(g, 'mana.two')
        self.assertEqual((self.price(g), g.state.play_history[-1].cost), (16, 4))
        self.portable(g)

    def test_alternative_health_armor_and_corpses_do_not_become_mana(self):
        for cid, account in (('mana.health', PaymentType.HEALTH), ('mana.armor', PaymentType.ARMOR),
                             ('mana.corpses', PaymentType.CORPSES)):
            with self.subTest(account=account):
                g = self.game((NAGA, cid, 'mana.three'))
                self.play(g, cid); self.play(g, 'mana.three')
                row = self.fact(g).intrinsic.player_spell_mana.rows[-1]
                self.assertEqual((self.price(g), row.payment, row.cost, row.mana_before, row.mana_after),
                    (20, account, 3, 10, 10))
                self.portable(g)

    def test_temporary_mana_counts_even_without_permanent_crystal_spend(self):
        g = self.game((NAGA, 'mana.temporary', 'mana.three'), mana=2, max_mana=2)
        self.play(g, 'mana.temporary'); self.play(g, 'mana.three')
        self.assertEqual((self.price(g), g.state.players[1].mana_spent,
                          g.state.players[1].temporary_mana, g.state.players[1].mana), (17, 0, 0, 2))
        self.portable(g)

    def test_later_mana_refresh_keeps_original_expenditure(self):
        g = self.game((NAGA, 'mana.three', 'mana.refresh'))
        self.play(g, 'mana.three'); self.play(g, 'mana.refresh')
        self.assertEqual((self.price(g), g.state.players[1].mana), (17, 10))
        self.portable(g)

    def test_payments_before_acquisition_are_counted_without_hand_progress(self):
        g = self.game(('mana.two', 'mana.acquire'))
        self.play(g, 'mana.two'); self.play(g, 'mana.acquire')
        self.assertEqual(self.price(g), 18)
        self.assertEqual(self.source(g).abilities, [])
        self.portable(g)

    def test_actual_payer_uses_own_total_across_both_players(self):
        g = self.game((NAGA, 'mana.two'), enemy_hand=(NAGA, 'mana.three'))
        self.play(g, 'mana.two'); g.apply(EndTurn(1)); self.play(g, 'mana.three')
        self.assertEqual((self.price(g), self.price(g, 2)), (18, 17))
        self.assertEqual(len(self.fact(g).intrinsic.player_spell_mana.rows), 2)
        self.portable(g)

    def test_turn_reset_does_not_erase_all_game_paid_prefix(self):
        g = self.game((NAGA, 'mana.two', 'mana.three'))
        self.play(g, 'mana.two'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.play(g, 'mana.three')
        self.assertEqual(self.price(g), 15)
        self.portable(g)

    def test_minion_and_hero_power_mana_payments_are_excluded(self):
        g = self.game((NAGA, 'card.1'), power='mage.power')
        self.play(g, 'card.1'); g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertEqual((self.price(g), f.quantity, len(f.rows), len(g.state.hero_power_history)), (20, 0, 1, 1))
        self.portable(g)

    def test_automatic_spell_body_does_not_invent_a_paid_physical_root(self):
        g = self.game((NAGA, 'mana.auto', 'mana.two'))
        self.play(g, 'mana.auto'); self.play(g, 'mana.two')
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertEqual((self.price(g), f.quantity, len(f.rows), len(g.state.cast_history)), (18, 2, 2, 2))
        self.portable(g)

    def test_countered_physical_spell_keeps_actual_mana_expenditure(self):
        g = self.game((NAGA, 'mana.three'), enemy_board=('mana.counter',))
        self.play(g, 'mana.three')
        self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual((self.price(g), g.state.players[1].mana, len(g.state.cast_history)), (17, 7, 1))
        self.assertEqual((g.state.cast_history[0].failure, g.state.cast_history[0].payload_started), ('countered', False))
        self.portable(g)

    def test_unfinished_paid_spell_already_contributes_and_restores(self):
        g = self.game((NAGA, 'mana.choice'))
        self.play(g, 'mana.choice')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.play_history[-1].completed)
        self.assertEqual(self.price(g), 18)
        saved = self.portable(g)
        other = Game.from_snapshot(saved, registry())
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.price(g), 18)

    def test_same_face_distinct_physical_roots_each_contribute_own_payment(self):
        g = self.game((NAGA, 'mana.two', 'mana.two'))
        first = self.play(g, 'mana.two'); second = self.play(g, 'mana.two')
        f = self.fact(g).intrinsic.player_spell_mana
        self.assertNotEqual(first, second)
        self.assertEqual(([r.source_id for r in f.rows], f.quantity, self.price(g)), ([first, second], 4, 16))
        self.portable(g)

    def test_all_game_expenditure_can_exceed_printed_cost_and_clamps_zero(self):
        g = self.game((NAGA, 'mana.three', 'mana.three', 'mana.three',
                       'mana.refill', 'mana.refill', 'mana.refill', 'mana.refill'))
        for _ in range(3): self.play(g, 'mana.three')
        for _ in range(4):
            self.play(g, 'mana.refill'); self.play(g, 'mana.three')
        self.assertEqual((self.price(g), self.fact(g).intrinsic.player_spell_mana.quantity), (0, 21))
        self.portable(g)

    def test_current_quotes_are_pure_and_generated_quotes_use_same_history(self):
        g = self.game((NAGA, 'mana.two'), enemy_hand=('card.1',))
        self.play(g, 'mana.two')
        before = g.snapshot()
        for _ in range(3):
            self.assertEqual(quote_cost(g.state, g.registry, self.source(g)).amount, 18)
            f = capture_generated_quote_fact(g.state, g.registry, 1, NAGA)
            validate_generated_quote_fact(g.registry, f)
            self.assertEqual(f.amount, 18)
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)

    def test_local_and_external_layers_follow_original_intrinsic_quantity(self):
        g = self.game((NAGA, 'mana.two', 'mana.local', 'mana.external'))
        self.play(g, 'mana.two'); self.play(g, 'mana.local'); self.play(g, 'mana.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (18, 8, 6))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, NAGA, cost=CostSpec(delta=-10))
        self.assertEqual(generated.amount, 6)
        self.portable(g)

    def test_display_legal_submission_and_actual_payment_share_one_quantity(self):
        g = self.game((NAGA, 'mana.two', 'mana.local'))
        self.play(g, 'mana.two'); self.play(g, 'mana.local')
        g.validate(PlayCard(1, self.source(g).id))
        port = g.for_player(1); dto = port.legal_actions()
        view = g.observe(1)['players'][0]['hand'][0]
        action = next(v for v in dto['actions'] if v.get('card') == view['ref'])
        self.assertEqual(view['cost']['amount'], 8)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (8, 0))
        self.portable(g)

    def test_insufficient_payment_leaves_all_original_state_unchanged(self):
        g = self.game((NAGA, 'mana.two'))
        self.play(g, 'mana.two'); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, NAGA)
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_requery_the_same_game_history(self):
        g = self.paid(extras=('mana.copy', 'mana.silence', 'mana.bounce'))
        naga_id = g.state.players[1].board[-1]
        self.play(g, 'mana.copy'); self.play(g, 'mana.silence'); self.play(g, 'mana.bounce')
        self.assertEqual((g.state.entities[naga_id].card_id, self.price(g)), (NAGA, 18))
        self.portable(g)

    def test_paid_choice_restore_and_later_spend_do_not_reprice_original_payment(self):
        g = self.paid(board=('mana.watch',))
        record = g.state.play_history[-1]
        stage = record.submitted_cost.quote.intrinsic
        self.assertEqual((record.cost, stage.player_spell_mana.quantity), (8, 2))
        saved = self.portable(g)
        for current in (g, Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry())):
            self.choose(current); self.play(current, 'mana.three')
            validate_intrinsic_history_prefix(stage, current.state, current.registry)
            self.assertEqual(current.state.play_history[2].submitted_cost.quote.intrinsic, stage)
        self.portable(g)

    def test_delayed_failure_rolls_back_to_original_paid_waiting_state(self):
        g = self.paid(board=('mana.watch',))
        before = self.portable(g)
        with self.assertRaisesRegex(ResolutionError, 'unknown.spell.mana'): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.portable(g)

    def test_frozen_payment_rows_require_typed_exact_account_and_debit(self):
        g = self.game((NAGA, 'mana.two')); self.play(g, 'mana.two')
        row = self.fact(g).intrinsic.player_spell_mana.rows[0]
        for changes in ({'cost': True}, {'payment': 'mana'}, {'kind': 'spell'}, {'mana_after': 9},
                {'source_id': 0}, {'hand_entry_id': False}, {'hand_entry_turn': row.turn + 1}, {'player_id': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(row, **changes)

    def test_frozen_prefix_keeps_cursor_order_allocator_and_actual_sum(self):
        g = self.game((NAGA, 'mana.two', 'mana.three'))
        self.play(g, 'mana.two'); self.play(g, 'mana.three')
        f = self.fact(g).intrinsic.player_spell_mana
        for changes in ({'rows': f.rows[:1]}, {'rows': tuple(reversed(f.rows))}, {'quantity': 2},
                {'after': 18}, {'play_history_length': 1}, {'next_entity_id': f.rows[-1].source_id},
                {'rows': (f.rows[0], replace(f.rows[1], action=f.rows[0].action))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(f, **changes)

    def test_frozen_all_rows_validate_unknown_or_wrong_excluded_faces(self):
        g = self.game((NAGA, 'card.1')); self.play(g, 'card.1')
        stage = self.fact(g).intrinsic; f = stage.player_spell_mana
        self.assertEqual(f.quantity, 0)
        for cid in ('unknown.spell.mana', 'mana.free', 'mage.power'):
            bad = replace(stage, player_spell_mana=replace(f, rows=(replace(f.rows[0], card_id=cid),)))
            with self.subTest(cid=cid), self.assertRaises(ValueError): validate_intrinsic_stage_fact(g.registry, bad)

    def test_compact_prefix_cannot_borrow_another_physical_paid_root(self):
        g = self.game((NAGA, 'mana.two', 'mana.three'))
        self.play(g, 'mana.two'); self.play(g, 'mana.three')
        stage = self.fact(g).intrinsic; f = stage.player_spell_mana
        row = replace(f.rows[0], source_id=f.rows[1].source_id)
        bad = replace(stage, player_spell_mana=replace(f, rows=(row, f.rows[1])))
        with self.assertRaisesRegex(ValueError, 'original physical payment prefix'):
            validate_intrinsic_history_prefix(bad, g.state, g.registry)

    def test_full_origin_and_boundary_reject_dropped_or_later_spend_rows(self):
        g = self.game((NAGA, 'mana.two', 'mana.three')); self.play(g, 'mana.two')
        stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        self.play(g, 'mana.three')
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(stage, g.state, g.registry)
        f = self.fact(g).intrinsic.player_spell_mana
        with self.assertRaises(ValueError): replace(stage, player_spell_mana=f)

    def test_physical_subject_cannot_come_from_future_allocator_or_other_payer(self):
        g = self.game((NAGA, 'mana.two')); self.play(g, 'mana.two')
        f = self.fact(g)
        with self.assertRaises(ValueError):
            replace(f, quote_input=replace(f.quote_input, source_id=f.intrinsic.player_spell_mana.next_entity_id))
        with self.assertRaises(ValueError):
            replace(f.intrinsic, player_spell_mana=replace(f.intrinsic.player_spell_mana,
                player_id=2, quantity=0, after=20))

    def test_rehashed_wire_cannot_drop_or_rewrite_original_payment_quantity(self):
        g = self.paid(); saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'drop_excluded', 'cursor',
                     'kind', 'account', 'cost', 'mana', 'boolean'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f = stage['player_spell_mana']
            if edit == 'quantity': f['quantity'] += 1
            elif edit == 'missing_field': del stage['player_spell_mana']
            elif edit == 'missing_fact': stage['player_spell_mana'] = None
            elif edit == 'extra': f['invented'] = 1
            elif edit == 'drop_excluded': f['rows'].pop()
            elif edit == 'cursor': f['play_history_length'] += 1
            elif edit == 'kind': f['rows'][0]['kind'] = 'minion'
            elif edit == 'account': f['rows'][0]['payment'] = 'health'
            elif edit == 'cost': f['rows'][0]['cost'] += 1
            elif edit == 'mana': f['rows'][0]['mana_after'] += 1
            else: f['rows'][0]['mana_before'] = True
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_price_hides_payment_prefix_and_opponent_hand(self):
        g = self.game((NAGA, 'mana.two'), enemy_hand=(NAGA, 'card.1'))
        self.play(g, 'mana.two'); own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 18)
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('player_spell_mana', 'play_history_length', 'next_entity_id', 'payment_state', 'submitted_cost'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_and_current_protocol_reject_old_saved_shapes(self):
        g = self.game(('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.player_spell_mana)
        self.play(g, 'card.1'); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            ('player-view-v86', 'player-actions-v12'))
        for version in (1, 173, 174, 175, 217, True, '176'):
            bad = deepcopy(saved); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())

if __name__ == '__main__':
    unittest.main()
