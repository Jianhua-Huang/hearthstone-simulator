"""Actual six-cost pool dependencies enter through the native Colossal executor."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.simple_followup_p68_cards import AMIRDRASSIL, WICKERFANG, LEGS, PREFIX, POOL_ID
from hs_sim.cards.native_pool_lifesteal_cards import FORM
from hs_sim.engine import (AppendageSpec, CardDefinition, CardMetadata, CardClass, CardType,
    EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity, Scenario, SelectChoice,
    SnapshotError, SummonStats, UseLocation, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, Destroy, GainArmor,
    InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.discovery_summons import selected as selected_discovery
from hs_sim.engine.model import LimitedTriggerSpec, SummonQuantitySpec
from hs_sim.engine.pools import (DiscoverFromPool, GenerateFromPool, GenerationContext,
    PoolCard, PoolDefinition, PoolMember, PoolQuery, SummonFromCandidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial, validate_material

TEST = 'k160.test.'
NAMED, FINITE, GENERATE, DISCOVER, TINY_SUMMON, DOUBLE, WATCH, TINY, LIMB, UNKNOWN = (
    TEST + n for n in ('named', 'finite', 'generate', 'discover', 'tiny_summon',
        'double', 'watch', 'tiny', 'limb', 'unknown'))
YETI = 'CORE_CS2_182'
CONTEXT = GenerationContext('k160-complete-explicit-six-cost-fixture', 'experimental')
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=6, max_cost=6)
SOURCE_PIN = hashlib.sha256(Path(__file__).read_bytes() +
    (Path(__file__).resolve().parents[1] / 'hs_sim/engine/summon_quantities.py').read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def fixture_registry(mode, unknown, role, pin):
    if role not in ('writer', 'reader') or pin != SOURCE_PIN:
        raise AssertionError('Incomplete immutable fixture key')
    r = build_registry()
    r.register_behavior(TEST + 'bc', lambda c: (GainArmor(c.player_id, 999),))
    r.register_card(CardDefinition(LIMB, 'Plain fixture appendage', CardType.MINION, attack=1, health=2))
    r.register_card(CardDefinition(TINY, 'Colossal with a real Battlecry declaration', CardType.MINION,
        attack=3, health=5, keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec(LIMB),),
        battlecry=TEST + 'bc'))
    r.register_card(CardDefinition(DOUBLE, 'Existing quantity carrier', CardType.MINION, health=12,
        summon_quantities=(SummonQuantitySpec(2),)))
    def named(c, cid=WICKERFANG):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(cid),), SummonCause.capture(c)),)
    bodies = {
        NAMED: named,
        FINITE: lambda c: (SummonFromCandidates(c.player_id, (WICKERFANG,), c.source_id, SummonCause.capture(c)),),
        GENERATE: lambda c: (GenerateFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c)),),
        DISCOVER: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c)),),
        TINY_SUMMON: lambda c: named(c, TINY),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid))
    members = [PoolMember(WICKERFANG)]
    if unknown:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.MINION, 6,
            CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON),
            battlecry=False, deathrattle=False, choose_one=False))
        members.append(PoolMember(UNKNOWN))
    r.register_pool(PoolDefinition(POOL_ID, 'k160-explicit-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(members), complete=True))
    if mode:
        def eligible(c):
            return c.state.entities[c.event.target_id].card_id == LEGS[0]
        def fail(c):
            raise ResolutionError('K160 deliberate failed continuation')
        def watch(c):
            child = c.state.card_summon_history[-1]
            body = child.deliveries[-1].entity.entity_id
            if mode == 'fatal':
                return (Damage(c.state.players[2].hero_id, 100, c.source_id),)
            if mode == 'free':
                victim = next(i for i in c.state.players[1].board if c.state.entities[i].card_id == YETI)
                return (Destroy(victim, c.source_id),)
            options = [ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(TEST + 'fail', c.source_id, c.player_id),)),
                ChoiceOption('kill_body', 'Remove original body', (Destroy(body, c.source_id),)),
                ChoiceOption('steal_body', 'Transfer original body', (ChangeControl(body, 2),)),
                ChoiceOption('kill_cause', 'Remove original physical cause',
                    (Destroy(child.request.cause.source.entity_id, c.source_id),))]
            sources = [i for i in c.state.players[1].board if c.state.entities[i].card_id == DOUBLE]
            if sources:
                options.append(ChoiceOption('kill_quantity', 'Remove accepted quantity source',
                    tuple(Destroy(i, c.source_id) for i in sources)))
            return (RequestChoice(c.player_id, tuple(options), c.source_id),)
        r.register_behavior(TEST + 'fail', fail)
        r.register_behavior(TEST + 'watch', watch)
        r.register_trigger_condition(TEST + 'leg', eligible)
        r.register_card(CardDefinition(WATCH, 'One actual appendage checkpoint', CardType.MINION, health=12,
            limited_triggers=(LimitedTriggerSpec('minion_summoned', TEST + 'watch', condition_id=TEST + 'leg'),)))
    r.validate()
    r.freeze()
    return r


class AttributedColossalEntryTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode=None, unknown=False, capacity=7):
        self.config = mode, unknown
        if mode:
            board = (WATCH, *board)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=hand, board=board, deck=(YETI,) * 40,
                mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_10', deck=(YETI,) * 40, mana=40, max_mana=40, mana_cap=40)),
            seed=160160, generation_context=CONTEXT),
            fixture_registry(mode, unknown, 'writer', SOURCE_PIN), Ruleset(max_board=capacity))

    def find(self, g, cid, zone='hand'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid):
        eid = self.find(g, cid)
        kind = g.state.entities[eid].kind
        g.apply(PlayCard(1, eid, position=len(g.state.players[1].board)
            if kind in (CardType.MINION, CardType.LOCATION) else None))
        return eid

    def choose(self, g, option):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, (option,)))

    def portable(self, g):
        reader = fixture_registry(*self.config, 'reader', SOURCE_PIN)
        self.assertIsNot(reader, g.registry)
        self.assertEqual(reader.fingerprint(), g.registry.fingerprint())
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('card_summon_history', 'colossal_history', 'rng_state', 'resolution_frame', 'source_allocation'):
                self.assertNotIn('"' + key + '"', public)
        return restored

    def assert_expansion(self, g, expected=4):
        rec = g.state.colossal_history[-1]
        self.assertEqual((rec.card_id, rec.reason, rec.completed), (WICKERFANG, 'summon', True))
        self.assertEqual(sum(i is not None for i in rec.limbs), expected)
        self.assertEqual([g.state.entities[i].card_id for i in rec.limbs if i is not None], list(LEGS[:expected]))
        self.assertEqual(g.state.card_summon_history[-1].deliveries[0].entity.entity_id, rec.entity_id)
        return rec

    def test_actual_amirdrassil_six_native_uses_reach_qualified_wickerfang(self):
        g = self.game((AMIRDRASSIL, AMIRDRASSIL))
        sources = [self.play(g, AMIRDRASSIL), self.play(g, AMIRDRASSIL)]
        before = g.snapshot()['rng_state']
        for round_index in range(3):
            for eid in sources:
                g.apply(UseLocation(1, eid))
                if len(g.state.pool_summon_history) < 6:
                    self.assertEqual(g.snapshot()['rng_state'], before)
            if round_index < 2:
                # The existing location clock opens after two owner starts.
                for _ in range(2):
                    g.apply(EndTurn(1))
                    g.apply(EndTurn(2))
        self.assertEqual([r.selected for r in g.state.pool_summon_history], [(), (), (), (), (), (WICKERFANG,)])
        self.assertEqual(sum(e.spec_id == PREFIX + 'location_progress' for e in g.state.players[1].player_effects), 6)
        self.assertEqual(g.state.card_summon_history[-1].request.cause.source.kind, CardType.LOCATION)
        self.assert_expansion(g)
        self.assertFalse(g.state.cast_history)
        self.portable(g)

    def test_named_finite_and_generated_plain_materials_use_the_same_native_entry(self):
        for cid in (NAMED, FINITE, GENERATE):
            with self.subTest(cid=cid):
                g = self.game((cid,))
                source = self.play(g, cid)
                self.assert_expansion(g)
                child = g.state.card_summon_history[-1]
                self.assertEqual(child.request.cause.source.entity_id, source)
                self.assertEqual((child.plan.total, child.status), (1, 'completed'))
                self.assertEqual(len(g.state.play_history), 1)
                self.portable(g)

    def test_actual_osk_six_cost_pool_grants_only_original_body_before_appendages(self):
        g = self.game((FORM,), mode='wait')
        source = self.play(g, FORM)
        child = g.state.card_summon_history[-1]
        body = g.state.entities[child.deliveries[0].entity.entity_id]
        self.assertEqual(child.request.materials[child.selected].keywords, (Keyword.TAUNT, Keyword.LIFESTEAL))
        self.assertTrue(all(any(a.kind == 'keyword' and a.keyword == k for a in body.abilities)
            for k in (Keyword.TAUNT, Keyword.LIFESTEAL)))
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g)
        self.choose(g, 'kill_cause')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        rec = self.assert_expansion(g)
        for eid in rec.limbs:
            self.assertFalse(any(a.kind == 'keyword' and a.origin != 'printed'
                and a.keyword in (Keyword.TAUNT, Keyword.LIFESTEAL) for a in g.state.entities[eid].abilities))
        self.portable(g)

    def test_selected_discovery_waits_inside_limbs_and_resumes_the_original_result(self):
        g = self.game((DISCOVER,), mode='wait')
        self.play(g, DISCOVER)
        self.portable(g)
        self.choose(g, g.state.pending_choice.options[0].id)
        self.assertEqual(selected_discovery(g.state.discovery_summon_history[-1].offers[0]), WICKERFANG)
        saved = g.snapshot()
        self.portable(g)
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        restored = self.portable(g)
        self.choose(g, 'ok')
        self.choose(restored, 'ok')
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assert_expansion(g)
        self.portable(g)

    def test_original_quantity_plan_finishes_each_colossal_before_next_body(self):
        g = self.game((GENERATE, NAMED), (DOUBLE,), mode='wait', capacity=12)
        self.play(g, GENERATE)
        self.assertEqual(g.state.card_summon_history[0].plan.total, 2)
        self.assertEqual(len(g.state.card_summon_history[0].deliveries), 1)
        self.assertEqual(g.state.colossal_history[0].attempted, 1)
        self.portable(g)
        self.choose(g, 'kill_quantity')
        self.assertEqual(len(g.state.colossal_history), 2)
        self.assertTrue(all(r.completed and all(i is not None for i in r.limbs) for r in g.state.colossal_history))
        child = g.state.card_summon_history[0]
        self.assertEqual((child.plan.total, len(child.deliveries), child.status), (2, 2, 'completed'))
        self.assertLess(max(i for i in g.state.colossal_history[0].limbs if i is not None), child.deliveries[1].entity.entity_id)
        self.play(g, NAMED)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history], [2, 1])
        self.portable(g)

    def test_actual_capacity_handles_partial_limbs_and_full_preselected_failure(self):
        for existing, limbs in ((4, 2), (6, 0), (7, None)):
            with self.subTest(existing=existing):
                g = self.game((GENERATE,), (YETI,) * existing)
                self.play(g, GENERATE)
                child = g.state.card_summon_history[-1]
                self.assertEqual(child.request.materials[0].card_id, WICKERFANG)
                if limbs is None:
                    self.assertEqual(child.deliveries[0].outcome, 'board_full')
                    self.assertFalse(g.state.colossal_history)
                else:
                    self.assert_expansion(g, limbs)
                self.portable(g)

    def test_each_appendage_rechecks_space_freed_by_previous_appendage_reaction(self):
        g = self.game((GENERATE,), (YETI, YETI), mode='free')
        self.play(g, GENERATE)
        self.assert_expansion(g)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.portable(g)

    def test_original_body_death_or_transfer_cancels_only_remaining_appendages(self):
        for option in ('kill_body', 'steal_body'):
            with self.subTest(option=option):
                g = self.game((GENERATE,), mode='wait')
                self.play(g, GENERATE)
                self.choose(g, option)
                rec = g.state.colossal_history[-1]
                self.assertEqual((rec.completed, rec.canceled, rec.attempted), (True, True, 1))
                self.assertEqual(sum(i is not None for i in rec.limbs), 1)
                self.assertIn(rec.limbs[0], g.state.players[1].board)
                self.assertEqual(g.state.card_summon_history[-1].status, 'completed')
                self.portable(g)

    def test_terminal_during_appendage_reactions_closes_original_roots(self):
        g = self.game((GENERATE,), mode='fatal')
        self.play(g, GENERATE)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertIsNone(g.state.pending_choice)
        self.assertTrue(all(r.completed for r in g.state.colossal_history))
        self.assertEqual(g.state.card_summon_history[-1].status, 'interrupted')
        self.portable(g)

    def test_native_summon_does_not_execute_colossal_battlecry(self):
        g = self.game((TINY_SUMMON,))
        self.play(g, TINY_SUMMON)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(g.state.colossal_history[-1].reason, 'summon')
        self.assertEqual(len(g.state.play_history), 1)
        self.portable(g)

    def test_unknown_eligible_material_is_not_deleted_even_when_board_is_full(self):
        g = self.game((GENERATE,), (YETI,) * 7, unknown=True)
        saved = g.snapshot()
        with self.assertRaises(Exception):
            self.play(g, GENERATE)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(tuple(m.card_id for m in g.registry.pool(POOL_ID, CONTEXT).members), (WICKERFANG, UNKNOWN))

    def test_waiting_snapshot_rejects_dropped_colossal_or_parent_controls(self):
        g = self.game((GENERATE,), mode='wait')
        self.play(g, GENERATE)
        saved = g.snapshot()
        for type_name in ('SummonAppendage', 'FinishColossal', 'FinishCardSummon'):
            bad = deepcopy(saved)
            removed = []
            def strip(value):
                if isinstance(value, list):
                    for item in list(value):
                        if isinstance(item, dict) and str(item.get('type', '')).endswith('.' + type_name):
                            value.remove(item)
                            removed.append(item)
                        else:
                            strip(item)
                elif isinstance(value, dict):
                    for item in value.values():
                        strip(item)
            strip(bad['resolution_frame'])
            self.assertTrue(removed, type_name)
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(type_name=type_name), self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, fixture_registry(*self.config, 'reader', SOURCE_PIN))

    def test_only_actual_plain_and_existing_pool_keyword_profiles_are_opened(self):
        r = fixture_registry(None, False, 'reader', SOURCE_PIN)
        plain = SummonEntryMaterial(WICKERFANG)
        # Copy, recruit, resurrection-pool and ordered-group validators retain
        # the restrictive default; only native plain/pool request sites opt in.
        with self.assertRaisesRegex(ValueError, 'ordinary non-composite'):
            validate_material(r, plain)
        validate_material(r, plain, allow_colossal=True)
        validate_material(r, replace(plain, keywords=(Keyword.TAUNT, Keyword.LIFESTEAL)), allow_colossal=True)
        for material in (replace(plain, stats=SummonStats(1, 1)),
                replace(plain, dormant_turns=2), replace(plain, keywords=(Keyword.CHARGE,)),
                replace(plain, deathrattles=(TEST + 'bc',)), replace(plain, on_summon=TEST + 'bc')):
            with self.subTest(material=material), self.assertRaisesRegex(ValueError, '(supported pool keywords|ordered Taunt/Lifesteal/Rush)'):
                validate_material(r, material, allow_colossal=True)
