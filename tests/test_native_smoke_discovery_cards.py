"""Smoke Bomb's explicit preview policy, full eligibility and paired recovery."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.native_smoke_discovery_cards import SMOKE, QUERY, CLAUSES, POOL_ID, OFFER_POLICY, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SpellSchool, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec, Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import canonical_digest

P = 'k124.test.'
COMBO, BATTLECRY, STEALTH, TRIPLE, DOUBLE = ('CORE_BOT_576', 'CORE_EX1_189', 'CORE_EX1_010', 'TLC_522', 'TIME_710')
YETI = 'CORE_CS2_182'
FOREIGN = P + 'foreign_battlecry'
UNKNOWN, UNKNOWN_FACT, UNKNOWN_STEALTH, UNKNOWN_NO = (P + s for s in ('unknown', 'unknown_fact', 'unknown_stealth', 'unknown_no'))
MEMBERS = (COMBO, BATTLECRY, STEALTH, TRIPLE, DOUBLE, YETI, FOREIGN)
EXPECTED = {COMBO, BATTLECRY, STEALTH, TRIPLE, DOUBLE}
CTX = GenerationContext('k124-host', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    original = r.card(BATTLECRY)
    foreign = replace(original, id=FOREIGN, metadata=replace(original.metadata, classes=(CardClass.MAGE,)))
    r.register_card(foreign)
    r.register_pool_card(PoolCard.from_definition(foreign))
    for cid in members:
        if cid in (UNKNOWN, UNKNOWN_FACT, UNKNOWN_STEALTH, UNKNOWN_NO):
            r.register_pool_card(PoolCard(cid, CardType.MINION, 3,
                CardMetadata(True, (CardClass.ROGUE,), Rarity.COMMON, tribes=(), factions=(), subtypes=()),
                keywords=(Keyword.STEALTH,) if cid == UNKNOWN_STEALTH else (),
                battlecry=True if cid == UNKNOWN else False if cid == UNKNOWN_NO else None,
                deathrattle=False, choose_one=False))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k124-complete-explicit-fixture', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    r.register_behavior(P + 'counter', lambda c: (SetSecret(2, 'EX1_287'),))
    r.register_card(CardDefinition(P + 'counter', 'Existing Counterspell installation', CardType.SPELL,
        metadata=META, on_play=P + 'counter'))
    if mode:
        r.register_behavior(P + 'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K124 deliberate delivery failure')))
        def watch(c):
            if mode == 'fail':
                return (InvokeBehavior(P + 'fail', c.source_id, 1),)
            if mode == 'fill':
                return (AddToHand(1, YETI, c.source_id),)
            return (RequestChoice(1, (ChoiceOption('ok', 'Continue', ()),
                ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),))), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_trigger_condition(P + 'eligible', lambda c: c.event.source_id is not None and
            c.state.entities[c.event.source_id].card_id == SMOKE)
        r.register_card(CardDefinition(P + 'watch', 'Original discovery observer', CardType.MINION, health=8,
            metadata=META, limited_triggers=(LimitedTriggerSpec('choice_selected' if mode == 'fill' else 'card_created',
                P + 'watch', condition_id=P + 'eligible'),)))
    r.validate()
    return r


class NativeSmokeDiscoveryTests(unittest.TestCase):
    def game(self, members=MEMBERS, mode=None, pool=True, context=CTX, hero='HERO_03', hand=(SMOKE,), seed=124):
        self.config = (members, mode, pool)
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=(P + 'watch',) if mode else (), deck=(YETI,) * 4,
                mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', deck=(YETI,) * 4),
        ), seed=seed, generation_context=context), registry(*self.config))

    def play(self, g, cid=SMOKE):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid))
        return eid

    def choose(self, g, index=0):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (q.options[index].id,)))

    def created(self, g, source):
        return [g.state.entities[e.target_id] for e in g.events if e.kind == 'card_created' and e.source_id == source]

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(saved, registry.__wrapped__(*self.config))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.config)).snapshot(), saved)
        for player in (1, 2):
            wire = json.dumps(g.for_player(player).observe()) + json.dumps(g.for_player(player).legal_actions()) + json.dumps(g.player_events(player))
            for key in ('resolution_frame', 'rng_state', 'PoolQuery', 'any_of', 'offered_gifts', 'gift_pool', 'behavior_id'):
                self.assertNotIn('"' + key + '"', wire)
        return other

    def test_complete_eleven_rows_two_faces_real_fire_and_explicit_uncalibrated_offer_policy(self):
        data = load_batch()
        self.assertEqual(len(data['cards'] + data['existing_gift_sources']), 11)
        self.assertEqual(len(data['official_observations']['observations']), 2)
        self.assertEqual(data['offer_policy'], OFFER_POLICY)
        self.assertFalse(data['cn_calibrated'])
        self.assertFalse(data['formal_pool_complete'])
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        raw = data['cards'][0]['record']
        for row in data['cards'] + data['existing_gift_sources']:
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
        for o in data['official_observations']['observations']:
            cn = o['locale'] == 'zh_CN'
            self.assertEqual(o['face']['name'], raw['name' if cn else 'name_en'])
            self.assertEqual(norm(o['face']['text']), norm(raw['text' if cn else 'text_en']))
        card = registry().card(SMOKE)
        self.assertEqual((card.cost, card.spell_school, card.metadata.classes), (2, SpellSchool.FIRE, (CardClass.ROGUE,)))
        self.assertFalse(card.keywords)
        self.assertIsNone(card.battlecry)
        self.assertIsNone(card.combo)

    def test_single_new_root_preserves_old_definitions_pool_rows_default_identity_and_formal_pool_boundary(self):
        with patch('hs_sim.cards.native_smoke_discovery_cards.register_native_smoke_discovery_cards', lambda r: None):
            before = build_registry()
        after = build_registry()
        self.assertEqual(set(after.cards) - set(before.cards), {SMOKE})
        self.assertTrue(all(asdict(before.card(cid)) == asdict(after.card(cid)) for cid in before.cards))
        self.assertEqual(dict(after.pool_cards), dict(before.pool_cards))
        self.assertEqual(dict(after.pools), dict(before.pools))
        self.assertEqual(dict(after.generation_families), dict(before.generation_families))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)
        self.assertFalse(any(p.id == POOL_ID or p.mode == 'standard' for p in after.pools.values()))

    def test_full_union_contains_each_original_member_once_and_current_class_is_independent_of_source_class(self):
        g = self.game()
        rows = resolve_candidates(g.registry, CTX, POOL_ID, QUERY, current_class=CardClass.ROGUE)
        self.assertEqual({m.card_id for m in rows}, EXPECTED)
        self.assertEqual(sum(m.weight for m in rows), 5)
        self.assertEqual(len(rows), 5)
        mage_rows = resolve_candidates(g.registry, CTX, POOL_ID, QUERY, current_class=CardClass.MAGE)
        self.assertEqual({m.card_id for m in mage_rows}, {BATTLECRY, STEALTH, FOREIGN})

    def test_one_paid_spell_has_one_three_offer_discovery_and_complete_original_gifts(self):
        g = self.game()
        self.play(g)
        self.assertEqual(len(g.state.pending_choice.options), 3)
        self.assertEqual(len({o.card_id for o in g.state.pending_choice.options}), 3)
        self.assertTrue({o.card_id for o in g.state.pending_choice.options}.issubset(EXPECTED))
        spec = g._frame.options[0].effects[0].batch.spec
        self.assertEqual(spec.query, QUERY)
        self.assertEqual(spec.query.any_of, CLAUSES)
        self.assertEqual(len(spec.gift_pool.members), 10)
        self.assertEqual(g.state.players[1].mana, 38)
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertFalse(g.state.battlecry_history)
        self.portable(g)

    def test_selected_pair_preview_matches_original_material_and_does_not_trigger_native_minion_bodies(self):
        g = self.game()
        source = self.play(g)
        option = g._frame.options[0]
        gift = option.effects[0].selection.gift
        self.choose(g)
        new, = self.created(g, source)
        self.assertEqual((new.card_id, new.cost, new.attack, new.max_health),
            (option.card_id, option.preview.cost, option.preview.attack, option.preview.max_health))
        self.assertEqual(new.zone, Zone.HAND if gift.destination == 'hand' else Zone.DECK)
        self.assertTrue(any(e.label == 'created_minion_grant:' + gift.id for e in new.enchantments))
        self.assertFalse(g.state.battlecry_history)
        self.assertFalse(g.state.combo_history)
        self.portable(g)

    def test_existing_offer_restores_independent_registry_and_selects_without_new_rng_or_payment(self):
        g = self.game()
        source = self.play(g)
        other = self.portable(g)
        rng = g._rng.getstate()
        with patch.object(random.Random, 'randrange', side_effect=AssertionError('Resampled original offer')):
            self.choose(g)
            self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(self.created(g, source)), 1)
        self.assertEqual(g.state.players[1].mana, 38)

    def test_unknown_implementation_or_unknown_fact_fails_before_any_candidate_or_gift_rng(self):
        for unknown in (UNKNOWN, UNKNOWN_FACT, UNKNOWN_STEALTH):
            with self.subTest(unknown=unknown):
                g = self.game(members=(*MEMBERS, unknown))
                saved = g.snapshot()
                self.assertNotIn(unknown, g.registry.cards)
                with patch.object(random.Random, 'randrange', side_effect=AssertionError('RNG before full eligibility')) as call:
                    with self.assertRaises(ResolutionError):
                        self.play(g)
                    call.assert_not_called()
                self.assertEqual(g.snapshot(), saved)

    def test_known_negative_unimplemented_member_is_excluded_by_metadata_not_by_coverage(self):
        g = self.game(members=(*MEMBERS, UNKNOWN_NO))
        self.assertNotIn(UNKNOWN_NO, g.registry.cards)
        self.play(g)
        self.assertTrue({o.card_id for o in g.state.pending_choice.options}.issubset(EXPECTED))

    def test_empty_inventory_keeps_spell_payment_and_does_not_sample_gifts(self):
        g = self.game(members=(YETI,))
        rng = g._rng.getstate()
        self.play(g)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 38)

    def test_missing_inventory_or_host_context_rolls_back_original_paid_spell(self):
        for changes in ({'pool': False}, {'context': None}):
            with self.subTest(changes=changes):
                g = self.game(**changes)
                saved = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(g)
                self.assertEqual(g.snapshot(), saved)

    def test_countered_spell_needs_no_pool_and_never_accepts_discovery(self):
        g = self.game(hand=(P + 'counter', SMOKE), pool=False, context=None)
        self.play(g, P + 'counter')
        rng = g._rng.getstate()
        source = self.play(g)
        self.assertFalse(self.created(g, source))
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.cast_history[-1].failure, 'countered')
        self.assertEqual(g.state.players[1].mana, 38)
        self.assertEqual(g._rng.getstate(), rng)

    def test_actual_delivery_wait_resumes_or_rolls_back_without_replacing_accepted_query(self):
        g = self.game(mode='wait')
        source = self.play(g)
        self.choose(g)
        saved = g.snapshot()
        other = self.portable(g)
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            game.apply(SelectChoice(1, game.state.pending_choice.id, ('ok',)))
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(self.created(g, source)), 1)

    def test_post_selection_failure_keeps_original_offer_allocation_and_rng(self):
        g = self.game(mode='fail')
        self.play(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'K124 deliberate'):
            self.choose(g)
        self.assertEqual(g.snapshot(), saved)

    def test_hand_overflow_burns_complete_selected_hand_gift_without_other_card_mutation(self):
        g = self.game(mode='fill', hand=(SMOKE,) + (YETI,) * 9)
        source = self.play(g)
        index = next(i for i, o in enumerate(g._frame.options) if o.effects[0].selection.gift.destination == 'hand')
        self.choose(g, index)
        new, = self.created(g, source)
        self.assertEqual(new.zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertTrue(any(e.kind == 'card_burned' and e.target_id == new.id for e in g.events))
        self.portable(g)

    def test_saved_query_rejects_bad_alternatives_clause_exclusions_and_previous_schema(self):
        g = self.game()
        self.play(g)
        saved = g.snapshot()
        def queries(node):
            if isinstance(node, dict):
                if node.get('type', '').endswith('.PoolQuery'):
                    yield node['fields']
                for v in node.values():
                    yield from queries(v)
            elif isinstance(node, list):
                for v in node:
                    yield from queries(v)
        self.assertGreaterEqual(len(list(queries(saved))), 4)
        for bad_clause in (False, True):
            bad = deepcopy(saved)
            values = list(queries(bad))
            if bad_clause:
                values[1]['exclude_source'] = True
            else:
                values[0]['any_of'] = None
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry(*self.config))
        old = deepcopy(saved)
        old['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry(*self.config))


if __name__ == '__main__':
    unittest.main()
