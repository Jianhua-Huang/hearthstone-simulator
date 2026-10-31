"""A single real intrinsic quantity: the current payer hero's missing health."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (BoardMinionCostSpec, CardDefinition, CardType, CostSpec,
    Game, HandCountCostSpec, HeroMissingHealthCostSpec, IllegalAction,
    InteractableSpec, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_cost, quote_generated_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption,
    CopyMinion, Damage, GainArmor, Heal, InvokeBehavior, ModifyCost, ReplaceHero,
    RequestChoice, ReturnToHand, SetStats, Silence)
from hs_sim.engine.health_loss import ChangeHeroMaxHealth, GainMaxHealth, LoseHealth
from hs_sim.engine.intrinsic_costs import (validate_generated_quote_fact,
    validate_intrinsic_history_prefix, validate_intrinsic_origin,
    validate_intrinsic_stage_fact)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


MOLTEN = 'EX1_620'
PATH = Path(__file__).resolve().parents[1] / 'data/support/hero-missing-health-cost-basics.json'
PIN = 'f7120afcf6d672e92dd9ee3eb36b05b34ba79bbd2863d79eb4114424525af9c2'


def evidence():
    support = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support) != PIN:
        raise ValueError('Hero quantity evidence changed')
    rows = {}
    for item in support['records']:
        if canonical_digest(item['data']) != item['data_sha256']:
            raise ValueError('Hero quantity complete raw changed')
        rows[item['id']] = item['data']
    return rows


def registry():
    r = opening_registry()
    row = evidence()[MOLTEN]
    r.register_card(CardDefinition(MOLTEN, row['name'], CardType.MINION,
        cost=row['cost'], attack=row['attack'], health=row['health'],
        metadata=metadata(rarity=Rarity.EPIC, tribes=('elemental',)),
        hero_missing_health_cost=HeroMissingHealthCostSpec()))
    r.register_card(replace(r.card('mage.hero'), id='hero.forty', health=40))
    r.register_behavior('hero.inert', lambda c: ())

    def hero(c, player=None):
        return c.state.players[c.player_id if player is None else player].hero_id

    def held(c):
        return next(eid for eid in c.state.players[c.player_id].hand if c.state.entities[eid].card_id == MOLTEN)

    def first(c):
        return c.state.players[c.player_id].board[0]

    scripts = {
        'hero.hurt': lambda c: (Damage(hero(c), 10, c.source_id),),
        'hero.lose20': lambda c: (LoseHealth(hero(c), 20, c.source_id),),
        'hero.enemy.lose': lambda c: (LoseHealth(hero(c, 3 - c.player_id), 7, c.source_id),),
        'hero.heal': lambda c: (Heal(hero(c), 5, c.source_id),),
        'hero.armor': lambda c: (GainArmor(c.player_id, 20),),
        'hero.grow': lambda c: (GainMaxHealth(c.player_id, 5, c.source_id),),
        'hero.shrink': lambda c: (ChangeHeroMaxHealth(c.player_id, -5, c.source_id),),
        'hero.clamp.grow': lambda c: (ChangeHeroMaxHealth(c.player_id, 10, c.source_id, 'clamp_current'),),
        'hero.clamp.shrink': lambda c: (ChangeHeroMaxHealth(c.player_id, -20, c.source_id, 'clamp_current'),),
        'hero.set': lambda c: (SetStats(hero(c), health=35, source_id=c.source_id),),
        'hero.replace': lambda c: (ReplaceHero(c.player_id, 'hero.forty', health=25),),
        'hero.copy': lambda c: (CopyMinion(first(c), c.player_id, mode='base'),),
        'hero.silence': lambda c: (Silence(first(c)),),
        'hero.bounce': lambda c: (ReturnToHand(first(c)),),
        'hero.local': lambda c: (ModifyCost(held(c), CostSpec(delta=-3)),),
        'hero.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-2, card_ids=(MOLTEN,))),),
        'hero.fail': lambda c: (Heal(hero(c), 5, c.source_id), AddToHand(c.player_id, 'unknown.hero.quantity')),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))

    def pause(c):
        if c.state.entities[c.event.source_id].card_id != MOLTEN:
            return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('heal', 'Heal after payment', (Heal(hero(c), 5, c.source_id),)),
            ChoiceOption('fault', 'Delayed failure fixture', (InvokeBehavior('hero.fail', c.source_id, c.player_id),)),
        ), c.source_id),)

    r.register_behavior('hero.pause', pause)
    r.register_card(CardDefinition('hero.watch', 'Paid completion observer', CardType.MINION,
        attack=1, health=3, triggers=(TriggerSpec('card_played', 'hero.pause'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class HeroMissingHealthCostTests(unittest.TestCase):
    def game(self, hand=(MOLTEN,), *, enemy_hand=(), board=(), mana=10, armor=0, enemy_armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, mana=mana, max_mana=10, armor=armor),
            PlayerSetup('warrior.hero', hand=enemy_hand, armor=enemy_armor)), seed=17), registry())

    def source(self, g, cid=MOLTEN, player=1):
        return next(g.state.entities[eid] for eid in g.state.players[player].hand if g.state.entities[eid].card_id == cid)

    def fact(self, g, cid=MOLTEN, player=1):
        return capture_quote_fact(g.state, g.registry, capture_cost_input(self.source(g, cid, player)))

    def price(self, g, cid=MOLTEN, player=1):
        return self.fact(g, cid, player).amount

    def play(self, g, cid):
        eid = self.source(g, cid).id
        g.apply(PlayCard(1, eid))
        return eid

    def choose(self, g, option='heal'):
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

    def test_complete_molten_raw_records_and_actual_missing_health_text_are_pinned(self):
        rows = evidence()
        original = {row['id']: row for row in json.loads((PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(set(rows), {MOLTEN, 'CORE_EX1_620'})
        for cid, row in rows.items():
            self.assertEqual(row, original[cid])
            self.assertEqual((row['cost'], row['attack'], row['health']), (20, 8, 8))
        self.assertIn('each Health your hero\nis missing', rows[MOLTEN]['text_en'])

    def test_finite_policy_and_only_ordinary_minion_declarations_are_supported(self):
        for profile in (None, True, 'damage.history', 'opponent.health', 'expression'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                HeroMissingHealthCostSpec(profile)
        r = registry()
        for changes in ({'kind': CardType.SPELL, 'health': 0}, {'hero_missing_health_cost': 'expression'},
                {'interactable': InteractableSpec('hero.inert')}, {'board_minion_cost': BoardMinionCostSpec()},
                {'hand_count_cost': HandCountCostSpec()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                r.register_card(replace(r.card(MOLTEN), id='bad.hero.quantity', **changes))

    def test_actual_payer_uses_own_current_hero_and_ignores_opponent_deficit(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.enemy.lose'), enemy_hand=(MOLTEN,))
        self.assertEqual((self.price(g), self.price(g, player=2)), (20, 20))
        self.play(g, 'hero.hurt')
        self.play(g, 'hero.enemy.lose')
        self.assertEqual((self.price(g), self.price(g, player=2)), (10, 13))
        f = self.fact(g, player=2).intrinsic.hero_missing_health
        self.assertEqual((f.hero_id, f.player_id, f.max_health, f.health), (g.state.players[2].hero_id, 2, 30, 23))
        self.portable(g)

    def test_damage_followed_by_healing_requotes_current_deficit_not_total_damage(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.heal'))
        self.play(g, 'hero.hurt')
        self.assertEqual(self.price(g), 10)
        self.play(g, 'hero.heal')
        self.assertEqual(self.price(g), 15)
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity), (30, 25, 5))
        self.portable(g)

    def test_armor_absorbs_damage_but_direct_health_loss_counts_actual_missing_health(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.lose20'), armor=20, enemy_armor=200)
        self.play(g, 'hero.hurt')
        self.assertEqual(self.price(g), 20)
        self.play(g, 'hero.lose20')
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((self.price(g), hero.armor), (0, 10))
        self.portable(g)

    def test_existing_maximum_growth_and_preserve_missing_reduction_keep_quantity(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.grow', 'hero.shrink'))
        self.play(g, 'hero.hurt')
        self.play(g, 'hero.grow')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity, self.price(g)), (35, 25, 10, 10))
        self.play(g, 'hero.shrink')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity, self.price(g)), (30, 20, 10, 10))
        self.portable(g)

    def test_clamp_current_maximum_policy_requotes_the_existing_public_health_values(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.clamp.grow', 'hero.clamp.shrink'))
        self.play(g, 'hero.hurt')
        self.play(g, 'hero.clamp.grow')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity, self.price(g)), (40, 20, 20, 0))
        self.play(g, 'hero.clamp.shrink')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity, self.price(g)), (20, 20, 0, 20))
        self.portable(g)

    def test_existing_set_stats_resets_deficit_without_retaining_prior_damage_price(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.set'))
        self.play(g, 'hero.hurt')
        self.play(g, 'hero.set')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertEqual((f.max_health, f.health, f.quantity, self.price(g)), (35, 35, 0, 20))
        self.portable(g)

    def test_hero_replacement_uses_new_current_identity_and_keeps_original_frozen_fact(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.replace'))
        self.play(g, 'hero.hurt')
        stage = self.fact(g).intrinsic
        old = stage.hero_missing_health.hero_id
        self.play(g, 'hero.replace')
        f = self.fact(g).intrinsic.hero_missing_health
        self.assertNotEqual(f.hero_id, old)
        self.assertEqual((f.hero_card_id, f.max_health, f.health, f.quantity, self.price(g)), ('hero.forty', 40, 25, 15, 5))
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)
        self.portable(g)

    def test_physical_and_generated_queries_share_quantity_without_writing_state_rng_or_ids(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'))
        self.play(g, 'hero.hurt')
        before = g.snapshot()
        for _ in range(3):
            generated = capture_generated_quote_fact(g.state, g.registry, 1, MOLTEN)
            self.assertEqual(generated.intrinsic.hero_missing_health, self.fact(g).intrinsic.hero_missing_health)
            self.assertEqual((generated.amount, self.price(g)), (10, 10))
            validate_generated_quote_fact(g.registry, generated)
            g.for_player(1).legal_actions()
        self.assertEqual(g.snapshot(), before)
        subject = self.source(g)
        self.assertEqual((subject.base_cost, subject.cost_modifier, subject.enchantments), (20, 0, []))

    def test_real_molten_zero_floor_allows_zero_mana_play_and_one_zero_payment(self):
        g = self.game(hand=(MOLTEN, 'hero.lose20'), mana=0)
        self.play(g, 'hero.lose20')
        self.assertEqual(self.price(g), 0)
        self.play(g, MOLTEN)
        play = g.state.play_history[-1]
        self.assertEqual((play.cost, g.state.players[1].mana, play.submitted_cost.quote.intrinsic.hero_missing_health.quantity), (0, 0, 20))
        self.portable(g)

    def test_original_intrinsic_local_and_external_cost_order_pays_once(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.local', 'hero.external'))
        for cid in ('hero.hurt', 'hero.local', 'hero.external'):
            self.play(g, cid)
        f = self.fact(g)
        self.assertEqual((f.intrinsic.base_cost, f.intrinsic.amount, f.local_amount, f.amount), (20, 10, 7, 5))
        self.play(g, MOLTEN)
        self.assertEqual((g.state.play_history[-1].cost, g.state.players[1].mana), (5, 5))
        self.portable(g)

    def test_generated_initial_external_and_final_minimum_keep_shared_cost_order(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.external'))
        self.play(g, 'hero.hurt')
        self.play(g, 'hero.external')
        f = capture_generated_quote_fact(g.state, g.registry, 1, MOLTEN, cost=CostSpec(delta=-3))
        self.assertEqual((f.intrinsic.amount, f.local_amount, f.amount), (10, 7, 5))
        validate_generated_quote_fact(g.registry, f)
        self.assertEqual(quote_generated_cost(g.state, g.registry, 1, MOLTEN, cost=CostSpec(set_to=0), minimum_cost=1).amount, 1)

    def test_player_display_enumeration_validation_and_actual_payment_share_original_hero_quote(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'))
        self.play(g, 'hero.hurt')
        subject = self.source(g)
        g.validate(PlayCard(1, subject.id))
        port = g.for_player(1)
        dto = port.legal_actions()
        ref = g.observe(1)['players'][0]['hand'][0]['ref']
        action = next(action for action in dto['actions'] if action.get('card') == ref)
        self.assertEqual(g.observe(1)['players'][0]['hand'][0]['cost']['amount'], 10)
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        play = g.state.play_history[-1]
        self.assertEqual((play.cost, g.state.players[1].mana, play.submitted_cost.quote.intrinsic.hero_missing_health.quantity), (10, 0, 10))
        self.portable(g)

    def test_insufficient_mana_does_not_change_health_hand_rng_or_payment(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'), mana=9)
        self.play(g, 'hero.hurt')
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, MOLTEN)
        self.assertEqual(g.snapshot(), before)

    def test_printed_copy_silence_and_bounce_preserve_rule_and_requote_current_hero(self):
        g = self.game(hand=('hero.hurt', 'hero.copy', 'hero.silence', 'hero.bounce', 'hero.bounce', 'hero.heal'), board=(MOLTEN,))
        for cid in ('hero.hurt', 'hero.copy', 'hero.silence', 'hero.bounce', 'hero.bounce', 'hero.heal'):
            self.play(g, cid)
        self.assertEqual(len(g.state.players[1].hand), 2)
        for eid in g.state.players[1].hand:
            subject = g.state.entities[eid]
            self.assertEqual(subject.base_cost, 20)
            self.assertEqual(g.registry.card(subject.card_id).hero_missing_health_cost, HeroMissingHealthCostSpec())
            self.assertEqual(quote_cost(g.state, g.registry, subject).amount, 15)
        self.portable(g)

    def test_frozen_old_quantity_survives_real_healing_but_is_not_a_new_origin(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt', 'hero.heal'))
        self.play(g, 'hero.hurt')
        stage = self.fact(g).intrinsic
        validate_intrinsic_origin(stage, g.state, g.registry)
        self.play(g, 'hero.heal')
        validate_intrinsic_history_prefix(stage, g.state, g.registry)
        self.assertEqual((stage.hero_missing_health.quantity, self.price(g)), (10, 15))
        with self.assertRaises(ValueError):
            validate_intrinsic_origin(stage, g.state, g.registry)

    def test_paid_completion_wait_restores_and_healing_does_not_rewrite_or_repeat_payment(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'), board=('hero.watch',))
        self.play(g, 'hero.hurt')
        subject_id = self.play(g, MOLTEN)
        receipt = g.state.play_history[-1].submitted_cost
        self.assertIsNotNone(g.state.pending_choice)
        saved = self.portable(g)
        restored = Game.from_snapshot(saved, registry())
        for current in (g, restored):
            self.choose(current)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(g.state.play_history[-1].submitted_cost, receipt)
        self.assertEqual((receipt.quote.amount, receipt.quote.intrinsic.hero_missing_health.quantity), (10, 10))
        self.assertEqual(quote_cost(g.state, g.registry, g.state.entities[subject_id]).amount, 15)
        self.assertEqual(g.state.players[1].mana, 0)
        self.assertIsNotNone(g.state.play_history[-1].paid_hand_close)
        self.portable(g)

    def test_delayed_failure_rolls_back_changed_health_and_original_paid_receipt(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'), board=('hero.watch',))
        self.play(g, 'hero.hurt')
        self.play(g, MOLTEN)
        before = self.portable(g)
        visible = g.observe(1)
        with self.assertRaisesRegex(ResolutionError, 'unknown.hero.quantity'):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.observe(1), visible)
        self.portable(g)

    def test_health_fact_rejects_boolean_future_invalid_payer_and_inconsistent_operands(self):
        g = self.game()
        f = self.fact(g).intrinsic.hero_missing_health
        for changes in ({'player_id': True}, {'player_id': 0}, {'hero_id': f.next_entity_id},
                {'hero_id': True}, {'next_entity_id': True}, {'max_health': True}, {'health': 31},
                {'health': 29}, {'quantity': 1}, {'quantity': -1}, {'before': True}, {'after': 19},
                {'hero_card_id': ''}, {'spec': None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(f, **changes)

    def test_stage_validation_requires_original_supported_hero_and_correct_payer_base(self):
        g = self.game()
        stage = self.fact(g).intrinsic
        f = stage.hero_missing_health
        for face in ('card.1', 'unknown.hero.quantity'):
            bad = replace(stage, hero_missing_health=replace(f, hero_card_id=face))
            with self.subTest(face=face), self.assertRaises(ValueError):
                validate_intrinsic_stage_fact(g.registry, bad)
        for changes in ({'player_id': 2}, {'before': 19, 'after': 19}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(stage, hero_missing_health=replace(f, **changes))
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, replace(stage, hero_missing_health=None))
        normal = self.fact(self.game(hand=('card.1',)), 'card.1').intrinsic
        with self.assertRaises(ValueError):
            validate_intrinsic_stage_fact(g.registry, replace(normal, hero_missing_health=replace(f, before=1, after=1)))

    def test_current_hero_inventory_rejects_wrong_zone_controller_or_unknown_face(self):
        g = self.game()
        for attribute, value in (('zone', Zone.SETASIDE), ('controller', 2), ('card_id', 'unknown.hero.quantity')):
            state = g.state
            setattr(state.entities[state.players[1].hero_id], attribute, value)
            source = state.entities[state.players[1].hand[0]]
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                capture_quote_fact(state, g.registry, capture_cost_input(source))

    def test_physical_quote_cannot_borrow_subject_from_after_original_allocator(self):
        g = self.game()
        f = self.fact(g)
        with self.assertRaisesRegex(ValueError, 'newer than its captured allocator'):
            replace(f, quote_input=replace(f.quote_input, source_id=f.intrinsic.hero_missing_health.next_entity_id))

    def test_rehashed_snapshots_reject_missing_extra_rewritten_and_borrowed_health_fact(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'))
        self.play(g, 'hero.hurt')
        self.play(g, MOLTEN)
        saved = self.portable(g)
        for edit in ('quantity', 'missing_field', 'missing_fact', 'extra', 'health', 'face', 'future', 'other_hero'):
            bad = deepcopy(saved)
            intrinsic = bad['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']
            health = intrinsic['hero_missing_health']
            if edit == 'quantity': health['quantity'] += 1
            elif edit == 'missing_field': del intrinsic['hero_missing_health']
            elif edit == 'missing_fact': intrinsic['hero_missing_health'] = None
            elif edit == 'extra': health['invented'] = 1
            elif edit == 'health': health['health'] += 1
            elif edit == 'face': health['hero_card_id'] = 'card.1'
            elif edit == 'future': health['hero_id'] = health['next_entity_id']
            else: health['hero_id'] = g.state.players[2].hero_id
            with self.subTest(edit=edit), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), registry())

    def test_player_public_price_does_not_export_internal_health_fact_or_opponent_hand(self):
        g = self.game(hand=(MOLTEN, 'hero.hurt'), enemy_hand=('card.1', 'card.2'))
        twin = self.game(hand=(MOLTEN, 'hero.hurt'), enemy_hand=('card.3', 'card.4'))
        self.play(g, 'hero.hurt')
        self.play(twin, 'hero.hurt')
        own = g.observe(1)
        self.assertEqual(own['players'][0]['hand'][0]['cost']['amount'], 10)
        self.assertEqual(twin.observe(1)['players'][0]['hand'][0]['cost'], own['players'][0]['hand'][0]['cost'])
        self.assertTrue(all(row['card_id'] is None and row.get('cost') is None for row in own['players'][1]['hand']))
        for secret in ('hero_missing_health', 'next_entity_id', 'payment_state', 'submitted_cost'):
            self.assertNotIn(secret, json.dumps(own))

    def test_default_none_and_strict_current_wire_preserve_public_protocols(self):
        g = self.game(hand=('card.1',))
        self.assertIsNone(self.fact(g, 'card.1').intrinsic.hero_missing_health)
        self.play(g, 'card.1')
        saved = self.portable(g)
        self.assertEqual((g.ruleset.id, g.mechanics.version, saved['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual((g.observe(1)['version'], g.for_player(1).observe()['version']),
            ('player-view-v122', 'player-actions-v13'))
        for version in (1, 171, 172, 217, True, '173'):
            bad = deepcopy(saved)
            bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, f'schemas 1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
                Game.from_snapshot(bad, registry())


if __name__ == '__main__':
    unittest.main()
