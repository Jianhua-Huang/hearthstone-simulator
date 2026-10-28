"""Actual Azerite rewards use complete ordinary sources without replacing rules."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json, tempfile, unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import azerite_reward_domains as native
from hs_sim.engine import Game, IllegalAction, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, ModifyCost, RequestChoice
from hs_sim.engine.excavate import Excavate, ExcavationClass, ExcavationProfile, PLAYABLE_CLASSES, excavation_count
from hs_sim.engine.model import CardClass, CardDefinition, CardType, CostSpec, LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery, resolve_candidates, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k619.'
NOOP, DIG, DISCOUNT, FAIL = (P + s for s in ('noop', 'dig', 'discount', 'fail'))
GET_WAIT, GET_FAIL, TRANSFORM_WAIT, TRANSFORM_FAIL, SUMMON_FAIL = (
    P + s for s in ('get_wait', 'get_fail', 'transform_wait', 'transform_fail', 'summon_fail'))
SPELL_QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True)
EIGHT_QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=8, max_cost=8, class_mode='current')


@lru_cache(None)
def format_for(role='writer'):
    fmt = build_cn37_local_pool_format(); r = fmt.registry
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    # Progress is produced by the public Excavate effect, without inventing
    # history rows or asserting that the production profile is already bound.
    pools = tuple(P + 'tier' + str(i) for i in (1, 2, 3))
    for pid, cid in zip(pools, ('WW_001t', 'WW_001t5', 'WW_001t11')):
        r.register_pool(PoolDefinition(pid, P + 'fixture', fmt.target_id, fmt.context.mode, (PoolMember(cid),)))
    r.register_excavation_profile(ExcavationProfile(P + 'progress', P + 'fixture', fmt.target_id,
        fmt.context.mode, pools, tuple(ExcavationClass(cls) for cls in sorted(PLAYABLE_CLASSES))))
    r.register_behavior(DIG, lambda c: (Excavate(c.player_id, c.source_id, count=4, profile_id=P + 'progress'),))
    r.register_card(CardDefinition(DIG, DIG, CardType.SPELL, on_play=DIG))
    def discount(c):
        target = next(eid for eid in c.state.players[c.player_id].hand
            if c.state.entities[eid].card_id == 'CORE_EX1_162')
        return (ModifyCost(target, CostSpec(delta=-1), c.source_id),)
    r.register_behavior(DISCOUNT, discount)
    r.register_card(CardDefinition(DISCOUNT, DISCOUNT, CardType.SPELL, on_play=DISCOUNT))
    def fail(c):
        raise ResolutionError('K619 deliberate source reaction failure')
    r.register_behavior(FAIL, fail)
    def watch(c, failure=False):
        if failure:
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    for cid, event, failure in ((GET_WAIT, 'card_added_to_hand', False), (GET_FAIL, 'card_added_to_hand', True),
            (TRANSFORM_WAIT, 'stored_card_transformed', False), (TRANSFORM_FAIL, 'stored_card_transformed', True),
            (SUMMON_FAIL, 'minion_summoned', True)):
        def eligible(c, event=event):
            entity = c.state.entities.get(c.event.target_id)
            if entity is None: return False
            if event == 'minion_summoned': return entity.card_id == 'CORE_UNG_848'
            if event == 'stored_card_transformed': return True
            card = r.card(entity.card_id)
            return card.kind == CardType.SPELL and card.metadata is not None and card.metadata.collectible is True
        r.register_trigger_condition(cid + '.eligible', eligible)
        r.register_behavior(cid, lambda c, failure=failure: watch(c, failure))
        r.register_card(CardDefinition(cid, cid, CardType.WEAPON, durability=50,
            limited_triggers=(LimitedTriggerSpec(event, cid, cid + '.eligible'),)))
    r.validate()
    return fmt


def registry(mode='normal', role='writer'):
    if mode != 'normal': raise ValueError('Unknown Azerite domain fixture')
    return format_for(role).registry


def query(pool, query, cls=CardClass.ROGUE, source=native.SCORPION, player=1):
    f = format_for()
    return resolve_candidates(f.registry, f.context, pool, query, current_class=cls,
        source_card_id=source, player_id=player, exclude_source_by_rule=True)


class AzeriteRewardDomainTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, hand, *, board=(), deck=(), enemy=(), weapon=None, seed=20, player=1, hero='HERO_03'):
        f = format_for()
        own = PlayerSetup(hero, hand=hand, board=board, deck=deck, weapon_card_id=weapon, mana=10, max_mana=10)
        other = PlayerSetup('HERO_08', board=enemy, hand=(NOOP,))
        setups = (own, other) if player == 1 else (other, own)
        return Game.from_scenario(Scenario(setups, active_player=player, seed=seed, generation_context=f.context), f.registry)

    def spells(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].hand
            if g.registry.card(g.state.entities[i].card_id).kind == CardType.SPELL
            and g.registry.card(g.state.entities[i].card_id).metadata is not None
            and g.registry.card(g.state.entities[i].card_id).metadata.collectible is True]

    def choose_card(self, g, cid):
        self.choose(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))

    def probe_spells(self, g, player=1):
        rng = Random(); rng.setstate(g._rng.getstate())
        candidates = query(native.CARDS_POOL, SPELL_QUERY, player=player)
        return sample_candidates(rng, candidates, 4, replacement=True), rng

    def test_full_three_sources_six_primary_faces_and_all_inventory_roles_are_pinned(self):
        d = native.load_batch()
        self.assertEqual([r['record']['id'] for r in d['existing_dependencies']], [native.SCORPION, native.OX, native.MURLOC])
        self.assertEqual(len(d['official_observations']), 6)
        self.assertEqual([len(x['candidate_ids']) for x in d['domains']], [1322, 44, 811])
        self.assertEqual(len(d['ordinary_member_metadata_sha256']), 1322)
        self.assertTrue(d['source_scope_bound']); self.assertFalse(d['real_excavate_profile_bound'])
        self.assertFalse(d['formal_pool_complete']); self.assertFalse(d['new_standard_roots'])

    def test_aliases_preserve_complete_source_members_weights_exclusions_and_ordinary_policy(self):
        f = format_for(); r = f.registry
        for domain in native.load_batch()['domains']:
            p = r.pool(domain['pool_id'], f.context)
            self.assertEqual(tuple((x.card_id, x.weight) for x in p.members), tuple(zip(domain['candidate_ids'], domain['weights'])))
            self.assertTrue(p.complete); self.assertEqual(p.excluded_card_ids, ())
        for kind in (CardType.MINION, CardType.SPELL):
            q = PoolQuery(kinds=(kind,), collectible=True)
            self.assertEqual(query(native.CARDS_POOL, q), query('constructed.cards', q))
        self.assertEqual(query(native.EIGHT_POOL, EIGHT_QUERY, CardClass.WARRIOR, native.OX),
            query('constructed.minions', EIGHT_QUERY, CardClass.WARRIOR, native.OX))
        self.assertGreater(len(query(native.CARDS_POOL, SPELL_QUERY)), 400)

    def test_source_preparation_is_pure_and_missing_last_ordinary_body_or_metadata_is_not_trimmed(self):
        f = format_for(); before = f.registry.fingerprint()
        self.assertEqual(len(native.local_pools(f.registry, f.context)), 3)
        self.assertEqual(f.registry.fingerprint(), before)
        other = build_cn37_launch_candidate_format(); cid = native.load_batch()['domains'][0]['candidate_ids'][-1]
        del other.registry._cards[cid]
        with self.assertRaisesRegex(UnsupportedDefinitionError, cid): native.local_pools(other.registry, other.context)
        self.assertEqual(len([p for p in other.registry.pools.values() if p.target_id == other.target_id]), 2)
        changed = deepcopy(native.load_batch()); changed['ordinary_member_metadata_sha256'][cid] = '0' * 64
        with patch.object(native, 'load_batch', lambda: changed), self.assertRaises(TargetValidationError):
            native.local_pools(f.registry, f.context)
        self.assertEqual(f.registry.fingerprint(), before)

    def test_rehashed_manifest_cannot_crop_any_domain_reorder_reweight_exclude_or_claim_official(self):
        for mode in ('crop0', 'crop1', 'crop2', 'order', 'weight', 'exclusion', 'official'):
            d = deepcopy(native.load_batch())
            if mode.startswith('crop'): d['domains'][int(mode[-1])]['candidate_ids'].pop()
            elif mode == 'order': d['domains'][0]['candidate_ids'].reverse()
            elif mode == 'weight': d['domains'][1]['weights'][0] = 2
            elif mode == 'exclusion': d['domains'][2]['excluded_card_ids'].append(d['domains'][2]['candidate_ids'][0])
            else: d['formal_pool_complete'] = True
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder) / 'changed.json'; p.write_text(json.dumps(d), encoding='utf8')
                with patch.object(native, 'BATCH_PATH', p), patch.object(native, 'BATCH_HASH', canonical_digest(d)):
                    with self.assertRaises(TargetValidationError): native.load_batch()

    def test_original_launch_legacy_samples_and_deck_qualification_are_unchanged(self):
        original = build_cn37_launch_candidate_format(); f = format_for()
        self.assertEqual(f.root_card_ids, original.root_card_ids)
        self.assertEqual(f.policy.allowed_card_ids, original.policy.allowed_card_ids)
        self.assertEqual(f.policy.banned_card_ids, original.policy.banned_card_ids)
        for pid, size in ((native.CARDS_POOL, 15), (native.EIGHT_POOL, 3), (native.TRANSFORM_POOL, 5)):
            with self.assertRaises(UnsupportedDefinitionError): original.registry.pool(pid, original.context)
            p = f.registry.pool(pid, GenerationContext('local-2026-09-23', 'experimental'))
            self.assertEqual(len(p.members), size); self.assertFalse(p.complete)

    def test_other_real_generic_pool_consumer_still_discovers_cards_of_all_types(self):
        g = self.game(('LOE_029',), seed=619)
        q = PoolQuery(min_cost=3, max_cost=3, collectible=True, class_mode='current', exclude_source=True)
        candidates = query(native.CARDS_POOL, q, source='LOE_029')
        self.assertTrue({CardType.MINION, CardType.SPELL} <= {g.registry.card(m.card_id).kind for m in candidates})
        rng = Random(); rng.setstate(g._rng.getstate()); offers = sample_candidates(rng, candidates, 3, replacement=False)
        self.play(g, 'LOE_029'); self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options), offers)
        self.choose_card(g, offers[0]); self.assertEqual(self.entity(g, offers[0]).base_cost, 3)
        self.assertEqual(g.state.players[1].mana, 10 - g.registry.card('LOE_029').cost)

    def test_scorpion_gets_four_real_cross_class_spells_with_original_rng_and_zero_cost_floor(self):
        g = self.game((native.SCORPION,), enemy=('CORE_EX1_162',)); selected, rng = self.probe_spells(g)
        self.assertIn('TIME_218', selected); self.play(g, native.SCORPION)
        cards = self.spells(g); self.assertEqual(tuple(e.card_id for e in cards), selected)
        self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g._rng.getstate(), rng.getstate())
        for e in cards:
            self.assertEqual((e.base_cost, e.cost), (g.registry.card(e.card_id).cost, max(1, g.registry.card(e.card_id).cost)))
        self.assertTrue(any(CardClass.ROGUE not in e.metadata.classes for e in (g.registry.card(x.card_id) for x in cards)))
        before = g.state.players[1].mana; self.play(g, 'TIME_218', self.entity(g, 'CORE_EX1_162', 2, 'board').id)
        self.assertEqual(g.state.players[1].mana, before - 1); self.portable(g)

    def test_scorpion_uses_actual_lifetime_progress_across_three_tier_restart(self):
        g = self.game((DIG, native.SCORPION)); self.play(g, DIG)
        self.assertEqual(excavation_count(g.state, 1), 4)
        self.assertEqual([x.tier for x in g.state.excavation_history], [1, 2, 3, 1])
        selected, rng = self.probe_spells(g); self.play(g, native.SCORPION)
        self.assertEqual(tuple(e.card_id for e in self.spells(g)), selected)
        for e in self.spells(g): self.assertEqual(e.cost, max(1, g.registry.card(e.card_id).cost - 4))
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.portable(g)

    def test_first_scorpion_delivery_wait_restores_failed_selection_atomically_and_finishes_same_four(self):
        g = self.game((native.SCORPION,), weapon=GET_WAIT); selected, rng = self.probe_spells(g)
        self.play(g, native.SCORPION); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.spells(g)), 1); self.assertEqual(g.state.players[1].mana, 6)
        g = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K619'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(tuple(e.card_id for e in self.spells(g)), selected)
        self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_scorpion_immediate_reaction_failure_rolls_back_payment_all_cards_and_random(self):
        g = self.game((native.SCORPION,), weapon=GET_FAIL); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K619'): self.play(g, native.SCORPION)
        self.assertEqual(g.snapshot(), saved)

    def test_full_hand_scorpion_still_samples_four_and_burns_three_without_overflow(self):
        g = self.game((native.SCORPION,) + (NOOP,) * 9); selected, rng = self.probe_spells(g)
        self.play(g, native.SCORPION); self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(tuple(e.card_id for e in self.spells(g)), selected[:1])
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 3)
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.assertEqual(g.state.players[1].mana, 6)

    def test_ox_two_independent_discoveries_wait_until_both_then_summon_without_battlecries(self):
        g = self.game((native.OX,), hero='HERO_01', seed=8, enemy=('CORE_EX1_162',))
        candidates = query(native.EIGHT_POOL, EIGHT_QUERY, CardClass.WARRIOR, native.OX)
        rng = Random(); rng.setstate(g._rng.getstate())
        expected = [sample_candidates(rng, candidates, 3, replacement=False) for _ in range(2)]
        self.play(g, native.OX)
        for index in range(2):
            self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options), expected[index])
            self.assertEqual(len(g.state.players[1].board), 1)
            g = self.portable(g); before = g.snapshot()
            with self.assertRaises(IllegalAction): self.choose(g, 'not-an-offer')
            self.assertEqual(g.snapshot(), before); self.choose_card(g, 'CORE_UNG_848')
        self.assertIsNone(g.state.pending_choice)
        drakes = [g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id == 'CORE_UNG_848']
        self.assertEqual(len(drakes), 2); self.assertNotEqual(drakes[0].id, drakes[1].id)
        self.assertEqual(self.entity(g, 'CORE_EX1_162', 2, 'board').health, 2)
        self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g._rng.getstate(), rng.getstate()); self.portable(g)

    def test_second_seat_ox_uses_current_rogue_plus_neutral_from_all_forty_four_stored_faces(self):
        g = self.game((native.OX,), player=2, hero='HERO_03', seed=8)
        candidates = query(native.EIGHT_POOL, EIGHT_QUERY, CardClass.ROGUE, native.OX, 2)
        self.assertGreater(len(candidates), 3)
        for row in candidates:
            self.assertTrue(set(g.registry.card(row.card_id).metadata.classes) & {CardClass.ROGUE, CardClass.NEUTRAL})
        self.play(g, native.OX, player=2); selected = []
        for _ in range(2):
            self.assertTrue({o.card_id for o in g.state.pending_choice.options} <= {m.card_id for m in candidates})
            selected.append(g.state.pending_choice.options[0].card_id); self.choose_card(g, selected[-1])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board], [native.OX] + selected)
        self.assertEqual(g.state.players[2].mana, 6)

    def test_ox_late_summon_failure_restores_original_second_menu_and_first_accepted_result(self):
        g = self.game((native.OX,), hero='HERO_01', seed=8, weapon=SUMMON_FAIL)
        self.play(g, native.OX); self.choose_card(g, 'CORE_UNG_848'); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K619'): self.choose_card(g, 'CORE_UNG_848')
        self.assertEqual(g.snapshot(), saved); self.assertEqual(len(g.state.players[1].board), 1); self.portable(g)

    def test_murloc_transforms_other_physical_minions_in_three_zones_keeps_printed_cost_and_source(self):
        g = self.game((native.MURLOC, 'CORE_EX1_162', native.MURLOC, 'CORE_CS2_029'),
            board=('CORE_EX1_162',), deck=('CORE_EX1_162', 'CORE_CS2_029'), enemy=('CORE_EX1_162',))
        old = [(i, g.state.entities[i].card_id, g.registry.card(g.state.entities[i].card_id).cost)
            for z in ('hand', 'deck', 'board') for i in getattr(g.state.players[1], z)]
        source = self.entity(g, native.MURLOC).id; enemy = asdict(self.entity(g, 'CORE_EX1_162', 2, 'board'))
        rng = Random(); rng.setstate(g._rng.getstate()); expected = {}
        for eid, cid, cost in old:
            if eid == source or g.registry.card(cid).kind != CardType.MINION: continue
            q = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost+3, max_cost=cost+3)
            expected[eid] = sample_candidates(rng, query(native.TRANSFORM_POOL, q, source=native.MURLOC), 1, replacement=True)[0]
        self.play(g, native.MURLOC)
        for eid, cid, cost in old:
            e = g.state.entities[eid]
            if eid in expected:
                self.assertEqual((e.card_id, e.cost, e.base_cost), (expected[eid], cost, cost+3))
            else: self.assertEqual(e.card_id, cid)
        self.assertEqual(asdict(self.entity(g, 'CORE_EX1_162', 2, 'board')), enemy)
        self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g._rng.getstate(), rng.getstate()); self.portable(g)

    def test_murloc_printed_policy_does_not_use_a_temporary_hand_discount_for_tier_or_retained_cost(self):
        g = self.game((DISCOUNT, native.MURLOC, 'CORE_EX1_162')); self.play(g, DISCOUNT)
        eid = self.entity(g, 'CORE_EX1_162').id; self.assertEqual(g.state.entities[eid].cost, 1)
        self.play(g, native.MURLOC)
        self.assertEqual((g.state.entities[eid].cost, g.state.entities[eid].base_cost), (2, 5))

    def test_murloc_first_stored_transform_wait_preserves_accepted_batch_and_private_input(self):
        g = self.game((native.MURLOC, 'CORE_EX1_162'), board=('CORE_EX1_162',),
            deck=('CORE_EX1_162',), weapon=TRANSFORM_WAIT)
        self.play(g, native.MURLOC); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 6); g = self.portable(g); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K619'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g); self.assertIsNone(g.state.pending_choice); self.portable(g)

    def test_murloc_immediate_failure_rolls_back_all_three_zones_source_payment_and_rng(self):
        g = self.game((native.MURLOC, 'CORE_EX1_162'), board=('CORE_EX1_162',),
            deck=('CORE_EX1_162',), weapon=TRANSFORM_FAIL); saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K619'): self.play(g, native.MURLOC)
        self.assertEqual(g.snapshot(), saved)

    def test_opponent_never_sees_private_generated_faces_discovery_offers_or_pool_internals(self):
        for cid, weapon in ((native.SCORPION, GET_WAIT), (native.OX, None), (native.MURLOC, TRANSFORM_WAIT)):
            g = self.game((cid, 'CORE_EX1_162'), hero='HERO_01', weapon=weapon); self.play(g, cid)
            other = g.for_player(2).observe(); row = other['observation']['players'][0]
            self.assertTrue(all(c['card_id'] is None for c in row['hand']))
            raw = json.dumps(other) + json.dumps(g.player_events(2))
            for key in ('rng_state', 'resolution_frame', 'candidate_ids', 'source_scope', native.POLICY):
                self.assertNotIn(key, raw)


if __name__ == '__main__':
    unittest.main()
