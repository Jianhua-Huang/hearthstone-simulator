"""Five real native entries and their original physical history boundaries."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_native_conditional_triggers as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,ForceAttack,
    GainArmor,GrantKeyword,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.local_pool_format import build_cn37_local_pool_format

VANESSA,KORVAS,ETC,LIADRIN,ZAVAS=native.ROOTS
P='k719.'
A,B,LOW,RUSH,FRAIL,OUT,NOOP,WEAPON=(P+x for x in ('plain','high','low','rush','frail','outcast','noop','weapon'))
KILL,HUSH,BOOST,SHAPE,GRANT,FORCE,DISC,GROW,AUTO,SUMMON=(P+x for x in ('kill','hush','boost','shape','grant','force','discard','grow','auto','summon'))
WAIT,FILL,FAIL=P+'wait',P+'fill',P+'fail'
CTX=GenerationContext(P+'explicit-native-fixture','experimental')


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format()if host else None;r=h.registry if h else defaults()
    if not host:native.register_past_native_conditional_triggers(r)
    meta=metadata(collectible=False,tribes=())
    for cid,attack,health,kw in ((A,2,6,()),(B,4,7,()),(LOW,1,2,()),
            (RUSH,2,4,(Keyword.RUSH,)),(FRAIL,2,1,(Keyword.RUSH,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=health,keywords=kw,metadata=meta))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=1,attack=2,durability=2,metadata=meta))
    r.register_behavior(NOOP,lambda c:())
    for cid in (NOOP,OUT):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=NOOP,
        keywords=(Keyword.OUTCAST,)if cid==OUT else (),metadata=meta))
    def discard(c):
        target=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ZAVAS)
        return(DiscardCard(CardReference.capture(target),c.source_id),)
    def grow(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==ZAVAS)
        return(BuffStoredCard(CardReference.capture(e),3,2,c.source_id,cost=CostSpec(delta=-1)),)
    helpers={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        BOOST:lambda c:(Buff(c.target_id,3,4,c.source_id),),SHAPE:lambda c:(Transform(c.target_id,B),),
        GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),),
        FORCE:lambda c:(ForceAttack(c.target_id,c.state.players[3-c.player_id].hero_id),),DISC:discard,GROW:grow,
        AUTO:lambda c:(CastSpell(c.player_id,OUT,c.source_id),),
        SUMMON:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(LOW),),SummonCause.capture(c)),)}
    for cid,body in helpers.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=meta,
            **({'targeting':TargetSpec()}if cid in(KILL,HUSH,BOOST,SHAPE,GRANT,FORCE)else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ValueError('K719 deliberate rollback')))
    def wait(c):
        event=c.event;target=c.state.entities.get(event.target_id);source=c.state.entities.get(event.source_id)
        qualifies=(event.kind=='ability_granted'and target is not None and target.card_id==LOW and Keyword.DIVINE_SHIELD in target.keywords or
            event.kind=='card_returned'and target is not None and target.card_id in(KORVAS,ZAVAS)or
            event.kind in('card_created','damage_dealt')and source is not None and source.card_id in(VANESSA,ETC))
        if not qualifies:return ()
        options=[ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))]
        if target is not None and target.zone==Zone.BOARD:options.append(ChoiceOption('bounce','Bounce original target',(ReturnToHand(target.id),)))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(WAIT,wait)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=20,metadata=meta,triggers=tuple(
        TriggerSpec(event,WAIT)for event in('card_created','card_returned','ability_granted','damage_dealt'))))
    r.register_behavior(FILL,lambda c:tuple(AddToHand(c.player_id,A,c.source_id)for _ in range(10))
        if c.event.player_id==c.player_id else ())
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=20,metadata=meta,triggers=(TriggerSpec('card_discarded',FILL),)))
    r.validate();return r,h.context if h else CTX


class PastNativeConditionalTriggerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),host=False):
        self.mode='host'if host else 'small';r,context=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*16,
            mana=40,max_mana=40,mana_cap=40,armor=500),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*16,
            mana=40,max_mana=40,mana_cap=40,armor=500)),seed=719,generation_context=context),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def finish(self,g):
        n=0
        while g.state.pending_choice is not None:
            n+=1;self.assertLess(n,20);self.choose(g)
    def enemy_play(self,g,cid):
        g.apply(EndTurn(1));eid=self.play(g,cid,player=2);g.apply(EndTurn(2));return eid
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_five_faces_twelve_primary_responses_and_uncropped_past(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),12);self.assertFalse(d['complete_past_source_bound'])
        self.assertNotIn('MIS_701',fixture()[0].cards)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_Vanessa_Combo_copies_last_opponent_play_across_turns(self):
        g=self.game((NOOP,VANESSA),enemy_hand=(A,));original=self.enemy_play(g,A)
        self.play(g,NOOP);source=self.play(g,VANESSA);copy=self.entity(g,A)
        self.assertNotEqual(copy.id,original);self.assertEqual((copy.attack,copy.max_health,copy.cost),(2,6,1))
        self.assertEqual(g.state.players[1].mana,38);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_Vanessa_without_Combo_or_opponent_history_gets_no_card(self):
        g=self.game((VANESSA,),enemy_hand=(A,));self.enemy_play(g,A)
        old=tuple(i for i in g.state.players[1].hand if g.state.entities[i].card_id==A);self.play(g,VANESSA)
        self.assertEqual(tuple(i for i in g.state.players[1].hand if g.state.entities[i].card_id==A),old)
        g=self.game((NOOP,VANESSA));self.play(g,NOOP);self.play(g,VANESSA)
        self.assertEqual(g.state.players[1].hand,[])

    def test_Vanessa_uses_original_played_face_after_transform_and_buffs(self):
        g=self.game((BOOST,SHAPE,VANESSA),enemy_hand=(A,));original=self.enemy_play(g,A)
        self.play(g,BOOST,original);self.play(g,SHAPE,original);self.play(g,VANESSA)
        e=self.entity(g,A);self.assertEqual((e.attack,e.max_health),(2,6));self.assertEqual(g.state.entities[original].card_id,B)

    def test_Vanessa_copies_weapon_and_actual_auto_producer_instead_of_effect_cast(self):
        for cid in (WEAPON,AUTO):
            with self.subTest(cid=cid):
                g=self.game((NOOP,VANESSA),enemy_hand=(cid,));self.enemy_play(g,cid)
                self.play(g,NOOP);self.play(g,VANESSA);self.assertEqual(self.entity(g,cid).cost,g.registry.card(cid).cost)

    def test_Vanessa_copy_notification_wait_restores_and_rolls_back_invalid_choice(self):
        g=self.game((NOOP,VANESSA),board=(WAIT,),enemy_hand=(A,));self.enemy_play(g,A)
        self.play(g,NOOP);self.play(g,VANESSA);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.entity(g,A).attack,2)

    def test_Korvas_has_actual_Charge_and_Lifesteal_and_returns_after_Outcast_card(self):
        g=self.game((KORVAS,OUT),enemy=(A,));source=self.play(g,KORVAS)
        self.assertTrue({Keyword.CHARGE,Keyword.LIFESTEAL}<=g.state.entities[source].keywords)
        g.apply(Attack(1,source,g.state.players[2].hero_id));self.play(g,OUT)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(g.state.entities[source].attacks_this_turn,0)
        self.portable(g)

    def test_Korvas_Outcast_keyword_matches_even_when_bonus_was_not_active(self):
        g=self.game((NOOP,OUT,NOOP),board=(KORVAS,));source=self.unit(g,KORVAS).id
        self.play(g,OUT);row=g.state.play_history[-1]
        self.assertEqual((row.hand_index,row.hand_size),(1,3));self.assertEqual(g.state.entities[source].zone,Zone.HAND)

    def test_Korvas_ordinary_and_opponent_cards_do_not_return_it(self):
        g=self.game((NOOP,),board=(KORVAS,),enemy_hand=(OUT,));source=self.unit(g,KORVAS).id
        self.play(g,NOOP);g.apply(EndTurn(1));self.play(g,OUT,player=2)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_Korvas_silence_suppresses_and_return_resets_local_buff(self):
        g=self.game((HUSH,OUT),board=(KORVAS,));source=self.unit(g,KORVAS).id
        self.play(g,HUSH,source);self.play(g,OUT);self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
        g=self.game((BOOST,OUT),board=(KORVAS,));source=self.unit(g,KORVAS).id
        self.play(g,BOOST,source);self.play(g,OUT)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(2,2))

    def test_Korvas_return_waiting_continues_independent_restored_game(self):
        g=self.game((OUT,),board=(KORVAS,WAIT));self.play(g,OUT)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.entity(g,KORVAS).cost,2)

    def test_ETC_real_Rush_attack_deals_two_ability_damage_to_enemy_hero(self):
        g=self.game((ETC,RUSH),enemy=(A,));source=self.play(g,ETC);rush=self.play(g,RUSH)
        before=g.state.entities[g.state.players[2].hero_id].armor;g.apply(Attack(1,rush,self.unit(g,A,2).id))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,before-2)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_ETC_Rush_attacker_that_dies_uses_frozen_original_keywords(self):
        g=self.game((FRAIL,),board=(ETC,),enemy=(B,));rush=self.play(g,FRAIL)
        before=g.state.entities[g.state.players[2].hero_id].armor;g.apply(Attack(1,rush,self.unit(g,B,2).id))
        self.assertEqual(g.state.entities[rush].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,before-2);self.portable(g)

    def test_ETC_current_granted_Rush_matches_and_non_Rush_does_not(self):
        for grant in (False,True):
            with self.subTest(grant=grant):
                g=self.game((GRANT,FORCE),board=(ETC,A));attacker=self.unit(g,A).id
                if grant:self.play(g,GRANT,attacker)
                before=g.state.entities[g.state.players[2].hero_id].armor;self.play(g,FORCE,attacker)
                self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,before-2-(2 if grant else 0))

    def test_ETC_silenced_original_Rush_no_longer_qualifies(self):
        g=self.game((HUSH,FORCE),board=(ETC,RUSH));attacker=self.unit(g,RUSH).id
        self.play(g,HUSH,attacker);before=g.state.entities[g.state.players[2].hero_id].armor
        self.play(g,FORCE,attacker);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,before-2)

    def test_ETC_actual_damage_choice_restores_and_rng_failure_is_atomic(self):
        g=self.game((RUSH,),board=(ETC,WAIT),enemy=(A,));rush=self.play(g,RUSH)
        g.apply(Attack(1,rush,self.unit(g,A,2).id));self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g)

    def test_Liadrin_actual_played_and_effect_summons_receive_both_keywords(self):
        g=self.game((LIADRIN,LOW,SUMMON));self.play(g,LIADRIN);first=self.play(g,LOW);self.play(g,SUMMON)
        targets=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==LOW]
        self.assertEqual(len(targets),2)
        for e in targets:self.assertTrue({Keyword.DIVINE_SHIELD,Keyword.RUSH}<=e.keywords)
        self.assertIn(first,[e.id for e in targets]);self.portable(g)

    def test_Liadrin_strict_lower_current_Attack_and_no_self_or_enemy_grant(self):
        g=self.game((LIADRIN,A,B),enemy_hand=(LOW,));source=self.play(g,LIADRIN)
        self.play(g,A);self.play(g,B);g.apply(EndTurn(1));self.play(g,LOW,player=2)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
        self.assertNotIn(Keyword.RUSH,self.unit(g,B).keywords);self.assertNotIn(Keyword.RUSH,self.unit(g,LOW,2).keywords)

    def test_Liadrin_uses_buffed_source_Attack_and_silence_stops_trigger(self):
        g=self.game((BOOST,B),board=(LIADRIN,));self.play(g,BOOST,self.unit(g,LIADRIN).id);self.play(g,B)
        self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,B).keywords)
        g=self.game((HUSH,LOW),board=(LIADRIN,));self.play(g,HUSH,self.unit(g,LIADRIN).id);self.play(g,LOW)
        self.assertNotIn(Keyword.RUSH,self.unit(g,LOW).keywords)

    def test_Liadrin_second_keyword_keeps_original_residence_across_real_wait(self):
        g=self.game((LOW,),board=(WAIT,LIADRIN));source=self.play(g,LOW)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.choose(g,'bounce');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords)
        self.portable(g)

    def test_Zavas_real_discard_returns_same_physical_card_with_growth(self):
        g=self.game((DISC,ZAVAS));before=self.entity(g,ZAVAS);source=self.play(g,DISC);after=self.entity(g,ZAVAS)
        self.assertEqual((after.id,after.attack,after.max_health),(before.id,4,4));self.assertNotEqual(after.hand_entry_id,before.hand_entry_id)
        self.assertEqual(g.state.discard_history[0].source_id,source);self.portable(g)

    def test_Zavas_new_acquisitions_repeat_and_keep_prior_growth_cost(self):
        g=self.game((GROW,DISC,DISC,ZAVAS));self.play(g,GROW);original=self.entity(g,ZAVAS).id
        self.play(g,DISC);self.play(g,DISC);after=self.entity(g,ZAVAS)
        self.assertEqual((after.id,after.attack,after.max_health,after.cost),(original,9,8,1))
        self.assertEqual(len(g.state.discard_history),2);self.portable(g)

    def test_Zavas_full_hand_return_keeps_discard_and_explicit_overflow(self):
        g=self.game((DISC,ZAVAS),board=(FILL,));original=self.entity(g,ZAVAS).id;self.play(g,DISC)
        self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.discard_history),1)

    def test_Zavas_return_waiting_restores_original_discard_and_payment(self):
        g=self.game((DISC,ZAVAS),board=(WAIT,));self.play(g,DISC)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual((self.entity(g,ZAVAS).attack,self.entity(g,ZAVAS).max_health),(4,4))

    def test_all_five_actual_standard_host_entries_and_native_effects(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                hand=(NOOP,cid,OUT,LOW,DISC)+((RUSH,)if cid==ETC else ())
                g=self.game(hand,enemy_hand=(A,),host=True);self.enemy_play(g,A)
                self.play(g,NOOP)
                if cid==ZAVAS:self.play(g,DISC);self.assertEqual(self.entity(g,ZAVAS).attack,4)
                else:
                    source=self.play(g,cid);self.assertEqual(g.state.entities[source].zone,Zone.BOARD)
                    if cid==VANESSA:self.assertEqual(self.entity(g,A).attack,2)
                    elif cid==KORVAS:self.play(g,OUT);self.assertEqual(self.entity(g,KORVAS).cost,2)
                    elif cid==LIADRIN:self.play(g,LOW);self.assertIn(Keyword.RUSH,self.unit(g,LOW).keywords)
                    elif cid==ETC:
                        rush=self.play(g,RUSH);before=g.state.entities[g.state.players[2].hero_id].armor
                        g.apply(Attack(1,rush,self.unit(g,A,2).id))
                        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,before-2)

