"""Niri's real paid plays and automatic casts share accepted cost facts."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.one_cost_play_provider_card import CARD,load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CastSpell,CastStoredSpell,
    CastWhenDrawnSpec,Game,Keyword,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,TriggerSpec,Zone)
from hs_sim.engine.effects import (AddCostModifier,ChoiceOption,Destroy,Draw,GainArmor,RequestChoice,ReturnToHand,
    Silence,Summon,InvokeBehavior)
from hs_sim.engine.model import CostSpec,PaymentType,RepeatCostFilter,RepeatMatchSpec,SpellRepeatSpec,TargetSpec
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest

P='niri.test.'
M1,M2,S1,S2,CWD,CHOICE,WATCH,FILL=(P+x for x in ('m1','m2','s1','s2','cwd','choice','watch','fill'))


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,1),))
    for cid,cost in ((M1,1),(M2,2),(FILL,0)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=3,battlecry=P+'bc',metadata=meta))
    def spell(cid,body,cost=0,**kw):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=cid,metadata=meta,**kw))
    for cid,cost in ((S1,1),(S2,2)):
        spell(cid,lambda c:(GainArmor(c.player_id,2),),cost)
    spell(CWD,lambda c:(GainArmor(c.player_id,3),),1,cast_when_drawn=CastWhenDrawnSpec(),keywords=(Keyword.CASTS_WHEN_DRAWN,))
    def fail(c):raise ResolutionError('Niri deliberately failing selected branch')
    r.register_behavior(P+'fail',fail)
    spell(CHOICE,lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',(GainArmor(c.player_id,2),)),
        ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),source_id=c.source_id),),1)
    spell(P+'auto',lambda c:(CastSpell(c.player_id,S1,c.source_id),))
    spell(P+'auto_two',lambda c:(CastSpell(c.player_id,S2,c.source_id),))
    spell(P+'auto_siphon',lambda c:(CastSpell(c.player_id,'EDR_531',c.source_id,
        next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==FILL),targeting='explicit'),))
    spell(P+'auto_choice',lambda c:(CastSpell(c.player_id,CHOICE,c.source_id,choices='player'),))
    spell(P+'stored',lambda c:(CastStoredSpell(CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]]),c.player_id,c.source_id),))
    spell(P+'draw',lambda c:(Draw(c.player_id,source_id=c.source_id),))
    spell(P+'summon',lambda c:(Summon(c.player_id,M1,c.source_id),))
    spell(P+'silence',lambda c:(Silence(c.target_id),),requires_target=True)
    def kill_source(c):
        target=next((i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==CARD),None)
        return (*((Destroy(target,c.source_id),)if target is not None else()),GainArmor(c.player_id,1))
    spell(P+'kill_source',kill_source,1)
    spell(P+'auto_kill',lambda c:(CastSpell(c.player_id,P+'kill_source',c.source_id),))
    for key,spec in (('discount',CostSpec(delta=-1)),('increase',CostSpec(delta=1)),('health',CostSpec(payment=PaymentType.HEALTH))):
        spell(P+key,lambda c,s=spec:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),s,c.source_id),),
            targeting=TargetSpec(zones=(Zone.HAND,Zone.DECK),kinds=(CardType.MINION,CardType.SPELL),relation='friendly'))
    spell(P+'next_discount',lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.SPELL,)),uses_remaining=1,source_id=c.source_id),))
    spell(P+'live_discount',lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.SPELL,)),source_id=c.source_id),))
    def watch(c):
        row=c.state.cast_history[dict(c.event.data)['cast_id']-1]
        return (GainArmor(2,1),)if row.card_id==S1 else()
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,metadata=meta,triggers=(TriggerSpec('spell_cast_accepted',WATCH),)))
    def return_played(c):
        row=c.state.play_history[dict(c.event.data)['play_id']-1]
        if row.card_id!=M1:return ()
        return (ReturnToHand(row.source_id),InvokeBehavior(P+'resummon',row.source_id,row.player_id))
    r.register_behavior(P+'resummon',lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.source_id]),c.player_id),))
    r.register_behavior(P+'returner',return_played)
    r.register_card(CardDefinition(P+'returner','Earlier listener',CardType.MINION,health=10,metadata=meta,triggers=(TriggerSpec('card_played',P+'returner'),)))
    r.validate();r.freeze();return r


class OneCostPlayProviderTests(unittest.TestCase):
    def game(self,hand=(S1,),board=(CARD,),enemy=(),deck=(FILL,)*5):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,deck=(FILL,)*5,mana=50,max_mana=50,mana_cap=50)),seed=226836),registry('writer'))
    def entity(self,g,cid,zone='board',pid=1):
        return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=S1,target=None,pid=1):
        e=self.entity(g,cid,'hand',pid);g.apply(PlayCard(pid,e.id,target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
    def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry('reader');self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        snap=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(snap,r)
        self.assertEqual(other.snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),r).snapshot(),snap)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','rng_state','SourceAllocationFact','quote_input','native_spell_repeat_accepted'):
                self.assertNotIn(key,public)
        return other
    def test_a00_paid_one_cost_spell_is_two_actual_casts_one_payment_one_play(self):
        g=self.game(board=(CARD,WATCH));self.play(g)
        self.assertEqual((self.armor(g),self.armor(g,2),g.state.players[1].mana),(4,2,49))
        self.assertEqual([(x.origin,x.iteration)for x in g.state.cast_history],[('hand',1),('repeat',2)])
        self.assertEqual(len(g.state.play_history),1);self.portable(g)
    def test_a01_generated_cast_is_repeated_without_fabricating_a_payment_or_play(self):
        g=self.game(hand=(P+'auto',),board=(CARD,WATCH));self.play(g,P+'auto')
        self.assertEqual((self.armor(g),self.armor(g,2),g.state.players[1].mana),(4,2,50))
        self.assertEqual([x.origin for x in g.state.cast_history],['hand','effect','native_repeat'])
        self.assertEqual(len(g.state.play_history),1);self.portable(g)
    def test_a02_one_cost_minion_stats_double_after_its_actual_battlecry(self):
        g=self.game(hand=(M1,));eid=self.play(g,M1);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health,e.max_health,self.armor(g),g.state.players[1].mana),(4,6,6,1,49));self.portable(g)
    def test_a03_full_raw_root_and_two_evidence_only_enchantments(self):
        d=load_batch();self.assertEqual([x['record']['id']for x in d['evidence_only']],['TLC_836e','TLC_836e2'])
        for row in (*d['cards'],*d['evidence_only']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertFalse(d['policy']['formal_pool_complete']);self.assertFalse(d['policy']['cn_calibrated'])
        self.assertEqual(len(d['official_observations']),2)
    def test_b00_paid_minion_uses_original_price_after_discount_or_increase(self):
        for cid,prep,expected in ((M2,'discount',(4,6)),(M1,'increase',(2,3))):
            with self.subTest(cid=cid):
                g=self.game(hand=(P+prep,cid));target=self.entity(g,cid,'hand').id;self.play(g,P+prep,target);self.play(g,cid)
                e=g.state.entities[target];self.assertEqual((e.attack,e.health),expected)
    def test_b01_consumed_discount_does_not_make_repeat_recheck_the_later_price(self):
        g=self.game(hand=(P+'next_discount',S2));self.play(g,P+'next_discount');self.play(g,S2)
        self.assertEqual((self.armor(g),g.state.players[1].mana),(4,49));self.assertEqual(len(g.state.cast_history),3);self.portable(g)
    def test_b02_zero_cost_spell_and_increased_one_cost_spell_do_not_repeat(self):
        for prep in ('discount','increase'):
            with self.subTest(prep=prep):
                g=self.game(hand=(P+prep,S1));target=self.entity(g,S1,'hand').id;self.play(g,P+prep,target);self.play(g)
                self.assertEqual(self.armor(g),2);self.assertFalse(any(x.origin=='repeat'for x in g.state.cast_history))
    def test_b03_one_cost_health_payment_still_repeats_once(self):
        g=self.game(hand=(P+'health',S1));target=self.entity(g,S1,'hand').id;self.play(g,P+'health',target);self.play(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,g.state.entities[g.state.players[1].hero_id].health),(4,50,29))
    def test_b04_real_siphoning_growth_gains_armor_only_from_destroying_the_original_target(self):
        for cid in ('EDR_531',P+'auto_siphon'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,),board=(CARD,FILL));target=self.entity(g,FILL).id
                self.play(g,cid,target if cid=='EDR_531'else None)
                self.assertEqual((self.armor(g),g.state.entities[target].zone),(8,Zone.GRAVEYARD))
                self.assertEqual(len([x for x in g.state.cast_history if x.card_id=='EDR_531']),2)
    def test_c00_stored_spell_uses_original_local_price_and_preserves_physical_source(self):
        g=self.game(hand=(P+'discount',P+'stored'),deck=(S2,FILL));eid=g.state.players[1].deck[0]
        self.play(g,P+'discount',eid);self.play(g,P+'stored')
        self.assertEqual(self.armor(g),4);self.assertEqual([x.source_id for x in g.state.cast_history if x.card_id==S2],[eid,eid]);self.portable(g)
    def test_c01_automatic_quote_observes_actual_live_discount_and_never_charges(self):
        for driver,armor in (('auto',2),('auto_two',4)):
            with self.subTest(driver=driver):
                g=self.game(hand=(P+'live_discount',P+driver));self.play(g,P+'live_discount');self.play(g,P+driver)
                self.assertEqual((self.armor(g),g.state.players[1].mana),(armor,50))
                self.assertEqual(len([x for x in g.state.cast_history if x.origin=='native_repeat']),int(driver=='auto_two'))
    def test_c02_drawn_spell_repeats_its_cast_but_has_only_one_replacement_draw(self):
        g=self.game(hand=(P+'draw',),deck=(CWD,FILL));eid=g.state.players[1].deck[0];self.play(g,P+'draw')
        self.assertEqual(self.armor(g),6);self.assertEqual([x.outcome for x in g.state.draw_history],['cast','hand'])
        self.assertEqual([x.source_id for x in g.state.cast_history[1:]],[eid,eid]);self.assertEqual(g.state.players[1].mana,50);self.portable(g)
    def test_c03_two_providers_share_twice_plan_without_recursive_automatic_casts(self):
        for cid in (S1,P+'auto'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,),board=(CARD,CARD));self.play(g,cid);self.assertEqual(self.armor(g),4)
                self.assertEqual(len([x for x in g.state.cast_history if x.card_id==S1]),2)
    def test_d00_automatic_waiting_restores_both_casts_and_failed_choice_rolls_back(self):
        g=self.game(hand=(P+'auto_choice',));self.play(g,P+'auto_choice');other=self.portable(g);snap=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g,'fail')
        self.assertEqual(g.snapshot(),snap)
        for game in (g,other):
            self.select(game);self.assertIsNotNone(game.state.pending_choice);self.select(game)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),4);self.portable(g)
    def test_d01_paid_waiting_keeps_one_original_price_and_one_payment(self):
        g=self.game(hand=(CHOICE,));self.play(g,CHOICE);self.portable(g);self.select(g);self.portable(g);self.select(g)
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,49,1))
    def test_d02_accepted_repeat_survives_provider_death_in_original_payload(self):
        for driver in ('kill_source','auto_kill'):
            with self.subTest(driver=driver):
                g=self.game(hand=(P+driver,));source=self.entity(g,CARD).id;self.play(g,P+driver)
                self.assertEqual((self.armor(g),g.state.entities[source].zone),(2,Zone.GRAVEYARD));self.portable(g)
    def test_e00_effect_summon_and_enemy_provider_do_not_double_a_play(self):
        g=self.game(hand=(P+'summon',));self.play(g,P+'summon');e=self.entity(g,M1)
        self.assertEqual((e.attack,e.health),(2,3))
        g=self.game(hand=(M1,),board=(),enemy=(CARD,));eid=self.play(g,M1);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health),(2,3))
    def test_e01_silenced_source_stops_future_minion_and_spell_modifications(self):
        g=self.game(hand=(P+'silence',M1,S1));self.play(g,P+'silence',self.entity(g,CARD).id);eid=self.play(g,M1);self.play(g)
        e=g.state.entities[eid];self.assertEqual((e.attack,e.health,self.armor(g)),(2,3,3))
    def test_e02_original_minion_leaving_and_reentering_is_not_rebound(self):
        g=self.game(hand=(M1,),board=(P+'returner',CARD));eid=self.play(g,M1);e=g.state.entities[eid]
        self.assertEqual((e.attack,e.health),(2,3));self.portable(g)
    def test_e03_unreviewed_cost_profiles_are_rejected_before_registration(self):
        from hs_sim.engine.repeat_matching import validate_repeat_cost_declaration
        for cost in (0,2):
            spec=SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(recipient_cost=RepeatCostFilter('cast_quote',minimum=cost,maximum=cost)))
            with self.assertRaises(ValueError):validate_repeat_cost_declaration(registry('writer'),spec)
