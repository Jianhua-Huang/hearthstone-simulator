"""The real Hawk acquires every full-domain Titan through ordinary creation."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json, tempfile, unittest
from pathlib import Path
from random import Random
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import azerite_hawk_domain as native
from hs_sim.engine import Game, PlayerSetup, ResolutionError, Scenario
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.model import BattlecryRepeatSpec, CardClass, CardDefinition, CardType, Keyword, LimitedTriggerSpec
from hs_sim.engine.pools import (GenerationContext, GenerationPolicy, PoolQuery,
    resolve_candidates, sample_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k618.'
WATCH, FAILWATCH, REPEAT, NOOP, FAIL = (P + x for x in ('watch', 'failwatch', 'repeat', 'noop', 'failure'))
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, keywords_all=(Keyword.TITAN,))
ALLOW = GenerationPolicy((Keyword.TITAN,))


@lru_cache(None)
def format_for(role='writer'):
    fmt = build_cn37_local_pool_format(); r = fmt.registry
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, cost=1, on_play=NOOP))
    def fail(c):
        raise ResolutionError('K618 deliberate generated-hand reaction failure')
    r.register_behavior(FAIL, fail)
    def watch(c, failure=False):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.card_id not in native.load_batch()['inventory']['candidate_ids']:
            return ()
        if failure:
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    for cid, failure in ((WATCH, False), (FAILWATCH, True)):
        r.register_behavior(cid, lambda c, failure=failure: watch(c, failure))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=50,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand', cid),)))
    r.register_card(CardDefinition(REPEAT, REPEAT, CardType.MINION, health=50,
        battlecry_repeats=(BattlecryRepeatSpec(),)))
    r.validate()
    return fmt


def registry(mode='normal', role='writer'):
    if mode != 'normal':
        raise ValueError('Unknown Hawk fixture mode')
    return format_for(role).registry


@lru_cache(None)
def candidates():
    fmt = format_for()
    return resolve_candidates(fmt.registry, fmt.context, native.POOL, QUERY,
        current_class=CardClass.MAGE, source_card_id=native.HAWK, policy=ALLOW, player_id=1)


@lru_cache(None)
def seeds():
    # No games or actual source actions are executed during seed preparation.
    result = {}
    for seed in range(256):
        cid = sample_candidates(Random(seed), candidates(), 1, replacement=True)[0]
        result.setdefault(cid, seed)
        if len(result) == 12:
            break
    if set(result) != set(native.load_batch()['inventory']['candidate_ids']):
        raise AssertionError('The full untrimmed domain needs a deterministic seed for every original Titan')
    return result


class AzeriteHawkDomainTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(registry)
    mode = 'normal'

    def game(self, *, seed=618, player=1, hand=(native.HAWK,), board=()):
        fmt = format_for()
        setup = tuple(PlayerSetup('HERO_08' if p == 1 else 'HERO_03', hand=hand if p == player else (),
            board=board if p == player else (), deck=('CORE_EX1_162',) * 8, mana=10, max_mana=10)
            for p in (1, 2))
        return Game.from_scenario(Scenario(setup, active_player=player, seed=seed, generation_context=fmt.context), fmt.registry)

    def generated(self, g, player=1):
        ids = set(native.load_batch()['inventory']['candidate_ids'])
        return [g.state.entities[i] for i in g.state.players[player].hand if g.state.entities[i].card_id in ids]

    def test_complete_thirteen_original_rows_two_reused_faces_and_all_native_dependencies_are_pinned(self):
        d = native.load_batch(); self.assertEqual(len(d['existing_dependencies']), 13)
        self.assertEqual(len(d['official_observations']), 2); self.assertTrue(d['inventory']['runtime_bound'])
        self.assertFalse(d['real_excavate_profile_bound']); self.assertFalse(d['formal_pool_complete'])
        r = format_for().registry
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))), row['definition_sha256'])

    def test_new_host_domain_keeps_twelve_identities_weights_roles_and_legacy_sample(self):
        fmt = format_for(); d = native.load_batch(); pool = fmt.registry.pool(native.POOL, fmt.context)
        self.assertEqual([m.card_id for m in pool.members], d['inventory']['candidate_ids'])
        self.assertEqual([m.weight for m in pool.members], d['inventory']['weights'])
        self.assertEqual(list(pool.excluded_card_ids), d['inventory']['excluded_card_ids']); self.assertTrue(pool.complete)
        old = fmt.registry.pool(native.POOL, GenerationContext('local-2026-09-23', 'experimental'))
        self.assertEqual([(m.card_id, m.weight) for m in old.members], [('TTN_903', 1)])
        self.assertFalse(old.complete)

    def test_every_titan_is_really_acquired_then_paid_at_one_without_replacing_its_native_body(self):
        for desired in native.load_batch()['inventory']['candidate_ids']:
            with self.subTest(titan=desired):
                g = self.game(seed=seeds()[desired]); probe = Random(); probe.setstate(g._rng.getstate())
                expected = sample_candidates(probe, candidates(), 1, replacement=True)
                self.assertEqual(expected, (desired,)); self.play(g, native.HAWK)
                card, = self.generated(g); self.assertEqual(card.card_id, desired); self.assertEqual(card.cost, 1)
                self.assertEqual(card.base_cost, g.registry.card(desired).cost)
                self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g._rng.getstate(), probe.getstate())
                self.assertFalse(any(e.kind == 'minion_summoned' and e.target_id == card.id for e in g.events))
                before = g.state.players[1].mana; eid = self.play(g, desired)
                self.assertEqual(g.state.players[1].mana, before - 1)
                active = [a for a in g.state.entities[eid].abilities if a.kind == 'activated']
                self.assertEqual(len(active), 3); self.assertTrue(all(not a.consumed for a in active))
                self.assertIn(Keyword.TITAN, g.state.entities[eid].keywords)
                if desired == 'TTN_960':
                    self.assertTrue(any(g.state.entities[i].card_id == 'TTN_960t' for i in g.state.players[1].board))
        self.portable(g)

    def test_other_hero_class_and_second_seat_still_use_complete_cross_class_domain(self):
        fmt = format_for()
        current = resolve_candidates(fmt.registry, fmt.context, native.POOL, QUERY,
            current_class=CardClass.ROGUE, source_card_id=native.HAWK, policy=ALLOW, player_id=2)
        self.assertEqual(current, candidates())
        g = self.game(seed=seeds()['TTN_075'], player=2); self.play(g, native.HAWK, player=2)
        card, = self.generated(g, 2); self.assertEqual((card.card_id, card.cost), ('TTN_075', 1))
        self.assertEqual(g.state.players[2].mana, 6); self.portable(g)

    def test_titan_exception_is_explicit_and_does_not_make_ordinary_generation_eligible(self):
        fmt = format_for()
        ordinary = resolve_candidates(fmt.registry, fmt.context, native.POOL, QUERY,
            current_class=CardClass.MAGE, source_card_id=native.HAWK, player_id=1)
        self.assertFalse(ordinary); self.assertEqual(len(candidates()), 12)
        self.assertEqual({m.card_id for m in candidates()}, set(native.load_batch()['inventory']['candidate_ids']))

    def test_two_original_battlecries_get_two_independent_one_cost_entities_with_original_rng(self):
        g = self.game(board=(REPEAT,)); probe = Random(); probe.setstate(g._rng.getstate())
        expected = sample_candidates(probe, candidates(), 2, replacement=True); self.play(g, native.HAWK)
        cards = self.generated(g)
        self.assertEqual(tuple(e.card_id for e in cards), expected); self.assertEqual(len({e.id for e in cards}), 2)
        self.assertTrue(all(e.cost == 1 for e in cards)); self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual(g._rng.getstate(), probe.getstate())

    def test_first_delivery_wait_keeps_selected_identity_cost_payment_and_remaining_repeat(self):
        g = self.game(board=(REPEAT, WATCH)); probe = Random(); probe.setstate(g._rng.getstate())
        expected = sample_candidates(probe, candidates(), 2, replacement=True); self.play(g, native.HAWK)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.players[1].mana, 6)
        first, = self.generated(g); self.assertEqual((first.card_id, first.cost), (expected[0], 1))
        g = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved); self.choose(g)
        self.assertEqual(tuple(e.card_id for e in self.generated(g)), expected)
        self.assertTrue(all(e.cost == 1 for e in self.generated(g)))
        self.assertEqual(g._rng.getstate(), probe.getstate()); self.portable(g)

    def test_late_generated_hand_failure_rolls_back_source_payment_creation_and_rng(self):
        g = self.game(board=(FAILWATCH,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, native.HAWK)
        self.assertEqual(g.snapshot(), saved)

    def test_full_hand_repeated_get_burns_second_reward_without_overflow_or_extra_source_payment(self):
        g = self.game(hand=(native.HAWK,) + (NOOP,) * 9, board=(REPEAT,))
        probe = Random(); probe.setstate(g._rng.getstate()); expected = sample_candidates(probe, candidates(), 2, replacement=True)
        self.play(g, native.HAWK); self.assertEqual(len(g.state.players[1].hand), 10)
        card, = self.generated(g); self.assertEqual((card.card_id, card.cost), (expected[0], 1))
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 1)
        self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g._rng.getstate(), probe.getstate())

    def test_opponent_cannot_see_random_reward_identity_internal_candidates_or_future_rng(self):
        g = self.game(board=(WATCH,)); self.play(g, native.HAWK); card, = self.generated(g)
        own = g.for_player(1).observe()['observation']; other = g.for_player(2).observe()['observation']
        self.assertEqual(own['players'][0]['hand'][0]['card_id'], card.card_id)
        self.assertIsNone(other['players'][0]['hand'][0]['card_id'])
        raw = json.dumps(g.for_player(2).observe()) + json.dumps(g.player_events(2))
        self.assertNotIn(card.card_id, raw)
        for private in ('rng_state', 'resolution_frame', 'generation_scopes', native.POLICY, 'candidate_ids'):
            self.assertNotIn(private, raw)

    def test_domain_preparation_is_pure_and_missing_or_changed_last_native_member_never_trims_pool(self):
        fmt = format_for(); before = fmt.registry.fingerprint(); pool = native.local_pool(fmt.registry, fmt.context)
        self.assertEqual(len(pool.members), 12); self.assertEqual(fmt.registry.fingerprint(), before)
        data = deepcopy(native.load_batch()); data['existing_dependencies'][-1]['definition_sha256'] = '0' * 64
        with patch.object(native, 'load_batch', lambda: data), self.assertRaises(TargetValidationError): native.local_pool(fmt.registry, fmt.context)
        self.assertEqual(fmt.registry.fingerprint(), before)
        launch = build_cn37_launch_candidate_format(); del launch.registry._cards['YOG_516']
        with self.assertRaisesRegex(UnsupportedDefinitionError, 'YOG_516'): native.local_pool(launch.registry, launch.context)

    def test_rehashed_manifest_cannot_trim_reorder_reweight_exclude_or_claim_official_completeness(self):
        for mode in ('trim', 'reorder', 'weight', 'exclusion', 'official'):
            data = deepcopy(native.load_batch())
            if mode == 'trim': data['inventory']['candidate_ids'].pop()
            elif mode == 'reorder': data['inventory']['candidate_ids'].reverse()
            elif mode == 'weight': data['inventory']['weights'][0] = 2
            elif mode == 'exclusion': data['inventory']['excluded_card_ids'].append('YOG_516')
            else: data['formal_pool_complete'] = True
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'changed.json'; path.write_text(json.dumps(data), encoding='utf8')
                with patch.object(native, 'BATCH_PATH', path), patch.object(native, 'BATCH_HASH', canonical_digest(data)):
                    with self.assertRaises(TargetValidationError): native.load_batch()

    def test_launch_factory_does_not_acquire_the_new_local_reward_context_or_deck_roots(self):
        original = build_cn37_launch_candidate_format(); fmt = format_for()
        self.assertEqual(fmt.root_card_ids, original.root_card_ids); self.assertNotIn(native.HAWK, fmt.root_card_ids)
        self.assertEqual(fmt.policy.allowed_card_ids, original.policy.allowed_card_ids)
        self.assertEqual(fmt.policy.banned_card_ids, original.policy.banned_card_ids)
        with self.assertRaises(UnsupportedDefinitionError): original.registry.pool(native.POOL, original.context)
        legacy = original.registry.pool(native.POOL, GenerationContext('local-2026-09-23', 'experimental'))
        self.assertEqual(len(legacy.members), 1); self.assertFalse(legacy.complete)
        self.assertFalse(fmt.formal_pool_complete); self.assertFalse(fmt.cn_bans_verified)


if __name__ == '__main__':
    unittest.main()
