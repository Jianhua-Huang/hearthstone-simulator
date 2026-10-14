"""Bounded capped Resource facts; synthetic fixtures, no old TestCase imports."""
from copy import deepcopy
from dataclasses import dataclass,replace
import json,os,pathlib,unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Registry,ResolutionError,Resource,RewindSpec,Scenario,SelectChoice,
    SnapshotError,SpendUpToResource,ResourceConsumptionResult,TriggerSpec,Zone,resource_result)
from hs_sim.engine.effects import (ChoiceOption,Damage,Effect,EquipWeapon,GainArmor,
    GainResource,RandomDamage,RequestChoice,ReturnToHand,SpendResource)
from hs_sim.engine.effects import InvokeBehavior,Summon
from hs_sim.engine.resource_operations import (FinishResourceConsumption,InvokeResourcePayload,
    ResourceConsumptionReceipt)
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.rewind import COUNTERS

@dataclass(frozen=True)
class SavedResourceValue(Effect):
    value:ResourceConsumptionResult
    def __post_init__(self):
        if type(self.value) is not ResourceConsumptionResult:raise ValueError('Expected frozen resource result')
        self.value.__post_init__()

def use_saved(r,work):return [GainArmor(work.value.player_id,work.value.actual_amount)]
def mechanics():return default_mechanics('v142-resource-typed-test').register(SavedResourceValue,use_saved)

def registry():
    r=Registry('v142-capped-resource-local-only')
    for d in (CardDefinition('hero','hero',CardType.HERO,health=100),
              CardDefinition('plain','plain',CardType.MINION,cost=1,attack=1,health=20)):
        r.register_card(d)
    def saved(c):
        v=c.resource_result
        bad=(GainResource(v.player_id,v.resource,3),SpendUpToResource(v.player_id,v.resource,99,c.source_id),
            RandomDamage(tuple(c.state.players[p].hero_id for p in (1,2)),1,c.source_id),EquipWeapon(v.player_id,'plain'))
        return [RequestChoice(v.player_id,(ChoiceOption('good','Good',(SavedResourceValue(v),)),ChoiceOption('bad','Bad',bad)),c.source_id)]
    def refund(c):
        v=c.resource_result
        return [GainResource(v.player_id,v.resource,10)] if v and v.parent_id is None else []
    def nested(c):
        v=c.resource_result
        return [GainResource(2,Resource.CORPSES,1),SpendUpToResource(2,Resource.CORPSES,2,c.source_id,'saved')] if v and v.parent_id is None else []
    def leave(c):
        v=c.resource_result
        return [ReturnToHand(v.source_id)] if v and c.state.entities[v.source_id].zone==Zone.BOARD else []
    bodies={'saved':saved,'refund':refund,'nested':nested,'leave':leave,
      'produce':lambda c:[SpendUpToResource(c.player_id,Resource.CORPSES,3,c.source_id,'saved')],
      'source':lambda c:[SpendUpToResource(1,Resource.CORPSES,3,c.state.players[1].board[0],'saved')],
      'legacy':lambda c:[SpendResource(1,Resource.CORPSES,3,on_success=(GainArmor(1,3),))],
      'terminal':lambda c:[SpendUpToResource(1,Resource.CORPSES,3,c.source_id,'terminal_payload')],
      'terminal_payload':lambda c:[Damage(c.state.players[2].hero_id,999,c.source_id)],
      'illegal_choice':lambda c:[RequestChoice(1,(ChoiceOption('bad','bad',(FinishResourceConsumption(1),)),),c.source_id)],
      'unknown_source':lambda c:[SpendUpToResource(1,Resource.CORPSES,3,999999)],
      'unknown_callback':lambda c:[SpendUpToResource(1,Resource.CORPSES,3,c.source_id,'not_registered')]}
    bodies['sourceless']=lambda c:[SpendUpToResource(1,Resource.CORPSES,5)]
    bodies['created_driver']=lambda c:[Summon(1,'plain'),InvokeBehavior('created_spend',source_id=c.source_id,player_id=1)]
    bodies['created_spend']=lambda c:[SpendUpToResource(1,Resource.CORPSES,3,c.state.players[1].board[-1],'saved')]
    for cap in (0,1,5,99):
        bodies['cap'+str(cap)]=(lambda value:lambda c:[SpendUpToResource(1,Resource.CORPSES,value,c.source_id)])(cap)
    for name,body in bodies.items():r.register_behavior(name,body)
    for name in ('produce','source','legacy','terminal','illegal_choice','unknown_source','unknown_callback','cap0','cap1','cap5','cap99','sourceless'):
        r.register_card(CardDefinition(name,name,CardType.SPELL,cost=1,on_play=name))
    for name in ('refund','nested','leave'):
        r.register_card(CardDefinition(name,name,CardType.MINION,health=30,triggers=(TriggerSpec('resource_spent',name),)))
    r.register_card(CardDefinition('retry','retry',CardType.SPELL,cost=1,on_play='produce',keywords=(Keyword.REWIND,),rewind=RewindSpec(2)))
    r.register_card(CardDefinition('created_retry','created_retry',CardType.SPELL,cost=1,on_play='created_driver',keywords=(Keyword.REWIND,),rewind=RewindSpec(1)))
    for n in (2,1,0):
        r.register_card(CardDefinition('f'+str(n),'f'+str(n),CardType.MINION,cost=1,attack=1,health=10,on_play='produce',
            keywords=(Keyword.REWIND,) if n else (),rewind=RewindSpec(n,'f'+str(n-1)) if n else None))
    return r

