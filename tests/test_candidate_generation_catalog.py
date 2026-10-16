"""Complete source candidates stay independent of executable card coverage."""
from copy import deepcopy
from dataclasses import asdict,replace
import json,random,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import (BATCH_HASH,BATCH_PATH,COST_HASH,load_batch,
    candidate_pool_rows,reviewed_zero_costs,register_candidate_pool_metadata)
from hs_sim.engine import (CardClass,CardDefinition,CardType,Game,Keyword,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,GenerationPolicy,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.registry import Registry,UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError,canonical_digest

P='k109.test.';YETI='CORE_CS2_182';CHEMIST='CORE_BOT_576';SHRINE='CATA_492';SIPHON='CATA_202';BRIGHT='CORE_EX1_189'
CTX=GenerationContext('k109-complete-candidate-experiment','experimental');POOL='constructed.cards'


def registry(wait=False):
    r=build_registry();ids=tuple(row.card_id for row in candidate_pool_rows())
    r.register_pool(PoolDefinition(POOL,'k109-complete-candidates-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in ids),complete=True))
    if wait:
        r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K109 deliberate failure')))
        r.register_behavior(P+'watch',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
        r.register_trigger_condition(P+'eligible',lambda c:c.event.player_id==1 and c.state.entities[c.event.target_id].card_id in('CATA_134','CATA_306','CATA_479','CATA_489','CATA_820'))
        r.register_card(CardDefinition(P+'watch','Actual creation observer',CardType.MINION,health=5,
            limited_triggers=(LimitedTriggerSpec('card_created',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


class CandidateGenerationCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.data=load_batch();cls.rows={x.card_id:x for x in candidate_pool_rows()};cls.r=build_registry()
    def game(self,hand=(),board=(),wait=False):
        if wait:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=109,generation_context=CTX),registry(wait))
    def play(self,g,cid,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def portable(self,g,wait=False):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(wait));self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(wait)).snapshot(),saved)
        for player in(1,2):
            public=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).legal_actions())+json.dumps(g.player_events(player))
            for field in('rng_state','resolution_frame','candidate_root_ids','pool_id','record_sha256','behavior_id'):self.assertNotIn('"'+field+'"',public)
        return other

    def test_complete_1188_source_rows_and_all_explicit_query_fields(self):
        d=self.data;self.assertEqual(canonical_digest(d),BATCH_HASH);self.assertEqual(len(d['cards']),1188);self.assertEqual(len(self.rows),1188);self.assertEqual(set(self.rows),set(d['candidate_root_ids']));self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        for row in d['cards']:
            raw=row['record'];meta=self.rows[raw['id']];self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertTrue(meta.metadata.collectible);self.assertIsNotNone(meta.metadata.tribes);self.assertIsNotNone(meta.metadata.factions);self.assertIsNotNone(meta.metadata.subtypes);self.assertIsInstance(meta.battlecry,bool)

    def test_catalog_adds_only_missing_metadata_never_executable_placeholders_or_pools(self):
        with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):before=build_registry()
        after=self.r;missing=set(self.rows)-set(before.cards)
        self.assertEqual(set(after.pool_cards)-set(before.pool_cards),missing);self.assertEqual(set(after.cards),set(before.cards));self.assertEqual({k:asdict(c)for k,c in after.cards.items()},{k:asdict(c)for k,c in before.cards.items()});self.assertEqual(dict(after.pools),dict(before.pools));self.assertTrue(all(after.pool_card(cid)==card for cid,card in before.pool_cards.items()));self.assertTrue(missing)
        for cid in missing:self.assertIn(cid,after.pool_cards)
        with self.assertRaises(UnsupportedDefinitionError):after.card(next(iter(missing)))
        self.assertFalse(any(p.mode=='standard'or p.id==POOL for p in after.pools.values()))

    def test_eight_individually_reviewed_absent_costs_are_zero(self):
        evidence=reviewed_zero_costs();self.assertEqual(len(evidence),8)
        for cid,row in evidence.items():self.assertIsNone(row['record']['cost']);self.assertNotIn('COST',row['record']['tags']);self.assertEqual(self.rows[cid].cost,0)
        self.assertEqual(self.data['cost_evidence']['sha256'],COST_HASH)

    def test_full_dual_tribe_school_and_conditional_immune_are_not_invented(self):
        self.assertEqual(self.rows['CATA_155'].metadata.tribes,('dragon','undead'));self.assertEqual(self.rows['DINO_435'].metadata.tribes,('all',));self.assertIn(Keyword.TAUNT,self.rows['JAIL_890'].keywords);self.assertNotIn(Keyword.IMMUNE,self.rows['FIR_959'].keywords);self.assertIn(Keyword.HERALD,self.rows[SHRINE].keywords)
        for cid in self.rows:
            if cid in self.r.cards:
                actual=PoolCard.from_definition(self.r.card(cid));expected=self.rows[cid];self.assertEqual(set(actual.keywords),set(expected.keywords));self.assertEqual(actual.battlecry,expected.battlecry)

    def test_complete_registry_keeps_executable_core_copy_identity(self):
        self.assertEqual(self.rows['CORE_EX1_189'].metadata.deck_identity,'CORE_EX1_189');self.assertEqual(self.r.pool_card('CORE_EX1_189').metadata.deck_identity,'EX1_189');self.assertEqual(self.rows['CORE_EX1_189'].generation_identity,self.r.pool_card('CORE_EX1_189').generation_identity)

    def test_registration_is_idempotent_and_no_default_bundle_change(self):
        r=build_registry();before=dict(r.pool_cards);register_candidate_pool_metadata(r);self.assertEqual(dict(r.pool_cards),before)
        from hs_sim.engine.representative import build_registry as default
        with patch('hs_sim.cards.candidate_generation_catalog.candidate_pool_rows',side_effect=AssertionError('Constructed-only catalog')):d=default()
        self.assertEqual(len(d.cards),311);self.assertEqual(d.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_entire_catalog_is_validated_before_any_pending_row_is_added(self):
        r=Registry('k109-atomic-test');row=list(self.rows.values())[-1];r.register_pool_card(replace(row,cost=row.cost+1));before=dict(r.pool_cards)
        with self.assertRaises(TargetValidationError):register_candidate_pool_metadata(r)
        self.assertEqual(dict(r.pool_cards),before);self.assertFalse(r.cards)

    def test_catalog_pin_and_individual_raw_shape_errors_fail_explicitly(self):
        with tempfile.TemporaryDirectory()as directory:
            p=Path(directory)/'bad.json';bad=deepcopy(self.data);bad['cards'].pop();p.write_text(json.dumps(bad),encoding='utf-8')
            with patch('hs_sim.cards.candidate_generation_catalog.BATCH_PATH',p),self.assertRaises(TargetValidationError):load_batch()
        for field,value in(('cost',None),('cost',True),('SPELL_SCHOOL',999),('TAUNT',2),('BATTLECRY',True),('collectible',False)):
            with self.subTest(field=field,value=value):
                bad=deepcopy(self.data);raw=next(x['record']for x in bad['cards']if x['record']['id']==SIPHON)
                (raw['tags']if field in('SPELL_SCHOOL','TAUNT','BATTLECRY')else raw)[field]=value
                with patch('hs_sim.cards.candidate_generation_catalog.load_batch',return_value=bad),self.assertRaises((TargetValidationError,ValueError)):candidate_pool_rows()

    def test_full_inventory_quest_bans_use_printed_metadata_before_executable_lookup(self):
        r=registry();query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,keywords_all=(Keyword.QUEST,));quests=[x for x in self.rows.values()if Keyword.QUEST in x.keywords];self.assertEqual(len(quests),12);self.assertEqual(resolve_candidates(r,CTX,POOL,query),())
        self.assertTrue(any(x.card_id not in r.cards for x in quests))
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(r,CTX,POOL,query,policy=GenerationPolicy((Keyword.QUEST,)))

    def test_full_inventory_still_rejects_unknown_legendary_before_rng_and_rolls_back(self):
        g=self.game((BRIGHT,));saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligible validation'))as calls:
            with self.assertRaises(ResolutionError):self.play(g,BRIGHT)
            calls.assert_not_called()
        self.assertEqual(g.snapshot(),saved)

    def test_real_combined_shatter_generation_queries_all_1188_candidates(self):
        g=self.game((SIPHON,));source=self.play(g,SIPHON);self.assertEqual(len(g.state.players[1].hand),1);new=g.state.entities[g.state.players[1].hand[0]];self.assertIn(new.card_id,('CATA_134','CATA_306','CATA_479','CATA_820'));self.assertNotIn(Keyword.SHATTER,new.keywords);self.assertEqual(g.state.players[1].mana,47);self.assertTrue(any(e.kind=='card_created'and e.target_id==new.id and e.source_id==source for e in g.events));self.portable(g)

    def test_actual_generated_wait_restore_clone_replay_bad_choice_rolls_back(self):
        g=self.game((SIPHON,),wait=True);self.play(g,SIPHON);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,True);saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g,True)

    def test_real_chemist_first_play_does_not_create_battlecry_or_combo_activation(self):
        g=self.game((CHEMIST,),board=(YETI,));target=g.state.players[1].board[0];self.play(g,CHEMIST);self.assertEqual(g.state.entities[target].attack,4);self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.combo_history);self.assertIsNone(g.registry.card(CHEMIST).battlecry);self.assertTrue(g.registry.card(CHEMIST).combo)

    def test_real_chemist_is_only_native_combo_with_original_target_and_history(self):
        g=self.game(('CORE_CS2_029',CHEMIST),board=(YETI,));target=g.state.players[1].board[0];self.play(g,'CORE_CS2_029',g.state.players[2].hero_id);source=self.play(g,CHEMIST,target);self.assertEqual(g.state.entities[target].attack,8);self.assertFalse(g.state.battlecry_history);self.assertEqual(len(g.state.combo_history),1);self.assertEqual(g.state.combo_history[0].source_id,source);self.assertTrue(g.state.combo_history[0].completed);self.portable(g)

    def test_printed_herald_location_stays_noncombat_and_cannot_gain_combat_definition(self):
        g=self.game((SHRINE,));source=self.play(g,SHRINE);entity=g.state.entities[source];self.assertEqual(entity.kind,CardType.LOCATION);self.assertIn(Keyword.HERALD,entity.keywords);self.assertEqual((entity.health,entity.attack,entity.durability),(0,0,2));self.assertFalse(g.state.herald_history);self.portable(g)
        for keywords in((Keyword.TAUNT,),(Keyword.HERALD,Keyword.RUSH)):
            with self.assertRaises(ValueError):self.r.register_card(replace(self.r.card(SHRINE),id=P+'bad_location',keywords=keywords))
        bad=deepcopy(g.snapshot());bad['state']['entities'][str(source)]['keywords']=['taunt'];bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

if __name__=='__main__':unittest.main()
