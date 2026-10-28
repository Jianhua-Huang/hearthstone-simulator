"""Real freeze/Excavate delivery through complete versioned local tables."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json, tempfile, unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch
from hs_sim.cards import build_registry
from hs_sim.cards import excavate_local_host as native
from hs_sim.engine import Game, IllegalAction, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.excavate import Excavate, excavation_count
from hs_sim.engine.model import CardClass, CardDefinition, CardType, Keyword, LimitedTriggerSpec, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolMember, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k620.'
NOOP, WAIT, FAILWATCH, FAIL = (P+s for s in ('noop', 'wait', 'failwatch', 'failure'))
HEROES = {CardClass.DEATH_KNIGHT:'HERO_11', CardClass.DEMON_HUNTER:'HERO_10', CardClass.DRUID:'HERO_06',
    CardClass.HUNTER:'HERO_05', CardClass.MAGE:'HERO_08', CardClass.PALADIN:'HERO_04', CardClass.PRIEST:'HERO_09',
    CardClass.ROGUE:'HERO_03', CardClass.SHAMAN:'HERO_02', CardClass.WARLOCK:'HERO_07', CardClass.WARRIOR:'HERO_01'}


@lru_cache(None)
def format_for(role='writer'):
    f = build_cn37_local_pool_format(); r = f.registry
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    for count in (3, 4, 8):
        cid = P+'dig'+str(count)
        r.register_behavior(cid, lambda c, count=count: (Excavate(c.player_id, c.source_id, count=count),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def fail(c): raise ResolutionError('K620 deliberate excavation reaction failure')
    r.register_behavior(FAIL, fail)
    for cid, failure in ((WAIT, False), (FAILWATCH, True)):
        def watch(c, failure=failure):
            if failure: return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(cid, watch)
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, durability=50,
            limited_triggers=(LimitedTriggerSpec('excavated', cid),)))
    r.validate()
    return f


def registry(mode='normal', role='writer'):
    if mode != 'normal': raise ValueError('Unknown Excavate fixture')
    return format_for(role).registry


def tier_candidates(tier):
    d = native.load_batch()['inventory']['shared_tiers'][tier-1]
    return tuple(PoolMember(cid, w) for cid, w in zip(d['member_ids'], d['weights']))


@lru_cache(None)
def shared_witnesses():
    # Pure seed preparation; each actual witness later uses three real spells.
    all_ids = {m.card_id for tier in (1, 2, 3) for m in tier_candidates(tier)}
    choices = []
    for seed in range(128):
        rng = Random(seed)
        selected = tuple(sample_candidates(rng, tier_candidates(tier), 1, replacement=True)[0] for tier in (1, 2, 3))
        choices.append((seed, selected))
    covered, result = set(), []
    while covered != all_ids:
        seed, selected = max(choices, key=lambda x: len(set(x[1])-covered))
        if not set(selected)-covered: raise AssertionError('Missing complete shared-treasure witness')
        result.append((seed, selected)); covered.update(selected)
    return tuple(result)


class ExcavateLocalHostTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, hand=(native.SPELL,), *, hero='HERO_08', player=1, seed=620, weapon=None):
        f = format_for()
        own = PlayerSetup(hero, hand=hand, weapon_card_id=weapon, mana=10, max_mana=10)
        other = PlayerSetup('HERO_03', board=('CORE_EX1_162',), hand=(NOOP,))
        return Game.from_scenario(Scenario((own, other) if player==1 else (other, own),
            active_player=player, seed=seed, generation_context=f.context), f.registry)

    def cast(self, g, *, player=1, hero=False):
        enemy = g.state.players[3-player]
        target = enemy.hero_id if hero else enemy.board[0]
        self.play(g, native.SPELL, target, player)
        return target

    def test_twenty_six_original_rows_fifty_two_primary_faces_and_ten_complete_roles(self):
        d = native.load_batch(); f = format_for()
        self.assertEqual(len(d['existing_dependencies']), 25); self.assertEqual(len(d['official_observations']), 52)
        self.assertTrue(d['real_excavate_profile_bound']); self.assertFalse(d['formal_pool_complete'])
        ps = native.local_pools(f.registry, f.context); self.assertEqual(len(ps), 10)
        self.assertEqual([len(p.members) for p in ps], [6, 6, 6] + [1]*7)
        for p in ps:
            actual = f.registry.pool(p.id, f.context)
            self.assertEqual(actual.members, p.members); self.assertEqual(actual.excluded_card_ids, p.excluded_card_ids)
            self.assertTrue(actual.complete)
        self.assertTrue(f.registry.excavation_profile('excavate', f.context).complete)

    def test_real_two_mana_frost_spell_freezes_enemy_character_then_excavates_original_reward(self):
        for target_hero in (False, True):
            g = self.game(); before = g._rng.getstate(); rng = Random(); rng.setstate(before)
            expected = sample_candidates(rng, tier_candidates(1), 1, replacement=True)[0]
            target = self.cast(g, hero=target_hero)
            self.assertTrue(g.state.entities[target].frozen); self.assertEqual(g.state.players[1].mana, 8)
            row, = g.state.excavation_history
            self.assertEqual((row.card_id, row.tier, row.count_before), (expected, 1, 0))
            self.assertEqual(row.target_id, format_for().target_id)
            self.assertEqual(g._rng.getstate(), rng.getstate()); self.assertEqual(excavation_count(g.state, 1), 1)
            card = g.registry.card(native.SPELL); self.assertEqual((card.cost, card.spell_school), (2, SpellSchool.FROST))
            self.assertEqual(self.entity(g, expected).cost, g.registry.card(expected).cost)
        self.portable(g)

    def test_friendly_targets_and_missing_required_target_are_rejected_without_payment_or_progress(self):
        g = self.game(); saved = g.snapshot()
        for target in (g.state.players[1].hero_id, None):
            with self.assertRaises(IllegalAction): self.play(g, native.SPELL, target)
            self.assertEqual(g.snapshot(), saved)

    def test_three_real_casts_generate_every_declared_shared_member_without_pool_cropping(self):
        seen = set()
        for seed, expected in shared_witnesses():
            g = self.game((native.SPELL,)*3, hero='HERO_06', seed=seed)
            for _ in range(3): self.cast(g)
            actual = tuple(row.card_id for row in g.state.excavation_history)
            self.assertEqual(actual, expected); seen.update(actual)
            self.assertEqual(g.state.players[1].mana, 4)
            self.assertEqual([row.tier for row in g.state.excavation_history], [1, 2, 3])
        self.assertEqual(seen, {m.card_id for tier in (1, 2, 3) for m in tier_candidates(tier)})

    def test_each_of_eleven_classes_uses_full_declared_fourth_reward_or_three_tier_restart(self):
        d = native.load_batch()['inventory']; rewards = {native.CLASS_IDS[row['class_id']]:row['card_id'] for row in d['class_rewards']}
        for cls, hero in HEROES.items():
            g = self.game((P+'dig4',), hero=hero); self.play(g, P+'dig4')
            rows = g.state.excavation_history; self.assertEqual(excavation_count(g.state, 1), 4)
            self.assertEqual([row.hero_class for row in rows], [cls]*4)
            self.assertEqual([row.tier for row in rows], [1, 2, 3, 4 if cls in rewards else 1])
            if cls in rewards: self.assertEqual(rows[-1].card_id, rewards[cls])
            self.assertTrue(all(row.profile_version == native.profile(format_for().context).version for row in rows))

    def test_second_seat_real_spell_advances_only_its_own_progress_and_uses_same_full_domain(self):
        g = self.game(player=2, hero='HERO_03'); target = self.cast(g, player=2)
        self.assertTrue(g.state.entities[target].frozen)
        self.assertEqual((excavation_count(g.state, 1), excavation_count(g.state, 2)), (0, 1))
        self.assertEqual(g.state.excavation_history[-1].hero_class, CardClass.ROGUE); self.portable(g)

    def test_real_fourth_excavation_earns_hawk_then_original_hawk_gets_and_plays_native_one_cost_titan(self):
        g = self.game((P+'dig3', native.SPELL)); self.play(g, P+'dig3'); self.cast(g)
        self.assertEqual(g.state.excavation_history[-1].card_id, 'WW_001t24')
        self.play(g, 'WW_001t24')
        ids = set(json.loads((native.ROOT/'data/cards/azerite-hawk-domain-v1.json').read_text(encoding='utf8'))['inventory']['candidate_ids'])
        titan, = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id in ids]
        self.assertEqual(titan.cost, 1); self.assertIn(Keyword.TITAN, titan.keywords)
        before = g.state.players[1].mana; eid = self.play(g, titan.card_id)
        self.assertEqual(g.state.players[1].mana, before-1)
        self.assertEqual(len([a for a in g.state.entities[eid].abilities if a.kind=='activated']), 3); self.portable(g)

    def test_real_excavation_wait_restores_original_freeze_payment_selection_and_failed_tail(self):
        g = self.game(weapon=WAIT); target = self.cast(g); self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(g.state.entities[target].frozen); self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(excavation_count(g.state, 1), 1); rng = g._rng.getstate(); g = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K620'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(g._rng.getstate(), rng); self.assertEqual(excavation_count(g.state, 1), 1)

    def test_excavated_reaction_failure_rolls_back_freeze_spell_payment_reward_history_and_random(self):
        g = self.game(weapon=FAILWATCH); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K620'): self.cast(g)
        self.assertEqual(g.snapshot(), saved)

    def test_full_hand_burns_later_treasures_but_preserves_two_complete_cycles_and_source_provenance(self):
        g = self.game((P+'dig8',)+(NOOP,)*9); self.play(g, P+'dig8')
        rows = g.state.excavation_history
        self.assertEqual([x.tier for x in rows], [1, 2, 3, 4]*2)
        self.assertEqual([x.burned for x in rows], [False]+[True]*7)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertEqual(len({x.reward_id for x in rows}), 8)
        self.assertEqual(rows[3].card_id, 'WW_001t24'); self.assertEqual(rows[7].card_id, 'WW_001t24')

    def test_public_progress_does_not_publish_private_treasure_identity_pool_or_random_state(self):
        g = self.game(weapon=WAIT); self.cast(g)
        view = g.for_player(2).observe(); self.assertIsNone(view['observation']['players'][0]['hand'][0]['card_id'])
        raw = json.dumps(view)+json.dumps(g.player_events(2))
        for key in ('rng_state', 'resolution_frame', 'profile_version', 'pool_version', native.POLICY): self.assertNotIn(key, raw)

    def test_old_launch_and_incomplete_experimental_profile_remain_separate_without_new_deck_roots(self):
        original = build_cn37_launch_candidate_format(); f = format_for(); ctx = GenerationContext('local-2026-09-23', 'experimental')
        self.assertEqual(f.root_card_ids, original.root_card_ids); self.assertNotIn(native.SPELL, f.root_card_ids)
        self.assertEqual(f.policy.allowed_card_ids, original.policy.allowed_card_ids)
        with self.assertRaises(UnsupportedDefinitionError): original.registry.excavation_profile('excavate', original.context)
        old = f.registry.excavation_profile('excavate', ctx); self.assertFalse(old.complete)
        for pid in old.shared_pools: self.assertEqual(len(f.registry.pool(pid, ctx).members), 1)
        self.assertEqual(len(f.registry.excavation_profiles), 2)

    def test_rehashed_manifest_cannot_crop_or_reweight_tiers_change_class_reward_or_claim_official(self):
        for mode in ('crop', 'weight', 'class', 'scope', 'official'):
            d = deepcopy(native.load_batch())
            if mode == 'crop': d['inventory']['shared_tiers'][0]['member_ids'].pop()
            elif mode == 'weight': d['inventory']['shared_tiers'][2]['weights'][0] = 2
            elif mode == 'class': d['inventory']['class_rewards'][0]['card_id'] = 'WW_001t24'
            elif mode == 'scope': d['real_excavate_profile_bound'] = False
            else: d['formal_pool_complete'] = True
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder)/'changed.json'; p.write_text(json.dumps(d), encoding='utf8')
                with patch.object(native, 'BATCH_PATH', p), patch.object(native, 'BATCH_HASH', canonical_digest(d)):
                    with self.assertRaises(TargetValidationError): native.load_batch()

    def test_prepare_requires_all_old_treasure_bodies_and_fails_before_registering_new_spell(self):
        r = card_batch.registration_prefix(build_registry,
            'hs_sim.cards.excavate_local_host.register_cryopreservation', lambda registry: None)
        self.assertNotIn(native.SPELL, r.cards); before = r.fingerprint()
        d = deepcopy(native.load_batch()); d['existing_dependencies'][-1]['definition_sha256'] = '0'*64
        with patch.object(native, 'load_batch', lambda: d), self.assertRaises(TargetValidationError): native.register_cryopreservation(r)
        self.assertEqual(r.fingerprint(), before); self.assertNotIn(native.SPELL, r.cards)
        native.register_cryopreservation(r); self.assertEqual(r.card(native.SPELL).cost, 2)
        before = r.fingerprint()
        with self.assertRaises(TargetValidationError): native.register_cryopreservation(r)
        self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__': unittest.main()
