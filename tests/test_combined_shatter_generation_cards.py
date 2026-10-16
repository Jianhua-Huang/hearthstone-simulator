"""Explicit format pools and already-combined native Shatter acquisition."""
from dataclasses import asdict,replace
import json,random,unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.combined_shatter_generation_cards import SIPHON,POOL_ID,PREFIX,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.effects import AddToHand,ChoiceOption,InvokeBehavior,RequestChoice
from hs_sim.engine.model import Rarity
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import (GenerationContext,GenerateFromPool,PoolCard,PoolDefinition,
    PoolMember,PoolQuery,resolve_candidates)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import canonical_digest

ROOTS=('CATA_134','CATA_306','CATA_479','CATA_489','CATA_820');YETI='CORE_CS2_182';PYRO='TIME_101';P='k107.test.';UNKNOWN=P+'unknown'
CONTEXT=GenerationContext('k107-explicit-fixture','experimental')


def registry(members=ROOTS,mode=None,pool=True):
    r=build_registry()
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,4,CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=()),keywords=(Keyword.SHATTER,)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k107-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def pick(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in ROOTS)
    def pause(c):return RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id)
    bodies=dict(current=lambda c:(CopyCard(CardReference.capture(pick(c)),c.player_id,mode='current',source_id=c.source_id),),
        base=lambda c:(CopyCard(CardReference.capture(pick(c)),c.player_id,mode='base',source_id=c.source_id),),
        full=lambda c:(AddToHand(1,YETI,c.source_id),InvokeBehavior(PREFIX+'generate',c.source_id,1)),
        pending=lambda c:(pause(c),AddToHand(1,'CATA_489',c.source_id,combined_shatter=True)),
        invalid=lambda c:(GenerateFromPool(1,POOL_ID,source_id=c.source_id,combined_shatter=True),),
        invalid_direct=lambda c:(AddToHand(1,YETI,c.source_id,combined_shatter=True),),
        ordinary=lambda c:(AddToHand(1,'CATA_489',c.source_id),),
        fail=lambda c:(_ for _ in()).throw(ResolutionError('K107 deliberate pending failure')))
    for name,body in bodies.items():r.register_behavior(P+name,body)
    for name in bodies:
        if name!='fail':r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name))
    if mode:
        def observer(c):
            e=c.state.entities[c.event.target_id]
            if e.card_id not in ROOTS:return ()
            if Keyword.SHATTER in e.keywords:raise AssertionError('First acquisition observer saw uncombined material')
            return(pause(c),)
        r.register_behavior(P+'observe',observer)
        r.register_card(CardDefinition(P+'observer','First arrival observer representative',CardType.MINION,health=8,
            triggers=(TriggerSpec('card_created'if mode=='created'else'card_added_to_hand',P+'observe'),)))
    r.validate();return r


