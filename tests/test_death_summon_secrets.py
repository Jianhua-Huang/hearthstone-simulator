"""Real death Secrets, entry health/dormancy, original material and recovery."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import death_summon_secrets as native
from hs_sim.cards.death_hand_return_secrets import KODO,register_death_hand_return_secrets
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,SnapshotError
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.copy_materials import validate_material as validate_copy
from hs_sim.engine.death_self_copies import entry_from_death
from hs_sim.engine.death_summon_entries import ResurrectOneHealth,SummonDormantDeathCopy
from hs_sim.engine.dormancy import AwakenMinion
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,GainArmor,
    GrantKeyword,Heal,InvokeBehavior,RandomDamage,RequestChoice,Silence)
from hs_sim.engine.model import (AuraSpec,CardDefinition,CardType,Keyword,Resource,RewindSpec,
    SummonQuantitySpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.local_pool_format import build_cn37_local_pool_format

REDEMPTION,EMERGENCY=native.LEAVES
P='k638.'
UNIT,FILL,WATCH,SHIELD,REBORN,SLEEP,AURA,QUANTITY=(P+x for x in ('unit','fill','watch','shield','reborn','sleep','aura','quantity'))
KILL,RETRY,CLEAR,BUFF,WOUND,HEAL,MUTE,STEAL,WAKE,NOOP,FAIL=(P+x for x in ('kill','retry','clear','buff','wound','heal','mute','steal','wake','noop','fail'))
PUBLIC_R,PUBLIC_E=(P+x for x in ('public_r','public_e'))


def original_entry(c,cid):
    death=c.state.death_history[-1];cause=SummonCause.capture(c)
    return (ResurrectOneHealth(c.player_id,death.id,source_id=c.source_id,position=death.position,cause=cause)
        if cid==REDEMPTION else SummonDormantDeathCopy(death.id,cause))


@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_death_summon_secrets(r);register_death_hand_return_secrets(r)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(P+'dr',lambda c:(GainArmor(c.player_id,2),))
    def fail(c):raise ResolutionError('K638 deliberate death-entry rollback')
    r.register_behavior(FAIL,fail)
    def prompt(c):
        fill=(SummonByCard(c.player_id,(SummonEntryMaterial(FILL),),SummonCause.capture(c)),)*7
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fill','Fill board',fill),
            ChoiceOption('fail','Fail',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id)
    def awake(c):
        if c.source.origin_entity_id is None:return (GainArmor(c.player_id,4),)
        if mode=='awake_fail':return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return (prompt(c),) if mode=='awake_wait' else (GainArmor(c.player_id,4),)
    def watch(c):
        if mode=='reveal':
            e=c.state.entities.get(c.event.source_id)
            return (prompt(c),) if e is not None and e.card_id in native.LEAVES else ()
        e=c.state.entities.get(c.event.target_id)
        if e is None or e.origin_entity_id is None:return ()
        if mode=='observe':return (GainArmor(c.player_id,e.health if e.dormancy is None else 20+e.dormancy.remaining_turns),)
        if mode=='fail':return (RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))
        return (prompt(c),) if mode=='entry' else ()
    r.register_behavior(P+'watch',watch);r.register_behavior(P+'awake',awake)
    for cid,attack,health in ((UNIT,3,5),(FILL,0,2),(WATCH,0,30),(SHIELD,2,5),(REBORN,2,3),(SLEEP,2,5),(AURA,0,20),(QUANTITY,0,20)):
        extra={}
        if cid==UNIT:extra['battlecry']=P+'bc'
        if cid==SHIELD:extra['keywords']=(Keyword.DIVINE_SHIELD,)
        if cid==REBORN:extra.update(keywords=(Keyword.REBORN,),deathrattle=P+'dr')
        if cid==SLEEP:extra.update(dormant_turns=3,on_awaken=P+'awake')
        if cid==AURA:extra['auras']=(AuraSpec(attack=2,health=3),)
        if cid==QUANTITY:extra['summon_quantities']=(SummonQuantitySpec(2),)
        if cid==WATCH:extra['triggers']=(TriggerSpec('secret_revealed' if mode=='reveal' else 'minion_summoned',P+'watch'),)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=0,attack=attack,health=health,metadata=metadata(tribes=()),**extra))
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),RETRY:lambda c:(Destroy(c.target_id,c.source_id),),
        CLEAR:lambda c:(DestroyBatch(tuple(c.state.players[3-c.player_id].board),c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,4,4,c.source_id),GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id)),
        WOUND:lambda c:(Damage(c.target_id,2,c.source_id),),HEAL:lambda c:(Heal(c.target_id,3,c.source_id),),
        MUTE:lambda c:(Silence(c.target_id),),STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),
        WAKE:lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SLEEP)),),
        NOOP:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);extra={}
        if cid not in (CLEAR,WAKE,NOOP):extra['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if cid==RETRY:extra.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(tribes=()),**extra))
    for cid,leaf in ((PUBLIC_R,REDEMPTION),(PUBLIC_E,EMERGENCY)):
        r.register_behavior(cid,lambda c,leaf=leaf:(prompt(c),original_entry(c,leaf)))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=0,health=10,battlecry=cid,metadata=metadata(tribes=())))
    r.validate();r.freeze();return r


@lru_cache(None)
def host():return build_cn37_local_pool_format().registry


class DeathSummonSecretTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand=(),*,board=(UNIT,),enemy=(),other_hand=(KILL,),mode='normal',player=1):
        self.mode=mode
        setups=[PlayerSetup('mage.hero',hand=hand,board=board,deck=(FILL,)*15,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(FILL,)*15,mana=40,max_mana=40,mana_cap=40)]
        if player==2:setups.reverse()
        return Game.from_scenario(Scenario(tuple(setups),active_player=player,seed=109),registry(mode))
    def arm(self,g,cid,p=1):eid=self.play(g,cid,player=p);g.apply(EndTurn(p));return eid
    def kill(self,g,eid=None,p=2):return self.play(g,KILL,eid or self.entity(g,UNIT,3-p,'board').id,player=p)
    def bodies(self,g,cid=UNIT,p=1):return [g.state.entities[i] for i in g.state.players[p].board if g.state.entities[i].card_id==cid]
    def settle(self,g):
        while g.state.pending_choice:self.choose(g)
    def wait_roundtrip(self,g):
        saved=g.snapshot();restored=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(restored)
        self.settle(g);self.settle(restored);self.assertEqual(g.snapshot(),restored.snapshot());return restored
    def fields(self,value,kind):
        result=[]
        if isinstance(value,dict):
            row=value.get('fields')
            if isinstance(row,dict) and 'death_id'in row and 'cause'in row and ('player_id'in row)==(kind==REDEMPTION):result.append(row)
            for child in value.values():result+=self.fields(child,kind)
        elif isinstance(value,list):
            for child in value:result+=self.fields(child,kind)
        return result
    def reject(self,saved):
        saved['events_hash']=canonical_hash(saved['events'])
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode,'independent-reader'))

    def test_complete_source_rows_and_improved_secret_remains_readonly(self):
        d=native.load_batch();self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations'])),(2,1,4))
        self.assertNotIn('TSC_929t',registry().cards);self.assertFalse(d['source_scope_bound']);self.assertFalse(d['cn_calibrated'])
        self.assertEqual([registry().card(c).secret.requires_board_space for c in native.LEAVES],[True,True])

    def test_real_secrets_pay_once_hide_and_reject_duplicates(self):
        for cid in native.LEAVES:
            g=self.game((cid,cid));mana=g.state.players[1].mana;self.play(g,cid)
            self.assertEqual(g.state.players[1].mana,mana-registry().card(cid).cost);saved=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid)
            self.assertEqual(g.snapshot(),saved);self.assertNotIn(cid,json.dumps(g.for_player(2).observe()))

    def test_redemption_preserves_printed_maximum_and_allows_ordinary_healing(self):
        g=self.game((REDEMPTION,BUFF,HEAL));eid=self.entity(g,UNIT,1,'board').id;self.play(g,BUFF,eid);self.arm(g,REDEMPTION);self.kill(g,eid)
        e=self.bodies(g)[0];self.assertNotEqual(e.id,eid);self.assertEqual((e.attack,e.max_health,e.health,e.damage),(3,5,1,4))
        self.assertFalse(Keyword.TAUNT in e.keywords);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);g.apply(EndTurn(2));self.play(g,HEAL,e.id)
        self.assertEqual(self.bodies(g)[0].health,4)

    def test_redemption_is_at_one_health_before_summon_observer_after_aura_refresh(self):
        g=self.game((REDEMPTION,),board=(AURA,UNIT,WATCH),mode='observe');self.arm(g,REDEMPTION);self.kill(g)
        e=self.bodies(g)[0];self.assertEqual((e.attack,e.max_health,e.health,e.damage),(5,8,1,7));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.resurrection_history[-1].entity_id,e.id)

    def test_redemption_keeps_printed_shield_and_discards_original_silence(self):
        g=self.game((REDEMPTION,MUTE),board=(SHIELD,));eid=self.entity(g,SHIELD,1,'board').id;self.play(g,MUTE,eid);self.arm(g,REDEMPTION);self.kill(g,eid)
        e=self.bodies(g,SHIELD)[0];self.assertEqual((e.health,e.max_health),(1,5));self.assertFalse(e.silenced);self.assertTrue(Keyword.DIVINE_SHIELD in e.keywords)

    def test_emergency_copies_current_stats_keywords_and_resets_injury(self):
        g=self.game((EMERGENCY,BUFF,WOUND));eid=self.entity(g,UNIT,1,'board').id;self.play(g,BUFF,eid);self.play(g,WOUND,eid);self.arm(g,EMERGENCY);self.kill(g,eid)
        e=self.bodies(g)[0];self.assertEqual((e.attack,e.max_health,e.health,e.damage),(7,9,9,0))
        self.assertEqual(e.dormancy.remaining_turns,1);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.assertEqual(g.state.death_history[-1].damage,2)
        g.apply(EndTurn(2));self.assertIn(Keyword.TAUNT,self.bodies(g)[0].keywords)

    def test_emergency_is_dormant_before_first_summon_observer(self):
        g=self.game((EMERGENCY,),board=(UNIT,WATCH),mode='observe');self.arm(g,EMERGENCY);self.kill(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,21);self.assertEqual(self.bodies(g)[0].dormancy.remaining_turns,1)

    def test_emergency_preserves_silence_and_dormant_body_is_protected(self):
        g=self.game((EMERGENCY,MUTE),board=(SHIELD,),other_hand=(KILL,KILL));eid=self.entity(g,SHIELD,1,'board').id
        self.play(g,MUTE,eid);self.arm(g,EMERGENCY);self.kill(g,eid);e=self.bodies(g,SHIELD)[0]
        self.assertTrue(e.silenced);self.assertFalse(Keyword.DIVINE_SHIELD in e.keywords);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.kill(g,e.id)
        self.assertEqual(g.snapshot(),saved);g.apply(EndTurn(2));self.assertIsNone(self.bodies(g,SHIELD)[0].dormancy)

    def test_emergency_overrides_printed_timed_dormancy_and_reuses_native_awaken(self):
        g=self.game((WAKE,EMERGENCY),board=(SLEEP,));self.play(g,WAKE);eid=self.entity(g,SLEEP,1,'board').id
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,4);self.arm(g,EMERGENCY);self.kill(g,eid)
        e=self.bodies(g,SLEEP)[0];self.assertEqual(e.dormancy.remaining_turns,1)
        summons=len([x for x in g.events if x.kind=='minion_summoned']);g.apply(EndTurn(2))
        self.assertIsNone(self.bodies(g,SLEEP)[0].dormancy);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,8)
        self.assertEqual(len([x for x in g.events if x.kind=='minion_summoned']),summons)

    def test_awakening_wait_restores_owner_clock_before_draw(self):
        g=self.game((WAKE,EMERGENCY),board=(SLEEP,),mode='awake_wait');self.play(g,WAKE)
        self.arm(g,EMERGENCY);self.kill(g,self.entity(g,SLEEP,1,'board').id);g.apply(EndTurn(2))
        self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g)
        self.assertIsNone(self.bodies(g,SLEEP)[0].dormancy);self.assertEqual(g.state.active_player,1)

    def test_failed_awakening_rolls_back_clock_countdown_and_rng(self):
        g=self.game((WAKE,EMERGENCY),board=(SLEEP,),mode='awake_fail');self.play(g,WAKE)
        self.arm(g,EMERGENCY);self.kill(g,self.entity(g,SLEEP,1,'board').id);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K638 deliberate'):g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(),saved);self.assertEqual(self.bodies(g,SLEEP)[0].dormancy.remaining_turns,1)

    def test_owner_turn_and_enemy_death_do_not_consume_either_secret(self):
        for cid in native.LEAVES:
            g=self.game((cid,KILL),board=(UNIT,FILL),enemy=(FILL,),other_hand=(KILL,KILL));self.play(g,cid)
            self.play(g,KILL,self.entity(g,FILL,1,'board').id);self.assertEqual(len(g.state.players[1].secrets),1);g.apply(EndTurn(1))
            self.kill(g,self.entity(g,FILL,2,'board').id);self.assertEqual(len(g.state.players[1].secrets),1)
            self.kill(g);self.assertFalse(g.state.players[1].secrets);self.assertEqual(len(self.bodies(g)),1)

    def test_simultaneous_deaths_use_one_original_subject_and_preserve_both_deaths(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,SHIELD),other_hand=(CLEAR,));eid=self.entity(g,UNIT,1,'board').id;self.arm(g,cid);self.play(g,CLEAR,player=2)
            self.assertEqual(len(g.state.death_history),2);self.assertEqual(g.state.players[1].resources[Resource.CORPSES],2)
            self.assertEqual(len(self.bodies(g)),1);self.assertEqual(self.bodies(g)[0].origin_entity_id,eid)

    def test_original_corpse_can_already_be_back_in_hand_before_new_entry(self):
        for cid in native.LEAVES:
            g=self.game((KODO,cid,BUFF));eid=self.entity(g,UNIT,1,'board').id;self.play(g,BUFF,eid);self.play(g,KODO);self.arm(g,cid);self.kill(g,eid)
            self.assertEqual(g.state.entities[eid].zone,Zone.HAND);e=self.bodies(g)[0];self.assertEqual(e.origin_entity_id,eid)
            self.assertEqual((e.attack,e.max_health),(3,5) if cid==REDEMPTION else (7,9))
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1)

    def test_original_reborn_and_deathrattle_remain_separate_from_secret_entry(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(REBORN,));eid=self.entity(g,REBORN,1,'board').id;self.arm(g,cid);self.kill(g,eid)
            bodies=self.bodies(g,REBORN);self.assertEqual(len(bodies),2);self.assertEqual(len({e.id for e in bodies}),2)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.assertEqual(len(g.state.death_history),1)
            if cid==EMERGENCY:g.apply(EndTurn(2));bodies=self.bodies(g,REBORN)
            self.assertEqual(sum(Keyword.REBORN in e.keywords for e in bodies),1)

    def test_quantity_uses_same_material_and_separate_body_and_dormancy_ids(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,QUANTITY));self.arm(g,cid);self.kill(g);bodies=self.bodies(g)
            self.assertEqual(len(bodies),2);self.assertEqual(len({e.id for e in bodies}),2);root=g.state.card_summon_history[-1]
            self.assertEqual(root.plan.total,2);self.assertEqual(len(root.deliveries),2)
            if cid==REDEMPTION:self.assertTrue(all(e.health==1 and e.max_health==5 for e in bodies))
            else:self.assertEqual(len({e.dormancy.id for e in bodies}),2)

    def test_death_controller_receives_new_body_from_stolen_physical_owner(self):
        for cid in native.LEAVES:
            g=self.game((STEAL,cid),board=(),enemy=(UNIT,));eid=self.entity(g,UNIT,2,'board').id
            self.play(g,STEAL,eid);self.arm(g,cid);self.kill(g,eid);e=self.bodies(g)[0]
            self.assertEqual((e.owner,e.controller,e.origin_entity_id),(1,1,eid))
            self.assertEqual((g.state.death_history[-1].owner,g.state.death_history[-1].controller),(2,1))

    def test_full_extra_attempt_does_not_allocate_a_second_special_body(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,QUANTITY,FILL,FILL,FILL,FILL,FILL));self.arm(g,cid);self.kill(g)
            self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len(self.bodies(g)),1)
            self.assertEqual([x.outcome for x in g.state.card_summon_history[-1].deliveries],['delivered','board_full'])

    def test_reveal_wait_freezes_original_death_and_failure_rolls_back(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,WATCH),mode='reveal');self.arm(g,cid);self.kill(g)
            self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g);self.assertEqual(len(self.bodies(g)),1)

    def test_space_fills_after_reveal_uses_existing_failed_delivery(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,WATCH),mode='reveal');self.arm(g,cid);self.kill(g);self.choose(g,'fill');self.settle(g)
            self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.bodies(g));self.assertFalse(g.state.players[1].secrets)

    def test_entry_wait_restores_frozen_quantity_and_original_material(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,WATCH,QUANTITY),mode='entry');self.arm(g,cid);self.kill(g)
            self.assertEqual(len(self.bodies(g)),1);self.assertIsNotNone(g.state.pending_choice);self.wait_roundtrip(g)
            self.assertEqual(len(self.bodies(g)),2);self.assertEqual(len(g.state.death_history),1)

    def test_queued_public_producers_restore_and_validate_original_death(self):
        for public,cid in ((PUBLIC_R,REDEMPTION),(PUBLIC_E,EMERGENCY)):
            g=self.game((public,));g.apply(EndTurn(1));self.kill(g);g.apply(EndTurn(2));self.play(g,public)
            self.assertTrue(any(type(e)in (ResurrectOneHealth,SummonDormantDeathCopy) for e in g._frame.continuation))
            self.wait_roundtrip(g);self.assertEqual(len(self.bodies(g)),1)

    def test_rehashed_pending_producers_reject_future_death_and_allocation(self):
        for public,cid in ((PUBLIC_R,REDEMPTION),(PUBLIC_E,EMERGENCY)):
            g=self.game((public,));g.apply(EndTurn(1));self.kill(g);g.apply(EndTurn(2));self.play(g,public);saved=g.snapshot()
            changed=json.loads(json.dumps(saved));self.fields(changed,cid)[0]['death_id']+=100;self.reject(changed)
            changed=json.loads(json.dumps(saved));self.fields(changed,cid)[0]['cause']['fields']['source']['fields']['next_entity_id']+=100;self.reject(changed)

    def test_entry_materials_reject_changed_health_and_dormancy_after_rehash(self):
        for cid,key in ((REDEMPTION,'remaining_health'),(EMERGENCY,'entry_dormant_turns')):
            g=self.game((cid,),board=(UNIT,WATCH,QUANTITY),mode='entry');self.arm(g,cid);self.kill(g);saved=g.snapshot()
            for bad in (None,True,0,2):
                changed=json.loads(json.dumps(saved));changed['state']['card_summon_history'][-1]['request']['materials'][0][key]=bad;self.reject(changed)

    def test_public_effects_reject_foreign_death_and_invalid_entry_shapes(self):
        g=self.game((PUBLIC_R,),enemy=(FILL,));g.apply(EndTurn(1));self.kill(g,self.entity(g,FILL,2,'board').id);g.apply(EndTurn(2));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'original friendly'):self.play(g,PUBLIC_R)
        self.assertEqual(g.snapshot(),saved)
        h=self.game((PUBLIC_E,));h.apply(EndTurn(1));self.kill(h);h.apply(EndTurn(2));self.play(h,PUBLIC_E)
        work=next(e for e in h._frame.continuation if type(e)is SummonDormantDeathCopy)
        for changes in ({'death_id':True},{'death_id':0},{'cause':None}):
            with self.assertRaises(ValueError):replace(work,**changes)
        mat=replace(entry_from_death(h.state.death_history[-1]),entry_dormant_turns=1)
        for changes in ({'entry_dormant_turns':True},{'entry_dormant_turns':2},{'profile':'board_copy'}):
            with self.assertRaises(ValueError):replace(mat,**changes)

    def test_timed_copy_explicitly_rejects_printed_permanent_dormancy(self):
        g=self.game();g.apply(EndTurn(1));self.kill(g);mat=replace(entry_from_death(g.state.death_history[-1]),entry_dormant_turns=1)
        r=opening_registry();r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=3,health=5,dormant_turns=None,permanent_dormancy=True,metadata=metadata(tribes=())))
        with self.assertRaisesRegex(ValueError,'permanent dormancy'):validate_copy(r,mat)

    def test_failed_entry_reaction_rolls_back_death_secret_payment_and_rng(self):
        for cid in native.LEAVES:
            g=self.game((cid,),board=(UNIT,WATCH),mode='fail');self.arm(g,cid);saved=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'K638 deliberate'):self.kill(g)
            self.assertEqual(g.snapshot(),saved);self.assertFalse(g.state.death_history)

    def test_true_retry_retires_original_entries_and_keeps_ids_monotonic(self):
        for cid in native.LEAVES:
            g=self.game((cid,),other_hand=(RETRY,));self.arm(g,cid);self.play(g,RETRY,self.entity(g,UNIT,1,'board').id,player=2)
            old=(g.state.death_history[-1].id,g.state.card_summon_history[-1].id,self.bodies(g)[0].id)
            self.portable(g);self.choose(g,'retry');self.settle(g)
            new=(g.state.death_history[-1].id,g.state.card_summon_history[-1].id,self.bodies(g)[0].id)
            self.assertTrue(all(b>a for a,b in zip(old,new)));self.assertEqual(len(g.state.death_history),1)
            self.assertEqual(g.state.players[1].resources[Resource.CORPSES],1);self.assertEqual(len(self.bodies(g)),1);self.portable(g)

    def test_second_actor_and_completed_materials_remain_private(self):
        for cid in native.LEAVES:
            g=self.game((cid,),player=2);self.arm(g,cid,2);self.kill(g,p=1);self.assertEqual(len(self.bodies(g,p=2)),1)
            for player in (1,2):
                text=json.dumps((g.for_player(player).observe(),g.player_events(player)))
                for key in ('ResurrectOneHealth','SummonDormantDeathCopy','copy_source','resolution_frame','rng_state','remaining_health','entry_dormant_turns','next_entity_id'):self.assertNotIn('"'+key+'"',text)
            self.portable(g)

    def test_complete_host_real_fireball_death_and_schema_guard(self):
        for cid in native.LEAVES:
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),board=('CS2_120',),deck=('CS2_120',),mana=10,max_mana=10),
                PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_120',),mana=10,max_mana=10)),seed=109),host())
            eid=g.state.players[1].board[0];self.arm(g,cid);self.play(g,'CS2_029',eid,player=2);e=self.bodies(g,'CS2_120')[0]
            self.assertEqual(e.health,1 if cid==REDEMPTION else e.max_health);self.assertEqual(e.dormancy is not None,cid==EMERGENCY)
            saved=g.snapshot();self.assertEqual(Game.from_snapshot(saved,build_cn37_local_pool_format().registry).snapshot(),saved)
            self.assertNotIn('WON_040',host().cards);saved['schema_version']=SNAPSHOT_SCHEMA_VERSION-1
            with self.assertRaises(SnapshotError):Game.from_snapshot(saved,host())


if __name__=='__main__':unittest.main()
