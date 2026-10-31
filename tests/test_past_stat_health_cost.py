"""Real stat/health/cost consumers, with physical storage and current cost proofs."""
from dataclasses import replace
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_stat_health_cost as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Draw,
    GainArmor,Heal,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.hand_upgrades import BuffStoredCard,SetStoredMinionStats
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,CastWhenDrawnSpec,CostSpec,
    DamageKind,HealingKind,Keyword,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.zones import CardReference,DestroyStoredCard,DiscardCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

EMERISS,WHITE,VALANAR,ALEX,MALYGOS,HOBART,HEDANIS,MUKLA,FANOTTEM,LANA=native.ROOTS
BANANA=native.EXISTING[0]
P='k726.'
A,B,SLEEP,SPELLPOWER,ZERO,ONE,FOUR,CAST=(P+x for x in('a','b','sleep','power','zero','one','four','cast'))
BOOST,HAND_BOOST,DECK_BOOST,HUSH,WOUND,KILL,RETURN,HEAL6,HEAL4,HEAL0,HERO_HURT,DRAW=(P+x for x in
    ('boost','hand_boost','deck_boost','hush','wound','kill','return','heal6','heal4','heal0','hero_hurt','draw'))
DISCARD,DESTROY_HAND,CONTROL,COPY,DISCOUNT,DECK_THREE,CAP4,CAP1,ENEMY_CAP12=(P+x for x in
    ('discard','destroy_hand','control','copy','discount','deck_three','cap4','cap1','enemy_cap12'))
WATCH,FILL,FAIL=P+'watch',P+'fill',P+'fail'
CTX=GenerationContext(P+'stat-health-cost-fixture','experimental')


