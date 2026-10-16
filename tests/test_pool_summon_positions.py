"""Real random Deathrattles forward original slots to existing summon plans."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.simple_followup_p30_cards import SNEED,MONGREL
from hs_sim.cards.simple_followup_p34_cards import ATLAS
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,SummonQuantitySpec,TargetMode,TargetSpec
from hs_sim.engine.pool_summons import validate_link,validate_record
from hs_sim.engine.pools import GenerateFromPool,GenerationContext,PoolDefinition,PoolMember,PoolQuery,SummonFromPool
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonCause

P='k118.test.';YETI='CORE_CS2_182';APPLE='CORE_GIL_667';BRIGHT='CORE_EX1_189';ROOTS=(SNEED,MONGREL,ATLAS)
CTX=GenerationContext('k118-position-experiment','experimental');POOL='constructed.cards';MEMBERS=(*ROOTS,YETI,APPLE,BRIGHT)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(mode=None):
    r=build_registry();r.register_pool(PoolDefinition(POOL,'k118-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in MEMBERS),complete=True))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K118 deliberate entry failure')))
    for name,body in(('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('trigger',lambda c:(TriggerDeathrattles(c.target_id,c.source_id),))):
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')))
    for name in('single','batch'):
        def body(c,kind=name):
            query=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4);cause=SummonCause.capture(c)
            request=SummonFromPool(c.player_id,POOL,query,source_id=c.source_id,cause=cause,position=1)if kind=='single'else GenerateFromPool(c.player_id,POOL,query,count=2,source_id=c.source_id,cause=cause,destination='board',board_position=1)
            return(RequestChoice(1,(ChoiceOption('ok','Accept original request',(request,)),),c.source_id),)
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META))
    r.register_card(CardDefinition(P+'twice','Existing minion quantity profile',CardType.MINION,health=8,metadata=META,
        summon_quantities=(SummonQuantitySpec(source_kinds=(CardType.MINION,)),)))
    if mode:
        def eligible(c):return any(root.request.cause.source.card_id in ROOTS and any(d.entity is not None and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Original entry pause',CardType.MINION,health=8,metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r

class PoolSummonPositionTests(unittest.TestCase):
    def game(self,source=ATLAS,mode=None,twice=False,hand=(P+'kill',),board=None):
        self.mode=mode
        board=(YETI,source,YETI)if board is None else board
        if twice:board=(*board,P+'twice')
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*5,mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=(YETI,)*5)),seed=118,generation_context=CTX),registry(mode))
    def play(self,g,cid=P+'kill',target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def bodies(self,g,source):return[d.entity.entity_id for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered']
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for name in('pool_basis','pool_summon_history','rng_state','resolution_frame','board_position'):self.assertNotIn('"'+name+'"',public)
        return other

    def test_atlas_middle_natural_death_summons_in_original_slot(self):
        g=self.game();left,source,right=g.state.players[1].board;self.play(g,target=source);new,=self.bodies(g,source);self.assertEqual(g.state.players[1].board,[left,new,right]);self.assertEqual(g.state.entities[new].card_id,APPLE);self.assertEqual(g.state.card_summon_history[-1].request.position,1);self.portable(g)

    def test_sneed_middle_natural_death_also_uses_original_slot(self):
        g=self.game(SNEED);left,source,right=g.state.players[1].board;self.play(g,target=source);new,=self.bodies(g,source);self.assertEqual(g.state.players[1].board,[left,new,right]);self.assertEqual(g.state.entities[new].card_id,BRIGHT);self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_mongrel_batch_entries_are_consecutive_in_original_slot(self):
        g=self.game(MONGREL);left,source,right=g.state.players[1].board;self.play(g,target=source);new=self.bodies(g,source);self.assertEqual(len(new),2);self.assertEqual(g.state.players[1].board,[left,*new,right]);batch=g.state.pool_summon_history[-1];self.assertEqual(batch.spec.position,1);self.assertEqual([root.request.position for root in g.state.card_summon_history],[1,2]);self.portable(g)

    def test_effect_triggered_living_carrier_summons_to_its_right(self):
        for source in ROOTS:
            with self.subTest(source=source):
                g=self.game(source,hand=(P+'trigger',));left,eid,right=g.state.players[1].board;self.play(g,P+'trigger',eid);new=self.bodies(g,eid);self.assertEqual(g.state.players[1].board,[left,eid,*new,right]);self.assertFalse(g.state.death_history);self.portable(g)

    def test_original_batches_offset_by_actual_prior_deliveries_including_extras(self):
        g=self.game(MONGREL,twice=True);left,source,right,provider=g.state.players[1].board;self.play(g,target=source);new=self.bodies(g,source);self.assertEqual(len(new),4);self.assertEqual(g.state.players[1].board,[left,*new,right,provider]);self.assertEqual([root.request.position for root in g.state.card_summon_history],[1,3]);self.portable(g)

    def test_first_entry_wait_restores_batch_position_and_no_resampling(self):
        g=self.game(MONGREL,mode='wait');left,source,right,observer=g.state.players[1].board;self.play(g,target=source);first,=self.bodies(g,source);self.assertEqual(g.state.players[1].board,[left,first,right,observer]);other=self.portable(g);rng=g._rng.getstate();saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):
            while game.state.pending_choice:self.choose(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].board,[left,*self.bodies(g,source),right,observer]);self.portable(g)

    def test_saved_public_single_and_batch_requests_preserve_declared_position(self):
        for kind in('single','batch'):
            with self.subTest(kind=kind):
                g=self.game(hand=(P+kind,),board=(YETI,YETI));left,right=g.state.players[1].board;source=self.play(g,P+kind);other=self.portable(g)
                for game in(g,other):self.choose(game)
                self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].board,[left,*self.bodies(g,source),right]);self.portable(g)

    def test_child_cannot_change_parent_batch_position(self):
        g=self.game(MONGREL,mode='wait');source=g.state.players[1].board[1];self.play(g,target=source);root=g.state.card_summon_history[-1];batch=g.state.pool_summon_history[-1];bad=replace(root,request=replace(root.request,position=2))
        with self.assertRaises(ValueError):validate_link(g.state,bad)
        with self.assertRaises(ValueError):validate_record(g.state,g.registry,replace(batch,spec=replace(batch.spec,position=2)))

    def test_position_domain_and_delivery_scope_are_explicit(self):
        for position in(True,-1,'top'):
            with self.subTest(position=position):
                with self.assertRaises(ValueError):SummonFromPool(1,POOL,position=position)
                with self.assertRaises(ValueError):GenerateFromPool(1,POOL,board_position=position)
        with self.assertRaises(ValueError):GenerateFromPool(1,POOL,board_position=0)
        self.assertIsNone(SummonFromPool(1,POOL).position);self.assertIsNone(GenerateFromPool(1,POOL).board_position)

    def test_old_schema328_is_rejected_and_default_content_preserved(self):
        from hs_sim.engine.representative import build_registry as defaults
        self.assertEqual(defaults().fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,329);g=self.game();s=g.snapshot();s['schema_version']=328
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

if __name__=='__main__':unittest.main()
