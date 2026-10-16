"""Actual remaining-health facts, before the SCH_140 finite price consumer."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game,
    HealthLossReplacementSpec, IllegalAction, Keyword, PaymentType, PlayCard, PlayerSetup,
    ResolutionError, RewindSpec, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, Buff, ChoiceOption, Damage,
    DamageBatch, Destroy, GainArmor, GrantKeyword, Heal, InvokeBehavior, RemoveEnchantment,
    ReplaceHero, RequestChoice, SetStats)
from hs_sim.engine.generated_heroes import InstallGeneratedHeroCard
from hs_sim.engine.health_loss import ChangeHeroMaxHealth, GainMaxHealth, LoseHealth, StealHeroHealth
from hs_sim.engine.hero_health_history import health_change_count, validate_state
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import HeroHealthChangeRecord
from hs_sim.engine.payment_projection import payment_plan, project_payment
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import registry as opening_registry

SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/hero-health-change-basics.json'
PIN = '12ac7eff1d3650d7bbf8a3f12ea44dd366069508822b950dc861ba1711e31309'


def registry():
    r = opening_registry()
    r.register_card(replace(r.card('mage.hero'), id='hero.forty', health=40))
    r.register_card(replace(r.card('mage.hero'), id='hero.playable', hero_card=True))
    r.register_card(CardDefinition('loss.guard', 'Existing replacement', CardType.MINION,
        health=4, health_loss_replacements=(HealthLossReplacementSpec(),)))
    r.register_card(CardDefinition('life.source', 'Existing lifesteal', CardType.MINION,
        health=4, keywords=(Keyword.LIFESTEAL,)))

    def hero(c, player=None):
        return c.state.players[c.player_id if player is None else player].hero_id

    scripts = {
        'hurt': lambda c: (Damage(hero(c), 3, c.source_id),),
        'enemy.hurt': lambda c: (Damage(hero(c, 3-c.player_id), 3, c.source_id),),
        'heal': lambda c: (Heal(hero(c), 2, c.source_id),),
        'zero': lambda c: (Damage(hero(c), 0, c.source_id), Heal(hero(c), 4, c.source_id)),
        'batch': lambda c: (DamageBatch((Damage(hero(c), 3, c.source_id),
            Damage(hero(c, 3-c.player_id), 3, c.state.players[c.player_id].board[0]))),),
        'two.packets': lambda c: (DamageBatch((Damage(hero(c), 2, c.source_id), Damage(hero(c), 3, c.source_id))),),
        'lifesteal': lambda c: (DamageBatch((Damage(hero(c), 3, c.source_id),
            Damage(hero(c, 3-c.player_id), 3, c.state.players[c.player_id].board[0]))),),
        'armor': lambda c: (GainArmor(c.player_id, 8),),
        'immune': lambda c: (GrantKeyword(hero(c), Keyword.IMMUNE),),
        'shield': lambda c: (GrantKeyword(hero(c), Keyword.DIVINE_SHIELD),),
        'loss': lambda c: (LoseHealth(hero(c), 4, c.source_id),),
        'grow': lambda c: (GainMaxHealth(c.player_id, 5, c.source_id),),
        'clamp.grow': lambda c: (ChangeHeroMaxHealth(c.player_id, 10, c.source_id, 'clamp_current'),),
        'clamp.shrink': lambda c: (ChangeHeroMaxHealth(c.player_id, -20, c.source_id, 'clamp_current'),),
        'transfer': lambda c: (StealHeroHealth(c.player_id, 3-c.player_id, 5, c.source_id),),
        'set': lambda c: (SetStats(hero(c), health=20, source_id=c.source_id),),
        'same.set': lambda c: (SetStats(hero(c), health=30, source_id=c.source_id),),
        'buff': lambda c: (Buff(hero(c), health=5, source_id=c.source_id),),
        'negative.maximum': lambda c: (Buff(hero(c), health=-35, source_id=c.source_id),),
        'temporary.buff': lambda c: (Buff(hero(c), health=5, source_id=c.source_id, expires_turn=c.state.turn),),
        'remove': lambda c: (RemoveEnchantment(hero(c), c.state.entities[hero(c)].enchantments[-1].id),),
        'replace.same': lambda c: (ReplaceHero(c.player_id, 'hero.forty'),),
        'replace.changed': lambda c: (ReplaceHero(c.player_id, 'hero.forty', health=25),),
        'generated.hero': lambda c: (InstallGeneratedHeroCard(c.player_id, 'hero.playable', c.source_id),),
        'pay.setup': lambda c: (AddCostModifier(c.player_id,
            CostSpec(payment=PaymentType.HEALTH, card_ids=('pay',)), 1),),
        'pay': lambda c: (Heal(hero(c), 2, c.source_id),),
        'late.acquire': lambda c: (AddToHand(c.player_id, 'card.2'),),
        'fatal': lambda c: (LoseHealth(hero(c), 40, c.source_id),),
        'destroy.hero': lambda c: (Destroy(hero(c), c.source_id),),
        'fail': lambda c: (Damage(hero(c), 3, c.source_id), AddToHand(c.player_id, 'unknown.health.fact')),
        'wait': lambda c: (Damage(hero(c), 3, c.source_id), RequestChoice(c.player_id, (
            ChoiceOption('heal', 'Heal', (Heal(hero(c), 2, c.source_id),)),
            ChoiceOption('fault', 'Failure probe', (InvokeBehavior('fail', c.source_id, c.player_id),)),
        ), c.source_id)),
    }
    for name, fn in scripts.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL,
            cost=5 if name == 'pay' else 0, on_play=name))
    r.register_behavior('retry.health', lambda c: (Damage(hero(c), 3, c.source_id),
        ReplaceHero(c.player_id, 'hero.forty', health=20)))
    r.register_card(CardDefinition('retry.health', 'Original state retry', CardType.SPELL,
        on_play='retry.health', keywords=(Keyword.REWIND,), rewind=RewindSpec()))

    def inspect(c):
        if c.state.entities[c.event.source_id].card_id == 'batch' and health_change_count(c.state, c.player_id) != 2:
            raise ResolutionError('Original first listener missed the complete numeric batch')
        return ()
    r.register_behavior('inspect', inspect)
    r.register_card(CardDefinition('watch', 'Original capture probe', CardType.MINION,
        health=4, triggers=(TriggerSpec('damage_dealt', 'inspect'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class HeroHealthChangeTests(unittest.TestCase):
    def game(self, hand=(), *, enemy_hand=(), board=(), armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, armor=armor,
                mana=10, max_mana=10, deck=('card.1',)*8),
            PlayerSetup('warrior.hero', hand=enemy_hand, mana=10, max_mana=10, deck=('card.1',)*8)), seed=19), registry())

    def play(self, g, name):
        player = g.state.active_player
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(player, source))

    def rows(self, g): return g.state.hero_health_change_history
    def count(self, g, player=1): return health_change_count(g.state, player)
    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)

    def test_complete_native_evidence_count_not_amount_or_deficit(self):
        raw = json.loads(SUPPORT.read_text(encoding='utf-8'))
        self.assertEqual(canonical_digest(raw), PIN)
        row = raw['records'][0]
        self.assertEqual(canonical_digest(row['data']), row['data_sha256'])
        self.assertEqual((row['id'], row['data']['cost'], row['data']['attack'], row['data']['health']), ('SCH_140', 10, 8, 8))
        self.assertIn('each time', row['data']['text_en'])
        self.assertNotIn('SCH_140', registry().cards)

    def test_initial_health_and_armor_do_not_invent_occurrences(self):
        g = self.game(armor=7)
        self.assertEqual((self.rows(g), self.count(g), g.state.next_hero_health_change_id), ([], 0, 1))

    def test_damage_and_healing_each_count_once_regardless_of_amount(self):
        g = self.game(('hurt', 'heal')); self.play(g, 'hurt'); self.play(g, 'heal')
        self.assertEqual([(r.health_before, r.health_after) for r in self.rows(g)], [(30, 27), (27, 29)])
        self.assertEqual(self.count(g), 2); self.check(g)

    def test_batch_net_zero_keeps_two_actual_changes(self):
        g = self.game(('batch',), board=('life.source', 'watch')); self.play(g, 'batch')
        self.assertEqual([(r.health_before, r.health_after) for r in self.rows(g) if r.player_id == 1], [(30, 27), (27, 30)])
        self.assertEqual(self.count(g), 2)
        self.assertTrue(all(health_result(e) is not None for e in g.events if e.kind == 'health_resolved'))
        self.check(g)

    def test_multiple_damage_packets_are_distinct_occurrences(self):
        g = self.game(('two.packets',)); self.play(g, 'two.packets')
        self.assertEqual([r.id for r in self.rows(g)], [1, 2]); self.assertEqual(self.count(g), 2)

    def test_zero_damage_and_full_overheal_do_not_count(self):
        g = self.game(('zero',)); self.play(g, 'zero')
        self.assertEqual((self.rows(g), self.count(g)), ([], 0)); self.check(g)

    def test_armor_only_damage_does_not_count(self):
        g = self.game(('hurt',), armor=10); self.play(g, 'hurt')
        self.assertEqual(self.count(g), 0); self.check(g)

    def test_armor_gain_does_not_count(self):
        g = self.game(('armor',)); self.play(g, 'armor'); self.assertEqual(self.count(g), 0)

    def test_immune_and_shield_prevention_do_not_count(self):
        for protection in ('immune', 'shield'):
            with self.subTest(protection=protection):
                g = self.game((protection, 'hurt')); self.play(g, protection); self.play(g, 'hurt')
                self.assertEqual(self.count(g), 0); self.check(g)

    def test_direct_loss_counts_actual_health_and_bypasses_armor(self):
        g = self.game(('loss',), armor=20); self.play(g, 'loss')
        self.assertEqual((self.count(g), self.rows(g)[0].event_kind), (1, 'health_lost'))
        self.assertEqual(self.rows(g)[0].health_after, 26); self.check(g)

    def test_replaced_damage_growth_counts_once_not_both_events(self):
        g = self.game(('hurt',), board=('loss.guard',)); self.play(g, 'hurt')
        self.assertEqual((self.count(g), self.rows(g)[0].health_after), (1, 33))
        self.assertEqual(self.rows(g)[0].event_kind, 'health_resolved'); self.check(g)

    def test_replaced_direct_loss_growth_counts_once(self):
        g = self.game(('loss',), board=('loss.guard',)); self.play(g, 'loss')
        self.assertEqual((self.count(g), self.rows(g)[0].health_after), (1, 34)); self.check(g)

    def test_lifesteal_records_actual_healing_separately(self):
        g = self.game(('lifesteal',), board=('life.source',)); self.play(g, 'lifesteal')
        self.assertEqual([(r.player_id, r.health_before, r.health_after) for r in self.rows(g)],
            [(1, 30, 27), (2, 30, 27), (1, 27, 30)])
        self.assertEqual((self.count(g), self.count(g, 2)), (2, 0)); self.check(g)

    def test_own_turn_relation_uses_real_owner_interval(self):
        g = self.game(('enemy.hurt',), enemy_hand=('hurt', 'enemy.hurt'))
        self.play(g, 'enemy.hurt'); self.assertEqual(self.count(g, 2), 0)
        g.apply(EndTurn(1)); self.play(g, 'hurt'); self.play(g, 'enemy.hurt')
        self.assertEqual((self.count(g), self.count(g, 2)), (0, 1))
        self.assertEqual([(r.active_player, r.owner_turn_id) for r in self.rows(g)], [(1, 1), (2, 2), (2, 2)])
        self.check(g)

    def test_prior_turn_changes_survive_and_later_acquisition_sees_them(self):
        g = self.game(('hurt', 'late.acquire')); self.play(g, 'hurt')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'late.acquire')
        self.assertEqual(self.count(g), 1); self.check(g)

    def test_maximum_growth_counts_remaining_change(self):
        g = self.game(('grow',)); self.play(g, 'grow')
        r = self.rows(g)[0]
        self.assertEqual((r.health_before, r.max_health_before, r.health_after, r.max_health_after), (30, 30, 35, 35))
        self.assertEqual(self.count(g), 1); self.check(g)

    def test_maximum_only_growth_and_clamp_current_do_not_count(self):
        g = self.game(('clamp.grow',)); self.play(g, 'clamp.grow')
        self.assertEqual(self.count(g), 0); self.check(g)

    def test_maximum_shrink_counts_only_when_current_is_clamped(self):
        g = self.game(('clamp.shrink',)); self.play(g, 'clamp.shrink')
        self.assertEqual((self.count(g), self.rows(g)[0].health_after), (1, 10)); self.check(g)

    def test_atomic_transfer_records_each_actual_hero_once(self):
        g = self.game(('transfer',)); self.play(g, 'transfer')
        self.assertEqual([(r.player_id, r.health_after) for r in self.rows(g)], [(2, 25), (1, 35)])
        self.assertEqual((self.count(g), self.count(g, 2)), (1, 0)); self.check(g)

    def test_stat_set_and_same_set_use_actual_before_after(self):
        g = self.game(('same.set', 'set')); self.play(g, 'same.set'); self.play(g, 'set')
        self.assertEqual(self.count(g), 1); self.assertEqual(self.rows(g)[0].event_kind, 'stats_changed'); self.check(g)

    def test_signed_health_buff_uses_original_mutator(self):
        g = self.game(('buff',)); self.play(g, 'buff')
        self.assertEqual((self.count(g), self.rows(g)[0].health_after), (1, 35)); self.check(g)

    def test_attachment_removal_counts_actual_clamp_once(self):
        g = self.game(('buff', 'remove')); self.play(g, 'buff'); self.play(g, 'remove')
        self.assertEqual([r.health_after for r in self.rows(g)], [35, 30])
        self.assertEqual(self.rows(g)[-1].event_kind, 'enchantment_removed'); self.check(g)

    def test_expiry_is_in_the_original_ending_owner_interval(self):
        g = self.game(('temporary.buff',)); self.play(g, 'temporary.buff'); g.apply(EndTurn(1))
        self.assertEqual([r.health_after for r in self.rows(g)], [35, 30])
        self.assertEqual((self.count(g), self.rows(g)[-1].owner_turn_id), (2, 1)); self.check(g)

    def test_same_health_hero_replacement_preserves_count(self):
        g = self.game(('hurt', 'replace.same')); self.play(g, 'hurt'); self.play(g, 'replace.same')
        self.assertEqual(self.count(g), 1); self.check(g)

    def test_changed_health_hero_replacement_records_both_physical_ids(self):
        g = self.game(('replace.changed',)); self.play(g, 'replace.changed'); row = self.rows(g)[0]
        self.assertNotEqual(row.old_hero_id, row.hero_id)
        self.assertEqual((row.health_before, row.health_after, self.count(g)), (30, 25, 1)); self.check(g)

    def test_played_and_generated_hero_preservation_do_not_invent_change(self):
        for name in ('hero.playable', 'generated.hero'):
            with self.subTest(name=name):
                g = self.game((name,)); self.play(g, name)
                self.assertEqual(self.count(g), 0); self.check(g)

    def test_health_payment_and_following_healing_are_independent_changes(self):
        g = self.game(('pay.setup', 'pay')); self.play(g, 'pay.setup'); self.play(g, 'pay')
        self.assertEqual([(r.event_kind, r.health_before, r.health_after) for r in self.rows(g)],
            [('health_spent', 30, 25), ('health_resolved', 25, 27)]); self.check(g)

    def test_armor_only_health_payment_has_no_payment_change(self):
        g = self.game(('pay.setup', 'pay'), armor=10); self.play(g, 'pay.setup'); self.play(g, 'pay')
        self.assertEqual(self.count(g), 0); self.check(g)

    def test_payment_projection_is_pure_and_contains_same_actual_record(self):
        g = self.game(('pay.setup', 'pay')); self.play(g, 'pay.setup')
        before = g.state; before.action_number += 1; untouched = deepcopy(before)
        entity = before.entities[before.players[1].hand[0]]
        quote = quote_cost(before, g.registry, entity)
        plan = payment_plan(before, quote); projected = project_payment(before, quote, cause_reason='PlayFromHand')
        self.assertEqual(before, untouched)
        self.assertEqual(health_change_count(projected.resource_state, 1), 1)
        self.assertTrue(plan.hero_health_data)
        self.play(g, 'pay')
        self.assertEqual(projected.resource_state.hero_health_change_history[0], self.rows(g)[0])

    def test_fatal_health_loss_is_recorded_but_destroy_flag_is_not_health(self):
        for name, expected in (('fatal', 1), ('destroy.hero', 0)):
            with self.subTest(name=name):
                g = self.game((name,)); self.play(g, name)
                self.assertEqual(self.count(g), expected); self.check(g)

    def test_exception_rolls_back_facts_events_rng_and_allocation(self):
        g = self.game(('fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fail')
        self.assertEqual(g.snapshot(), before)

    def test_waiting_restore_clone_and_replay_keep_original_facts(self):
        g = self.game(('wait',)); self.play(g, 'wait'); self.assertEqual(self.count(g), 1)
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry())
        choice = g.state.pending_choice
        action = SelectChoice(1, choice.id, ('heal',))
        g.apply(action); restored.apply(action)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(self.count(g), 2); self.check(g)

    def test_failed_choice_does_not_append_or_reallocate_health_facts(self):
        g = self.game(('wait',)); self.play(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1, g.state.pending_choice.id, ('fault',)))
        self.assertEqual(g.snapshot(), before)

    def test_saved_count_cursor_and_numeric_types_are_strict(self):
        g = self.game(('hurt',)); self.play(g, 'hurt')
        for field, value in (('id', True), ('health_after', 27.0), ('owner_turn_id', 99), ('hero_id', 999999)):
            with self.subTest(field=field):
                saved = g.snapshot(); saved['state']['hero_health_change_history'][0][field] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())
        saved = g.snapshot(); saved['state']['next_hero_health_change_id'] = 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())

    def test_saved_record_cannot_be_omitted_or_change_original_event(self):
        g = self.game(('hurt',)); self.play(g, 'hurt')
        saved = g.snapshot(); saved['state']['hero_health_change_history'] = []
        saved['state']['next_hero_health_change_id'] = 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())
        saved = g.snapshot(); saved['state']['hero_health_change_history'][0]['health_before'] = 29
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())

    def test_old_schema_and_missing_persistent_fields_are_rejected(self):
        g = self.game()
        self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        saved = g.snapshot(); saved['schema_version'] = 199
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry())
        for field in ('hero_health_change_history', 'next_hero_health_change_id'):
            saved = g.snapshot(); del saved['state'][field]
            with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())

    def test_retry_restores_original_facts_and_does_not_count_discarded_attempt(self):
        g = self.game(('hurt', 'retry.health')); self.play(g, 'hurt'); self.play(g, 'retry.health')
        self.assertEqual(self.count(g), 3); self.check(g)
        old_new_hero = g.state.players[1].hero_id
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('retry',)))
        self.assertEqual(self.count(g), 3)
        self.assertNotIn(old_new_hero, g.state.entities)
        self.assertEqual([r.id for r in self.rows(g)], [1, 2, 3])
        self.check(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.count(g), 3); self.check(g)

    def test_negative_maximum_keeps_original_fatal_stat_result(self):
        g = self.game(('negative.maximum',)); self.play(g, 'negative.maximum')
        row = self.rows(g)[0]
        self.assertEqual((row.health_after, row.max_health_after, self.count(g)), (-5, -5, 1))
        self.assertEqual((g.state.status, g.state.winner), ('finished', 2))
        self.assertFalse(any(e.kind == 'health_resolved' for e in g.events))
        self.check(g)

    def test_retry_original_host_cursor_is_strict(self):
        g = self.game(('retry.health',)); self.play(g, 'retry.health')
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('retry',)))
        saved = g.snapshot()
        marker = next(e for e in saved['events'] if e['kind'] == 'timeline_rewound')
        marker['data']['event_start'] = True
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(saved), registry())

    def test_queries_and_player_views_are_pure_and_do_not_expose_facts(self):
        g = self.game(('hurt',)); self.play(g, 'hurt'); before = g.snapshot()
        for _ in range(3):
            self.assertEqual(self.count(g), 1)
            for player in (1, 2):
                view = json.dumps(g.observe(player))
                self.assertNotIn('hero_health_change_history', view)
                self.assertNotIn('hero_health_transition', view)
                self.assertNotIn('hero_health_change_id', view)
        self.assertEqual(g.snapshot(), before)
        for player in (True, 1.0, 0, 3):
            with self.assertRaises(ValueError): health_change_count(g.state, player)

