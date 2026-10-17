"""Flat disjunction is pure eligibility, with explicit unknown structural facts."""
from dataclasses import asdict, replace
from itertools import permutations
import json
import random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.native_smoke_discovery_cards import CLAUSES
from hs_sim.engine import CardClass, CardMetadata, CardType, Keyword, Rarity
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.model import CardAbilityCondition
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery,
    matches_metadata, resolve_candidates, sample_candidates)
from hs_sim.engine.registry import Registry, UnsupportedDefinitionError

CTX = GenerationContext('k124-public', 'experimental')
META = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=(), factions=(), subtypes=())


class PoolQueryAlternativesTests(unittest.TestCase):
    def matches(self, query, *, keywords=(), printed=False, current=False, meta=META, **extra):
        args = dict(card_id='k124.candidate', kind=CardType.MINION, cost=3, meta=meta, spell_school=None,
            keywords=keywords, current_class=CardClass.ROGUE, printed_battlecry=printed, current_battlecry=current,
            printed_deathrattle=False, printed_choose_one=False)
        args.update(extra)
        return matches_metadata(query, **args)

    def test_flat_declaration_rejects_mutability_duplicates_nested_queries_and_branch_exclusions(self):
        a, b, c = CLAUSES
        for values in (None, [a, b], (a,), (a, a), (a, object()), (a, PoolQuery(any_of=(b, c))),
                       (a, PoolQuery(exclude_source=True)), (a, PoolQuery(exclude_card_ids=('x',)))):
            with self.subTest(values=values), self.assertRaises(ValueError):
                PoolQuery(any_of=values)
        self.assertEqual(PoolQuery(any_of=(a, b, c)).any_of, CLAUSES)

    def test_invalid_later_clause_is_never_hidden_by_a_known_matching_first_clause(self):
        bad = PoolQuery()
        object.__setattr__(bad, 'deathrattle', 1)
        with self.assertRaises(ValueError):
            PoolQuery(any_of=(CLAUSES[0], bad))
        cyclic = PoolQuery()
        object.__setattr__(cyclic, 'any_of', (cyclic, CLAUSES[0]))
        with self.assertRaises(ValueError):
            cyclic.__post_init__()

    def test_all_clause_orders_have_same_true_false_and_unknown_results(self):
        for clauses in permutations(CLAUSES):
            query = PoolQuery(any_of=clauses)
            for keywords in ((), (Keyword.COMBO,), (Keyword.STEALTH,), (Keyword.COMBO, Keyword.STEALTH)):
                for printed in (True, False, None):
                    with self.subTest(clauses=clauses, keywords=keywords, printed=printed):
                        if not keywords and printed is None:
                            with self.assertRaises(UnknownCardFactError):
                                self.matches(query, keywords=keywords, printed=printed)
                        else:
                            self.assertEqual(self.matches(query, keywords=keywords, printed=printed), bool(keywords) or printed is True)

    def test_common_type_cost_class_and_collectibility_remain_conjunctive(self):
        query = PoolQuery(kinds=(CardType.MINION,), min_cost=2, max_cost=4, collectible=True,
            class_mode='current', any_of=CLAUSES)
        self.assertTrue(self.matches(query, keywords=(Keyword.STEALTH,)))
        for change in ({'kind': CardType.SPELL}, {'cost': 1}, {'cost': 5},
                       {'meta': replace(META, collectible=False)}, {'meta': replace(META, classes=(CardClass.MAGE,))}):
            with self.subTest(change=change):
                self.assertFalse(self.matches(query, keywords=(Keyword.STEALTH,), **change))

    def test_common_unknown_cannot_be_overridden_by_true_but_false_alternatives_can_exclude(self):
        query = PoolQuery(collectible=True, any_of=CLAUSES)
        with self.assertRaisesRegex(UnknownCardFactError, 'metadata'):
            self.matches(query, meta=None, keywords=(Keyword.STEALTH,))
        self.assertFalse(self.matches(query, meta=None, printed=False))
        query = PoolQuery(rarities=(Rarity.LEGENDARY,), any_of=CLAUSES)
        with self.assertRaisesRegex(UnknownCardFactError, 'rarity'):
            self.matches(query, meta=replace(META, rarity=None), printed=True)
        self.assertFalse(self.matches(query, meta=replace(META, rarity=None), printed=False))

    def test_each_flat_clause_is_a_conjunction_and_known_nonmatch_beats_missing_fact(self):
        query = PoolQuery(any_of=(
            PoolQuery(ability=CardAbilityCondition(basis='printed'), keywords_all=(Keyword.COMBO,)),
            PoolQuery(tribes_any=('beast',), keywords_all=(Keyword.STEALTH,)),
        ))
        self.assertFalse(self.matches(query, printed=None, meta=replace(META, tribes=None)))
        with self.assertRaises(UnknownCardFactError):
            self.matches(query, printed=None, keywords=(Keyword.COMBO,), meta=replace(META, tribes=None))

    def test_printed_and_current_battlecry_alternatives_keep_their_original_basis(self):
        current = PoolQuery(any_of=(PoolQuery(ability=CardAbilityCondition()), CLAUSES[0]))
        printed = PoolQuery(any_of=(PoolQuery(ability=CardAbilityCondition(basis='printed')), CLAUSES[0]))
        self.assertTrue(self.matches(printed, printed=True, current=False))
        self.assertFalse(self.matches(current, printed=True, current=False))
        self.assertFalse(self.matches(printed, printed=False, current=True))
        self.assertTrue(self.matches(current, printed=False, current=True))

    def test_unknown_fact_is_not_negative_even_without_a_disjunction(self):
        with self.assertRaises(UnknownCardFactError):
            self.matches(PoolQuery(ability=CardAbilityCondition(basis='printed')), printed=None)
        with self.assertRaises(UnknownCardFactError):
            self.matches(PoolQuery(deathrattle=True), printed_deathrattle=None)
        self.assertFalse(self.matches(PoolQuery(deathrattle=True, keywords_all=(Keyword.COMBO,)), printed_deathrattle=None))

    def test_overlapping_real_traits_are_one_candidate_with_original_weight(self):
        r = build_registry()
        members = (PoolMember('TLC_522', 5), PoolMember('CORE_BOT_576', 2), PoolMember('CORE_EX1_010', 3),
                   PoolMember('CORE_CS2_182', 7))
        r.register_pool(PoolDefinition('k124', 'v1', CTX.target_id, CTX.mode, members))
        rows = resolve_candidates(r, CTX, 'k124', PoolQuery(any_of=CLAUSES))
        self.assertEqual({m.card_id: m.weight for m in rows}, {'TLC_522': 5, 'CORE_BOT_576': 2, 'CORE_EX1_010': 3})
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(m.weight for m in rows), 10)
        rng = random.Random(124)
        expected = random.Random(124)
        ticket = expected.randrange(10)
        for member in rows:
            ticket -= member.weight
            if ticket < 0:
                selected = member.card_id
                break
        self.assertEqual(sample_candidates(rng, rows, 1, replacement=True), (selected,))
        self.assertEqual(rng.getstate(), expected.getstate())

    def test_aliases_still_deduplicate_after_complete_member_validation(self):
        r = build_registry()
        base = r.card('TLC_522')
        # Use two explicit equivalent aliases without changing the existing printed row.
        for cid in ('k124.a', 'k124.b'):
            card = replace(base, id=cid)
            r.register_card(card)
            r.register_pool_card(PoolCard.from_definition(card, identity='k124.family'))
        r.register_pool(PoolDefinition('k124.aliases', 'v1', CTX.target_id, CTX.mode,
            (PoolMember('k124.a', 4), PoolMember('k124.b', 4))))
        r.validate()
        rows = resolve_candidates(r, CTX, 'k124.aliases', PoolQuery(any_of=CLAUSES))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].weight, 4)

    def test_unknown_eligible_implementation_and_unknown_fact_are_distinct_explicit_errors(self):
        for keywords, fact, error in (((), True, UnsupportedDefinitionError),
                ((Keyword.STEALTH,), None, UnsupportedDefinitionError), ((), None, UnknownCardFactError)):
            with self.subTest(keywords=keywords, fact=fact):
                r = Registry('k124.unknown')
                r.register_pool_card(PoolCard('unknown', CardType.MINION, 2, META, keywords=keywords, battlecry=fact))
                r.register_pool(PoolDefinition('k124', 'v1', CTX.target_id, CTX.mode, (PoolMember('unknown'),)))
                with self.assertRaises(error):
                    resolve_candidates(r, CTX, 'k124', PoolQuery(any_of=CLAUSES))
                self.assertFalse(r.cards)

    def test_class_referenced_only_inside_alternative_still_requires_known_hero_context(self):
        r = Registry('k124.class')
        query = PoolQuery(any_of=(PoolQuery(class_mode='current'), PoolQuery(keywords_all=(Keyword.STEALTH,))))
        r.register_pool(PoolDefinition('empty', 'v1', CTX.target_id, CTX.mode, ()))
        with self.assertRaisesRegex(ValueError, 'current playable hero class'):
            resolve_candidates(r, CTX, 'empty', query)
        self.assertEqual(resolve_candidates(r, CTX, 'empty', query, current_class=CardClass.ROGUE), ())

    def test_closed_record_json_query_decoder_restores_empty_and_typed_flat_alternatives(self):
        from hs_sim.engine.pool_summons import query_from_dict
        for query in (PoolQuery(), PoolQuery(kinds=(CardType.MINION,), collectible=True, any_of=CLAUSES)):
            with self.subTest(query=query):
                wire = json.loads(json.dumps(asdict(query)))
                restored = query_from_dict(wire)
                self.assertEqual(restored, query)
                self.assertIs(type(restored.any_of), tuple)
                for clause in restored.any_of:
                    self.assertIs(type(clause), PoolQuery)

    def test_closed_record_decoder_rejects_missing_nested_mutable_or_excluding_alternative_shapes(self):
        from copy import deepcopy
        from hs_sim.engine.pool_summons import query_from_dict
        wire = json.loads(json.dumps(asdict(PoolQuery(any_of=CLAUSES))))
        bads = []
        for value in (None, {}, [wire['any_of'][0]], [wire['any_of'][0]] * 2):
            bad = deepcopy(wire)
            bad['any_of'] = value
            bads.append(bad)
        bad = deepcopy(wire)
        del bad['any_of']
        bads.append(bad)
        for field, value in (('any_of', [wire]), ('exclude_source', True), ('undeclared', True)):
            bad = deepcopy(wire)
            bad['any_of'][0][field] = value
            bads.append(bad)
        for bad in bads:
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                query_from_dict(bad)

    def test_actual_recruit_closes_and_restores_history_containing_nonempty_alternatives(self):
        from hs_sim.engine import CardDefinition, Game, PlayCard, PlayerSetup, Scenario, SummonFromZone, Zone
        from hs_sim.engine.summon_quantities import SummonCause
        from hs_sim.engine.replay import build_replay, replay
        query = PoolQuery(kinds=(CardType.MINION,), any_of=CLAUSES)
        def make():
            r = build_registry()
            r.register_behavior('k124.recruit', lambda c: (SummonFromZone(c.player_id, 1, zone=Zone.DECK,
                query=query, source_id=c.source_id, cause=SummonCause.capture(c)),))
            r.register_card(CardDefinition('k124.recruit', 'Real recruit query fixture', CardType.SPELL,
                metadata=META, on_play='k124.recruit'))
            return r
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_03', hand=('k124.recruit',),
            deck=('CORE_CS2_182', 'CORE_EX1_010')), PlayerSetup('HERO_08'))), make())
        source = g.state.players[1].hand[0]
        original = g.state.players[1].deck[1]
        g.apply(PlayCard(1, source))
        self.assertEqual(g.state.players[1].board, [original])
        self.assertEqual(len(g.state.players[1].deck), 1)
        self.assertEqual(g.state.recruit_summon_history[0].spec.query, query)
        self.assertEqual(g.state.recruit_summon_history[0].status, 'completed')
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, make()).snapshot(), saved)
        self.assertEqual(replay(build_replay(g), make()).snapshot(), saved)


if __name__ == '__main__':
    unittest.main()