class CombinedShatterGenerationTests(unittest.TestCase):
    def game(self,hand=(SIPHON,),hero='HERO_03',members=ROOTS,mode=None,pool=True,context=CONTEXT,board=(),enemy=()):
        self.members=members;self.mode=mode;self.pool=pool;self.context=context
        if mode:board=(*board,P+'observer')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=107,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target));return eid
    def generated(self,g):return[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id in ROOTS]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        snapshot=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snapshot,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),snapshot);self.assertEqual(g.clone().snapshot(),snapshot);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),snapshot)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('combined_shatter','rng_state','resolution_frame','behavior_id','pool_id','source_zone_epoch'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_rogue_shadow_face_and_all_five_existing_source_pins(self):
        d=load_batch();r=build_registry();row,=d['cards'];raw=row['record'];c=r.card(SIPHON);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=SIPHON));self.assertEqual(c.metadata.classes,(CardClass.ROGUE,));self.assertEqual((c.cost,c.spell_school),(3,SpellSchool.SHADOW));self.assertFalse(c.requires_target);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertTrue(d['required_generation_context']);self.assertEqual(len(d['official_observations']['observations']),2)
        self.assertEqual(tuple(x['record']['id']for x in d['existing_dependencies']),ROOTS)
        for x in d['cards']+d['existing_dependencies']:
            self.assertEqual(canonical_digest(x['record']),x['record_sha256'])
            if 'definition_sha256'in x:self.assertEqual(canonical_digest(asdict(r.card(x['record']['id']))),x['definition_sha256'])

    def test_only_one_card_added_and_no_production_formal_pool_installed(self):
        with patch('hs_sim.cards.combined_shatter_generation_cards.register_combined_shatter_generation_cards',lambda r:None):old=build_registry()
        r=build_registry();self.assertEqual(set(r.cards)-set(old.cards),{SIPHON});self.assertTrue(all(asdict(old.card(cid))==asdict(r.card(cid))for cid in old.cards));self.assertEqual(dict(old.pools),dict(r.pools));self.assertFalse(any(p.mode=='standard'for p in r.pools.values()))

    def test_actual_current_hero_class_and_complete_pool_determine_rng_choice(self):
        g=self.game(hero='HERO_08');q=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='other',include_neutral=False,keywords_all=(Keyword.SHATTER,));candidates=resolve_candidates(g.registry,CONTEXT,POOL_ID,q,current_class=CardClass.MAGE,player_id=1);self.assertEqual(tuple(x.card_id for x in candidates),tuple(x for x in ROOTS if x!='CATA_489'));rng=random.Random();rng.setstate(g._rng.getstate());expected=candidates[rng.randrange(len(candidates))].card_id
        source=self.play(g,SIPHON);generated,=self.generated(g);self.assertEqual(generated.card_id,expected);self.assertEqual(g.state.players[1].mana,47);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertTrue(all(e.source_id==source for e in g.events if e.kind in('card_created','card_added_to_hand')));self.assertFalse(any(e.kind in('card_shattered','cards_recombined')for e in g.events));self.portable(g)

    def test_each_real_family_is_created_whole_without_native_split_or_recombine_event(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game(members=(cid,));self.play(g,SIPHON);e,=self.generated(g);self.assertEqual(e.card_id,cid);self.assertNotIn(Keyword.SHATTER,e.keywords);native=[a for a in e.abilities if a.kind=='keyword'and a.keyword==Keyword.SHATTER];self.assertEqual(len(native),1);self.assertTrue(native[0].consumed);self.assertFalse(any(x.kind in('card_shattered','cards_recombined')for x in g.events))

    def test_observers_see_combined_state_before_first_creation_or_arrival_notification(self):
        for mode in('created','arrival'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode,members=('CATA_489',));self.play(g,SIPHON);self.assertIsNotNone(g.state.pending_choice);e,=self.generated(g);self.assertNotIn(Keyword.SHATTER,e.keywords);other=self.portable(g);before=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_missing_context_or_matching_format_pool_errors_and_rolls_back(self):
        for context,pool in((None,True),(CONTEXT,False),(GenerationContext(CONTEXT.target_id,'standard'),True)):
            with self.subTest(context=context,pool=pool):
                g=self.game(context=context,pool=pool);before=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,SIPHON)
                self.assertEqual(g.snapshot(),before)

    def test_unknown_eligible_candidate_rejects_before_rng_even_with_full_hand(self):
        for full in(False,True):
            with self.subTest(full=full):
                g=self.game(hand=((P+'full',)+(YETI,)*9)if full else(SIPHON,),members=('CATA_489',UNKNOWN));before=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,P+'full'if full else SIPHON)
                self.assertEqual(g.snapshot(),before)

    def test_empty_eligible_pool_consumes_no_rng_and_does_not_invent_fallback(self):
        g=self.game(hero='HERO_08',members=('CATA_489',));before=g._rng.getstate();self.play(g,SIPHON);self.assertFalse(self.generated(g));self.assertEqual(g._rng.getstate(),before);self.assertEqual(g.state.players[1].mana,47);self.portable(g)

    def test_full_hand_burns_complete_combined_material_without_fragments(self):
        g=self.game(hand=(P+'full',)+(YETI,)*9,members=('CATA_489',));self.play(g,P+'full');self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.generated(g));e=self.first(g,'CATA_489',zone='graveyard');self.assertNotIn(Keyword.SHATTER,e.keywords);self.assertTrue(any(x.kind=='card_burned'and x.target_id==e.id for x in g.events));self.assertFalse(any(x.kind in('card_shattered','cards_recombined')for x in g.events));self.portable(g)

    def test_pyromancer_does_not_fire_for_already_combined_creation(self):
        g=self.game(members=('CATA_489',),board=(PYRO,),enemy=(YETI,));before=self.first(g,YETI,zone='board',p=2).health;self.play(g,SIPHON);self.assertEqual(self.first(g,YETI,zone='board',p=2).health,before);self.assertFalse(any(x.kind=='card_shattered'for x in g.events))

    def test_generated_whole_can_be_paid_and_execute_both_real_halves(self):
        g=self.game(members=('CATA_489',),enemy=(YETI,));target=self.first(g,YETI,zone='board',p=2).id;self.play(g,SIPHON);self.play(g,'CATA_489',target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,43);self.assertEqual(len(g.state.cast_history),2);self.portable(g)

    def test_current_copy_preserves_consumption_and_base_copy_restores_splitting(self):
        for mode in('current','base'):
            with self.subTest(mode=mode):
                g=self.game(hand=(SIPHON,P+mode,YETI),members=('CATA_489',));self.play(g,SIPHON);self.play(g,P+mode)
                if mode=='current':self.assertEqual(len(self.generated(g)),2);self.assertFalse(any(x.kind=='card_shattered'for x in g.events))
                else:self.assertEqual(len(self.generated(g)),1);self.assertEqual(len([x for x in g.events if x.kind=='card_shattered']),1);spec=g.registry.card('CATA_489').shatter;self.assertEqual({g.state.entities[i].card_id for i in g.state.players[1].hand if g.state.entities[i].card_id!=YETI},{'CATA_489',spec.left_card_id,spec.right_card_id})
                self.portable(g)

    def test_all_combined_candidates_and_direct_carriers_must_be_native_whole_spells(self):
        for cid,members in((P+'invalid',('CATA_489',SIPHON)),(P+'invalid_direct',('CATA_489',))):
            with self.subTest(cid=cid):
                g=self.game((cid,),members=members);before=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,cid)
                self.assertEqual(g.snapshot(),before)

    def test_ordinary_created_shatter_still_splits(self):
        g=self.game((P+'ordinary',YETI));self.play(g,P+'ordinary');self.assertEqual(len([x for x in g.events if x.kind=='card_shattered']),1);self.assertFalse(self.generated(g));self.portable(g)

    def test_pending_creation_declaration_restores_and_failure_rolls_back(self):
        g=self.game((P+'pending',));self.play(g,P+'pending');other=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([x.card_id for x in self.generated(g)],['CATA_489']);self.portable(g)

    def test_combined_declaration_rejects_nonboolean_and_nonhand_delivery(self):
        for value in(1,None,'yes'):
            with self.subTest(value=value),self.assertRaises(ValueError):AddToHand(1,'CATA_489',combined_shatter=value)
            with self.subTest(value=value),self.assertRaises(ValueError):GenerateFromPool(1,POOL_ID,combined_shatter=value)
        for zone in('board','deck'):
            with self.subTest(zone=zone),self.assertRaises(ValueError):GenerateFromPool(1,POOL_ID,destination=zone,combined_shatter=True)

    def test_malformed_pending_combined_flag_rejected_after_rehash(self):
        g=self.game((P+'pending',));self.play(g,P+'pending');bad=g.snapshot()
        def tamper(v):
            if isinstance(v,dict):
                if v.get('type','').endswith('.AddToHand'):v['fields']['combined_shatter']=1;return True
                return any(tamper(x)for x in v.values())
            if isinstance(v,list):return any(tamper(x)for x in v)
            return False
        self.assertTrue(tamper(bad));bad['state_hash']=canonical_hash({k:v for k,v in bad.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())


if __name__=='__main__':unittest.main()
