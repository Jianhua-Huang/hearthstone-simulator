"""Actual Nature entries and their shared resource, stat and delivery boundaries."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import build_registry, past_nature_basic_effects as native
from hs_sim.cards.simple_followup_p89_cards import QUERIES, WO, PAST_POOL
from hs_sim.engine import Game, IllegalAction, PlayerSetup, ResolutionError, Ruleset, Scenario
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (Buff, ChoiceOption, Draw, GainTemporaryMana,
    InvokeBehavior, RandomDamage, RequestChoice)
from hs_sim.engine.model import CardClass, CardDefinition, CardType, Keyword, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.pools import resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k658.'
A, ZERO, DRAW, BOOST, TEMP, POWER, DEAD, DORM = (P + x for x in
    ('three', 'zero', 'draw', 'boost', 'temporary', 'spellpower', 'death_wait', 'dormant'))
FAIL = P + 'deliberate_failure'


def prompt(c, player):
    return RequestChoice(player, (ChoiceOption('continue', 'Continue'),
        ChoiceOption('fail', 'Fail after actual RNG', (
            RandomDamage((c.state.players[3-player].hero_id,), 1, c.source_id),
            InvokeBehavior(FAIL, c.source_id, player)))), c.source_id)


@lru_cache(maxsize=1)
def original_registry():
    return build_registry()


@lru_cache(maxsize=None)
def fixture(role='writer'):
    r = opening_registry()
    original = original_registry()
    overflow = original.card(native.OVERFLOW)
    r.register_behavior(overflow.on_play, original.behavior(overflow.on_play))
    r.register_card(overflow)
    r.register_pool_card(original.pool_card(native.OVERFLOW))
    native.register_past_nature_basic_effects(r)
    r.register_behavior(FAIL, lambda c: (_ for _ in ()).throw(ValueError('K658 deliberate reaction failure')))
    r.register_behavior(DRAW, lambda c: (Draw(c.player_id, 2, c.source_id),))
    r.register_behavior(BOOST, lambda c: (Buff(c.target_id, 3, 0, c.source_id),))
    r.register_behavior(TEMP, lambda c: (GainTemporaryMana(c.player_id, 4),))
    r.register_behavior(DEAD, lambda c: (prompt(c, c.player_id),))
    for cid, fields in ((A, dict(cost=3, attack=3, health=5)), (ZERO, dict(health=1)),
            (POWER, dict(health=20, spell_damage=2)), (DEAD, dict(health=3, deathrattle=DEAD)),
            (DORM, dict(attack=2, health=3, dormant_turns=2))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, metadata=metadata(collectible=False), **fields))
    for cid in (DRAW, BOOST, TEMP):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=metadata(collectible=False), **({'targeting': TargetSpec()} if cid == BOOST else {})))
    for kind in ('wait_summon', 'fail_summon', 'wait_deck', 'wait_damage'):
        key = P + kind

        def watch(c, kind=kind):
            e = c.event
            if kind.endswith('summon'):
                target = c.state.entities.get(e.target_id)
                if e.kind != 'minion_summoned' or target is None or target.card_id not in native.TOKENS:
                    return ()
                if kind == 'fail_summon':
                    return (RandomDamage((c.state.players[3-target.controller].hero_id,), 1, c.source_id),
                        InvokeBehavior(FAIL, c.source_id, target.controller))
                return (prompt(c, target.controller),)
            source = c.state.entities.get(e.source_id)
            if source is None or source.card_id not in native.SPELLS:
                return ()
            matching = (kind == 'wait_deck' and e.kind == 'stored_card_buffed' and source.card_id == 'TOY_805' or
                kind == 'wait_damage' and e.kind == 'damage_dealt' and source.card_id == 'REV_307')
            if not matching:
                return ()
            return (prompt(c, source.controller),)

        r.register_behavior(key, watch)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=30,
            triggers=tuple(TriggerSpec(event, key) for event in
                ('minion_summoned', 'stored_card_buffed', 'damage_dealt'))))
    r.validate()
    return r


@lru_cache(maxsize=None)
def host(role='writer'):
    return build_cn37_local_pool_format()


class PastNatureBasicTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'mini'
    registry_factory = staticmethod(lambda mode, role:
        host(role).registry if mode == 'host' else fixture(role))

    def game(self, hand, *, board=(), enemy=(), deck=(A,) * 6, enemy_deck=(A,) * 6,
            mana=10, maximum=10, cap=10, enemy_mana=10, enemy_maximum=10,
            watch=None, player=1, limit=7):
        self.mode = 'mini'
        own = PlayerSetup('mage.hero', hand=hand, board=board, deck=deck,
            mana=mana, max_mana=maximum, mana_cap=cap)
        other = PlayerSetup('mage.hero', board=enemy + ((P + watch,) if watch else ()),
            deck=enemy_deck, mana=enemy_mana, max_mana=enemy_maximum)
        return Game.from_scenario(Scenario((own, other) if player == 1 else (other, own),
            active_player=player, seed=658), fixture(), ruleset=Ruleset(max_board=limit))

    def test_complete_twenty_original_rows_twenty_eight_primary_faces_and_exact_nineteen_definitions(self):
        d = native.load_batch()
        self.assertEqual(len(d['cards'] + d['dependencies'] + d['existing_dependencies']), 20)
        self.assertEqual(len(d['official_observations']), 28)
        r = fixture()
        for row in d['cards'] + d['dependencies']:
            cid = row['record']['id']
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
        self.assertEqual(len(d['complete_druid_Nature_inventory']), 85)
        self.assertFalse(d['source_scope_bound'] or d['formal_pool_complete'] or d['cn_calibrated'])
        self.assertTrue(all(r.card(cid).on_play for cid in native.SPELLS))

    def test_registration_preflight_rejects_duplicate_or_changed_existing_dependency_without_partial_changes(self):
        r = fixture()
        before = r.fingerprint()
        with self.assertRaises(TargetValidationError):
            native.register_past_nature_basic_effects(r)
        self.assertEqual(r.fingerprint(), before)
        with patch.dict(r._pool_cards):
            r._pool_cards.pop(native.OVERFLOW)
            with self.assertRaises((UnsupportedDefinitionError, TargetValidationError)):
                native.register_past_nature_basic_effects(r)

    def test_biology_project_fills_each_actual_account_and_clips_independently(self):
        g = self.game(('BOT_054',), mana=5, maximum=5, enemy_mana=3, enemy_maximum=8)
        self.play(g, 'BOT_054')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (7, 6))
        self.assertEqual((g.state.players[2].max_mana, g.state.players[2].mana), (10, 5))
        g = self.game(('BOT_054',), enemy_mana=3, enemy_maximum=9)
        self.play(g, 'BOT_054')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (10, 9))
        self.assertEqual((g.state.players[2].max_mana, g.state.players[2].mana), (10, 4))
        self.assertFalse(g.state.players[1].hand or g.state.players[2].hand)

    def test_both_empty_growth_spells_pay_once_and_preserve_current_available_mana(self):
        for cid, cost, growth in (('CS2_013', 2, 1), ('BT_130', 4, 2)):
            with self.subTest(cid=cid):
                g = self.game((cid,), mana=5, maximum=5)
                self.play(g, cid)
                self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (5+growth, 5-cost))
                self.assertFalse(g.state.players[1].hand)

    def test_each_full_permanent_cap_generates_one_original_excess_mana_and_it_draws_normally(self):
        for cid in ('CS2_013', 'BT_130'):
            with self.subTest(cid=cid):
                g = self.game((cid,), maximum=12, mana=12, cap=12)
                self.play(g, cid)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [native.OVERFLOW])
                before = g.state.players[1].mana
                self.play(g, native.OVERFLOW)
                self.assertEqual(g.state.players[1].mana, before)
                self.assertEqual(len(g.state.players[1].deck), 5)
                self.assertEqual(self.entity(g, A).card_id, A)

    def test_overgrowth_one_crystal_below_cap_keeps_useful_growth_without_an_overflow_card(self):
        g = self.game(('BT_130',), maximum=9, mana=9)
        self.play(g, 'BT_130')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (10, 5))
        self.assertFalse(g.state.players[1].hand)

    def test_temporary_mana_above_cap_never_substitutes_for_permanent_crystals(self):
        g = self.game((TEMP, 'CS2_013'), maximum=8, mana=8)
        self.play(g, TEMP)
        self.assertEqual(g.state.players[1].mana, 12)
        self.play(g, 'CS2_013')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (9, 10))
        self.assertFalse(g.state.players[1].hand)

    def test_lightning_bloom_refreshes_spent_mana_and_applies_actual_next_turn_overload(self):
        from hs_sim.engine import EndTurn
        g = self.game(('SCH_427',), maximum=5, mana=1)
        self.play(g, 'SCH_427')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].max_mana, g.state.players[1].overload_owed), (3, 5, 2))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].overload_locked, g.state.players[1].mana), (6, 2, 4))
        self.portable(g)

    def test_barkskin_can_buff_either_minion_and_armor_always_goes_to_caster(self):
        for target_player in (1, 2):
            with self.subTest(target_player=target_player):
                g = self.game(('LOOT_047',), board=(A,), enemy=(A,))
                target = self.entity(g, A, target_player, zone='board')
                self.play(g, 'LOOT_047', target.id)
                target = g.state.entities[target.id]
                self.assertEqual((target.attack, target.max_health, target.health), (3, 8, 8))
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 0)

    def test_earthen_scales_uses_current_post_buff_attack_and_rejects_enemy_targets(self):
        g = self.game((BOOST, 'UNG_108'), board=(A,), enemy=(A,))
        target = self.entity(g, A, zone='board')
        self.play(g, BOOST, target.id)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, 'UNG_108', self.entity(g, A, 2, zone='board').id)
        self.assertEqual(g.snapshot(), before)
        self.play(g, 'UNG_108', target.id)
        target = g.state.entities[target.id]
        self.assertEqual((target.attack, target.max_health), (7, 6))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)

    def test_shrinkwrap_changes_only_original_deck_minions_and_material_survives_draw_and_play(self):
        g = self.game(('TOY_805', DRAW, A), deck=(A, ZERO, BOOST))
        original = tuple(g.state.players[1].deck)
        self.play(g, 'TOY_805')
        self.assertEqual(tuple(g.state.players[1].deck), original)
        first, zero, spell = (g.state.entities[i] for i in original)
        self.assertEqual((first.attack, first.max_health, local_cost(first)[0]), (2, 5, 2))
        self.assertEqual((zero.attack, zero.max_health, local_cost(zero)[0]), (0, 1, 0))
        self.assertEqual(local_cost(spell)[0], 0)
        self.assertEqual(local_cost(self.entity(g, A))[0], 3)
        self.play(g, DRAW)
        from hs_sim.engine import PlayCard
        g.apply(PlayCard(1, first.id))
        first = g.state.entities[first.id]
        self.assertEqual((first.zone, first.attack, first.max_health), (Zone.BOARD, 2, 5))
        self.assertEqual(g.state.players[1].mana, 5)

    def test_original_deck_stat_wait_restores_remaining_card_refs_and_private_events(self):
        g = self.game(('TOY_805',), deck=(A, ZERO), watch='wait_deck')
        self.play(g, 'TOY_805')
        self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        for _ in range(2):
            self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
        view = json.dumps(g.for_player(2).observe()) + json.dumps(g.player_events(2))
        for key in ('stored_card_buffed', 'cost_delta', 'card_reference', 'rng_state'):
            self.assertNotIn(key, view)

    def test_naturalize_draws_for_caster_opponent_even_when_destroying_a_friendly_minion(self):
        for target_player in (1, 2):
            with self.subTest(target_player=target_player):
                g = self.game(('EX1_161',), board=(A,), enemy=(A,))
                target = self.entity(g, A, target_player, zone='board')
                self.play(g, 'EX1_161', target.id)
                target = g.state.entities[target.id]
                self.assertEqual(target.zone, Zone.GRAVEYARD)
                self.assertEqual((len(g.state.players[1].hand), len(g.state.players[2].hand)), (0, 2))
                self.assertEqual(g.state.players[1].mana, 9)

    def test_naturalize_original_death_wait_precedes_ordinary_two_draws_and_recovers(self):
        g = self.game(('EX1_161',), enemy=(DEAD,))
        self.play(g, 'EX1_161', self.entity(g, DEAD, 2, zone='board').id)
        self.assertEqual(g.state.pending_choice.player_id, 2)
        self.assertEqual(len(g.state.players[2].hand), 0)
        restored = self.portable(g)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(len(g.state.players[2].hand), 2)

    def test_three_fixed_summon_spells_keep_original_token_ids_counts_and_turtle_taunt(self):
        for cid, token, count in (('BAR_533', 'BAR_533t', 2), ('BOT_420', 'EX1_tk9', 2), ('EX1_571', 'EX1_tk9', 3)):
            with self.subTest(cid=cid):
                g = self.game((cid,))
                self.play(g, cid)
                board = [g.state.entities[i] for i in g.state.players[1].board]
                self.assertEqual([e.card_id for e in board], [token] * count)
                self.assertTrue(all(Keyword.TAUNT in e.keywords for e in board) if cid == 'BAR_533' else all(Keyword.TAUNT not in e.keywords for e in board))

    def test_witchwood_apple_creates_two_original_playable_hand_treants_and_uses_normal_overflow(self):
        g = self.game(('GIL_663',) + (A,) * 9)
        self.play(g, 'GIL_663')
        tokens = [e for e in g.state.entities.values() if e.card_id == 'GIL_663t']
        self.assertEqual(len(tokens), 2)
        self.assertEqual({e.zone for e in tokens}, {Zone.HAND, Zone.GRAVEYARD})
        self.play(g, 'GIL_663t')
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(self.entity(g, 'GIL_663t', zone='board').attack, 2)

    def test_arbor_up_buffs_actual_post_summon_board_and_excludes_opponent_and_dormant(self):
        g = self.game(('YOP_026',), board=(A, DORM), enemy=(A,))
        self.play(g, 'YOP_026')
        self.assertEqual((self.entity(g, A, zone='board').attack, self.entity(g, A, zone='board').max_health), (5, 6))
        for i in g.state.players[1].board:
            e = g.state.entities[i]
            if e.card_id == 'DMF_061t2':
                self.assertEqual((e.attack, e.max_health), (4, 3))
        self.assertEqual(self.entity(g, DORM, zone='board').max_health, 3)
        self.assertEqual(self.entity(g, A, 2, zone='board').attack, 3)

    def test_arbor_up_full_and_partial_capacity_still_buff_every_actual_live_friendly_body(self):
        for occupied in (2, 3):
            with self.subTest(occupied=occupied):
                g = self.game(('YOP_026',), board=(A,) * occupied, limit=3)
                self.play(g, 'YOP_026')
                self.assertEqual(len(g.state.players[1].board), 3)
                self.assertEqual(sum(g.state.entities[i].card_id == 'DMF_061t2' for i in g.state.players[1].board), 3-occupied)
                self.assertTrue(all(g.state.entities[i].attack >= 4 for i in g.state.players[1].board))

    def test_natural_causes_spell_damage_does_not_change_original_treant_stats(self):
        g = self.game(('REV_307',), board=(POWER,))
        self.play(g, 'REV_307', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 4)
        token = self.entity(g, 'REV_336t2', zone='board')
        self.assertEqual((token.attack, token.max_health), (2, 2))

    def test_damage_wait_before_original_summon_and_failed_selection_restore_exact_rng_and_queue(self):
        g = self.game(('REV_307',), watch='wait_damage')
        self.play(g, 'REV_307', g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.players[1].board)
        restored = self.portable(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.entity(g, 'REV_336t2', zone='board').attack, 2)

    def test_actual_fixed_summon_and_random_reaction_failure_roll_back_complete_paid_action(self):
        g = self.game(('BAR_533',), watch='fail_summon')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'BAR_533')
        self.assertEqual(g.snapshot(), before)

    def test_second_player_executes_resources_and_hidden_hand_tokens_without_cross_player_leaks(self):
        g = self.game(('BOT_054', 'GIL_663'), player=2, maximum=5, mana=5)
        self.play(g, 'BOT_054', player=2)
        self.play(g, 'GIL_663', player=2)
        self.assertEqual(g.state.players[2].max_mana, 7)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].hand], ['GIL_663t'] * 2)
        text = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for key in ('GIL_663t', 'hand_entry_id', 'rng_state', 'resolution_frame'):
            self.assertNotIn(key, text)
        self.portable(g)

    def test_real_local_host_uses_exact_new_faces_and_preserves_closed_complete_nature_source(self):
        self.mode = 'host'
        f = host()
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_06', hand=('CS2_013', 'GIL_663', 'REV_307', 'YOP_026'),
            deck=('CORE_CS2_182',) * 6, mana=30, max_mana=30, mana_cap=30), PlayerSetup('HERO_08')),
            seed=658, generation_context=f.context), f.registry)
        for cid in ('CS2_013', native.OVERFLOW, 'GIL_663'):
            self.play(g, cid)
        self.play(g, 'REV_307', g.state.players[2].hero_id)
        self.play(g, 'YOP_026')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['REV_336t2', 'DMF_061t2', 'DMF_061t2'])
        for row in native.load_batch()['cards'] + native.load_batch()['dependencies']:
            self.assertEqual(canonical_digest(asdict(f.registry.card(row['record']['id']))),
                row['definition_sha256'])
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, PAST_POOL, QUERIES[WO],
                current_class=CardClass.DRUID, source_card_id=WO, exclude_source_by_rule=True)
        self.portable(g)