class CappedResourceTests(unittest.TestCase):
    def game(self,hand=('produce',),board=(),balance=5,other=4):
        self.index=0
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*8,mana=10,max_mana=10,corpses=balance),
            PlayerSetup('hero',deck=('plain',)*8,mana=10,max_mana=10,corpses=other)),seed=142),registry(),mechanics=mechanics())
    def stash(self,label,value):
        folder=os.environ.get('HS142_EVIDENCE_DIR')
        if folder:
            self.index+=1;p=pathlib.Path(folder)/self._testMethodName/(str(self.index).zfill(3)+'-'+label+'.json')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))
    def cast(self,g,name='produce'):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name);g.apply(PlayCard(1,i));return i
    def choose(self,g,key='good'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def values(self,g):return [resource_result(e) for e in g.events if resource_result(e) is not None]
    def bank(self,g,p=1):return g.state.players[p].resources[Resource.CORPSES]
    def portable(self,g,label='waiting'):
        snap=json.loads(json.dumps(g.snapshot()));self.stash(label,snap)
        restored=Game.from_snapshot(deepcopy(snap),registry(),mechanics=mechanics())
        self.assertEqual(restored.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry(),mechanics=mechanics()).snapshot(),snap)
        return restored
    def private(self,g):
        for p in (1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for field in ('resource_operations','operation_id','parent_id','balance_before','source_zone_epoch','resource_result','resolution_frame'):
                self.assertNotIn('"'+field+'"',public)
    def reject(self,snap,label):
        snap['events_hash']=canonical_hash(snap['events'])
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')})
        self.stash(label,snap)
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(snap,registry(),mechanics=mechanics())
        self.assertNotIn('digest mismatch',str(error.exception).lower())

    def test_cap_zero_equal_below_above_and_empty_still_freeze_real_fact(self):
        for balance,cap in ((0,0),(0,5),(5,0),(5,1),(5,5),(5,99)):
            with self.subTest(balance=balance,cap=cap):
                g=self.game(hand=('cap'+str(cap),),balance=balance);source=self.cast(g,'cap'+str(cap));v=self.values(g)[0]
                self.assertEqual((v.cap,v.balance_before,v.actual_amount,v.balance_after),(cap,balance,min(balance,cap),max(0,balance-cap)))
                self.assertEqual((v.source_id,v.source_card_id,v.player_id,v.profile),(source,'cap'+str(cap),1,'after_resource_reactions'))
                self.assertEqual(g.state.next_resource_operation_id,2);self.assertEqual(g.state.resource_operations,[])
                self.assertEqual(self.bank(g),v.balance_after);self.assertEqual(self.bank(g,2),4);self.portable(g,'stable-cap')
        g=self.game(hand=('sourceless',));self.cast(g,'sourceless');v=self.values(g)[0]
        self.assertEqual(v.actual_amount,5);self.assertIsNone(v.source_id);self.assertIsNone(v.source_allocation)
        self.portable(g,'sourceless-default')

    def test_strict_cap_resource_profile_and_callback_declaration(self):
        for kwargs in ({'cap':True},{'cap':-1},{'cap':1.0},{'cap':1,'resource':'corpses'},
                       {'cap':1,'profile':'hero_lethal_at_debit'},{'cap':1,'profile':'unknown'},
                       {'cap':1,'on_result':'saved','source_id':None}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                SpendUpToResource(**({'player_id':1,'resource':Resource.CORPSES}|kwargs))

    def test_post_spend_refund_changes_live_bank_without_changing_frozen_actual(self):
        g=self.game(board=('refund',));self.cast(g);v=self.values(g)[0]
        self.assertEqual(self.bank(g),12);self.assertEqual((v.balance_before,v.balance_after,v.actual_amount),(5,2,3))
        self.assertEqual(g._frame.options[0].effects[0].value,v);self.portable(g);self.choose(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.assertEqual(self.bank(g),12)
        self.assertFalse(g.state.resource_operations);self.private(g);self.portable(g,'final')

    def test_cross_player_nested_reaction_keeps_parent_and_original_paid_proof_windows(self):
        g=self.game(board=('nested',));self.cast(g)
        self.assertEqual([(v.operation_id,v.parent_id,v.player_id,v.actual_amount) for v in self.values(g)],[(1,None,1,3),(2,1,2,2)])
        self.assertEqual(g.state.pending_choice.player_id,2);self.assertEqual([r.result.operation_id for r in g.state.resource_operations],[1,2])
        restored=self.portable(g,'child-player2-wait');clone=g.clone()
        for branch in (g,restored,clone):
            self.choose(branch);self.assertEqual(branch.state.pending_choice.player_id,1)
            self.assertEqual([r.result.operation_id for r in branch.state.resource_operations],[1])
            self.portable(branch,'parent-player1-wait');self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.assertEqual((self.bank(g),self.bank(g,2)),(2,3));self.private(g);self.portable(g,'nested-final')

    def test_true_waiting_bad_refund_nested_debit_rng_rolls_back_complete_boundary(self):
        g=self.game();self.cast(g);before=g.snapshot();restored=self.portable(g);clone=g.clone()
        for branch in (g,restored,clone):
            with self.assertRaises(ResolutionError):self.choose(branch,'bad')
            self.assertEqual(branch.snapshot(),before);self.choose(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot(),clone.snapshot())
        self.assertEqual(self.bank(g),2);self.assertEqual(g.state.next_resource_operation_id,2);self.portable(g,'after-rollback-good')

    def test_rehashed_result_request_parent_source_and_complete_tail_forgery_rejected(self):
        g=self.game(board=('nested',));self.cast(g);original=g.snapshot()
        for field,value in (('actual_amount',1),('cap',True),('operation_id',999),('parent_id',None),('source_owner',2),('source_zone_epoch',999)):
            bad=deepcopy(original);bad['state']['resource_operations'][-1]['result'][field]=value;self.reject(bad,'result-'+field)
        bad=deepcopy(original);bad['state']['resource_operations'][-1]['request']['cap']=1;self.reject(bad,'request-cap')
        bad=deepcopy(original);bad['state']['next_resource_operation_id']=2;self.reject(bad,'future-cursor')
        bad=deepcopy(original)
        controls=bad['resolution_frame']['fields']['continuation']['tuple']
        found=[i for i,w in enumerate(controls) if w.get('type')=='hs_sim.engine.resource_operations.FinishResourceConsumption'];self.assertTrue(found)
        controls.pop(found[0]);self.reject(bad,'missing-original-finish')
        bad=deepcopy(original);controls=bad['resolution_frame']['fields']['continuation']['tuple']
        positions=[i for i,w in enumerate(controls) if w.get('type')=='hs_sim.engine.resource_operations.FinishResourceConsumption'];self.assertEqual(len(positions),2)
        a,b=positions;controls[a],controls[b]=controls[b],controls[a];self.reject(bad,'reversed-LIFO')
        self.assertEqual(g.snapshot(),original)

    def test_choices_reject_internal_resource_control_before_automatic_or_live_execute(self):
        g=self.game(hand=('illegal_choice',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.cast(g,'illegal_choice')
        self.assertEqual(g.snapshot(),before)
        g=self.game();self.cast(g);bad=deepcopy(g.snapshot())
        option=bad['resolution_frame']['fields']['options']['tuple'][0]['fields']['effects']['tuple']
        from hs_sim.engine.continuations import FrameCodec
        option.append(FrameCodec(g.mechanics,g.registry).encode(InvokeResourcePayload(1)))
        self.reject(bad,'offered-internal-invoke')

    def test_physical_source_returned_after_spend_retains_original_face_epoch(self):
        g=self.game(hand=('source',),board=('plain','leave'));source=g.state.players[1].board[0]
        original=g.state.entities[source];self.cast(g,'source');value=self.values(g)[0]
        self.assertEqual((value.source_id,value.source_card_id,value.source_zone,value.source_zone_epoch,value.source_entered_order),
                         (source,'plain',Zone.BOARD,original.zone_epoch,original.entered_order))
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertGreater(g.state.entities[source].zone_epoch,value.source_zone_epoch)
        self.portable(g,'original-source-left-board');self.choose(g);self.portable(g,'source-final')

    def test_unknown_source_callback_fail_before_debit_and_old_spend_has_no_new_fact(self):
        for name in ('unknown_source','unknown_callback'):
            g=self.game(hand=(name,));before=g.snapshot()
            with self.assertRaises(ResolutionError):self.cast(g,name)
            self.assertEqual(g.snapshot(),before)
        g=self.game(hand=('legacy',));self.cast(g,'legacy');self.assertEqual(self.values(g),[])
        self.assertEqual(g.state.next_resource_operation_id,1);self.assertEqual(self.bank(g),2);self.portable(g,'legacy-compat')

    def test_terminal_payload_keeps_original_fact_and_closes_only_real_active_scope(self):
        g=self.game(hand=('terminal',));self.cast(g,'terminal')
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(self.values(g)),1)
        self.assertEqual(g.state.resource_operations,[]);self.assertEqual(g.state.next_resource_operation_id,2);self.portable(g,'terminal')

    def test_real_paid_spell_three_rewind_attempts_keep_monotonic_counter_and_facts(self):
        self.assertIn('next_resource_operation_id',COUNTERS)
        g=self.game(hand=('retry',));self.cast(g,'retry')
        for attempt in range(1,4):
            g=self.portable(g,'real-spell-attempt-'+str(attempt))
            self.assertEqual([v.operation_id for v in self.values(g)],list(range(1,attempt+1)))
            self.assertEqual([v.actual_amount for v in self.values(g)],[3]*attempt)
            self.choose(g);self.assertFalse(g.state.resource_operations)
            if attempt<3:self.portable(g,'rewind-request');self.choose(g,'retry')
        self.assertEqual((g.state.next_resource_operation_id,len(g.state.play_history),len(g.state.cast_history),g.state.players[1].mana),(4,1,1,9))
        self.assertEqual(self.bank(g),2);self.private(g);self.portable(g,'spell-retry-final')

    def test_real_paid_minion_face_rewind_preserves_new_counter_all_normalization_paths(self):
        g=self.game(hand=('f2',));eid=self.cast(g,'f2')
        for attempt in range(1,4):
            g=self.portable(g,'real-minion-attempt-'+str(attempt));self.choose(g)
            if attempt<3:self.choose(g,'retry')
        self.assertEqual([v.operation_id for v in self.values(g)],[1,2,3]);self.assertEqual(g.state.next_resource_operation_id,4)
        self.assertEqual(g.state.entities[eid].card_id,'f0');self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(self.bank(g,2),4);self.assertEqual(len(g.state.play_history),1);self.portable(g,'minion-retry-final')

    def test_completed_fact_future_operation_and_unknown_source_card_are_rejected(self):
        g=self.game(hand=('cap5',));self.cast(g,'cap5');original=g.snapshot()
        self.assertEqual(g.state.resource_operations,[]);self.portable(g,'completed-baseline')
        for field,value in (('operation_id',999999),('source_card_id','not_registered')):
            with self.subTest(field=field):
                bad=deepcopy(original)
                event=next(e for e in bad['events'] if e['kind']=='resource_spent' and 'result' in e['data'])
                for pair in event['data']['result']:
                    if pair[0]==field:pair[1]=value
                self.reject(bad,'completed-'+field)

    def test_actual_created_source_deleted_by_retry_keeps_complete_original_allocation_fact(self):
        g=self.game(hand=('created_retry',));self.cast(g,'created_retry');first=self.values(g)[0]
        self.assertEqual(first.source_card_id,'plain');self.assertIn(first.source_id,g.state.entities)
        self.portable(g,'first-created-source');self.choose(g);self.choose(g,'retry')
        second=self.values(g)[1];self.assertEqual([v.operation_id for v in self.values(g)],[1,2])
        self.assertNotEqual(first.source_id,second.source_id);self.assertNotIn(first.source_id,g.state.entities)
        self.assertIn(second.source_id,g.state.entities);self.assertEqual(g.state.next_resource_operation_id,3)
        self.assertLess(first.source_allocation.next_entity_id,g.state.next_entity_id)
        self.assertTrue(any(e.kind=='timeline_rewound' for e in g.events))
        self.portable(g,'retry-deleted-old-physical-source');self.choose(g);self.portable(g,'completed-with-historical-missing-source')
        bad=deepcopy(g.snapshot())
        event=next(e for e in bad['events'] if e['kind']=='resource_spent' and 'result' in e['data'])
        for pair in event['data']['result']:
            if pair[0]=='source_allocation':pair[1]=None
        self.reject(bad,'missing-original-allocation-proof')
        bad=deepcopy(g.snapshot())
        event=next(e for e in bad['events'] if e['kind']=='resource_spent' and 'result' in e['data'])
        allocation=next(pair[1] for pair in event['data']['result'] if pair[0]=='source_allocation')
        for pair in allocation:
            if pair[0]=='next_entity_id':pair[1]=999999
        self.reject(bad,'future-original-allocation-limit')

if __name__=='__main__':unittest.main()
