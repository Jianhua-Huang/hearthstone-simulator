"""One real finite price consumer of original hero health-change facts."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardClass, CardDefinition, CardMetadata, CardType,
    CostSpec, EndTurn, Game, HandCountCostSpec, HeroHealthChangeCostSpec, HeroMissingHealthCostSpec,
    IllegalAction, IntrinsicCostSpec, Keyword, MinionDeathCostSpec, PaymentType, PlayerOverloadCostSpec,
    PlayerPlayedClassCostSpec, PlayerSetup, PlayerSpellCountCostSpec, PlayerHeroPowerCountCostSpec,
    PlayerSpellManaCostSpec, PlayCard, Rarity, ResolutionError, RewindSpec, Scenario, SelectChoice,
    SnapshotError, TriggerSpec, health_change_count)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact, capture_quote_fact, quote_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, CopyMinion, Damage,
    GainArmor, Heal, InvokeBehavior, ModifyCost, ReplaceHero, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact, validate_intrinsic_history_prefix,
    validate_intrinsic_origin, validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

GIANT = 'SCH_140'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/hero-health-change-basics.json'
PIN = '12ac7eff1d3650d7bbf8a3f12ea44dd366069508822b950dc861ba1711e31309'


def evidence():
    support = json.loads(SUPPORT.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Health-change full evidence changed')
    row, = support['records']
    if row['id'] != GIANT or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Health-change raw record changed')
    return row['data']


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_card(CardDefinition(GIANT, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'],
        metadata=CardMetadata(True, (CardClass.PRIEST, CardClass.WARLOCK), Rarity.EPIC, tribes=('UNDEAD',)),
        hero_health_change_cost=HeroHealthChangeCostSpec()))
    r.register_card(CardDefinition('h.hero40', 'Replacement fixture', CardType.HERO, health=40,
        initial_hero_power='mage.power', metadata=metadata(CardClass.MAGE, collectible=False)))

    def hero(c):
        return c.state.players[c.player_id].hero_id

    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == GIANT)

    def board(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == GIANT)

    bodies = {
        'h.hurt': lambda c: (Damage(hero(c), 3, c.source_id),),
        'h.heal': lambda c: (Heal(hero(c), 2, c.source_id),),
        'h.enemy': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 3, c.source_id),),
        'h.noop': lambda c: (GainArmor(c.player_id, 10), Damage(hero(c), 3, c.source_id),
            Heal(hero(c), 5, c.source_id), Heal(hero(c), 0, c.source_id)),
        'h.many': lambda c: (Damage(hero(c), 1, c.source_id), Heal(hero(c), 1, c.source_id)) * 6,
        'h.acquire': lambda c: (AddToHand(c.player_id, GIANT),),
        'h.local': lambda c: (ModifyCost(held(c), CostSpec(set_to=6)),),
        'h.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(GIANT,))),),
        'h.healthpay': lambda c: (AddCostModifier(c.player_id,
            CostSpec(payment=PaymentType.HEALTH, card_ids=(GIANT,)), 1),),
        'h.replace': lambda c: (ReplaceHero(c.player_id, 'h.hero40', health=25),),
        'h.replace.same': lambda c: (ReplaceHero(c.player_id, 'h.hero40'),),
        'h.copy': lambda c: (CopyMinion(board(c), c.player_id, mode='base'),),
        'h.copy.enemy': lambda c: (CopyMinion(board(c), 3-c.player_id, mode='base'),),
        'h.enemy.bounce': lambda c: (ReturnToHand(next(eid for eid in c.state.players[3-c.player_id].board
            if c.state.entities[eid].card_id == GIANT)),),
        'h.silence': lambda c: (Silence(board(c)),),
        'h.bounce': lambda c: (ReturnToHand(board(c)),),
        'h.fail': lambda c: (Damage(hero(c), 3, c.source_id), AddToHand(c.player_id, 'unknown.health.price')),
        'h.pause': lambda c: (Damage(hero(c), 3, c.source_id), RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Heal once', (Heal(hero(c), 2, c.source_id),)),
            ChoiceOption('fault', 'Delayed failure probe', (InvokeBehavior('h.fail', c.source_id, c.player_id),)),
        ), c.source_id)),
        'h.retry': lambda c: (Damage(hero(c), 3, c.source_id), ReplaceHero(c.player_id, 'h.hero40', health=20)),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            keywords=(Keyword.REWIND,) if cid == 'h.retry' else (),
            rewind=RewindSpec() if cid == 'h.retry' else None))

    def paid_pause(c):
        if c.state.entities[c.event.source_id].card_id != GIANT:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('continue', 'Continue original paid root',
                (Damage(hero(c), 1, c.source_id), AddToHand(c.player_id, GIANT))),
            ChoiceOption('fault', 'Delayed failure probe', (InvokeBehavior('h.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('h.paid.pause', paid_pause)
    r.register_card(CardDefinition('h.watch', 'Original completion-window probe', CardType.MINION, health=4,
        triggers=(TriggerSpec('card_played', 'h.paid.pause'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class HeroHealthChangeCostTests(unittest.TestCase):
    def game(self, hand=(GIANT,), *, enemy_hand=(), board=(), mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.1',)*5, mana=mana, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, deck=('card.1',)*5, mana=10, max_mana=10)), seed=19), registry())

    def source(self, g, cid=GIANT, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=GIANT, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, player=1):
        return self.fact(g, player=player).amount

    def play(self, g, cid):
        player = g.state.active_player
        source = self.source(g, cid, player).id
        g.apply(PlayCard(player, source))
        return source

    def choose(self, g, option='continue'):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def one(self, extras=(), *, board=()):
        g = self.game((GIANT, 'h.hurt', *extras), board=board)
        self.play(g, 'h.hurt')
        return g

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry())
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            self.assertEqual(other.observe(player), g.observe(player))
        return saved

    def test_full_pinned_native_has_only_its_real_10_cost_8_8_price_declaration(self):
        raw = evidence()
        catalog = json.loads((SUPPORT.parents[1] / 'extracted/cards.json').read_bytes())
        self.assertEqual(raw, next(row for row in catalog if row['id'] == GIANT))
        d = registry().card(GIANT)
        self.assertEqual((d.cost, d.attack, d.health, d.metadata.classes, d.metadata.tribes, d.metadata.rarity),
            (10, 8, 8, (CardClass.PRIEST, CardClass.WARLOCK), ('UNDEAD',), Rarity.EPIC))
        self.assertIsNone(d.on_play)
        self.assertEqual(d.hero_health_change_cost, HeroHealthChangeCostSpec())

    def test_declaration_is_finite_ordinary_and_rejects_unreviewed_formula_stacks(self):
        with self.assertRaises(ValueError):
            HeroHealthChangeCostSpec('invented.expression')
        extras = (dict(kind=CardType.SPELL), dict(choice_only=True),
            dict(board_minion_cost=BoardMinionCostSpec()), dict(hand_count_cost=HandCountCostSpec()),
            dict(hero_missing_health_cost=HeroMissingHealthCostSpec()),
            dict(player_spell_count_cost=PlayerSpellCountCostSpec()),
            dict(player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()),
            dict(player_spell_mana_cost=PlayerSpellManaCostSpec()), dict(minion_death_cost=MinionDeathCostSpec()),
            dict(player_overload_cost=PlayerOverloadCostSpec()),
            dict(player_played_class_cost=PlayerPlayedClassCostSpec(CardClass.MAGE)),
            dict(intrinsic_costs=(IntrinsicCostSpec(delta=-1),)))
        for extra in extras:
            values = dict(id='bad.health.price', name='Bad', kind=CardType.MINION, health=1,
                hero_health_change_cost=HeroHealthChangeCostSpec())
            values.update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                registry().register_card(CardDefinition(**values))

    def test_empty_history_keeps_printed_price_and_empty_actual_cursor(self):
        g = self.game()
        f = self.fact(g).intrinsic.hero_health_changes
        self.assertEqual((self.price(g), f.records, f.quantity, f.next_hero_health_change_id), (10, (), 0, 1))
        self.portable(g)

    def test_damage_amount_is_one_occurrence_and_healing_is_a_second(self):
        g = self.one(('h.heal',))
        self.assertEqual((self.price(g), g.state.entities[g.state.players[1].hero_id].health), (9, 27))
        self.play(g, 'h.heal')
        self.assertEqual((self.price(g), health_change_count(g.state, 1)), (8, 2))
        self.assertEqual(self.fact(g).intrinsic.hero_health_changes.quantity, 2)
        self.portable(g)

    def test_nominal_damage_armor_and_full_heals_do_not_discount(self):
        g = self.game((GIANT, 'h.noop'))
        self.play(g, 'h.noop')
        self.assertEqual((self.price(g), g.state.hero_health_change_history), (10, []))

    def test_net_zero_health_keeps_every_occurrence_and_price_floors_zero(self):
        g = self.game((GIANT, 'h.many'))
        self.play(g, 'h.many')
        f = self.fact(g).intrinsic.hero_health_changes
        self.assertEqual((f.quantity, len(f.records), self.price(g), g.state.entities[g.state.players[1].hero_id].health),
            (12, 12, 0, 30))
        self.play(g, GIANT)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (0, 10))
        self.portable(g)

    def test_only_the_affected_heroes_genuine_own_turns_discount_each_payer(self):
        g = self.game((GIANT, 'h.hurt', 'h.enemy'), enemy_hand=(GIANT, 'h.hurt', 'h.enemy'))
        self.play(g, 'h.hurt'); self.play(g, 'h.enemy')
        self.assertEqual((self.price(g), self.price(g, 2)), (9, 10))
        g.apply(EndTurn(1)); self.play(g, 'h.hurt'); self.play(g, 'h.enemy')
        self.assertEqual((self.price(g), self.price(g, 2)), (9, 9))
        self.assertEqual(len(self.fact(g).intrinsic.hero_health_changes.records), 4)
        self.portable(g)

    def test_changes_before_native_acquisition_are_preserved(self):
        g = self.game(('h.hurt', 'h.acquire'))
        self.play(g, 'h.hurt'); self.play(g, 'h.acquire')
        self.assertEqual(self.price(g), 9)
        self.portable(g)

    def test_physical_generated_and_player_quote_use_same_original_quantity(self):
        g = self.one()
        physical = self.fact(g)
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
        self.assertEqual((physical.intrinsic, physical.amount), (generated.intrinsic, generated.amount))
        validate_generated_quote_fact(g.registry, generated)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'], 9)

    def test_generated_minimum_follows_zero_intrinsic_amount(self):
        g = self.game((GIANT, 'h.many')); self.play(g, 'h.many')
        f = capture_generated_quote_fact(g.state, g.registry, 1, GIANT, minimum_cost=4)
        self.assertEqual((f.intrinsic.amount, f.amount), (0, 4))
        validate_generated_quote_fact(g.registry, f)

    def test_original_local_and_external_layers_follow_the_frozen_quantity(self):
        g = self.one(('h.heal', 'h.local', 'h.external'))
        self.play(g, 'h.heal'); self.play(g, 'h.local'); self.play(g, 'h.external')
        f = self.fact(g)
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (8, 6, 4))
        generated = capture_generated_quote_fact(g.state, g.registry, 1, GIANT, cost=CostSpec(set_to=6))
        self.assertEqual(generated.amount, 4)
        self.play(g, GIANT)
        self.assertEqual(g.state.play_history[-1].cost, 4)
        self.portable(g)

    def test_native_player_submission_and_payment_share_the_visible_price(self):
        g = self.one(); port = g.for_player(1); dto = port.legal_actions()
        card = next(v for v in g.observe(1)['players'][0]['hand'] if v['card_id'] == GIANT)
        action = next(v for v in dto['actions'] if v.get('card') == card['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (9, 1))
        self.portable(g)

    def test_insufficient_payment_leaves_original_state_and_price_intact(self):
        g = self.game(mana=8); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g, GIANT)
        self.assertEqual(g.snapshot(), before)

    def test_real_hero_replacement_keeps_prior_occurrences_and_adds_only_actual_change(self):
        g = self.one(('h.replace', 'h.heal')); original = self.fact(g).intrinsic
        old_hero = g.state.players[1].hero_id
        self.play(g, 'h.replace')
        self.assertNotEqual(g.state.players[1].hero_id, old_hero)
        self.assertEqual(self.price(g), 8)
        self.play(g, 'h.heal'); self.assertEqual(self.price(g), 7)
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        self.portable(g)

    def test_same_health_physical_replacement_does_not_discount_again(self):
        g = self.one(('h.replace.same',)); self.play(g, 'h.replace.same')
        self.assertEqual((self.price(g), health_change_count(g.state, 1)), (9, 1))
        self.portable(g)

    def test_printed_copy_silence_and_bounce_requery_current_player_history(self):
        g = self.one(('h.copy', 'h.silence', 'h.bounce'))
        self.play(g, GIANT); self.play(g, 'h.copy'); self.play(g, 'h.silence'); self.play(g, 'h.bounce')
        self.assertEqual((self.price(g), health_change_count(g.state, 1)), (9, 1))
        self.portable(g)

    def test_copy_to_other_player_uses_the_new_payers_own_history(self):
        g = self.one(('h.copy.enemy', 'h.enemy.bounce'))
        self.play(g, GIANT); self.play(g, 'h.copy.enemy'); self.play(g, 'h.enemy.bounce')
        self.assertEqual(self.price(g, 2), 10)
        self.portable(g)

    def test_old_frozen_prefix_allows_later_health_and_turn_progress(self):
        g = self.one(('h.heal',)); original = self.fact(g).intrinsic
        validate_intrinsic_origin(original, g.state, g.registry)
        self.play(g, 'h.heal'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        self.assertEqual((original.hero_health_changes.quantity, original.amount, self.price(g)), (1, 9, 8))
        with self.assertRaises(ValueError): validate_intrinsic_origin(original, g.state, g.registry)
        self.portable(g)

    def test_health_payment_keeps_the_pre_payment_quote_before_new_occurrence(self):
        g = self.one(('h.healthpay',)); self.play(g, 'h.healthpay'); self.play(g, GIANT)
        record = g.state.play_history[-1]
        self.assertEqual((record.cost, record.payment, record.submitted_cost.quote.intrinsic.hero_health_changes.quantity),
            (9, PaymentType.HEALTH, 1))
        self.assertEqual((health_change_count(g.state, 1), capture_generated_quote_fact(g.state, g.registry, 1, GIANT).amount), (2, 8))
        self.portable(g)

    def test_paid_completion_choice_restores_and_later_changes_do_not_reprice_root(self):
        g = self.one(board=('h.watch',)); self.play(g, GIANT)
        self.assertIsNotNone(g.state.pending_choice)
        saved = self.portable(g)
        other = Game.from_snapshot(saved, registry())
        original = g.state.play_history[-1].submitted_cost.quote.intrinsic
        self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((self.price(g), g.state.play_history[1].cost, original.amount), (8, 9, 9))
        validate_intrinsic_history_prefix(original, g.state, g.registry)
        self.portable(g)

    def test_error_after_paid_choice_rolls_back_to_original_waiting_and_frozen_price(self):
        g = self.one(board=('h.watch',)); self.play(g, GIANT); before = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.play_history[-1].cost, 9)

    def test_unpaid_health_choice_reprices_current_hand_after_resume(self):
        g = self.game((GIANT, 'h.pause')); self.play(g, 'h.pause')
        self.assertEqual(self.price(g), 9); self.portable(g)
        self.choose(g); self.assertEqual(self.price(g), 8); self.portable(g)

    def test_failed_health_action_restores_complete_prior_price(self):
        g = self.game((GIANT, 'h.fail')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'h.fail')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.price(g), 10)

    def test_original_retry_restores_history_and_does_not_duplicate_price_discount(self):
        g = self.one(('h.retry',)); self.play(g, 'h.retry')
        self.assertEqual(self.price(g), 7); self.portable(g)
        self.choose(g, 'retry')
        self.assertEqual((self.price(g), health_change_count(g.state, 1)), (7, 3))
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_frozen_quantity_cursor_types_allocation_and_amount_are_strict(self):
        g = self.one(); stage = self.fact(g).intrinsic; f = stage.hero_health_changes
        with self.assertRaises(FrozenInstanceError): f.quantity = 2
        for changes in (dict(records=()), dict(records=list(f.records)), dict(quantity=True),
                dict(quantity=2), dict(after=8), dict(health_history_length=2),
                dict(next_hero_health_change_id=3), dict(next_entity_id=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(f, **changes)
        with self.assertRaises(ValueError): replace(stage, hero_health_changes=replace(f, player_id=2, quantity=0, after=10))
        with self.assertRaises(ValueError): replace(stage, hero_health_changes=replace(f, action=f.action+1))
        with self.assertRaises(ValueError): replace(self.fact(g), quote_input=replace(self.fact(g).quote_input, source_id=f.next_entity_id))

    def test_complete_prefix_retains_excluded_opponent_rows_and_rejects_changed_origins(self):
        g = self.one(('h.enemy',)); self.play(g, 'h.enemy')
        stage = self.fact(g).intrinsic; f = stage.hero_health_changes
        self.assertEqual((f.quantity, len(f.records)), (1, 2))
        with self.assertRaises(ValueError): replace(f, records=f.records[:1])
        row = replace(f.records[1], event_kind='health_lost')
        changed = replace(stage, hero_health_changes=replace(f, records=(f.records[0], row)))
        validate_intrinsic_stage_fact(g.registry, changed)
        with self.assertRaises(ValueError): validate_intrinsic_history_prefix(changed, g.state, g.registry)
        with self.assertRaises(ValueError): validate_intrinsic_origin(changed, g.state, g.registry)

    def test_later_owner_interval_cannot_be_borrowed_by_original_price(self):
        g = self.one(); stage = self.fact(g).intrinsic; f = stage.hero_health_changes
        changed = replace(f, records=(replace(f.records[0], owner_turn_id=2),))
        with self.assertRaises(ValueError): replace(stage, hero_health_changes=changed)

    def test_rehashed_paid_wire_requires_complete_original_health_change_fact(self):
        g = self.one(); self.play(g, GIANT); saved = self.portable(g)
        for mode in ('quantity', 'field', 'fact', 'extra', 'records', 'cursor', 'event', 'owner', 'boolean'):
            bad = deepcopy(saved)
            stage = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            f = stage['hero_health_changes']
            if mode == 'quantity': f['quantity'] += 1
            elif mode == 'field': del stage['hero_health_changes']
            elif mode == 'fact': stage['hero_health_changes'] = None
            elif mode == 'extra': f['invented'] = 1
            elif mode == 'records': f['records'] = []
            elif mode == 'cursor': f['next_hero_health_change_id'] += 1
            elif mode == 'event': f['records'][0]['event_kind'] = 'health_lost'
            elif mode == 'owner': f['records'][0]['owner_turn_id'] = 0
            else: f['records'][0]['action'] = True
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_current_protocol_requires_explicit_none_leaf_on_ordinary_cards(self):
        g = self.game(('card.1',)); self.assertIsNone(self.fact(g, 'card.1').intrinsic.hero_health_changes)
        self.play(g, 'card.1'); saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']), ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        bad = deepcopy(saved)
        del bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['hero_health_changes']
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        for schema in (1, 199, 200, 217, True, 201.0, '201'):
            bad = deepcopy(saved); bad['schema_version'] = schema
            with self.subTest(schema=schema), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_quotes_views_and_detached_facts_do_not_mutate_or_leak_private_history(self):
        g = self.one(); before = g.snapshot()
        for _ in range(2):
            self.assertEqual(quote_cost(g.state, g.registry, self.source(g)).amount, 9)
            capture_generated_quote_fact(g.state, g.registry, 1, GIANT)
            for player in (1, 2):
                text = json.dumps(g.observe(player))
                for private in ('hero_health_change_history', 'next_hero_health_change_id',
                        'hero_health_changes', 'health_history_length', 'submitted_cost', 'payment_state'):
                    self.assertNotIn(private, text)
        state = g.state; state.hero_health_change_history.clear()
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.price(g), 9)


if __name__ == '__main__':
    unittest.main()
