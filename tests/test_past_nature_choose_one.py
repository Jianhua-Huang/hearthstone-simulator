"""Real two-branch Nature cards, explicit combined behavior and original targets."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.cards import build_registry, past_nature_choose_one as native
from hs_sim.cards.simple_followup_p89_cards import WO, PAST_POOL, QUERIES
from hs_sim.engine import Game, IllegalAction, PlayCard, PlayerSetup, ResolutionError, Ruleset, Scenario
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, InvokeBehavior,
    RandomDamage, RequestChoice, ReturnToHand)
from hs_sim.engine.model import CardClass, CardDefinition, CardType, Keyword, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.pools import resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k659.'
A, LOW, BOTH, POWER, PING, AUTO = (P + x for x in ('unit', 'small', 'both', 'power', 'ping', 'automatic'))
FAIL, REENTER = P + 'deliberate_failure', P + 'reenter'
ALL_TOKENS = (*native.TOKENS, *native.EXISTING)


@lru_cache(maxsize=1)
def original_registry():
    return build_registry()


@lru_cache(maxsize=None)
def fixture(role='writer'):
    r = opening_registry()
    original = original_registry()
    for cid in native.EXISTING:
        r.register_card(original.card(cid))
        r.register_pool_card(original.pool_card(cid))
    native.register_past_nature_choose_one(r)

    def fail(c):
        raise ValueError('K659 deliberate failure after real RNG')

    def reenter(c):
        target = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == A)
        return (SummonStoredCard(CardReference.capture(target), c.player_id,
            cause=SummonCause.capture(c)),)

    r.register_behavior(FAIL, fail)
    r.register_behavior(REENTER, reenter)
    r.register_behavior(PING, lambda c: (Damage(c.target_id, 8, c.source_id),))
    r.register_behavior(AUTO, lambda c: (CastSpell(c.player_id, 'AT_037', c.source_id,
        target_id=c.state.players[3-c.player_id].hero_id, targeting='explicit', branch_id='AT_037:combined'),))
    for cid, fields in ((A, dict(attack=3, health=12)), (LOW, dict(attack=1, health=2)),
            (BOTH, dict(health=20, choose_both=True)), (POWER, dict(health=20, spell_damage=2))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, metadata=metadata(collectible=False), **fields))
    r.register_card(CardDefinition(PING, PING, CardType.SPELL, on_play=PING,
        targeting=TargetSpec(), metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(AUTO, AUTO, CardType.SPELL, on_play=AUTO, metadata=metadata(collectible=False)))
    for mode in ('wait', 'fail', 'reentry', 'provider'):
        key = P + 'watch.' + mode

        def watch(c, mode=mode):
            e = c.event
            target = c.state.entities.get(e.target_id)
            if e.kind != 'minion_summoned' or target is None or target.card_id not in ALL_TOKENS:
                return ()
            pid = target.controller
            if mode == 'reentry':
                if target.card_id != 'DRG_311t':
                    return ()
                original = next(c.state.entities[i] for i in c.state.players[pid].board
                    if c.state.entities[i].card_id == A)
                return (ReturnToHand(original.id), InvokeBehavior(REENTER, c.source_id, pid))
            if mode == 'provider' and target.card_id != 'TSC_650t':
                return ()
            if mode == 'fail':
                return (RandomDamage((c.state.players[3-pid].hero_id,), 1, c.source_id),
                    InvokeBehavior(FAIL, c.source_id, pid))
            extra = ()
            if mode == 'provider':
                provider = next(c.state.entities[i] for i in c.state.players[pid].board
                    if c.state.entities[i].card_id == BOTH)
                extra = (Destroy(provider.id, c.source_id),)
            return (RequestChoice(pid, (ChoiceOption('continue', 'Continue', extra),
                ChoiceOption('fail', 'Fail after real RNG', (
                    RandomDamage((c.state.players[3-pid].hero_id,), 1, c.source_id),
                    InvokeBehavior(FAIL, c.source_id, pid)))), c.source_id),)

        r.register_behavior(key, watch)
        r.register_card(CardDefinition(key, key, CardType.MINION, health=30,
            triggers=(TriggerSpec('minion_summoned', key),)))
    r.validate()
    return r


@lru_cache(maxsize=None)
def host(role='writer'):
    return build_cn37_local_pool_format()


class PastNatureChooseOneTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'mini'
    registry_factory = staticmethod(lambda mode, role:
        host(role).registry if mode == 'host' else fixture(role))

    def game(self, card, *, board=(), enemy=(), both=False, watch=None, own_watch=False,
            player=1, maximum=30, mana=30, cap=30, limit=7, hand_extra=()):
        self.mode = 'mini'
        watcher = (P + 'watch.' + watch,) if watch else ()
        own = PlayerSetup('mage.hero', hand=(card, *hand_extra),
            board=board + ((BOTH,) if both else ()) + (watcher if own_watch else ()),
            deck=(A,) * 8, mana=mana, max_mana=maximum, mana_cap=cap)
        other = PlayerSetup('mage.hero', board=enemy + (() if own_watch else watcher), deck=(A,) * 8)
        return Game.from_scenario(Scenario((own, other) if player == 1 else (other, own),
            active_player=player, seed=659), fixture(), ruleset=Ruleset(max_board=limit))

    def play_branch(self, g, cid, branch, target=None, player=1):
        eid = self.entity(g, cid, player).id
        g.apply(PlayCard(player, eid, target, branch_id=branch))
        return eid

    def test_complete_44_records_22_primary_faces_and_all_original_native_pins(self):
        d = native.load_batch()
        self.assertEqual(len(d['cards'] + d['dependencies'] + d['existing_dependencies'] + d['evidence_only']), 44)
        self.assertEqual(len(d['official_observations']), 22)
        r = fixture()
        for row in d['cards'] + d['dependencies'] + d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))), row['definition_sha256'])
        self.assertEqual(len(d['complete_druid_Nature_inventory']), 85)
        self.assertFalse(d['source_scope_bound'] or d['formal_pool_complete'] or d['cn_calibrated'])
        for cid in native.CHOICES:
            self.assertTrue(r.card(cid).choice_only)
            self.assertNotIn(cid, r.pool_cards)
        for cid in native.ROOTS:
            self.assertTrue(r.pool_card(cid).choose_one)

    def test_registration_is_preflighted_and_never_partially_overwrites_existing_material(self):
        r = fixture()
        before = r.fingerprint()
        with self.assertRaises(TargetValidationError):
            native.register_past_nature_choose_one(r)
        self.assertEqual(r.fingerprint(), before)

    def test_live_root_has_actual_branches_and_combined_mode_requires_real_authority(self):
        g = self.game('AT_037')
        eid = self.entity(g, 'AT_037').id
        actions = [a for a in g.legal_actions() if type(a) is PlayCard and a.entity_id == eid]
        self.assertEqual({a.branch_id for a in actions}, {'AT_037a', 'AT_037b'})
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play_branch(g, 'AT_037', 'AT_037:combined', g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), before)
        g = self.game('AT_037', both=True)
        eid = self.entity(g, 'AT_037').id
        self.assertEqual({a.branch_id for a in g.legal_actions() if type(a) is PlayCard and a.entity_id == eid}, {'AT_037:combined'})

    def test_all_eight_normal_summon_branches_use_exact_named_bodies_and_one_root_payment(self):
        cases = [('AT_037', 'AT_037b', 'AT_037t', 2), ('DRG_311', 'DRG_311a', 'DRG_311t', 1),
            ('GVG_041', 'GVG_041b', 'CS2_231', 5), ('SW_422', 'SW_422a', 'SW_422t', 1),
            ('TRL_254', 'TRL_254b', 'TRL_254t', 2), ('TSC_650', 'TSC_650a', 'TSC_650t', 1),
            ('TSC_650', 'TSC_650d', 'TSC_650t4', 6), ('ULD_135', 'ULD_135a', 'ULD_135at', 1)]
        for cid, branch, token, count in cases:
            with self.subTest(cid=cid, branch=branch):
                g = self.game(cid)
                self.play_branch(g, cid, branch)
                self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [token] * count)
                self.assertEqual(g.state.players[1].mana, 30-g.registry.card(cid).cost)
                self.assertEqual(len(g.state.play_history), 1)
                self.assertEqual(len(g.state.cast_history), 1)
                self.assertEqual(g.state.cast_history[0].branch_id, branch)

    def test_living_roots_damage_uses_spell_damage_and_summons_no_saplings_in_that_branch(self):
        g = self.game('AT_037', board=(POWER,))
        self.play_branch(g, 'AT_037', 'AT_037a', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 4)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [POWER])

    def test_crystal_damage_branch_rejects_hero_and_heal_branch_accepts_hero(self):
        g = self.game('DAL_350', enemy=(A,), hand_extra=(PING,))
        hero = g.state.players[1].hero_id
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play_branch(g, 'DAL_350', 'DAL_350a', hero)
        self.assertEqual(g.snapshot(), before)
        self.play(g, PING, hero)
        self.play_branch(g, 'DAL_350', 'DAL_350b', hero)
        self.assertEqual(g.state.entities[hero].damage, 3)
        g = self.game('DAL_350', enemy=(A,))
        target = self.entity(g, A, 2, zone='board').id
        self.play_branch(g, 'DAL_350', 'DAL_350a', target)
        self.assertEqual(g.state.entities[target].damage, 2)

    def test_all_five_normal_single_target_buffs_keep_actual_stats_and_taunt(self):
        cases = [('DRG_311', 'DRG_311b', 3, 14, True), ('EX1_155', 'EX1_155a', 7, 12, False),
            ('EX1_155', 'EX1_155b', 3, 16, True), ('GVG_041', 'GVG_041a', 8, 17, True),
            ('TRL_254', 'TRL_254a', 5, 16, True)]
        for cid, branch, attack, health, taunt in cases:
            with self.subTest(cid=cid, branch=branch):
                g = self.game(cid, board=(A,))
                target = self.entity(g, A, zone='board').id
                self.play_branch(g, cid, branch, target)
                current = g.state.entities[target]
                self.assertEqual((current.attack, current.max_health, Keyword.TAUNT in current.keywords), (attack, health, taunt))

    def test_normal_sow_buff_reads_current_friendly_minions_without_creating_a_treant(self):
        g = self.game('SW_422', board=(A, LOW), enemy=(A,))
        self.play_branch(g, 'SW_422', 'SW_422b')
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board], [4, 2])
        self.assertEqual(self.entity(g, A, 2, zone='board').attack, 3)

    def test_hidden_oasis_normal_healing_restores_twelve_and_does_not_summon(self):
        g = self.game('ULD_135', hand_extra=(PING, PING))
        hero = g.state.players[1].hero_id
        self.play(g, PING, hero); self.play(g, PING, hero)
        self.play_branch(g, 'ULD_135', 'ULD_135b', hero)
        self.assertEqual(g.state.entities[hero].damage, 4)
        self.assertFalse(g.state.players[1].board)

    def test_invigorate_each_normal_branch_and_actual_combined_pay_once_without_excess_mana(self):
        for branch, growth, draws, both in [('WON_014s', 1, 0, False), ('WON_014s2', 0, 1, False),
                ('WON_014:combined', 1, 1, True)]:
            with self.subTest(branch=branch):
                g = self.game('WON_014', both=both, maximum=5, mana=5, cap=10)
                self.play_branch(g, 'WON_014', branch)
                self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (5+growth, 3))
                self.assertEqual(len(g.state.players[1].deck), 8-draws)
        g = self.game('WON_014', both=True)
        self.play_branch(g, 'WON_014', 'WON_014:combined')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand], [A])

    def test_living_roots_combined_damage_then_two_actual_saplings_and_only_one_cast(self):
        g = self.game('AT_037', both=True)
        self.play_branch(g, 'AT_037', 'AT_037:combined', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage, 2)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [BOTH, 'AT_037t', 'AT_037t'])
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history), g.state.players[1].mana), (1, 1, 29))

    def test_crystal_combined_hero_only_heals_and_minion_takes_damage_before_healing(self):
        g = self.game('DAL_350', both=True, hand_extra=(PING,))
        hero = g.state.players[1].hero_id
        self.play(g, PING, hero)
        self.play_branch(g, 'DAL_350', 'DAL_350:combined', hero)
        self.assertEqual(g.state.entities[hero].damage, 3)
        g = self.game('DAL_350', both=True, enemy=(A,), hand_extra=(PING,))
        target = self.entity(g, A, 2, zone='board').id
        self.play(g, PING, target)
        self.play_branch(g, 'DAL_350', 'DAL_350:combined', target)
        self.assertEqual(g.state.entities[target].damage, 5)

    def test_crystal_combined_lethal_damage_never_heals_a_dead_minion_back_into_play(self):
        g = self.game('DAL_350', both=True, enemy=(LOW,))
        target = self.entity(g, LOW, 2, zone='board').id
        self.play_branch(g, 'DAL_350', 'DAL_350:combined', target)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def test_three_targeted_combined_summon_buffs_preserve_original_target_and_named_entries(self):
        for cid, token, count, attack, health in [('DRG_311', 'DRG_311t', 1, 3, 14),
                ('GVG_041', 'CS2_231', 5, 8, 17), ('TRL_254', 'TRL_254t', 2, 5, 16)]:
            with self.subTest(cid=cid):
                g = self.game(cid, both=True, board=(A,), limit=10)
                target = self.entity(g, A, zone='board').id
                self.play_branch(g, cid, cid+':combined', target)
                self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (attack, health))
                self.assertIn(Keyword.TAUNT, g.state.entities[target].keywords)
                self.assertEqual(sum(g.state.entities[i].card_id == token for i in g.state.players[1].board), count)

    def test_mark_of_nature_combined_is_one_explicit_four_four_taunt_result(self):
        g = self.game('EX1_155', both=True, board=(A,))
        target = self.entity(g, A, zone='board').id
        self.play_branch(g, 'EX1_155', 'EX1_155:combined', target)
        current = g.state.entities[target]
        self.assertEqual((current.attack, current.max_health), (7, 16))
        self.assertIn(Keyword.TAUNT, current.keywords)

    def test_sow_combined_summons_before_live_board_buff_so_new_treant_is_three_two(self):
        g = self.game('SW_422', both=True, board=(A,))
        self.play_branch(g, 'SW_422', 'SW_422:combined')
        tree = self.entity(g, 'SW_422t', zone='board')
        self.assertEqual((tree.attack, tree.max_health), (3, 2))
        self.assertEqual(self.entity(g, A, zone='board').attack, 4)

    def test_flipper_combined_keeps_orca_first_and_fills_only_actual_remaining_spaces(self):
        g = self.game('TSC_650', both=True)
        self.play_branch(g, 'TSC_650', 'TSC_650:combined')
        cards = [g.state.entities[i] for i in g.state.players[1].board]
        self.assertEqual([e.card_id for e in cards], [BOTH, 'TSC_650t'] + ['TSC_650t4'] * 5)
        self.assertIn(Keyword.TAUNT, cards[1].keywords)
        self.assertTrue(all(Keyword.RUSH in e.keywords for e in cards[2:]))

    def test_oasis_combined_summons_original_ancient_then_heals_same_selected_character(self):
        g = self.game('ULD_135', both=True, hand_extra=(PING, PING))
        hero = g.state.players[1].hero_id
        self.play(g, PING, hero); self.play(g, PING, hero)
        self.play_branch(g, 'ULD_135', 'ULD_135:combined', hero)
        self.assertEqual(g.state.entities[hero].damage, 4)
        ancient = self.entity(g, 'ULD_135at', zone='board')
        self.assertEqual((ancient.attack, ancient.max_health), (6, 6))
        self.assertIn(Keyword.TAUNT, ancient.keywords)

    def test_full_board_disables_summon_only_option_but_keeps_other_real_option(self):
        g = self.game('AT_037', board=(A,) * 7)
        eid = self.entity(g, 'AT_037').id
        self.assertEqual({a.branch_id for a in g.legal_actions() if type(a) is PlayCard and a.entity_id == eid}, {'AT_037a'})
        g = self.game('TSC_650', board=(A,) * 7)
        eid = self.entity(g, 'TSC_650').id
        self.assertFalse([a for a in g.legal_actions() if type(a) is PlayCard and a.entity_id == eid])
        g = self.game('DRG_311', both=True, board=(A,) * 6)
        target = self.entity(g, A, zone='board').id
        self.play_branch(g, 'DRG_311', 'DRG_311:combined', target)
        self.assertEqual(g.state.entities[target].max_health, 14)

    def test_captured_target_cannot_receive_buff_or_taunt_after_bounce_and_new_residence(self):
        g = self.game('DRG_311', board=(A,), both=True, watch='reentry', own_watch=True)
        target = self.entity(g, A, zone='board').id
        old_presence = g.state.entities[target].board_presence_id
        self.play_branch(g, 'DRG_311', 'DRG_311:combined', target)
        current = g.state.entities[target]
        self.assertNotEqual(current.board_presence_id, old_presence)
        self.assertEqual((current.attack, current.max_health), (3, 12))
        self.assertNotIn(Keyword.TAUNT, current.keywords)

    def test_wait_after_first_entry_restores_original_combined_body_and_failed_choice_rng(self):
        g = self.game('TRL_254', board=(A,), both=True, watch='wait')
        target = self.entity(g, A, zone='board').id
        self.play_branch(g, 'TRL_254', 'TRL_254:combined', target)
        self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        for _ in range(2):
            self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[target].max_health, 16)

    def test_provider_death_during_orca_wait_keeps_captured_combined_and_all_six_later_otters(self):
        g = self.game('TSC_650', both=True, watch='provider')
        self.play_branch(g, 'TSC_650', 'TSC_650:combined')
        self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['TSC_650t'] + ['TSC_650t4'] * 6)
        self.assertEqual(g.state.cast_history[0].branch_id, 'TSC_650:combined')
        self.portable(g)

    def test_failure_after_actual_named_entry_restores_payment_branch_allocations_and_rng(self):
        g = self.game('AT_037', watch='fail')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play_branch(g, 'AT_037', 'AT_037b')
        self.assertEqual(g.snapshot(), before)

    def test_automatic_real_combined_uses_same_native_body_without_second_payment_or_child_casts(self):
        g = self.game(AUTO, both=True)
        self.play(g, AUTO)
        self.assertEqual(g.state.players[1].mana, 30)
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 2))
        self.assertEqual((g.state.cast_history[-1].card_id, g.state.cast_history[-1].origin,
            g.state.cast_history[-1].branch_id), ('AT_037', 'effect', 'AT_037:combined'))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [BOTH, 'AT_037t', 'AT_037t'])
        self.portable(g)

    def test_second_seat_private_hand_options_and_saved_source_proofs_stay_out_of_opponent_events(self):
        g = self.game('AT_037', player=2, watch='wait')
        text = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        self.assertNotIn('AT_037', text)
        self.play_branch(g, 'AT_037', 'AT_037b', player=2)
        text = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
        for key in ('branch_layout', 'quantity_plan', 'rng_before', 'resolution_frame', 'submitted_cost'):
            self.assertNotIn(key, text)
        self.portable(g)

    def test_real_local_host_plays_actual_fandral_combined_and_retains_closed_full_nature_scope(self):
        self.mode = 'host'
        f = host()
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_06', hand=('AT_037', 'SW_422'),
            board=('OG_044',), mana=10, max_mana=10), PlayerSetup('HERO_08')),
            seed=659, generation_context=f.context), f.registry)
        self.play_branch(g, 'AT_037', 'AT_037:combined', g.state.players[2].hero_id)
        self.play_branch(g, 'SW_422', 'SW_422:combined')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], ['OG_044', 'AT_037t', 'AT_037t', 'SW_422t'])
        self.assertEqual(self.entity(g, 'SW_422t', zone='board').attack, 3)
        self.assertEqual((g.state.players[1].mana, len(g.state.cast_history)), (8, 2))
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(f.registry, f.context, PAST_POOL, QUERIES[WO],
                current_class=CardClass.DRUID, source_card_id=WO, exclude_source_by_rule=True)
        self.portable(g)
