"""Actual generation/history entries, original target facts and source residence."""
from copy import deepcopy
from functools import lru_cache
import json,unittest
from random import Random
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from test_past_stored_transform_recruit import fixture as stored_fixture
from hs_sim.cards import past_cast_history_followups as native,past_real_concoctions_cards as concoctions
from hs_sim.engine import EndTurn,Game,PlayerSetup,Scenario
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.model import (BoardPresenceReference,CardClass,CardDefinition,CardType,DamageKind,
    Keyword,LimitedTriggerSpec,SpellSchool,TargetSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,cast_record
from hs_sim.engine.spell_history import RecastFromHistory,RecastSpell,SpellHistoryQuery,spell_history_candidates
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone

LYRA,PUTRICIDE,ASVEDON,JACE,LYNESSA=native.ROOTS
P='k736.'
A,B,PRIEST,FOREIGN,NEUTRAL=(P+x for x in('a','b','priest','foreign','neutral'))
ZERO,BUFF,FEL,FROST,HEALFEL,KILL,ALL,STEAL,SILENCE,RETURN,AUTO,FAIL=(P+x for x in
    ('zero','buff','fel','frost','friendly_fel','kill','all','steal','silence','return','auto','fault'))
WATCH_CAST,WATCH_HAND=(P+x for x in('watch_cast','watch_hand'))
CTX=GenerationContext(P+'complete-controlled-domain','experimental')


def fixture(role='writer',mode='small'):
    return cached_fixture(role,mode)


@lru_cache(None)
def cached_fixture(role,mode):
    r,host=stored_fixture(P+role+'.'+mode,'host'if mode=='host'else'small')
    if mode!='host':
        concoctions.register_past_real_concoctions_cards(r)
        native.register_past_cast_history_followups(r)
    plain=metadata(collectible=False,tribes=())
    for cid in(A,B):
        card=CardDefinition(cid,cid,CardType.MINION,cost=3,attack=1,health=20,metadata=metadata(tribes=()))
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    def enemies(c):return(c.state.players[3-c.player_id].hero_id,*c.state.players[3-c.player_id].board)
    bodies={ZERO:lambda c:(),BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        FEL:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        FROST:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        HEALFEL:lambda c:(Buff(c.target_id,1,1,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        ALL:lambda c:(DestroyBatch(tuple(i for p in(1,2)for i in c.state.players[p].board),c.source_id),),
        STEAL:lambda c:(ChangeControl(c.target_id,c.player_id),),SILENCE:lambda c:(Silence(c.target_id),),
        RETURN:lambda c:(ReturnToHand(c.target_id),),
        AUTO:lambda c:(CastSpell(c.player_id,FEL,c.source_id,target_preference=native.AutomaticTargetPreference.ENEMY_IF_AVAILABLE),),
        PRIEST:lambda c:(GainArmor(c.player_id,2),),FOREIGN:lambda c:(),NEUTRAL:lambda c:()}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        target=(TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')if cid in(BUFF,HEALFEL,RETURN)else
            TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,STEAL,SILENCE)else
            TargetSpec()if cid in(FEL,FROST)else None)
        school=SpellSchool.FEL if cid in(FEL,HEALFEL)else SpellSchool.FROST if cid==FROST else None
        meta=metadata(CardClass.PRIEST if cid==PRIEST else CardClass.WARRIOR if cid==FOREIGN else CardClass.NEUTRAL,tribes=())if cid in(PRIEST,FOREIGN,NEUTRAL)else plain
        card=CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,spell_school=school,metadata=meta)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K736 deliberate failed continuation')))
    def wait(c):
        options=[ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage(enemies(c),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        lynessa=next((c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==LYNESSA),None)
        if lynessa is not None:
            options.append(ChoiceOption('bounce','Bounce and reenter',(ReturnToHand(lynessa.id),
                SummonFromZone(c.player_id,zone=Zone.HAND,query=PoolQuery(kinds=(CardType.MINION,),card_ids=(LYNESSA,)),
                    selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))))
            options.append(ChoiceOption('kill','Remove original',(Destroy(lynessa.id,c.source_id),)))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    for cid,event in((WATCH_CAST,'spell_cast_finished'),(WATCH_HAND,'hand_card_entered')):
        r.register_behavior(cid,wait)
        def condition(c,event=event):
            if c.event.action==0:return False
            if event=='spell_cast_finished':
                record=cast_record(c.state,dict(c.event.data)['cast_id'])
                return record.player_id==c.player_id and record.origin=='history'
            return c.event.player_id==c.player_id
        r.register_trigger_condition(cid,condition)
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=plain,
            limited_triggers=(LimitedTriggerSpec(event,cid,cid),)))
    if mode!='host':
        members=(A,B,PRIEST,FOREIGN,NEUTRAL)
        if mode=='unknown':
            card=CardDefinition(P+'unknown',P+'unknown',CardType.SPELL,metadata=metadata(CardClass.PRIEST,tribes=()))
            r.register_pool_card(PoolCard.from_definition(card));members=(*members,card.id)
        for pool in('constructed.cards','constructed.minions'):
            r.register_pool(PoolDefinition(pool,P+'complete-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in members)))
    r.validate();return r,host if mode=='host'else CTX


class CastHistoryFollowupTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode)[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,weapon=None,mode='small',seed=736):
        self.mode=mode;r,ctx=fixture('writer',mode)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',hand=hand,board=board,
            deck=(A,)*8 if deck is None else deck,mana=60,max_mana=60,mana_cap=60,armor=500,weapon_card_id=weapon),
            PlayerSetup('HERO_01',hero_power_card_id='HERO_01bp',hand=enemy_hand,board=enemy,deck=(A,)*8,
                mana=60,max_mana=60,mana_cap=60,armor=500)),seed=seed,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def faces(self,g,p=1,zone='hand'):return[g.state.entities[i].card_id for i in getattr(g.state.players[p],zone)]
    def drain(self,g):
        while g.state.pending_choice:self.choose(g,g.state.pending_choice.options[0].id)
    def fault(self,g):
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def auto_play(self,g,cid):
        entity=self.entity(g,cid);targets=g.legal_targets(entity.id)
        self.play(g,cid,targets[0]if targets else None);self.drain(g)

    def test_complete_twenty_six_roles_fifty_two_faces_and_all_original_ten_sources(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),52)
        self.assertEqual(sum(len(d[k])for k in('cards','existing_dependencies','evidence_only')),26)
        self.assertEqual(d['original_ten_source_roots'],list(native.ORIGINAL_TEN));self.assertEqual(len(d['required_next_source_roots']),5)
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(d['base_Concoction_weights'],[1]*5)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_all_five_current_host_roots_have_actual_paid_entries(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(A,),enemy=(A,),mode='host');old=g.state.players[1].mana;self.play(g,cid);self.drain(g)
                self.assertEqual(g.state.players[1].mana,old-g.registry.card(cid).cost)

    def test_Lyra_uses_complete_Priest_spell_pool_before_own_hand_spell_payload(self):
        g=self.game((ALL,),board=(LYRA,));self.play(g,ALL)
        self.assertEqual(self.faces(g),[PRIEST]);self.assertEqual(self.faces(g,zone='board'),[]);self.portable(g)

    def test_Lyra_excludes_opponent_and_automatic_spells_under_original_listener_policy(self):
        g=self.game((AUTO,),board=(LYRA,),enemy=(A,),enemy_hand=(ZERO,));self.play(g,AUTO)
        self.assertEqual(self.faces(g),[PRIEST]);g.apply(EndTurn(1));self.play(g,ZERO,player=2)
        self.assertEqual(self.faces(g).count(PRIEST),1);self.portable(g)

    def test_Lyra_silence_or_removed_original_source_prevents_new_generation(self):
        g=self.game((SILENCE,ZERO),board=(LYRA,));self.play(g,SILENCE,self.unit(g,LYRA).id)
        self.assertEqual(self.faces(g).count(PRIEST),1);self.play(g,ZERO);self.assertEqual(self.faces(g).count(PRIEST),1)

    def test_Lyra_full_hand_burn_keeps_full_pool_and_unknown_eligible_fails_atomically(self):
        g=self.game((ZERO,)+(A,)*9,board=(LYRA,LYRA));self.play(g,ZERO);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(any(e.kind=='card_burned'for e in g.events))
        g=self.game((ZERO,),board=(LYRA,),mode='unknown');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,ZERO)
        self.assertEqual(g.snapshot(),saved)

    def test_Lyra_generated_hand_notification_wait_has_portable_original_CAST(self):
        g=self.game((ZERO,),board=(LYRA,),weapon=WATCH_HAND);self.play(g,ZERO);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Putricide_generates_all_five_actual_base_Concoctions_and_each_executes(self):
        ids=tuple(sorted(native.SINGLES))
        for cid in native.SINGLES:
            with self.subTest(cid=cid):
                seed=next(n for n in range(200)if ids[Random(n).randrange(5)]==cid)
                g=self.game((KILL,),board=(PUTRICIDE,),enemy=(A,B),seed=seed);self.play(g,KILL,self.unit(g,A,2).id)
                self.assertIn(cid,self.faces(g));self.auto_play(g,cid)
                self.assertTrue(any(row.card_id==cid and row.completed for row in g.state.cast_history))
        self.portable(g)

    def test_Putricide_both_controllers_deaths_mix_two_original_physical_rewards(self):
        g=self.game((KILL,KILL),board=(PUTRICIDE,A),enemy=(A,));self.play(g,KILL,self.unit(g,A).id);self.play(g,KILL,self.unit(g,A,2).id)
        rewards=self.faces(g);self.assertEqual(len(rewards),1);self.assertNotIn(rewards[0],native.SINGLES)
        self.assertIn(rewards[0],{x['record']['id']for x in native.load_batch()['existing_dependencies']});self.auto_play(g,rewards[0]);self.portable(g)

    def test_Putricide_source_dying_in_same_batch_does_not_generate_from_dead_observer(self):
        g=self.game((ALL,),board=(PUTRICIDE,A),enemy=(A,));self.play(g,ALL)
        self.assertEqual(self.faces(g),[]);self.assertEqual(self.faces(g,zone='board'),[])

    def test_Putricide_real_reward_hand_wait_restores_mixture_and_failed_choice(self):
        g=self.game((KILL,),board=(PUTRICIDE,),enemy=(A,),weapon=WATCH_HAND);self.play(g,KILL,self.unit(g,A,2).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Asvedon_recasts_actual_last_opponent_hand_spell_not_later_automatic(self):
        g=self.game((ASVEDON,),enemy_hand=(BUFF,AUTO),enemy=(A,));g.apply(EndTurn(1));self.play(g,BUFF,self.unit(g,A,2).id,player=2);self.play(g,AUTO,player=2)
        g.apply(EndTurn(2));before=len(g.state.cast_history);mana=g.state.players[1].mana;self.play(g,ASVEDON)
        new=g.state.cast_history[before:];self.assertEqual([r.card_id for r in new if r.origin=='history'],[AUTO])
        self.assertEqual([r.card_id for r in new if r.origin=='effect'],[FEL])
        # AUTO's genuine child remains a separate effect CAST, not a selected hand occurrence.
        self.assertEqual(g.state.players[1].mana,mana-g.registry.card(ASVEDON).cost);self.portable(g)

    def test_Asvedon_no_opponent_history_has_no_CAST_or_rng(self):
        g=self.game((ASVEDON,));rng=g.snapshot()['rng_state'];self.play(g,ASVEDON)
        self.assertEqual(g.state.cast_history,[]);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertIn(Keyword.TAUNT,self.unit(g,ASVEDON).keywords)

    def test_Asvedon_history_CAST_wait_continues_exact_original_copy(self):
        g=self.game((ASVEDON,),enemy_hand=(BUFF,),enemy=(A,),weapon=WATCH_CAST);g.apply(EndTurn(1));self.play(g,BUFF,self.unit(g,A,2).id,player=2);g.apply(EndTurn(2))
        self.play(g,ASVEDON);self.assertIsNotNone(g.state.pending_choice);self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Jace_recasts_every_hand_Fel_occurrence_once_and_never_new_history(self):
        g=self.game((FEL,FEL,FROST,AUTO,JACE),enemy=(A,));self.play(g,FEL,self.unit(g,A,2).id);self.play(g,FEL,self.unit(g,A,2).id)
        self.play(g,FROST,self.unit(g,A,2).id);self.play(g,AUTO);old=len(g.state.cast_history);self.play(g,JACE)
        casts=g.state.cast_history[old:];self.assertEqual(len(casts),2);self.assertTrue(all(c.card_id==FEL and c.origin=='history'for c in casts));self.portable(g)

    def test_Jace_enemy_preference_and_friendly_only_fallback_share_original_target_rules(self):
        g=self.game((FEL,HEALFEL,JACE),board=(A,),enemy=(A,));self.play(g,FEL,self.unit(g,A,2).id);self.play(g,HEALFEL,self.unit(g,A).id)
        old=len(g.state.cast_history);self.play(g,JACE);rows=g.state.cast_history[old:];self.assertEqual(len(rows),2)
        for row in rows:self.assertEqual(row.target_origin.controller,2 if row.card_id==FEL else 1)
        self.portable(g)

    def test_Jace_random_batch_wait_retains_full_original_prefix_and_rolls_back_choice(self):
        g=self.game((FEL,FEL,JACE),enemy=(A,),weapon=WATCH_CAST);self.play(g,FEL,self.unit(g,A,2).id);self.play(g,FEL,self.unit(g,A,2).id);self.play(g,JACE)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);h=self.portable(g);self.drain(g);self.drain(h);self.assertEqual(g.snapshot(),h.snapshot())

    def test_Lynessa_uses_original_target_controller_after_control_changes(self):
        g=self.game((BUFF,STEAL,LYNESSA),board=(A,),enemy=(B,),enemy_hand=(STEAL,));original=self.unit(g,A).id
        self.play(g,BUFF,original);self.play(g,STEAL,self.unit(g,B,2).id);g.apply(EndTurn(1));self.play(g,STEAL,original,player=2);g.apply(EndTurn(2))
        rows=spell_history_candidates(g.state,g.registry,1,native.FRIENDLY)
        self.assertEqual([r.card_id for r in rows],[BUFF]);self.assertEqual(g.state.entities[original].controller,2)
        old=len(g.state.cast_history);self.play(g,LYNESSA);self.assertEqual([r.card_id for r in g.state.cast_history[old:]],[BUFF])
        self.assertEqual((self.unit(g,LYNESSA).attack,self.unit(g,LYNESSA).max_health),(3,4));self.portable(g)

    def test_Lynessa_replays_all_duplicate_friendly_target_spells_on_original_self_only(self):
        g=self.game((BUFF,BUFF,FROST,LYNESSA),board=(A,),enemy=(A,));self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);self.play(g,FROST,self.unit(g,A,2).id)
        old=len(g.state.cast_history);self.play(g,LYNESSA);rows=g.state.cast_history[old:]
        self.assertEqual(len(rows),2);self.assertTrue(all(r.card_id==BUFF and r.target_id==self.unit(g,LYNESSA).id for r in rows))
        self.assertEqual((self.unit(g,LYNESSA).attack,self.unit(g,LYNESSA).max_health),(5,7));self.portable(g)

    def test_Lynessa_returning_original_self_stops_remaining_CASTs_without_fallback(self):
        seed=next(n for n in range(100)if Random(n).randrange(3)==2)
        g=self.game((BUFF,BUFF,RETURN,LYNESSA),board=(A,),seed=seed);self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);self.play(g,RETURN,self.unit(g,A).id)
        old=len(g.state.cast_history);self.play(g,LYNESSA);self.assertEqual(len(g.state.cast_history)-old,1)
        self.assertEqual(g.state.cast_history[-1].card_id,RETURN);self.assertIn(LYNESSA,self.faces(g));self.portable(g)

    def test_Lynessa_wait_same_entity_reentry_does_not_rebind_or_consume_more_rng(self):
        g=self.game((BUFF,BUFF,LYNESSA),board=(A,),weapon=WATCH_CAST);self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);old=len(g.state.cast_history)
        self.play(g,LYNESSA);self.assertIsNotNone(g.state.pending_choice);original=self.unit(g,LYNESSA);rng=g.snapshot()['rng_state'];self.fault(g)
        h=self.portable(g);self.choose(g,'bounce');self.choose(h,'bounce');self.assertEqual(g.snapshot(),h.snapshot())
        current=self.unit(g,LYNESSA);self.assertEqual(current.id,original.id);self.assertNotEqual(current.board_presence_id,original.board_presence_id)
        self.assertEqual(len(g.state.cast_history)-old,1);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_Lynessa_wait_original_death_stops_the_accepted_remaining_batch(self):
        g=self.game((BUFF,BUFF,LYNESSA),board=(A,),weapon=WATCH_CAST);self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);old=len(g.state.cast_history)
        self.play(g,LYNESSA);self.assertIsNotNone(g.state.pending_choice);self.choose(g,'kill')
        self.assertEqual(len(g.state.cast_history)-old,1);self.assertNotIn(LYNESSA,self.faces(g,zone='board'));self.portable(g)

    def test_new_history_shapes_reject_enemy_query_mixed_preference_and_non_source_target(self):
        with self.assertRaises(ValueError):SpellHistoryQuery(side='enemy',origins=('hand',),target_policy='friendly_minion')
        with self.assertRaises(ValueError):SpellHistoryQuery(target_policy='friendly_minion')
        with self.assertRaises(ValueError):RecastSpell(1,1,9,10,'explicit',target_residence=BoardPresenceReference(9,1))
        with self.assertRaises(ValueError):RecastFromHistory(1,source_id=9,target_id=9,targeting='explicit',target_residence=BoardPresenceReference(9,1))

    def test_rehashed_wait_cannot_borrow_a_future_original_source_residence(self):
        g=self.game((BUFF,BUFF,LYNESSA),board=(A,),weapon=WATCH_CAST);self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);self.play(g,LYNESSA)
        saved=g.snapshot();changed=0
        def visit(v):
            nonlocal changed
            if isinstance(v,dict):
                for k,z in v.items():
                    if k=='target_residence'and isinstance(z,dict):
                        target=z.get('fields',z)
                        if 'presence_id'in target:target['presence_id']=g.state.next_order+100;changed+=1
                    visit(z)
            elif isinstance(v,list):
                for z in v:visit(z)
        visit(saved);self.assertGreater(changed,0)
        saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,fixture('independent-reader')[0])

    def test_both_DTOs_hide_original_target_history_query_private_frame_and_rng(self):
        g=self.game((BUFF,BUFF,LYNESSA),board=(A,),weapon=WATCH_CAST);self.play(g,BUFF,self.unit(g,A).id);self.play(g,BUFF,self.unit(g,A).id);self.play(g,LYNESSA)
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe())
            for key in('target_residence','target_policy','resolution_frame','rng_state','before_id'):self.assertNotIn('"'+key+'"',view)
        self.drain(g)
