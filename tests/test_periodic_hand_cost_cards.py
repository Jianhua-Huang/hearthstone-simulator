"""Actual native hand targets and generated cards share owner-start discounts."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

import test_native_held_opponent_copy_cards as f
from hs_sim.cards.periodic_hand_cost_cards import CARVER,CIRCADIA,EIGHT,POOL_ID,load_batch,register_periodic_hand_cost_cards
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Destroy,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,ReturnToHand)
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.hand_turn_costs import GrantHandTurnDiscount
from hs_sim.engine.model import CardClass,CardMetadata,LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard

P='k198.';EXP=P+'spell';CHEAP=P+'cheap';A=P+'eight_a';B=P+'eight_b';LOW=P+'seven';HIGH=P+'nine';SPELL=P+'eight_spell';UNKNOWN=P+'unknown';WATCH=P+'watch'
CONTEXT=GenerationContext('k198-complete-explicit-pool','experimental')


def stamps(e):return[a for a in e.enchantments if a.hand_turn_discount]


@lru_cache(maxsize=None)
def registry(mode=None):
    r=f.registry.__wrapped__(P+str(mode));register_periodic_hand_cost_cards(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K198 deliberate failure')))
    for cid,cost,kind,cls in((EXP,6,f.CardType.SPELL,CardClass.PRIEST),(CHEAP,3,f.CardType.SPELL,CardClass.PRIEST),
            (A,8,f.CardType.MINION,CardClass.PRIEST),(B,8,f.CardType.MINION,CardClass.MAGE),
            (LOW,7,f.CardType.MINION,CardClass.PRIEST),(HIGH,9,f.CardType.MINION,CardClass.PRIEST),
            (SPELL,8,f.CardType.SPELL,CardClass.PRIEST)):
        fields={'on_play':P+'noop'}if kind==f.CardType.SPELL else{'attack':5,'health':8}
        d=f.CardDefinition(cid,cid,kind,cost=cost,metadata=CardMetadata(True,(cls,),Rarity.COMMON,tribes=()),**fields)
        r.register_card(d);r.register_pool_card(PoolCard.from_definition(d))
    r.register_pool_card(PoolCard(UNKNOWN,f.CardType.MINION,8,CardMetadata(True,(CardClass.PRIEST,),Rarity.COMMON,tribes=()),battlecry=False,deathrattle=False,choose_one=False))
    members=(LOW,HIGH,SPELL)if mode=='empty'else(A,B,LOW,HIGH,SPELL)
    if mode=='unknown':members=(*members,UNKNOWN)
    r.register_pool(PoolDefinition(POOL_ID,'k198-explicit-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(x)for x in members),complete=True))
    def held(c,zone=f.Zone.HAND):
        return next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone.value)
            if stamps(c.state.entities[i]))
    def cycle(c):
        e=held(c)
        return(MoveCard(CardReference.capture(e),c.player_id,f.Zone.DECK,'top',source_id=c.source_id),f.Draw(c.player_id,source_id=c.source_id))
    def grant_fail(c):
        return(GrantHandTurnDiscount(CardReference.capture(c.state.entities[c.target_id]),c.source_id),
            RandomDamage(tuple(c.state.players[p].hero_id for p in(1,2)),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
    bodies={
        'pair':lambda c:tuple(CopyCard(CardReference.capture(held(c)),c.player_id,mode=m,source_id=c.source_id)for m in('current','base')),
        'give':lambda c:(MoveCard(CardReference.capture(held(c)),3-c.player_id,f.Zone.HAND,source_id=c.source_id),),
        'stash':lambda c:(MoveCard(CardReference.capture(held(c)),c.player_id,f.Zone.DECK,'bottom',source_id=c.source_id),),
        'pull':lambda c:(MoveCard(CardReference.capture(held(c,f.Zone.DECK)),c.player_id,f.Zone.HAND,source_id=c.source_id),),
        'change':lambda c:(TransformStoredCard(CardReference.capture(held(c)),CHEAP,c.source_id),),
        'cycle':cycle,
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'grant_fail':grant_fail,
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        fields={'targeting':f.MINION_TARGET}if name in('kill','bounce')else{'targeting':f.TargetSpec(zones=(f.Zone.HAND,),kinds=(f.CardType.SPELL,),relation='friendly')}if name=='grant_fail'else{}
        r.register_card(f.CardDefinition(P+name,P+name,f.CardType.SPELL,on_play=P+name,**fields))
    if mode in('wait','created','fill'):
        event={'wait':'cost_modified','created':'card_created','fill':'minion_summoned'}[mode]
        def eligible(c):
            if mode=='wait':
                return c.event.player_id is None and c.event.target_id is not None and bool(stamps(c.state.entities[c.event.target_id]))
            e=c.state.entities.get(c.event.target_id if mode=='created'else c.event.source_id)
            return e is not None and e.card_id in((A,B)if mode=='created'else(CIRCADIA,))
        def react(c):
            if mode=='fill':return(AddToHand(c.player_id,EXP,c.source_id),)
            if mode=='created':
                e=c.state.entities[c.event.target_id]
                if len(stamps(e))!=1 or stamps(e)[0].hand_discount_turn is not None:
                    raise ResolutionError('Generated minion missed its atomic original periodic grant')
                return(GainArmor(c.player_id,1),)
            options=[ChoiceOption('ok','Continue',()),ChoiceOption('fail','Rollback',(
                RandomDamage(tuple(c.state.players[p].hero_id for p in(1,2)),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id)))]
            later=next((c.state.entities[i]for i in c.state.players[c.player_id].hand
                if i!=c.event.target_id and stamps(c.state.entities[i])),None)
            if later is not None:
                options.append(ChoiceOption('move','Reenter later target',(
                    MoveCard(CardReference.capture(later),c.player_id,f.Zone.DECK,'top',source_id=c.source_id),f.Draw(c.player_id,source_id=c.source_id))))
                options.append(ChoiceOption('change','Change later face',(TransformStoredCard(CardReference.capture(later),CHEAP,c.source_id),)))
            return(RequestChoice(c.player_id,tuple(options),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'react',react)
        r.register_card(f.CardDefinition(WATCH,WATCH,f.CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,P+'react',condition_id=P+'eligible'),)))
    r.validate();return r


class PeriodicHandCostTests(unittest.TestCase):
    def game(self,hand=(CARVER,EXP),mode=None,actor=1,enemy_hand=()):
        self.mode=mode
        own=f.PlayerSetup(f.HERO,hand=hand,deck=(EXP,)*12,board=(WATCH,)if mode in('wait','created','fill')else(),mana=100,max_mana=100,mana_cap=100)
        other=f.PlayerSetup(f.HERO,hand=enemy_hand,deck=(A,)*12,mana=100,max_mana=100,mana_cap=100)
        return f.Game.from_scenario(f.Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=198,generation_context=CONTEXT),registry(mode))

    def eid(self,g,cid,p=None):
        p=g.state.active_player if p is None else p
        return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)

    def play(self,g,cid,target=None,entity=None):
        p=g.state.active_player;eid=self.eid(g,cid,p)if entity is None else entity
        g.apply(f.PlayCard(p,eid,target));return eid

    def price(self,g,eid):return f.quote_unselected_cost(g.state,g.registry,g.state.entities[eid]).amount

    def round(self,g):
        p=g.state.active_player;g.apply(f.EndTurn(p));g.apply(f.EndTurn(3-p))

    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(f.SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=registry.__wrapped__(self.mode)
        self.assertEqual(f.Game.from_snapshot(deepcopy(s),r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(f.replay(f.build_replay(g),r).snapshot(),s)
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('hand_discount_turn','hand_turn_discount','resolution_frame','rng_state','zone_epoch'):
                self.assertNotIn('"'+key+'"',visible)

    def reject(self,s,g):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')
        s['state_hash']=canonical_hash({k:s[k]for k in keys})
        with self.assertRaises(SnapshotError)as caught:f.Game.from_snapshot(s,g.registry)
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_complete_two_native_cards_and_two_evidence_only_enchantments(self):
        d=load_batch();r=registry()
        self.assertEqual([x['record']['id']for x in d['cards']],[CARVER,CIRCADIA])
        self.assertEqual([x['record']['id']for x in d['evidence_only']],['CATA_566e','TIME_102e'])
        self.assertEqual((r.card(CARVER).cost,r.card(CARVER).attack,r.card(CARVER).health),(3,3,2))
        self.assertEqual((r.card(CIRCADIA).cost,r.card(CIRCADIA).attack,r.card(CIRCADIA).health),(3,2,2))
        self.assertEqual(len(d['official_observations']),4)

    def test_real_hand_target_grants_without_an_upfront_discount(self):
        g=self.game();eid=self.eid(g,EXP);source=self.play(g,CARVER,eid)
        self.assertEqual(self.price(g,eid),6);self.assertEqual(len(stamps(g.state.entities[eid])),1)
        self.assertEqual(stamps(g.state.entities[eid])[0].source_id,source)
        self.assertIsNone(stamps(g.state.entities[eid])[0].hand_discount_turn);self.portable(g)

    def test_own_start_reduces_once_and_opponent_start_does_not(self):
        g=self.game();eid=self.eid(g,EXP);self.play(g,CARVER,eid)
        g.apply(f.EndTurn(1));self.assertEqual(self.price(g,eid),6)
        g.apply(f.EndTurn(2));self.assertEqual(self.price(g,eid),5)
        self.round(g);self.assertEqual(self.price(g,eid),4);self.portable(g)

    def test_empty_other_hand_keeps_existing_optional_battlecry_policy(self):
        g=self.game((CARVER,));source=self.play(g,CARVER)
        self.assertEqual(g.state.entities[source].zone,f.Zone.BOARD)
        self.assertFalse(any(stamps(e)for e in g.state.entities.values()));self.portable(g)

    def test_enemy_hand_target_is_rejected_atomically(self):
        g=self.game(enemy_hand=(EXP,));s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CARVER,self.eid(g,EXP,2))
        self.assertEqual(g.snapshot(),s)

    def test_two_independent_grants_stack_on_the_same_physical_card(self):
        g=self.game((CARVER,CARVER,EXP));eid=self.eid(g,EXP)
        self.play(g,CARVER,eid);self.play(g,CARVER,eid);self.round(g)
        self.assertEqual(self.price(g,eid),4);self.assertEqual(len(stamps(g.state.entities[eid])),2);self.portable(g)

    def test_discount_reaches_zero_through_the_ordinary_cost_floor(self):
        g=self.game((CARVER,f.B));eid=self.eid(g,f.B);self.play(g,CARVER,eid)
        self.round(g);self.assertEqual(self.price(g,eid),0)
        self.round(g);self.assertEqual(self.price(g,eid),0)

    def test_source_death_does_not_remove_the_granted_hand_effect(self):
        g=self.game((CARVER,EXP,P+'kill'));eid=self.eid(g,EXP);source=self.play(g,CARVER,eid)
        self.play(g,P+'kill',source);self.round(g)
        self.assertEqual(g.state.entities[source].zone,f.Zone.GRAVEYARD);self.assertEqual(self.price(g,eid),5)

    def test_second_player_uses_its_own_real_turn_start(self):
        g=self.game(actor=2);eid=self.eid(g,EXP);self.play(g,CARVER,eid)
        self.round(g);self.assertEqual(self.price(g,eid),5);self.portable(g)

    def test_current_copy_keeps_grant_and_local_price_but_base_copy_does_not(self):
        g=self.game((CARVER,EXP,P+'pair'));eid=self.eid(g,EXP);self.play(g,CARVER,eid);self.round(g)
        self.play(g,P+'pair');ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==EXP and(i==eid or g.state.entities[i].copy_origin is not None)]
        self.assertEqual([self.price(g,i)for i in ids],[5,5,6])
        self.assertEqual([len(stamps(g.state.entities[i]))for i in ids],[1,1,0])
        self.round(g);self.assertEqual([self.price(g,i)for i in ids],[4,4,6]);self.portable(g)

    def test_deck_residence_pauses_and_drawn_hand_resumes_the_same_grant(self):
        g=self.game((CARVER,EXP,P+'stash',P+'pull'));eid=self.eid(g,EXP);self.play(g,CARVER,eid)
        self.play(g,P+'stash');self.round(g)
        self.assertEqual(g.state.entities[eid].zone,f.Zone.DECK);self.assertEqual(self.price(g,eid),6)
        self.play(g,P+'pull');self.round(g);self.assertEqual(self.price(g,eid),5);self.portable(g)

    def test_transfer_uses_the_new_hand_controllers_future_starts(self):
        g=self.game((CARVER,EXP,P+'give'));eid=self.eid(g,EXP);self.play(g,CARVER,eid);self.play(g,P+'give')
        g.apply(f.EndTurn(1));self.assertEqual(g.state.entities[eid].controller,2)
        self.assertEqual(self.price(g,eid),5);self.portable(g)

    def test_ordinary_stored_transform_clears_the_grant_with_other_material(self):
        g=self.game((CARVER,EXP,P+'change'));eid=self.eid(g,EXP);self.play(g,CARVER,eid);self.play(g,P+'change')
        self.assertEqual(g.state.entities[eid].card_id,CHEAP);self.assertFalse(stamps(g.state.entities[eid]))
        self.round(g);self.assertEqual(self.price(g,eid),3);self.portable(g)

    def test_played_board_card_does_not_tick_and_normal_bounce_resets_it(self):
        g=self.game((CARVER,A,P+'bounce'));eid=self.eid(g,A);self.play(g,CARVER,eid);self.play(g,A,entity=eid)
        self.round(g);self.assertIsNone(stamps(g.state.entities[eid])[0].hand_discount_turn)
        self.play(g,P+'bounce',eid);self.assertFalse(stamps(g.state.entities[eid]))
        self.round(g);self.assertEqual(self.price(g,eid),8);self.portable(g)

    def test_existing_native_hand_progress_coexists_without_being_replaced(self):
        g=self.game((CARVER,f.CARD,f.P+'copy'));eid=self.eid(g,f.CARD);self.play(g,CARVER,eid);self.round(g)
        self.assertEqual(self.price(g,eid),4);self.assertEqual(f.ability(g.state.entities[eid]).progress_value,0)
        self.play(g,f.P+'copy');copied=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].copy_origin is not None)
        self.play(g,copied.card_id,entity=copied.id)
        self.assertEqual(f.ability(g.state.entities[eid]).progress_value,1);self.assertEqual(self.price(g,eid),0);self.portable(g)

    def test_first_cost_wait_saves_completed_tick_and_restores_remaining_grants(self):
        g=self.game((CARVER,CARVER,EXP),mode='wait');eid=self.eid(g,EXP)
        self.play(g,CARVER,eid);self.play(g,CARVER,eid);self.round(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.price(g,eid),5);self.portable(g)
        self.choose(g,'ok');self.assertEqual(self.price(g,eid),4);self.portable(g)

    def test_later_card_reentry_cannot_borrow_its_already_captured_start(self):
        g=self.game((CARVER,CARVER,EXP,EXP),mode='wait');ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==EXP]
        self.play(g,CARVER,ids[0]);self.play(g,CARVER,ids[1]);self.round(g);self.choose(g,'move')
        self.assertEqual([self.price(g,i)for i in ids],[5,6]);self.portable(g)

    def test_transform_clears_a_later_already_captured_periodic_attachment(self):
        g=self.game((CARVER,CARVER,EXP,EXP),mode='wait');ids=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==EXP]
        self.play(g,CARVER,ids[0]);self.play(g,CARVER,ids[1]);self.round(g);self.choose(g,'change')
        self.assertEqual(g.state.entities[ids[1]].card_id,CHEAP)
        self.assertFalse(stamps(g.state.entities[ids[1]]))
        self.assertEqual([self.price(g,i)for i in ids],[5,3]);self.portable(g)

    def test_failed_tick_choice_restores_rng_information_and_completed_prefix(self):
        g=self.game((CARVER,CARVER,EXP),mode='wait');eid=self.eid(g,EXP)
        self.play(g,CARVER,eid);self.play(g,CARVER,eid);self.round(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok');self.assertEqual(self.price(g,eid),4)

    def test_grant_failure_rolls_back_new_stamp_rng_and_payment(self):
        g=self.game((P+'grant_fail',EXP));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'grant_fail',self.eid(g,EXP))
        self.assertEqual(g.snapshot(),s)

    def test_actual_payment_uses_the_reduced_cost(self):
        g=self.game();eid=self.eid(g,EXP);self.play(g,CARVER,eid);self.round(g)
        mana=g.state.players[1].mana;self.play(g,EXP,entity=eid)
        self.assertEqual(mana-g.state.players[1].mana,5);self.portable(g)

    def test_generated_minion_has_the_grant_at_its_first_creation_notification(self):
        g=self.game((CIRCADIA,),mode='created');self.play(g,CIRCADIA)
        e=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id in(A,B))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(self.price(g,e.id),8);self.round(g);self.assertEqual(self.price(g,e.id),7);self.portable(g)

    def test_generation_keeps_the_complete_eight_cost_minion_domain(self):
        r=registry();members=resolve_candidates(r,CONTEXT,POOL_ID,EIGHT,player_id=1)
        self.assertEqual({m.card_id for m in members},{A,B})
        g=self.game((CIRCADIA,));self.play(g,CIRCADIA)
        ids=[g.state.entities[i].card_id for i in g.state.players[1].hand]
        self.assertEqual(len(ids),1);self.assertIn(ids[0],(A,B))

    def test_unknown_eligible_candidate_is_not_cropped_or_rerolled(self):
        g=self.game((CIRCADIA,),mode='unknown');s=g.snapshot()
        with self.assertRaisesRegex((ValueError,ResolutionError),UNKNOWN):self.play(g,CIRCADIA)
        self.assertEqual(g.snapshot(),s)

    def test_empty_pool_does_not_consume_randomness_or_make_a_false_card(self):
        g=self.game((CIRCADIA,),mode='empty');rng=g.snapshot()['rng_state'];self.play(g,CIRCADIA)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.assertFalse(g.state.players[1].hand)

    def test_burned_generated_card_has_complete_material_but_does_not_tick(self):
        g=self.game((CIRCADIA,*(EXP,)*9),mode='fill');self.play(g,CIRCADIA)
        e=next(e for e in g.state.entities.values()if e.card_id in(A,B)and e.owner==1)
        self.assertEqual(e.zone,f.Zone.GRAVEYARD);self.assertEqual(len(stamps(e)),1)
        self.round(g);self.assertIsNone(stamps(g.state.entities[e.id])[0].hand_discount_turn);self.portable(g)

    def test_hand_grant_declaration_rejects_deck_reference(self):
        g=self.game();e=g.state.entities[g.state.players[1].deck[0]]
        with self.assertRaises(ValueError):GrantHandTurnDiscount(CardReference.capture(e),self.eid(g,CARVER))

    def test_generated_grant_rejects_unreviewed_delivery_or_other_grant(self):
        value=GenerateFromPool(1,POOL_ID,EIGHT,source_id=1,minion_grant=CreatedMinionGrant(special='hand_turn_discount'))
        for changes in({'destination':'deck'},{'count':2},{'source_id':None},{'minion_grant':CreatedMinionGrant(special='prepare')}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(value,**changes)

    def test_rehashed_future_tick_or_inconsistent_flag_is_rejected(self):
        g=self.game();eid=self.eid(g,EXP);self.play(g,CARVER,eid)
        for flag,last in((True,g.state.turn+1),(False,1)):
            s=g.snapshot();row=s['state']['entities'][str(eid)]['enchantments'][0]
            row['hand_turn_discount']=flag;row['hand_discount_turn']=last;self.reject(s,g)

    def test_previous_399_schema_is_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=399
        with self.assertRaises(SnapshotError):f.Game.from_snapshot(s,g.registry)
