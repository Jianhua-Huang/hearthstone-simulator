"""Original physical deaths, hand admission, reset, atomic cost and recovery."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import death_hand_return_secrets as native
from hs_sim.cards.past_secret_base_effects import register_past_secret_base_effects,TRICKS,WISDOM
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost
from hs_sim.engine.death_hand_returns import ReturnDeadMinion
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,GainArmor,
    GrantDeathrattle,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice)
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,Resource,RewindSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.secret_conditions import SecretHandSpace
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference,DiscardCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

KODO,CHEAT=native.LEAVES
P='k637.';UNIT,FILL,WATCH,REBORN,SMALL=(P+x for x in ('unit','fill','watch','reborn','small'))
KILL,CLEAR,FILLER,BUFF,STEAL,PUBLIC,WAIT,DOUBLE,DISCARD,NOOP,FAIL=(P+x for x in ('kill','clear','filler','buff','steal','public','wait','double','discard','noop','fail'))
RETRYKILL=P+'retrykill'


def mana_cost(entity):return local_cost(entity)[0]


def captured(c,*,cut=2):
    death=next(d for d in reversed(c.state.death_history) if d.controller==c.player_id)
    return ReturnDeadMinion(death.id,SourceAllocationFact.capture(c.state,c.state.entities[death.entity_id]),
        SourceAllocationFact.capture(c.state,c.source),cut)


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();register_past_secret_base_effects(r);native.register_death_hand_return_secrets(r)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'dr',lambda c:(GainArmor(c.player_id,2),))
    for cid,attack,health,cost in ((UNIT,3,5,4),(FILL,0,2,0),(WATCH,0,30,0),(REBORN,2,3,3),(SMALL,1,1,1)):
        extra={'battlecry':P+'bc'} if cid==UNIT else {}
        if cid==REBORN:extra.update(keywords=(Keyword.REBORN,),deathrattle=P+'dr')
        if cid==WATCH and mode!='normal':extra['triggers']=(TriggerSpec('secret_revealed' if mode=='reveal' else 'hand_card_entered',P+'watch'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    def prompt(c):
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fill','Fill hand',(AddToHand(c.player_id,FILL,c.source_id),)*2),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id)
    def wait(c):return (prompt(c),captured(c))
    def twice(c):e=captured(c);return (e,e)
    def buff(c):
        return (Buff(c.target_id,4,4,c.source_id),GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),RETRYKILL:lambda c:(Destroy(c.target_id,c.source_id),),CLEAR:lambda c:(DestroyBatch(tuple(c.state.players[3-c.player_id].board),c.source_id),),
        FILLER:lambda c:(AddToHand(3-c.player_id,FILL,c.source_id),),BUFF:buff,STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),
        PUBLIC:lambda c:(captured(c),),WAIT:wait,DOUBLE:twice,
        DISCARD:lambda c:(DiscardCard(CardReference.capture(next(c.state.entities[i] for i in c.state.players[3-c.player_id].hand if c.state.entities[i].card_id==UNIT)),c.source_id),),
        NOOP:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);extra={}
        if cid in (KILL,RETRYKILL,BUFF,STEAL):extra['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if cid==RETRYKILL:extra.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    def fail(c):raise ResolutionError('K637 deliberate return/choice rollback')
    def watch(c):
        if mode=='reveal':
            e=c.state.entities.get(c.event.source_id)
            return (prompt(c),) if e is not None and e.card_id in native.LEAVES else ()
        data=dict(c.event.data);entry=c.state.hand_entries[data['hand_entry_id']-1]
        if entry.player_id!=c.player_id or entry.reason!='return':return ()
        e=c.state.entities[entry.entity_id]
        if mode=='fail':return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        if mode=='observe':return (GainArmor(c.player_id,mana_cost(e)),)
        return (prompt(c),)
    r.register_behavior(FAIL,fail);r.register_behavior(P+'watch',watch);r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class DeathHandReturnTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(UNIT,),enemy=(),other_hand=(KILL,),mode='normal',player=1,max_hand=10,hand_cap=None):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,hand_cap=hand_cap,deck=(FILL,)*12,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*12,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=107),registry(mode),Ruleset(max_hand=max_hand))
    def arm(self,g,cid,p=1):eid=self.play(g,cid,player=p);g.apply(EndTurn(p));return eid
    def secrets(self,g,p=1):return [g.state.entities[i].card_id for i in g.state.players[p].secrets]
    def kill(self,g,target=None,p=2):self.play(g,KILL,target or self.entity(g,UNIT,3-p,'board').id,player=p)
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def wait_roundtrip(self,g):
        saved=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored)
        self.settle(g);self.settle(restored);self.assertEqual(g.snapshot(),restored.snapshot());return restored
    def effect_fields(self,value):
        result=[]
        if isinstance(value,dict):
            if isinstance(value.get('fields'),dict) and set(value['fields'])=={'death_id','card','source','cost_reduction'}:result.append(value['fields'])
            for x in value.values():result+=self.effect_fields(x)
        elif isinstance(value,list):
            for x in value:result+=self.effect_fields(x)
        return result
    def reject(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode,'independent-reader'))

    def test_three_complete_rows_four_faces_and_readonly_discount_evidence(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(2,1,4))
        self.assertNotIn('LOOT_204e',registry().cards);self.assertFalse(d['source_scope_bound']);self.assertFalse(d['cn_calibrated'])

    def test_two_real_paid_hidden_secrets_reject_duplicate_without_payment(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));mana=g.state.players[1].mana;self.play(g,cid);self.assertEqual(g.state.players[1].mana,mana-registry().card(cid).cost)
            saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved);self.assertNotIn(cid,json.dumps(g.for_player(2).observe()))

    def test_kodo_returns_original_identity_resets_buffs_and_never_runs_battlecry(self):
        g=self.game((KODO,BUFF));eid=self.entity(g,UNIT,1,'board').id;self.play(g,BUFF,eid);self.arm(g,KODO);rng=g._rng.getstate();self.kill(g,eid)
        e=g.state.entities[eid];self.assertEqual((e.zone,e.attack,e.max_health,e.damage),(Zone.HAND,3,5,0));self.assertNotIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertEqual(len(g.state.death_history),1);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_cheat_death_discount_is_installed_before_replay_and_one_actual_payment(self):
        g=self.game((CHEAT,));eid=self.entity(g,UNIT,1,'board').id;self.arm(g,CHEAT);self.kill(g,eid)
        self.assertEqual(mana_cost(g.state.entities[eid]),2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)
        self.portable(g);g.apply(EndTurn(2));mana=g.state.players[1].mana;g.apply(PlayCard(1,eid))
        self.assertEqual(g.state.players[1].mana,mana-2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.entities[eid].zone,Zone.BOARD)

    def test_cheat_death_cost_reduction_uses_zero_floor(self):
        g=self.game((CHEAT,),board=(SMALL,));eid=self.entity(g,SMALL,1,'board').id;self.arm(g,CHEAT);self.kill(g,eid)
        self.assertEqual(mana_cost(g.state.entities[eid]),0)

    def test_unrelated_enemy_death_and_hand_discard_do_not_trigger(self):
        g=self.game((KODO,UNIT),board=(),enemy=(UNIT,),other_hand=(KILL,DISCARD));self.arm(g,KODO)
        self.kill(g,self.entity(g,UNIT,2,'board').id);self.play(g,DISCARD,player=2)
        self.assertIn(KODO,self.secrets(g));self.assertEqual(len(g.state.death_history),1)

    def test_owner_turn_death_keeps_secret(self):
        g=self.game((KODO,KILL));self.play(g,KODO);self.kill(g,self.entity(g,UNIT,1,'board').id,p=1)
        self.assertIn(KODO,self.secrets(g));self.assertFalse(any(g.state.entities[i].card_id==UNIT for i in g.state.players[1].hand))

    def test_simultaneous_deaths_return_only_original_first_subject_and_credit_both(self):
        g=self.game((KODO,),board=(UNIT,UNIT),other_hand=(CLEAR,));first=g.state.players[1].board[0];self.arm(g,KODO);self.play(g,CLEAR,player=2)
        self.assertEqual([i for i in g.state.players[1].hand if g.state.entities[i].card_id==UNIT],[first])
        self.assertEqual(len(g.state.death_history),2);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],2)

    def test_stolen_dead_card_returns_to_death_controller_retaining_physical_owner(self):
        g=self.game((CHEAT,STEAL),board=(),enemy=(UNIT,));eid=self.entity(g,UNIT,2,'board').id
        self.play(g,STEAL,eid);self.arm(g,CHEAT);self.kill(g,eid)
        e=g.state.entities[eid];self.assertEqual((e.owner,e.controller,e.zone),(2,1,Zone.HAND));self.assertEqual(mana_cost(e),2);self.portable(g)

    def test_full_hand_keeps_secret_and_later_new_death_does_not_revisit_old_body(self):
        g=self.game((KODO,)+(FILL,)*9,board=(UNIT,UNIT),other_hand=(FILLER,KILL,KILL));old,other=g.state.players[1].board
        self.arm(g,KODO);self.play(g,FILLER,player=2);self.kill(g,old);self.assertIn(KODO,self.secrets(g));self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        g.apply(EndTurn(2));self.play(g,FILL);g.apply(EndTurn(1));self.kill(g,other)
        self.assertEqual(g.state.entities[other].zone,Zone.HAND);self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)

    def test_hand_admission_uses_rules_default_and_player_override(self):
        for maximum,override,cap in ((3,None,3),(5,2,2)):
            g=self.game((CHEAT,)+(FILL,)*(cap-1),other_hand=(FILLER,KILL),max_hand=maximum,hand_cap=override)
            self.arm(g,CHEAT);self.play(g,FILLER,player=2);self.kill(g)
            self.assertEqual(len(g.state.players[1].hand),cap);self.assertIn(CHEAT,self.secrets(g))

    def test_reveal_wait_preserves_original_death_and_both_real_return_bodies(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,WATCH),mode='reveal');eid=self.entity(g,UNIT,1,'board').id;self.arm(g,cid);self.kill(g,eid)
            self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g)
            self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.assertEqual(mana_cost(g.state.entities[eid]),2 if cid==CHEAT else 4)

    def test_hand_fills_after_reveal_burns_original_without_second_death_or_credit(self):
        g=self.game((CHEAT,)+(FILL,)*8,board=(UNIT,WATCH),mode='reveal');eid=self.entity(g,UNIT,1,'board').id
        self.arm(g,CHEAT);self.kill(g,eid);epoch=g.state.entities[eid].zone_epoch;self.choose(g,'fill')
        self.assertEqual((g.state.entities[eid].zone,g.state.entities[eid].zone_epoch),(Zone.GRAVEYARD,epoch+1))
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertTrue(any(e.kind=='card_burned' and e.target_id==eid for e in g._events));self.portable(g)

    def test_acquisition_listener_observes_reset_body_and_discount_before_reacting(self):
        g=self.game((CHEAT,),board=(UNIT,WATCH),mode='observe');self.arm(g,CHEAT);self.kill(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)

    def test_original_deathrattle_and_reborn_remain_independent_of_return(self):
        g=self.game((KODO,),board=(REBORN,));eid=self.entity(g,REBORN,1,'board').id;self.arm(g,KODO);self.kill(g,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(len(g.state.players[1].board),1);child=g.state.entities[g.state.players[1].board[0]]
        self.assertNotEqual(child.id,eid);self.assertEqual(child.health,1);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.portable(g)

    def test_failed_return_acquisition_rolls_back_whole_death_payment_and_rng(self):
        g=self.game((CHEAT,),board=(UNIT,WATCH),mode='fail');self.arm(g,CHEAT);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.kill(g)
        self.assertEqual(g.snapshot(),saved)

    def test_successful_return_hand_wait_restores_actual_arrival_without_returning_twice(self):
        g=self.game((CHEAT,),board=(UNIT,WATCH),mode='hand');eid=self.entity(g,UNIT,1,'board').id;self.arm(g,CHEAT);self.kill(g,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.wait_roundtrip(g)
        self.assertEqual(sum(x.entity_id==eid and x.reason=='return' for x in g.state.hand_entries),1)

    def test_accepted_public_effect_before_wait_roundtrips_and_returns_same_identity(self):
        g=self.game((WAIT,),other_hand=(KILL,));eid=self.entity(g,UNIT,1,'board').id;g.apply(EndTurn(1));self.kill(g,eid);g.apply(EndTurn(2));self.play(g,WAIT)
        self.assertEqual(sum(type(x) is ReturnDeadMinion for x in g._frame.continuation),1)
        self.assertTrue(self.effect_fields(g.snapshot()));self.wait_roundtrip(g);self.assertEqual(g.state.entities[eid].zone,Zone.HAND)

    def test_repeating_same_public_material_cannot_duplicate_or_reacquire_card(self):
        g=self.game((DOUBLE,));eid=self.entity(g,UNIT,1,'board').id;g.apply(EndTurn(1));self.kill(g,eid);g.apply(EndTurn(2));self.play(g,DOUBLE)
        self.assertEqual(sum(i==eid for i in g.state.players[1].hand),1);self.assertEqual(len(g.state.death_history),1);self.portable(g)

    def test_queued_effect_rejects_other_death_future_allocation_and_changed_epoch(self):
        g=self.game((WAIT,),board=(UNIT,UNIT),other_hand=(CLEAR,));g.apply(EndTurn(1));self.play(g,CLEAR,player=2);g.apply(EndTurn(2));self.play(g,WAIT)
        saved=g.snapshot();self.assertTrue(self.effect_fields(saved))
        for field,value in (('death_id',1),('death_id',999),('cost_reduction',True),('cost_reduction',-1)):
            changed=json.loads(json.dumps(saved));self.effect_fields(changed)[0][field]=value;self.reject(changed)
        for field in ('zone_epoch','next_entity_id','entered_order'):
            changed=json.loads(json.dumps(saved));card=self.effect_fields(changed)[0]['card']['fields'];card[field]+=100;self.reject(changed)

    def test_public_return_and_transient_guard_reject_wrong_shapes(self):
        for value in (None,1,0,(),True):
            if value is True:continue
            with self.assertRaises(ValueError):SecretHandSpace(value)
        self.assertFalse(SecretHandSpace(False).matched)
        g=self.game((WAIT,));g.apply(EndTurn(1));self.kill(g);g.apply(EndTurn(2));self.play(g,WAIT)
        work=next(x for x in g._frame.continuation if type(x) is ReturnDeadMinion)
        for kwargs in ({'card':None},{'source':None},{'cost_reduction':True},{'cost_reduction':-1},
                {'card':replace(work.card,zone=Zone.HAND)},{'card':replace(work.card,kind=CardType.SPELL)},
                {'source':replace(work.source,controller=2)}):
            with self.subTest(kwargs=tuple(kwargs)),self.assertRaises(ValueError):replace(work,**kwargs)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        with self.assertRaises(ValueError):codec.encode(SecretHandSpace(True))
        saved=g.snapshot();saved['schema_version']=617;self.reject(saved)

    def test_retry_reexecutes_original_death_without_duplicate_return_or_corpse(self):
        g=self.game((CHEAT,),other_hand=(RETRYKILL,));eid=self.entity(g,UNIT,1,'board').id;self.arm(g,CHEAT)
        self.play(g,RETRYKILL,eid,player=2);old=g.state.death_history[-1].id;self.portable(g)
        self.choose(g,'retry');self.settle(g);self.assertEqual(len(g.state.death_history),1)
        self.assertGreater(g.state.death_history[-1].id,old);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)
        self.assertEqual(sum(i==eid for i in g.state.players[1].hand),1);self.portable(g)

    def test_two_real_secrets_do_not_move_original_dead_residence_twice(self):
        g=self.game((KODO,CHEAT));self.play(g,KODO);self.arm(g,CHEAT);self.kill(g)
        self.assertEqual(len([i for i in g.state.players[1].hand if g.state.entities[i].card_id==UNIT]),1)
        self.assertIn(CHEAT,self.secrets(g));self.assertNotIn(KODO,self.secrets(g))

    def test_dirty_tricks_and_hidden_wisdom_keep_full_hand_and_existing_boolean_callbacks_work(self):
        for cid in (TRICKS,WISDOM):
            g=self.game((cid,)+(FILL,)*2,board=(),other_hand=(FILLER,NOOP,NOOP,NOOP),max_hand=5,hand_cap=3)
            self.arm(g,cid);self.play(g,FILLER,player=2)
            for _ in range(3):self.play(g,NOOP,player=2)
            self.assertIn(cid,self.secrets(g));self.assertEqual(len(g.state.players[1].hand),3)

    def test_second_actor_receives_same_original_card_and_private_materials_stay_hidden(self):
        g=self.game((CHEAT,),player=2);eid=self.entity(g,UNIT,2,'board').id;self.arm(g,CHEAT,2);self.kill(g,eid,p=1)
        self.assertEqual((g.state.entities[eid].controller,g.state.entities[eid].zone,mana_cost(g.state.entities[eid])),(2,Zone.HAND,2))
        for player in (1,2):
            text=json.dumps((g.for_player(player).observe(),g.player_events(player)))
            for key in ('ReturnDeadMinion','SourceAllocationFact','copy_source','resolution_frame','rng_state','next_entity_id','cost_reduction'):self.assertNotIn(key,text)
        self.portable(g)

    def test_complete_host_actual_death_returns_original_real_minion(self):
        r=host();g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(CHEAT,),board=('CS2_120',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_120',),mana=10,max_mana=10)),seed=107),r)
        eid=g.state.players[1].board[0];self.arm(g,CHEAT);self.play(g,'CS2_029',eid,player=2)
        self.assertEqual(g.state.entities[eid].zone,Zone.HAND);self.assertEqual(mana_cost(g.state.entities[eid]),0)
        self.assertNotIn('WON_040',r.cards);saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)


if __name__=='__main__':unittest.main()
