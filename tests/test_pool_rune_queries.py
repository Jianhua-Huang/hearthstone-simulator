"""Printed rune eligibility is independent of school and executable coverage."""
from dataclasses import asdict, replace
import json
import unittest

from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Rarity, Registry, SpellSchool
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.model import Runes
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery,
                                 matches_metadata, resolve_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError

META = CardMetadata(True, (CardClass.DEATH_KNIGHT,), Rarity.COMMON, runes=Runes(), tribes=())
CONTEXT = GenerationContext('k168-rune-query', 'experimental')


class PoolRuneQueryTests(unittest.TestCase):
    def matches(self, query, *, meta=META, kind=CardType.MINION, cost=2, school=None):
        return matches_metadata(query, card_id='candidate', kind=kind, cost=cost,
                                meta=meta, spell_school=school, keywords=())

    def test_rune_declarations_require_unique_immutable_known_names(self):
        for value in ([], None, ('frost','frost'), ('Frost',), ('nature',), (True,), ('',)):
            with self.subTest(value=value), self.assertRaises(ValueError):PoolQuery(runes_any=value)
        self.assertEqual(PoolQuery(runes_any=('frost','blood')).runes_any, ('frost','blood'))
        self.assertEqual(PoolQuery().runes_any, ())

    def test_json_reader_preserves_runes_in_both_common_and_alternative_predicates(self):
        from hs_sim.engine.pool_summons import query_from_dict
        query=PoolQuery(runes_any=('frost',),any_of=(PoolQuery(min_cost=2),PoolQuery(runes_any=('blood',))))
        saved=json.loads(json.dumps(asdict(query)))
        self.assertEqual(query_from_dict(saved),query)
        for value in ('frost',False,{},['nature'],['frost','frost']):
            with self.subTest(value=value),self.assertRaises(ValueError):
                query_from_dict(dict(saved,runes_any=value))
        del saved['runes_any']
        with self.assertRaises(ValueError):query_from_dict(saved)

    def test_each_rune_matches_positive_printed_requirement_including_mixed_and_three(self):
        for rune in ('blood','frost','unholy'):
            query=PoolQuery(runes_any=(rune,))
            for amount in (0,1,3):
                meta=replace(META,runes=Runes(**{rune:amount}))
                self.assertEqual(self.matches(query,meta=meta), amount>0)
        mixed=replace(META,runes=Runes(blood=1,unholy=1))
        self.assertTrue(self.matches(PoolQuery(runes_any=('frost','unholy')),meta=mixed))
        self.assertFalse(self.matches(PoolQuery(runes_any=('frost',)),meta=mixed))

    def test_school_does_not_imply_a_rune_and_a_rune_does_not_require_a_school(self):
        query=PoolQuery(runes_any=('frost',))
        self.assertFalse(self.matches(query,kind=CardType.SPELL,school=SpellSchool.FROST))
        frost=replace(META,runes=Runes(frost=1))
        self.assertTrue(self.matches(query,meta=frost))
        self.assertTrue(self.matches(query,meta=frost,kind=CardType.SPELL,school=SpellSchool.SHADOW))
        self.assertFalse(self.matches(PoolQuery(runes_any=('frost',),spell_schools=(SpellSchool.FROST,)),
                                      meta=frost,kind=CardType.SPELL,school=SpellSchool.SHADOW))

    def test_missing_runes_on_death_knight_are_unknown_but_known_other_class_cannot_have_them(self):
        query=PoolQuery(runes_any=('frost',))
        for meta in (None,replace(META,runes=None)):
            with self.subTest(meta=meta),self.assertRaises(UnknownCardFactError):self.matches(query,meta=meta)
        self.assertFalse(self.matches(query,meta=replace(META,classes=(CardClass.MAGE,),runes=None)))
        self.assertTrue(self.matches(PoolQuery(),meta=replace(META,runes=None)))

    def test_known_false_and_flat_alternatives_preserve_existing_three_valued_logic(self):
        unknown=replace(META,runes=None)
        self.assertFalse(self.matches(PoolQuery(kinds=(CardType.SPELL,),runes_any=('frost',)),meta=unknown))
        self.assertFalse(self.matches(PoolQuery(min_cost=3,runes_any=('frost',)),meta=unknown))
        for clauses in ((PoolQuery(runes_any=('frost',)),PoolQuery(max_cost=2)),
                        (PoolQuery(max_cost=2),PoolQuery(runes_any=('frost',)))):
            self.assertTrue(self.matches(PoolQuery(any_of=clauses),meta=unknown))
            self.assertFalse(self.matches(PoolQuery(min_cost=3,any_of=clauses),meta=unknown))
        with self.assertRaises(UnknownCardFactError):
            self.matches(PoolQuery(any_of=(PoolQuery(runes_any=('frost',)),PoolQuery(min_cost=3))),meta=unknown)

    def test_generation_aliases_cannot_conflate_different_printed_rune_facts(self):
        r=Registry('k168-alias')
        for cid,runes in (('a',Runes(frost=1)),('b',Runes(blood=1))):
            r.register_pool_card(PoolCard(cid,CardType.MINION,2,replace(META,runes=runes),identity='same'))
        r.register_pool(PoolDefinition('p','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('a'),PoolMember('b'))))
        with self.assertRaisesRegex(ValueError,'Conflicting generation aliases'):r.validate()

    def test_eligible_unadapted_rune_cards_fail_instead_of_being_removed(self):
        r=Registry('k168-unadapted')
        for cid,runes in (('missing-frost',Runes(frost=1)),('missing-blood',Runes(blood=1))):
            r.register_pool_card(PoolCard(cid,CardType.MINION,2,replace(META,runes=runes)))
        r.register_pool(PoolDefinition('p','v1',CONTEXT.target_id,CONTEXT.mode,
                                      (PoolMember('missing-blood'),PoolMember('missing-frost'))))
        r.validate()
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(r,CONTEXT,'p',PoolQuery(runes_any=('frost',)))
        self.assertEqual(resolve_candidates(r,CONTEXT,'p',PoolQuery(runes_any=('unholy',))),())


if __name__=='__main__':unittest.main()