@lru_cache(None)
def full(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer',host=False):
    h=full(role);r=h.registry if host else defaults()
    if not host:
        old=h.registry.card(BANANA)
        r.register_behavior(old.on_play,h.registry.behavior(old.on_play));r.register_card(old);r.register_pool_card(h.registry.pool_card(BANANA))
        native.register_past_stat_health_cost(r)
    meta=metadata(collectible=False,tribes=())
    for cid,atk,hp,fields in((A,2,3,{}),(B,4,20,{}),(SLEEP,2,5,dict(dormant_turns=2)),(SPELLPOWER,0,10,dict(spell_damage=3))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp,metadata=meta,**fields))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def stored(c,zone):
        e=next(c.state.entities[i]for i in getattr(c.state.players[c.player_id],zone)if c.state.entities[i].kind==CardType.MINION)
        return(BuffStoredCard(CardReference.capture(e),3,4,c.source_id),)
    def first(c,kind=A):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==kind)
    def deck_three(c):
        e=c.state.entities[c.state.players[c.player_id].deck[0]]
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(set_to=3),c.source_id),)
    bodies={ZERO:lambda c:(GainArmor(c.player_id,1),),ONE:lambda c:(GainArmor(c.player_id,1),),FOUR:lambda c:(GainArmor(c.player_id,1),),
        CAST:lambda c:(GainArmor(c.player_id,2),),BOOST:lambda c:(Buff(c.target_id,3,4,c.source_id),),
        HAND_BOOST:lambda c:stored(c,'hand'),DECK_BOOST:lambda c:stored(c,'deck'),HUSH:lambda c:(Silence(c.target_id),),
        WOUND:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        RETURN:lambda c:(ReturnToHand(c.target_id),),HEAL6:lambda c:(Heal(c.target_id,6,c.source_id,HealingKind.SPELL),),
        HEAL4:lambda c:(Heal(c.target_id,4,c.source_id,HealingKind.SPELL),),HEAL0:lambda c:(Heal(c.target_id,0,c.source_id,HealingKind.SPELL),),
        HERO_HURT:lambda c:(LoseHealth(c.state.players[c.player_id].hero_id,7,c.source_id),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        DISCARD:lambda c:(DiscardCard(CardReference.capture(first(c)),c.source_id),),
        DESTROY_HAND:lambda c:(DestroyStoredCard(CardReference.capture(first(c)),c.source_id),),
        CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),),COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id),),
        DISCOUNT:lambda c:(ModifyStoredCost(CardReference.capture(first(c,FANOTTEM)),CostSpec(delta=-2),c.source_id),),
        DECK_THREE:deck_three,CAP4:lambda c:(SetHandCapacity(c.player_id,4),),CAP1:lambda c:(SetHandCapacity(c.player_id,1),),
        ENEMY_CAP12:lambda c:(SetHandCapacity(3-c.player_id,12),)}
    targeted={BOOST,HUSH,WOUND,KILL,RETURN,HEAL6,HEAL4,HEAL0,CONTROL,COPY}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);extra=dict(targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))if cid in targeted else{}
        if cid==CAST:extra.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=4 if cid==FOUR else 1 if cid==ONE else 0,on_play=cid,metadata=meta,**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K726 deliberate rollback')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        if c.event.kind=='minion_summoned'and(target is None or target.card_id!=FANOTTEM):return()
        if not(source is not None and source.card_id in native.ROOTS or target is not None and target.card_id==FANOTTEM):return()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        if source is not None and source.zone==Zone.BOARD and source.kind==CardType.MINION:
            options+=(ChoiceOption('remove','Remove original source',(Destroy(source.id,c.source_id),)),)
        remaining=[c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION and i!=c.event.target_id]
        if remaining:options+=(ChoiceOption('destroy_other','Remove next stored original',(DestroyStoredCard(CardReference.capture(remaining[0]),c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,durability=10,metadata=meta,
        triggers=tuple(TriggerSpec(e,WATCH)for e in('stored_card_buffed','stored_card_stats_set','ability_granted','card_drawn','health_resolved','minion_summoned'))))
    r.register_behavior(FILL,lambda c:(AddToHand(c.player_id,ZERO,c.source_id),)if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==MALYGOS else())
    r.register_card(CardDefinition(FILL,FILL,CardType.WEAPON,durability=10,metadata=meta,triggers=(TriggerSpec('card_drawn',FILL),)))
    r.validate();return r,h.context if host else CTX


class StatHealthCostTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,enemy_deck=None,host=False,watch=False,weapon=False,fill=False):
        self.mode='host'if host else'small';r,ctx=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,weapon_card_id=WATCH if watch else FILL if fill else 'CS2_082'if weapon else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12 if enemy_deck is None else enemy_deck,
                mana=40,max_mana=40,mana_cap=40,armor=500)),seed=726,generation_context=ctx),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def quote(self,g,cid):return quote_unselected_cost(g.state,g.registry,self.entity(g,cid)).amount
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:count+=1;self.assertLess(count,80);self.choose(g)
    def fault(self,g):
        old=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),old)

    def test_ten_complete_roots_twenty_four_primary_faces_and_unchanged_real_Banana(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),24);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(d['dependencies'],[]);self.assertEqual(d['existing_dependencies'][0]['record']['dbf_id'],1694)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))
        self.assertNotIn('MIS_701',fixture()[0].cards)

    def test_all_ten_current_host_paid_entries_execute(self):
        for cid in native.ROOTS:
            g=self.game((cid,A),deck=(ZERO,ONE,A,A),enemy=(B,),host=True)
            target=self.unit(g,B,2).id if cid==ALEX else None;sid=self.play(g,cid,target)
            self.assertTrue(g.state.play_history[0].completed);self.assertEqual(g.state.play_history[0].source_id,sid)
            if cid==EMERISS:self.assertEqual(self.entity(g,A).attack,4)
            if cid==WHITE:self.assertTrue(all(g.state.entities[i].attack==3 for i in g.state.players[1].deck if g.state.entities[i].kind==CardType.MINION))
            if cid==VALANAR:self.assertIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)
            if cid==ALEX:self.assertEqual(self.unit(g,B,2).health,12)
            if cid==MALYGOS:self.assertEqual(len(g.state.players[1].hand),3)
            if cid==HOBART:self.assertEqual(self.entity(g,A).health,3)
            if cid==HEDANIS:self.assertEqual(g.state.entities[sid].health,4)
            if cid==MUKLA:self.assertEqual(len(g.state.players[2].hand),10)
            if cid==FANOTTEM:self.assertEqual(g.state.play_history[0].cost,4)
            if cid==LANA:self.assertEqual(g.state.entities[sid].attack,1)

    def test_Emeriss_doubles_current_original_hand_stats_and_excludes_other_zones(self):
        g=self.game((HAND_BOOST,A,EMERISS,ZERO),deck=(A,),enemy_hand=(A,));self.play(g,HAND_BOOST);self.play(g,EMERISS)
        self.assertEqual((self.entity(g,A).attack,self.entity(g,A).health),(10,14));self.assertEqual(self.entity(g,A,2).health,3)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].health,3);sid=self.play(g,A)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(10,14))

    def test_Emeriss_original_group_skips_later_removed_recipient_through_wait(self):
        g=self.game((EMERISS,A,B),watch=True);self.play(g,EMERISS);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);sid=self.entity(g,B).id;self.choose(g,'destroy_other');self.finish(g)
        self.assertEqual(self.entity(g,A).health,6);self.assertEqual((g.state.entities[sid].zone,g.state.entities[sid].health),(Zone.GRAVEYARD,20));self.portable(g)

    def test_White_sets_only_current_deck_attack_and_preserves_Health_Cost_and_spells(self):
        g=self.game((DECK_BOOST,WHITE,DRAW,HUSH),deck=(A,ZERO),enemy_deck=(A,));self.play(g,DECK_BOOST);self.play(g,WHITE)
        e=g.state.entities[g.state.players[1].deck[0]];self.assertEqual((e.attack,e.health),(7,7))
        sets=[x for x in e.enchantments if x.set_attack is not None];self.assertEqual(len(sets),1);self.assertIsNone(sets[0].set_health)
        self.play(g,DRAW);sid=self.play(g,A);self.assertEqual(g.state.entities[sid].health,7);self.play(g,HUSH,sid)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(2,3))

    def test_White_attack_only_wait_restores_and_does_not_create_an_Inner_Fire_cast(self):
        g=self.game((WHITE,),deck=(A,B),watch=True);self.play(g,WHITE);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].deck],[3,20]);self.assertEqual(g.state.cast_history,[]);self.portable(g)

    def test_stored_partial_assignment_keeps_full_deck_replacement_and_cost_mixing_rejected(self):
        g=self.game(deck=(A,));e=g.state.entities[g.state.players[1].deck[0]];ref=CardReference.capture(e)
        with self.assertRaises(ValueError):SetStoredMinionStats(ref,3,3)
        with self.assertRaises(ValueError):SetStoredMinionStats(ref,3,None,cost=CostSpec(set_to=1))

    def test_Valanar_no_four_gate_includes_spells_and_reads_current_local_cost(self):
        g=self.game((VALANAR,),deck=(FOUR,));sid=self.play(g,VALANAR);self.assertNotIn(Keyword.TAUNT,g.state.entities[sid].keywords)
        g=self.game((DECK_THREE,VALANAR,HUSH),deck=(FOUR,));self.play(g,DECK_THREE);sid=self.play(g,VALANAR)
        self.assertIn(Keyword.TAUNT,g.state.entities[sid].keywords);self.assertIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)
        self.play(g,HUSH,sid);self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)

    def test_Valanar_keyword_wait_restores_original_source(self):
        g=self.game((VALANAR,),deck=(),watch=True);sid=self.play(g,VALANAR);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g);self.assertEqual(g.state.entities[sid].zone,Zone.GRAVEYARD);self.portable(g)

    def test_Alex_friendly_hero_heals_eight_and_enemy_minion_takes_exactly_eight(self):
        g=self.game((HERO_HURT,ALEX),board=(SPELLPOWER,));self.play(g,HERO_HURT);hero=g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].health,23);self.play(g,ALEX,hero);self.assertEqual(g.state.entities[hero].health,30)
        g=self.game((ALEX,),board=(SPELLPOWER,),enemy=(B,));self.play(g,ALEX,self.unit(g,B,2).id);self.assertEqual(self.unit(g,B,2).health,12)

    def test_Alex_friendly_minion_heals_and_enemy_hero_armor_loses_eight(self):
        g=self.game((WOUND,ALEX),board=(B,));sid=self.unit(g,B).id;self.play(g,WOUND,sid);self.play(g,ALEX,sid);self.assertEqual(g.state.entities[sid].health,20)
        g=self.game((ALEX,));self.play(g,ALEX,g.state.players[2].hero_id);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,492)

    def test_Alex_health_wait_restores_and_rolls_back_failed_random_choice(self):
        g=self.game((ALEX,),enemy=(B,),watch=True);self.play(g,ALEX,self.unit(g,B,2).id);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.finish(g);self.assertEqual(self.unit(g,B,2).health,12);self.portable(g)

    def test_Hedanis_self_damage_ignores_spell_bonus_and_real_overheal_hits_five(self):
        g=self.game((HEDANIS,HEAL6),board=(SPELLPOWER,));sid=self.play(g,HEDANIS);self.assertEqual(g.state.entities[sid].health,4)
        self.play(g,HEAL6,sid);self.assertEqual(g.state.entities[sid].health,8);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,495)

    def test_Hedanis_no_excess_zero_other_target_and_silence_do_not_trigger(self):
        g=self.game((HEDANIS,HEAL4,HEAL0,HEAL6,HUSH,HEAL6),board=(A,));sid=self.play(g,HEDANIS)
        for spell,target in((HEAL4,sid),(HEAL0,sid),(HEAL6,self.unit(g,A).id)):
            self.play(g,spell,target);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,500)
        self.play(g,HUSH,sid);self.play(g,HEAL6,sid);self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,500)

    def test_Hedanis_random_damage_wait_restores_actual_health_reaction(self):
        g=self.game((HEAL6,),board=(HEDANIS,),watch=True);self.play(g,HEAL6,self.unit(g,HEDANIS).id)
        self.assertIsNotNone(g.state.pending_choice);self.fault(g);g=self.portable(g);self.finish(g)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,495);self.portable(g)

    def test_Hobart_requires_actual_weapon_and_buffs_only_hand_and_deck_minions(self):
        for weapon in(False,True):
            g=self.game((HOBART,A,ZERO),board=(A,),deck=(A,ZERO),enemy_hand=(A,),weapon=weapon);self.play(g,HOBART)
            self.assertEqual(self.entity(g,A).health,5 if weapon else 3);self.assertEqual(g.state.entities[g.state.players[1].deck[0]].health,5 if weapon else 3)
            self.assertEqual(self.unit(g,A).health,3);self.assertEqual(self.entity(g,A,2).health,3)

    def test_Hobart_two_zone_wait_continues_after_original_source_dies(self):
        g=self.game((HOBART,A),deck=(A,),watch=True);self.play(g,HOBART);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.choose(g,'remove');self.finish(g);self.assertEqual(self.entity(g,A).health,5)
        self.assertEqual(g.state.entities[g.state.players[1].deck[0]].health,5);self.portable(g)

    def test_Malygos_draws_only_original_physical_spells_and_stops_empty_without_fatigue(self):
        g=self.game((MALYGOS,),deck=(A,ZERO,B,ONE,FOUR,A));self.play(g,MALYGOS)
        self.assertEqual(sorted(g.state.entities[i].card_id for i in g.state.players[1].hand),sorted((ZERO,ONE,FOUR)))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[A,B,A]);self.assertEqual(len(g.state.draw_history),3)
        self.assertTrue(all(x.completed and x.source_id==self.unit(g,MALYGOS).id for x in g.state.draw_history))
        self.assertFalse(any(e.kind=='card_burned'for e in g.events))

    def test_Malygos_full_hand_and_empty_spell_pool_preserve_rng(self):
        g=self.game((MALYGOS,)+(A,)*9,deck=(ZERO,)*4);self.play(g,MALYGOS)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.players[1].deck),3)
        for deck in((),(A,B)):
            g=self.game((MALYGOS,),deck=deck);rng=g._rng.getstate();self.play(g,MALYGOS)
            self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.draw_history,[])

    def test_Malygos_uses_actual_capacity_and_rechecks_after_each_draw_reaction(self):
        g=self.game((CAP4,MALYGOS),deck=(ZERO,)*8,fill=True);self.play(g,CAP4);self.play(g,MALYGOS)
        self.assertEqual(len(g.state.players[1].hand),4);self.assertEqual(len(g.state.draw_history),2)
        g=self.game((CAP1,MALYGOS,A,A),deck=(ZERO,)*8);self.play(g,CAP1);rng=g._rng.getstate();self.play(g,MALYGOS)
        self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual(g._rng.getstate(),rng)

    def test_Malygos_cast_when_drawn_replacements_finish_before_next_spell_tutor(self):
        g=self.game((MALYGOS,),deck=(CAST,ZERO,A));self.play(g,MALYGOS)
        self.assertTrue(any(x.card_id==CAST and x.completed for x in g.state.cast_history))
        self.assertTrue(all(g.state.entities[i].kind==CardType.MINION for i in g.state.players[1].deck))
        self.assertTrue(all(x.card_id in(CAST,ZERO)for x in g.state.draw_history if x.parent_id is None))
        replacements=[x for x in g.state.draw_history if x.parent_id is not None];self.assertEqual(len(replacements),1)
        self.assertIn(replacements[0].card_id,(ZERO,A));self.assertTrue(all(x.completed for x in g.state.draw_history))
        self.assertEqual(sorted(g.state.entities[i].card_id for i in g.state.players[1].hand+g.state.players[1].deck),sorted((ZERO,A)))

    def test_Malygos_draw_wait_restore_continues_even_after_source_removed(self):
        g=self.game((MALYGOS,),deck=(ZERO,ONE,FOUR),watch=True);self.play(g,MALYGOS);self.assertIsNotNone(g.state.pending_choice)
        self.fault(g);g=self.portable(g);self.choose(g,'remove');self.finish(g)
        self.assertEqual(len(g.state.players[1].hand),3);self.assertEqual(g.state.players[1].deck,[]);self.portable(g)

    def test_Mukla_uses_opponent_actual_capacity_existing_cards_and_real_Banana_effect(self):
        g=self.game((ENEMY_CAP12,MUKLA),enemy_hand=(A,));self.play(g,ENEMY_CAP12);self.play(g,MUKLA)
        self.assertEqual(len(g.state.players[2].hand),12);self.assertEqual(sum(g.state.entities[i].card_id==BANANA for i in g.state.players[2].hand),11)
        self.end(g);sid=self.play(g,A,player=2);self.play(g,BANANA,sid,2)
        self.assertEqual((g.state.entities[sid].attack,g.state.entities[sid].health),(3,4))

    def test_Mukla_full_enemy_hand_adds_nothing_and_Rush_is_native(self):
        g=self.game((MUKLA,),enemy_hand=(A,)*10);sid=self.play(g,MUKLA)
        self.assertEqual(len(g.state.players[2].hand),10);self.assertIn(Keyword.RUSH,g.state.entities[sid].keywords)
        self.assertFalse(any(e.card_id==BANANA for e in g.state.entities.values()))

    def test_Fanottem_quotes_exact_current_deck_size_including_above_printed_thirty(self):
        for count in(0,1,5,35):
            g=self.game((FANOTTEM,),deck=(A,)*count);self.assertEqual(self.quote(g,FANOTTEM),count)
            sid=self.play(g,FANOTTEM);self.assertEqual(g.state.play_history[-1].cost,count)
            self.assertIn(Keyword.TAUNT,g.state.entities[sid].keywords);self.assertIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)

    def test_Fanottem_requotes_after_real_draw_and_local_modifiers_apply_after_intrinsic(self):
        g=self.game((FANOTTEM,DRAW,DISCOUNT),deck=(A,)*5);self.assertEqual(self.quote(g,FANOTTEM),5)
        self.play(g,DRAW);self.assertEqual(self.quote(g,FANOTTEM),4);self.play(g,DISCOUNT);self.assertEqual(self.quote(g,FANOTTEM),2)
        self.play(g,FANOTTEM);self.assertEqual(g.state.play_history[-1].cost,2)

    def test_Fanottem_payment_wait_restores_complete_new_minion_intrinsic_fact(self):
        g=self.game((FANOTTEM,),deck=(A,)*6,watch=True);self.play(g,FANOTTEM);self.assertIsNotNone(g.state.pending_choice)
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for private in('current_deck','condition_facts','source_guard'):self.assertNotIn('"'+private+'"',view)
        self.assertEqual(g.state.play_history[-1].cost,6);self.fault(g);g=self.portable(g);self.finish(g);self.portable(g)

    def test_Fanottem_exact_finite_profile_does_not_enable_other_kinds_or_arbitrary_operands(self):
        r=fixture()[0]
        with self.assertRaises(ValueError):replace(native.DECK_PRICE,delta=-1)
        with self.assertRaises(ValueError):replace(native.DECK_PRICE,card_count=2)
        with self.assertRaises(ValueError):r._validate_card(CardDefinition(P+'bad',P+'bad',CardType.SPELL,intrinsic_costs=(native.DECK_PRICE,)))

    def test_Lana_reads_committed_discards_in_hand_deck_and_after_real_play(self):
        g=self.game((DISCARD,A,LANA),deck=(LANA,A));self.play(g,DISCARD)
        self.assertEqual(self.entity(g,LANA).attack,2);self.assertEqual(g.state.entities[g.state.players[1].deck[0]].attack,2)
        sid=self.play(g,LANA);self.assertEqual(g.state.entities[sid].attack,2);self.assertIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)

    def test_Lana_destruction_opponent_discard_and_silence_do_not_borrow_counts(self):
        g=self.game((DESTROY_HAND,A,HUSH),board=(LANA,),enemy_hand=(DISCARD,A));sid=self.unit(g,LANA).id
        self.play(g,DESTROY_HAND);self.assertEqual(g.state.entities[sid].attack,1);self.end(g);self.play(g,DISCARD,player=2)
        self.assertEqual(g.state.entities[sid].attack,1);self.end(g);self.play(g,HUSH,sid)
        self.assertNotIn(Keyword.LIFESTEAL,g.state.entities[sid].keywords)

    def test_Lana_return_current_copy_and_controller_change_use_actual_current_history(self):
        g=self.game((DISCARD,A,COPY,RETURN,CONTROL),board=(LANA,),enemy_hand=(DISCARD,A));sid=self.unit(g,LANA).id;self.play(g,DISCARD)
        self.play(g,COPY,sid);copies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==LANA]
        self.assertEqual([e.attack for e in copies],[2,2]);self.play(g,RETURN,sid);self.assertEqual(self.play(g,LANA),sid)
        self.assertEqual(g.state.entities[sid].attack,2);self.play(g,CONTROL,sid);self.assertEqual(g.state.entities[sid].attack,1)
        self.end(g);self.play(g,DISCARD,player=2);self.assertEqual(g.state.entities[sid].attack,2);self.portable(g)


if __name__=='__main__':unittest.main()
