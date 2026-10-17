"""Printed eligibility is complete even when executable coverage is incomplete."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import random
import re
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import candidate_pool_rows, load_batch as catalog_batch
from hs_sim.cards.native_ability_discovery_cards import GARDENING, SYMBIOSIS, ROOTS, QUERIES, POOL_ID, load_batch
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.effects import AddToHand, InvokeBehavior
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import LimitedTriggerSpec, Rarity, SpellSchool
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery, matches_metadata, resolve_candidates
from hs_sim.engine.registry import Registry, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION, canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest

P = 'k122.test.'
YETI = 'CORE_CS2_182'
DR = 'CORE_EX1_096'
DR2 = 'CORE_EX1_110'
CHOOSE_SPELL = 'CORE_AT_037'
CHOOSE_MINION = 'EDR_257'
CHOOSE_WEAPON = 'EDR_525'
MAGE_CHOOSE = 'EDR_872'
WARLOCK = 'CORE_CS2_065'
UNKNOWN_DR = P + 'unknown_deathrattle'
UNKNOWN_CHOOSE = P + 'unknown_choose_one'
UNKNOWN_NO = P + 'unknown_nonmatching'
MEMBERS = (YETI, DR, DR2, CHOOSE_SPELL, CHOOSE_MINION, CHOOSE_WEAPON, MAGE_CHOOSE, WARLOCK)
CTX = GenerationContext('k122-host', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def registry(members=MEMBERS, mode=None, pool=True):
    r = build_registry()
    for cid in members:
        if cid in (UNKNOWN_DR, UNKNOWN_CHOOSE, UNKNOWN_NO):
            r.register_pool_card(PoolCard(cid, CardType.MINION, 2,
                CardMetadata(True, (CardClass.NEUTRAL,) if cid != UNKNOWN_CHOOSE else (CardClass.PALADIN,),
                    Rarity.COMMON, tribes=(), factions=(), subtypes=()), battlecry=False,
                deathrattle=cid == UNKNOWN_DR, choose_one=cid == UNKNOWN_CHOOSE))
    if pool:
        r.register_pool(PoolDefinition(POOL_ID, 'k122-complete-explicit-fixture', CTX.target_id, CTX.mode,
            tuple(PoolMember(cid) for cid in members), complete=True))
    if mode:
        r.register_behavior(P + 'fail', lambda c: (_ for _ in ()).throw(ResolutionError('K122 deliberate delivery failure')))
        r.register_behavior(P + 'watch', lambda c: (InvokeBehavior(P + 'fail', c.source_id, 1),)
            if mode == 'fail' else (AddToHand(1, YETI, c.source_id),))
        r.register_trigger_condition(P + 'eligible', lambda c: c.event.source_id is not None and
            c.state.entities[c.event.source_id].card_id in ROOTS)
        r.register_card(CardDefinition(P + 'watch', 'Actual discovery observer', CardType.MINION, health=8,
            metadata=META, limited_triggers=(LimitedTriggerSpec('card_created' if mode == 'fail' else 'choice_selected',
                P + 'watch', condition_id=P + 'eligible'),)))
    r.validate()
    return r


class NativeAbilityDiscoveryTests(unittest.TestCase):
    def game(self, cid=GARDENING, *, members=MEMBERS, hero='HERO_08', mode=None, pool=True, context=CTX, seed=122, hand=None):
        self.config = (members, mode, pool)
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=(cid,) if hand is None else hand, board=(P + 'watch',) if mode else (),
                deck=(YETI,) * 6, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_08', deck=(YETI,) * 6),
        ), seed=seed, generation_context=context), registry(*self.config))

    def play(self, g, cid=GARDENING):
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
        fresh = registry.__wrapped__(*self.config)
        other = Game.from_snapshot(saved, fresh)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry.__wrapped__(*self.config)).snapshot(), saved)
        for seat in (1, 2):
            wire = json.dumps(g.for_player(seat).observe()) + json.dumps(g.for_player(seat).legal_actions()) + json.dumps(g.player_events(seat))
            for key in ('resolution_frame', 'rng_state', 'PoolQuery', 'gift_pool', 'offered_gifts', 'pool_basis'):
                self.assertNotIn('"' + key + '"', wire)
            self.assertNotIn('entities', g.for_player(seat).observe()['observation'])
        return other

    def test_complete_original_faces_metadata_and_no_native_ability_inferred_from_text(self):
        d = load_batch()
        r = registry()
        self.assertEqual(len(d['cards'] + d['existing_gift_sources']), 12)
        self.assertEqual(len(d['official_observations']['observations']), 4)
        norm = lambda s: re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]', '', s)
        for row in d['cards']:
            raw = row['record']
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            for o in (x for x in d['official_observations']['observations'] if x['card_id'] == raw['id']):
                cn = o['locale'] == 'zh_CN'
                self.assertEqual(o['face']['name'], raw['name' if cn else 'name_en'])
                self.assertEqual(norm(o['face']['text']), norm(raw['text' if cn else 'text_en']))
                self.assertEqual(o['face']['manaCost'], raw['cost'])
            self.assertFalse(r.pool_card(raw['id']).deathrattle)
            self.assertFalse(r.pool_card(raw['id']).choose_one)
        self.assertEqual(r.card(GARDENING).metadata.classes, (CardClass.WARLOCK,))
        self.assertEqual(r.card(SYMBIOSIS).metadata.classes, (CardClass.DRUID,))
        self.assertIsNone(r.card(GARDENING).spell_school)
        self.assertEqual(r.card(SYMBIOSIS).spell_school, SpellSchool.NATURE)

    def test_gardening_filters_printed_deathrattle_minions_and_uses_one_paid_discovery(self):
        g = self.game()
        source = self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {DR, DR2})
        spec = g._frame.options[0].effects[0].batch.spec
        self.assertTrue(spec.query.deathrattle)
        self.assertEqual(len(spec.gift_pool.members), 10)
        self.assertEqual(g.state.players[1].mana, 38)
        self.portable(g)
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.portable(g)

    def test_gardening_current_hero_class_controls_eligibility_not_warlock_printing(self):
        members = ('CORE_ICC_021', 'EDR_485', DR)
        g = self.game(members=members, hero='HERO_05')
        expected = {cid for cid in members if CardClass.NEUTRAL in g.registry.card(cid).metadata.classes or
            CardClass.HUNTER in g.registry.card(cid).metadata.classes}
        self.assertEqual(len(expected), 2)
        self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, expected)

    def test_symbiosis_accepts_native_choose_one_spell_minion_weapon_of_other_classes(self):
        members = (CHOOSE_SPELL, CHOOSE_MINION, CHOOSE_WEAPON)
        g = self.game(SYMBIOSIS, members=members, hero='HERO_08')
        source = self.play(g, SYMBIOSIS)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, set(members))
        self.assertEqual({g.registry.card(o.card_id).kind for o in g.state.pending_choice.options},
            {CardType.SPELL, CardType.MINION, CardType.WEAPON})
        self.assertEqual(g.state.players[1].mana, 39)
        self.portable(g)
        self.choose(g)
        self.assertEqual(len(self.created(g, source)), 1)
        self.assertIsNotNone(g.registry.card(self.created(g, source)[0].card_id).choose_one)
        self.portable(g)

    def test_symbiosis_excludes_current_class_neutral_and_non_choose_one(self):
        g = self.game(SYMBIOSIS, hero='HERO_06')
        self.play(g, SYMBIOSIS)
        offered = {o.card_id for o in g.state.pending_choice.options}
        self.assertEqual(offered, {CHOOSE_MINION, CHOOSE_WEAPON, MAGE_CHOOSE})
        self.assertFalse(offered.intersection((CHOOSE_SPELL, YETI, DR, WARLOCK)))

    def test_two_real_waiting_states_restore_and_finish_without_resampling_or_repayment(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game(cid)
                source = self.play(g, cid)
                other = self.portable(g)
                saved_rng = deepcopy(g.snapshot()['rng_state'])
                with patch.object(random.Random, 'randrange', side_effect=AssertionError('Resampled existing offer')):
                    self.choose(g)
                    self.choose(other)
                self.assertEqual(g.snapshot(), other.snapshot())
                self.assertEqual(g.snapshot()['rng_state'], saved_rng)
                self.assertEqual(len(self.created(g, source)), 1)

    def test_delivery_failure_restores_committed_original_offer_rng_and_payment(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game(cid, mode='fail')
                self.play(g, cid)
                saved = g.snapshot()
                with self.assertRaisesRegex(ResolutionError, 'K122 deliberate'):
                    self.choose(g)
                self.assertEqual(g.snapshot(), saved)

    def test_hand_overflow_burns_the_selected_complete_result_for_both_sources(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game(cid, mode='fill', hand=(cid,) + (YETI,) * 9)
                source = self.play(g, cid)
                index = next(i for i, o in enumerate(g._frame.options) if
                    cid != GARDENING or o.effects[0].selection.gift.destination == 'hand')
                self.choose(g, index)
                self.assertEqual(len(g.state.players[1].hand), 10)
                result, = self.created(g, source)
                self.assertNotIn(result.id, g.state.players[1].hand)
                self.assertTrue(any(e.kind == 'card_burned' and e.target_id == result.id for e in g.events))

    def test_complete_eligible_unknowns_fail_before_any_candidate_or_gift_rng(self):
        for cid, unknown in ((GARDENING, UNKNOWN_DR), (SYMBIOSIS, UNKNOWN_CHOOSE)):
            with self.subTest(cid=cid):
                g = self.game(cid, members=(DR, CHOOSE_MINION, unknown))
                saved = g.snapshot()
                with patch.object(random.Random, 'randrange', side_effect=AssertionError('RNG before validation')) as call:
                    with self.assertRaises(ResolutionError):
                        self.play(g, cid)
                    call.assert_not_called()
                self.assertEqual(g.snapshot(), saved)

    def test_known_negative_independent_unknown_metadata_is_excluded_normally(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g = self.game(cid, members=(DR, CHOOSE_MINION, UNKNOWN_NO))
                self.play(g, cid)
                self.assertEqual({o.card_id for o in g.state.pending_choice.options},
                    {DR} if cid == GARDENING else {CHOOSE_MINION})

    def test_empty_inventory_is_rng_neutral_but_keeps_original_spell_and_payment(self):
        for cid, mana in ((GARDENING, 38), (SYMBIOSIS, 39)):
            with self.subTest(cid=cid):
                g = self.game(cid, members=(YETI,))
                before_rng = deepcopy(g.snapshot()['rng_state'])
                self.play(g, cid)
                self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.players[1].mana, mana)
                self.assertEqual(g.snapshot()['rng_state'], before_rng)

    def test_missing_host_inventory_or_context_rolls_back_both_original_spells(self):
        for cid in ROOTS:
            for config in ({'pool': False}, {'context': None}):
                with self.subTest(cid=cid, config=config):
                    g = self.game(cid, **config)
                    saved = g.snapshot()
                    with self.assertRaises(ResolutionError):
                        self.play(g, cid)
                    self.assertEqual(g.snapshot(), saved)

    def test_saved_new_query_facts_reject_unknown_fields_bad_bools_and_old_schema(self):
        g = self.game()
        self.play(g)
        saved = g.snapshot()
        old = deepcopy(saved)
        old['schema_version'] = SNAPSHOT_SCHEMA_VERSION - 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(old, registry(*self.config))
        def queries(node):
            if isinstance(node, dict):
                if node.get('type', '').endswith('.PoolQuery'):
                    yield node['fields']
                for value in node.values():
                    yield from queries(value)
            elif isinstance(node, list):
                for value in node:
                    yield from queries(value)
        self.assertTrue(list(queries(saved)))
        for field, value in (('deathrattle', 1), ('choose_one', 'yes'), ('invented_ability', True)):
            bad = deepcopy(saved)
            for q in queries(bad):
                q[field] = value
            bad['state_hash'] = canonical_hash({k: v for k, v in bad.items() if k not in
                ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(bad, registry(*self.config))


class PrintedAbilityPoolFactsTests(unittest.TestCase):
    def test_all_1188_complete_source_rows_have_independent_native_boolean_facts(self):
        rows = candidate_pool_rows()
        raw = {x['record']['id']: x['record'] for x in catalog_batch()['cards']}
        self.assertEqual(len(rows), 1188)
        for row in rows:
            self.assertIs(type(row.deathrattle), bool)
            self.assertIs(type(row.choose_one), bool)
            self.assertEqual(row.deathrattle, raw[row.card_id]['tags'].get('DEATHRATTLE', 0) == 1)
            self.assertEqual(row.choose_one, raw[row.card_id]['tags'].get('CHOOSE_ONE', 0) == 1)

    def test_complete_catalog_rejects_bad_native_flags_instead_of_coercing_them(self):
        data = catalog_batch()
        for tag in ('DEATHRATTLE', 'CHOOSE_ONE'):
            for value in (True, -1, 2, '1'):
                with self.subTest(tag=tag, value=value):
                    bad = deepcopy(data)
                    bad['cards'][0]['record']['tags'][tag] = value
                    with patch('hs_sim.cards.candidate_generation_catalog.load_batch', return_value=bad):
                        with self.assertRaises(TargetValidationError):
                            candidate_pool_rows()

    def test_finite_public_fields_require_real_bools(self):
        row = PoolCard.from_definition(registry().card(DR))
        for field in ('deathrattle', 'choose_one'):
            for value in (0, 1, (), 'true'):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError):
                        replace(row, **{field: value})
                    with self.assertRaises(ValueError):
                        PoolQuery(**{field: value})

    def test_unknown_positive_or_negative_fact_is_not_assumed_false(self):
        row = PoolCard.from_definition(registry().card(DR))
        args = dict(card_id=row.card_id, kind=row.kind, cost=row.cost, meta=row.metadata,
            spell_school=row.spell_school, keywords=row.keywords)
        for field in ('deathrattle', 'choose_one'):
            for wanted in (True, False):
                with self.subTest(field=field, wanted=wanted):
                    with self.assertRaisesRegex(ValueError, 'Unknown candidate printed'):
                        matches_metadata(PoolQuery(**{field: wanted}), **args)
                    for fact in (True, False):
                        self.assertEqual(matches_metadata(PoolQuery(**{field: wanted}), **args,
                            **{'printed_' + field: fact}), wanted == fact)

    def test_known_other_nonmatch_can_exclude_unknown_fact_without_executable_lookup(self):
        row = PoolCard.from_definition(registry().card(DR))
        args = dict(card_id=row.card_id, kind=row.kind, cost=row.cost, meta=row.metadata,
            spell_school=row.spell_school, keywords=row.keywords)
        self.assertFalse(matches_metadata(PoolQuery(kinds=(CardType.SPELL,), deathrattle=True), **args))
        self.assertFalse(matches_metadata(PoolQuery(deathrattle=True, choose_one=True), **args,
            printed_deathrattle=None, printed_choose_one=False))
        self.assertFalse(matches_metadata(PoolQuery(deathrattle=True, choose_one=True), **args,
            printed_deathrattle=False, printed_choose_one=None))

    def test_generation_aliases_with_conflicting_native_facts_are_rejected(self):
        for field in ('deathrattle', 'choose_one'):
            with self.subTest(field=field):
                r = Registry('k122-alias-conflict')
                row = PoolCard.from_definition(registry().card(DR), identity='one-face')
                r.register_pool_card(row)
                r.register_pool_card(replace(row, card_id=P + 'alias', **{field: not getattr(row, field)}))
                r.register_pool(PoolDefinition('test', 'v1', CTX.target_id, CTX.mode,
                    (PoolMember(row.card_id), PoolMember(P + 'alias'))))
                with self.assertRaisesRegex(ValueError, 'Conflicting generation aliases'):
                    r.validate()

    def test_known_definition_cannot_conflict_with_independent_native_flag(self):
        for field in ('deathrattle', 'choose_one'):
            with self.subTest(field=field):
                r = Registry('k122-fact-conflict')
                card = registry().card(DR)
                # This narrow registry tests metadata validation without unrelated behavior registration.
                card = replace(card, deathrattle=None)
                r.register_card(card)
                r.register_pool_card(replace(PoolCard.from_definition(card), **{field: True}))
                with self.assertRaisesRegex(ValueError, 'Pool metadata differs'):
                    r.validate()


if __name__ == '__main__':
    unittest.main()
