"""Source-bound candidate construction and complete ordinary generation."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hs_sim.candidate_format import (POOL_ID,SOURCE_PATH,
    build_cn37_candidate_format,load_source_facts)
from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass,CardDefinition,CardType,DeckSpec,Game,Keyword,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,expand_fabled_cards)
from hs_sim.engine.construction import validate_deck
from hs_sim.engine.pools import GenerationContext,PoolQuery,resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import TargetValidationError

BRIGHT='CORE_EX1_189';STONE='Core_UNG_072';ROOT='TIME_005'


def fillers(fmt,count):
    cards=[];used=Counter()
    for cid in fmt.root_card_ids:
        c=fmt.registry.card(cid)
        if(c.kind!=CardType.MINION or c.metadata.classes!=(CardClass.NEUTRAL,)or c.metadata.rarity==Rarity.LEGENDARY):continue
        if c!=CardDefinition(c.id,c.name,c.kind,cost=c.cost,attack=c.attack,health=c.health,
                keywords=c.keywords,metadata=c.metadata):continue
        identity=c.metadata.deck_identity or cid
        limit=c.metadata.max_copies or 2
        while used[identity]<limit and len(cards)<count:cards.append(cid);used[identity]+=1
        if len(cards)==count:return tuple(cards)
    raise AssertionError('The fixed source lacks enough plain neutral filler cards')


def deck(fmt,*,hero='HERO_08',cls=CardClass.MAGE,cards=None):
    return DeckSpec(hero,fmt.registry.card(hero).initial_hero_power,cls,
        fillers(fmt,30)if cards is None else cards)


class CandidateFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fmt=build_cn37_candidate_format();cls.restore=build_cn37_candidate_format()

    def portable(self,g):
        saved=g.snapshot();other=self.restore
        self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(Game.from_snapshot(saved,other.registry).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),other.registry).snapshot(),saved)

    def test_full_source_domain_policy_and_generation_share_fixed_target(self):
        f=self.fmt;pool=f.registry.pool(POOL_ID,f.context)
        self.assertEqual(len(f.root_card_ids),1188)
        self.assertEqual(tuple(m.card_id for m in pool.members),f.root_card_ids)
        self.assertEqual((f.policy.target_id,pool.target_id),(f.target_id,f.target_id))
        self.assertEqual((f.policy.mode,f.context.mode,pool.mode),('experimental',)*3)
        self.assertFalse(f.formal_pool_complete);self.assertFalse(f.policy.pool_complete)
        self.assertEqual(f.frozen_client_version,'37.0.0.255026')
        self.assertEqual(f.effective_until,'2026-10-21T01:00:00+08:00')
        self.assertEqual({m.weight for m in pool.members},{1})

    def test_real_thirty_card_opening_retains_original_decks_and_replays(self):
        f=self.fmt;decks=(deck(f),deck(f));g=f.new_game(decks,seed=321,first_player=1)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        while g.state.pending_choice is not None:
            q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
        context=g.snapshot()['generation_context']
        self.assertEqual(context['target_id'],f.target_id)
        self.assertEqual(context['starting_decks'],[list(d.cards)for d in decks])
        self.assertIn('GAME_005',[g.state.entities[i].card_id for i in g.state.players[2].hand])
        self.portable(g)

    def test_actual_brightwing_generates_from_complete_bound_domain(self):
        f=self.fmt;g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(BRIGHT,),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=321,generation_context=f.context),f.registry)
        source=g.state.players[1].hand[0];g.apply(PlayCard(1,source))
        self.assertEqual(len(g.state.players[1].hand),1)
        card=g.state.entities[g.state.players[1].hand[0]]
        self.assertIn(card.card_id,f.root_card_ids);self.assertEqual(card.kind,CardType.MINION)
        self.assertEqual(f.registry.card(card.card_id).metadata.rarity,Rarity.LEGENDARY)
        self.assertNotIn(card.card_id,f.registry.fabled_generation_exclusions);self.portable(g)

    def test_actual_stonehill_discovery_wait_restores_complete_source_domain(self):
        f=self.fmt;g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(STONE,),mana=10,max_mana=10),
            PlayerSetup('HERO_08')),seed=322,generation_context=f.context),f.registry)
        g.apply(PlayCard(1,g.state.players[1].hand[0]));q=g.state.pending_choice
        self.assertIsNotNone(q);self.assertEqual(len(q.options),3)
        self.assertTrue(all(o.card_id in f.root_card_ids for o in q.options))
        self.assertTrue(all(Keyword.TAUNT in f.registry.pool_card(o.card_id).keywords for o in q.options))
        self.portable(g);selected=q.options[0].card_id
        g.apply(SelectChoice(q.player_id,q.id,(q.options[0].id,)))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[selected])
        self.assertTrue(g.state.play_history[-1].completed);self.portable(g)

    def test_real_fabled_forty_card_setup_uses_conditional_companions(self):
        f=self.fmt;cards=expand_fabled_cards((ROOT,*fillers(f,30)),f.registry)
        own=deck(f,hero='HERO_07',cls=CardClass.WARLOCK,cards=cards)
        self.assertEqual(len(cards),40);self.assertTrue(validate_deck(own,f.registry,f.policy).valid)
        g=f.new_game((own,deck(f)),seed=323,first_player=1)
        self.assertEqual(g.state.players[1].original_deck,cards);self.portable(g)

    def test_orphaned_companions_and_non_candidate_roots_remain_invalid(self):
        f=self.fmt;companion=f.registry.fabled[ROOT].companion_card_ids[0]
        orphan=deck(f,hero='HERO_07',cls=CardClass.WARLOCK,cards=(companion,*fillers(f,29)))
        self.assertFalse(validate_deck(orphan,f.registry,f.policy).valid)
        outside='CORE_CS2_182';self.assertNotIn(outside,f.policy.allowed_card_ids)
        invalid=deck(f,cards=(outside,*fillers(f,29)))
        self.assertIn('format_legality',{i.code for i in validate_deck(invalid,f.registry,f.policy).issues})

    def test_formal_wild_and_unrelated_pack_domains_are_not_fabricated(self):
        f=self.fmt
        with self.assertRaises(TargetValidationError):f.require_formal()
        for mode in('standard','wild'):
            with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(f.registry,GenerationContext(f.target_id,mode),POOL_ID,PoolQuery())
        with self.assertRaises(UnsupportedDefinitionError):f.registry.pool('constructed.standard_pack',f.context)

    def test_source_binding_rejects_changed_scope_phase_and_complete_claims(self):
        original=json.loads(SOURCE_PATH.read_text(encoding='utf8'))
        for key,value in(('region','EU'),('official_patch','37.2'),('standard_pool_complete',True),
                ('hotfix_set_complete',True),('official_effective_at','2026-10-15T01:00:00+08:00')):
            bad=deepcopy(original);bad[key]=value
            with tempfile.TemporaryDirectory()as tmp:
                p=Path(tmp)/'source.json';p.write_text(json.dumps(bad),encoding='utf8')
                with patch('hs_sim.candidate_format.SOURCE_PATH',p),self.assertRaises(TargetValidationError):load_source_facts()

    def test_historical_progress_fields_do_not_change_semantic_binding(self):
        facts=load_source_facts();data=json.loads(SOURCE_PATH.read_text(encoding='utf8'))
        data['current_standard_candidate_source']['registered_candidate_root_count']=0
        data['standard_candidate_inventory']='historical-counter-not-a-source-input'
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'source.json';p.write_text(json.dumps(data),encoding='utf8')
            with patch('hs_sim.candidate_format.SOURCE_PATH',p):self.assertEqual(load_source_facts(),facts)

    def test_missing_deck_root_is_not_removed_even_when_randomly_excluded(self):
        for cid in(BRIGHT,'JAIL_500'):
            r=build_registry();r._cards.pop(cid)
            with patch('hs_sim.candidate_format.build_registry',return_value=r),self.assertRaises(UnsupportedDefinitionError):build_cn37_candidate_format()

    def test_source_catalog_mismatch_fails_before_registry_work(self):
        from hs_sim.cards.candidate_generation_catalog import load_batch
        data=load_batch();data['policy']['source_commit']='0'*40
        with (patch('hs_sim.candidate_format.load_batch',return_value=data),
                patch('hs_sim.candidate_format.build_registry',side_effect=AssertionError('Unexpected registry work')),
                self.assertRaises(TargetValidationError)):
            build_cn37_candidate_format()

    def test_default_registry_keeps_its_original_unbound_pools(self):
        ordinary=build_registry()
        self.assertFalse(any(p.id==POOL_ID for p in ordinary.pools.values()))
        self.assertNotEqual(ordinary.fingerprint(),self.fmt.registry.fingerprint())

    def test_clean_process_builder_needs_no_extraction_or_network(self):
        root=str(Path(__file__).resolve().parents[1])
        code="""import sys,json,pathlib,urllib.request
sys.path.insert(0,sys.argv[1])
original=pathlib.Path.open
def guarded(path,*args,**kwargs):
    if 'outputs' in path.parts:raise AssertionError('Extracted output required: '+str(path))
    return original(path,*args,**kwargs)
pathlib.Path.open=guarded
urllib.request.urlopen=lambda *a,**k:(_ for _ in()).throw(AssertionError('Network required'))
from hs_sim.candidate_format import build_cn37_candidate_format
f=build_cn37_candidate_format()
print(json.dumps({'roots':len(f.root_card_ids),'mode':f.context.mode}))
"""
        with tempfile.TemporaryDirectory()as tmp:
            child=subprocess.run([sys.executable,'-B','-X','utf8','-c',code,root],cwd=tmp,
                capture_output=True,text=True,encoding='utf8',timeout=40)
        self.assertEqual(child.returncode,0,child.stderr)
        self.assertEqual(json.loads(child.stdout),{'roots':1188,'mode':'experimental'})


if __name__=='__main__':unittest.main()
