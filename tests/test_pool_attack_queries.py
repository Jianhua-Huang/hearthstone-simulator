"""Printed minion attack is an independent, nullable generation inventory fact."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.cards import candidate_generation_catalog as catalog
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Rarity,Registry
from hs_sim.engine.card_conditions import UnknownCardFactError
from hs_sim.engine.pool_summons import query_from_dict
from hs_sim.engine.pools import (GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,
                                 matches_metadata,resolve_candidates)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError,canonical_digest

META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('beast',))
CONTEXT=GenerationContext('k169-public','experimental')


class PoolAttackQueryTests(unittest.TestCase):
    def matches(self,query,attack=None,*,kind=CardType.MINION,meta=META,cost=2):
        return matches_metadata(query,card_id='candidate',kind=kind,cost=cost,meta=meta,
                                spell_school=None,keywords=(),printed_attack=attack)

    def test_parity_and_scalar_declarations_reject_boolean_negative_or_nonminion_facts(self):
        for value in (True,0,1,'ODD','',[],{}):
            with self.subTest(value=value),self.assertRaises(ValueError):PoolQuery(attack_parity=value)
        for value in (True,-1,1.0,'3'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                PoolCard('bad',CardType.MINION,2,META,attack=value)
        with self.assertRaises(ValueError):PoolCard('spell',CardType.SPELL,2,META,attack=0)
        self.assertIsNone(PoolCard('unknown',CardType.MINION,2,META).attack)

    def test_known_zero_is_even_and_arbitrary_nonnegative_printed_attacks_have_exact_parity(self):
        for attack in (0,1,2,3,99,100):
            for parity in ('odd','even'):
                self.assertEqual(self.matches(PoolQuery(attack_parity=parity),attack),
                                 attack%2==(1 if parity=='odd'else 0))
        self.assertFalse(self.matches(PoolQuery(attack_parity='odd'),None,kind=CardType.SPELL))
        self.assertTrue(self.matches(PoolQuery(),None))

    def test_unknown_attack_remains_unknown_and_other_known_nonmatches_can_exclude(self):
        query=PoolQuery(attack_parity='odd')
        with self.assertRaises(UnknownCardFactError):self.matches(query)
        self.assertFalse(self.matches(PoolQuery(min_cost=3,attack_parity='odd')))
        self.assertFalse(self.matches(PoolQuery(tribes_any=('dragon',),attack_parity='odd')))
        with self.assertRaises(UnknownCardFactError):
            self.matches(PoolQuery(tribes_any=('beast',),attack_parity='odd'),meta=replace(META,tribes=None))

    def test_flat_alternatives_share_original_attack_and_keep_common_conjunctions(self):
        clauses=(PoolQuery(attack_parity='odd'),PoolQuery(min_cost=4))
        self.assertTrue(self.matches(PoolQuery(any_of=clauses),3))
        self.assertFalse(self.matches(PoolQuery(any_of=clauses),2))
        with self.assertRaises(UnknownCardFactError):self.matches(PoolQuery(any_of=clauses))
        self.assertTrue(self.matches(PoolQuery(any_of=(clauses[0],PoolQuery(max_cost=2)))))
        self.assertFalse(self.matches(PoolQuery(min_cost=3,any_of=clauses),3))

    def test_shared_json_query_reader_preserves_typed_scalar_and_rejects_missing_or_invalid_fields(self):
        query=PoolQuery(attack_parity='odd',any_of=(PoolQuery(max_cost=3),PoolQuery(attack_parity='even')))
        saved=json.loads(json.dumps(asdict(query)));self.assertEqual(query_from_dict(saved),query)
        for value in (True,1,[],{},'unknown'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                query_from_dict(dict(saved,attack_parity=value))
        del saved['attack_parity']
        with self.assertRaises(ValueError):query_from_dict(saved)

    def test_inventory_unknown_does_not_borrow_an_executable_definitions_attack(self):
        r=Registry('k169-independent')
        card=CardDefinition('a','a',CardType.MINION,cost=2,attack=3,health=2,metadata=META)
        r.register_card(card);r.register_pool_card(replace(PoolCard.from_definition(card),attack=None))
        r.register_pool(PoolDefinition('p','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('a'),)))
        r.validate()
        with self.assertRaises(UnknownCardFactError):resolve_candidates(r,CONTEXT,'p',PoolQuery(attack_parity='odd'))
        self.assertEqual(tuple(x.card_id for x in resolve_candidates(r,CONTEXT,'p',PoolQuery())),('a',))

    def test_known_attack_disagreement_and_conflicting_generation_aliases_are_rejected(self):
        card=CardDefinition('a','a',CardType.MINION,cost=2,attack=3,health=2,metadata=META)
        r=Registry('k169-conflict');r.register_card(card)
        r.register_pool_card(replace(PoolCard.from_definition(card),attack=2))
        with self.assertRaisesRegex(ValueError,'Pool metadata differs'):r.validate()
        r=Registry('k169-alias')
        for cid,attack in (('a',1),('b',3)):
            r.register_pool_card(PoolCard(cid,CardType.MINION,2,META,identity='same',attack=attack))
        r.register_pool(PoolDefinition('p','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('a'),PoolMember('b'))))
        with self.assertRaisesRegex(ValueError,'Conflicting generation aliases'):r.validate()

    def test_eligible_unimplemented_odd_candidate_is_never_removed_from_the_inventory(self):
        r=Registry('k169-missing')
        for cid,attack in (('even',2),('odd',3)):
            r.register_pool_card(PoolCard(cid,CardType.MINION,2,META,attack=attack))
        r.register_pool(PoolDefinition('p','v1',CONTEXT.target_id,CONTEXT.mode,(PoolMember('even'),PoolMember('odd'))))
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(r,CONTEXT,'p',PoolQuery(attack_parity='odd'))
        self.assertEqual(resolve_candidates(r,CONTEXT,'p',PoolQuery(attack_parity='odd',min_cost=3)),())

    def test_all_729_candidate_minion_attacks_are_independent_and_17_omitted_zeros_are_attested(self):
        rows=catalog.candidate_pool_rows();raw={x['record']['id']:x['record']for x in catalog.load_batch()['cards']}
        zero=catalog.reviewed_zero_attacks();self.assertEqual(len(zero),17)
        minions=[x for x in rows if x.kind==CardType.MINION];self.assertEqual(len(minions),729)
        for row in rows:
            if row.kind==CardType.MINION:
                self.assertEqual(row.attack,raw[row.card_id]['attack']if raw[row.card_id]['attack']is not None else zero[row.card_id]['reviewed_attack'])
            else:self.assertIsNone(row.attack)

    def test_rehashed_zero_evidence_cannot_admit_wrong_types_duplicate_locale_or_explicit_tag(self):
        original=json.loads(catalog.ATTACK_PATH.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory()as directory:
            path=Path(directory)/'attack.json'
            for change in ('boolean','locale','explicit'):
                data=deepcopy(original)
                if change=='boolean':data['official_observations'][0]['face']['attack']=False
                elif change=='locale':data['official_observations'][1]['locale']='zh_CN'
                else:
                    item=data['cards'][0];item['record']['tags']['ATK']=0;item['record_sha256']=canonical_digest(item['record'])
                path.write_text(json.dumps(data),encoding='utf-8')
                with self.subTest(change=change),patch.object(catalog,'ATTACK_PATH',path),patch.object(catalog,'ATTACK_HASH',canonical_digest(data)),self.assertRaises(TargetValidationError):catalog.reviewed_zero_attacks()


if __name__=='__main__':unittest.main()
