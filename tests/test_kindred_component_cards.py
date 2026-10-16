"""Actual next-Kindred sources repeat only their native qualified component."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.kindred_component_cards import load_batch,BATCH_HASH,PREFIX
from hs_sim.engine import (CardDefinition,CardMetadata,CardClass,CardType,CastWhenDrawnSpec,DamageKind,EndTurn,
    Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

CHALLENGER='TLC_251';PRIMER='DINO_435';THIEF='TLC_429';TOKEN='TLC_429t';YETI='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry(mode=None):
    r=build_registry()
    bodies=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        bounce=lambda c:(ReturnToHand(c.target_id),),give=lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        transform=lambda c:(Transform(c.target_id,YETI),),summon=lambda c:(Summon(c.player_id,THIEF),),
        cast=lambda c:(CastSpell(c.player_id,'TLC_440',c.source_id,c.state.players[2].hero_id,targeting='explicit'),),
        fail=lambda c:(AddToHand(c.player_id,'k68.missing',c.source_id),),
        auto=lambda c:(Damage(c.state.players[2].hero_id,1,c.source_id,DamageKind.SPELL),))
    for name,body in bodies.items():
        r.register_behavior('k68.'+name,body)
        if name=='fail':continue
        extra=dict(spell_school=SpellSchool.FIRE,keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())if name=='auto'else{}
        r.register_card(CardDefinition('k68.'+name,name,CardType.SPELL,on_play='k68.'+name,
            requires_target=name in('kill','silence','bounce','give','transform'),metadata=META,**extra))
    r.register_behavior('k68.noop',lambda c:())
    for school in(SpellSchool.FROST,SpellSchool.FIRE,SpellSchool.HOLY,SpellSchool.NATURE,SpellSchool.SHADOW,SpellSchool.FEL):
        r.register_card(CardDefinition('k68.'+school.value,school.value,CardType.SPELL,on_play='k68.noop',spell_school=school,metadata=META))
    for name,attack,health in(('large',1,20),('larger',8,20)):
        r.register_card(CardDefinition('k68.'+name,name,CardType.MINION,attack=attack,health=health,metadata=META))
    r.register_card(CardDefinition('k68.dormant','Dormant physical endpoint',CardType.MINION,attack=1,health=20,dormant_turns=2,metadata=META))
    if mode:
        def watch(c):
            event=c.event
            target=c.state.entities.get(event.target_id if event.kind=='minion_summoned'else event.source_id)
            wanted=TOKEN if mode in('wait','late_fail','depart')else 'TLC_600'
            if target is None or target.card_id!=wanted:return()
            if mode in('late_fail','price_fail'):return(InvokeBehavior('k68.fail',c.source_id,c.player_id),)
            original=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==THIEF),None)
            extras=(ChoiceOption('depart','Return original thief',(ReturnToHand(original),)),)if mode=='depart'and original is not None else()
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',(GainArmor(c.state.players[1].hero_id,1),)),
                ChoiceOption('bad','Fail',(InvokeBehavior('k68.fail',c.source_id,c.player_id),)),*extras),source_id=c.source_id),)
        key='k68.watch.'+mode;r.register_behavior(key,watch)
        r.register_card(CardDefinition(key,'Actual boundary fixture',CardType.MINION,health=20,metadata=META,
            triggers=(TriggerSpec('minion_summoned'if mode in('wait','late_fail','depart')else'minion_counter_check',key),)))
    return r


def rehash(saved):
    saved['events_hash']=canonical_hash(saved['events'])
    saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
    return saved


def wires(value,name):
    if isinstance(value,dict):
        if value.get('type','').endswith('.'+name):yield value
        for x in value.values():yield from wires(x,name)
    elif isinstance(value,list):
        for x in value:yield from wires(x,name)


class KindredComponentCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(YETI,)*12,mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=enemy,hand=enemy_hand,deck=(YETI,)*12,mana=50,max_mana=50,mana_cap=50)),seed=1068),self.r if mode is None else registry(mode))
    def entities(self,g,cid,p=1,zone='board'):
        s=g.state;return[s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid]
    def play(self,g,cid,target=None,p=1):
        eid=self.entities(g,cid,p,'hand')[0].id;g.apply(PlayCard(p,eid,target));return eid
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def qualified(self,hand,primer=PRIMER,**kwargs):
        g=self.game((primer,CHALLENGER,*hand),**kwargs);self.play(g,primer);self.cycle(g);self.play(g,CHALLENGER);return g
    def price(self,g,cid):return quote_cost(g.state,g.registry,self.entities(g,cid,zone='hand')[0]).amount
    def portable(self,g,mode=None):
        saved=g.snapshot();other=Game.from_snapshot(saved,registry(mode));self.assertEqual(other.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def drain(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def waiting(self,mode='wait'):
        g=self.qualified((THIEF,),board=('k68.watch.'+mode,),mode=mode);self.play(g,THIEF)
        self.assertIsNotNone(g.state.pending_choice);return g
    def test_complete_root_and_seventeen_native_profiles(self):
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH)
        self.assertEqual((len(d['cards']),len(d['reviewed_consumers'])),(1,17))
        self.assertTrue({x['record']['id']for x in d['reviewed_consumers']}.issubset(self.r.kindred_profiles))
        for row in d['cards']+d['reviewed_consumers']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        c=self.r.card(CHALLENGER);self.assertEqual((c.cost,c.attack,c.health,c.metadata.tribes),(3,3,2,('murloc',)))
        self.assertIsNotNone(c.battlecry);self.assertEqual({k for k,v in self.r.kindred_profiles.items()if v.mode=='cost'},{'TLC_366','TLC_600','TLC_816'})
    def test_qualified_thief_summons_four_real_tokens_and_pays_once(self):
        g=self.qualified((THIEF,));before=g.state.players[1].mana;self.play(g,THIEF)
        self.assertEqual(len(self.entities(g,TOKEN)),4);self.assertEqual(g.state.players[1].mana,before-self.r.card(THIEF).cost)
        row=g.state.kindred_history[-1];self.assertEqual((row.plan,row.finished,row.completed),(('active','active'),(0,1),True));self.portable(g)
    def test_only_next_kindred_is_doubled(self):
        g=self.qualified(('TLC_903',THIEF));self.play(g,'TLC_903');self.play(g,THIEF)
        self.assertEqual(len(self.entities(g,TOKEN)),2);self.assertEqual([x.repetitions for x in g.state.kindred_history[-2:]],[2,1])
    def test_unqualified_kindred_consumes_pending_source_local_policy(self):
        g=self.game((CHALLENGER,THIEF,'TLC_903'));self.play(g,CHALLENGER);self.play(g,THIEF)
        self.assertFalse(g.state.players[1].player_effects);self.assertFalse(self.entities(g,TOKEN))
        self.assertFalse(g.state.kindred_history[-1].condition.matched);self.assertEqual(g.state.kindred_history[-1].plan,());self.portable(g)
    def test_non_kindred_card_leaves_next_source_pending(self):
        g=self.game((CHALLENGER,YETI));self.play(g,CHALLENGER);self.play(g,YETI)
        self.assertEqual(len(g.state.players[1].player_effects),1);self.assertFalse(g.state.kindred_history)
    def test_opponent_kindred_does_not_consume_owner_source(self):
        g=self.game((CHALLENGER,),enemy_hand=(THIEF,));self.play(g,CHALLENGER);g.apply(EndTurn(1));self.play(g,THIEF,p=2)
        self.assertEqual(len(g.state.players[1].player_effects),1);self.assertEqual(g.state.kindred_history[-1].player_id,2)
    def test_multiple_pending_sources_use_max_two_and_each_consumes_once(self):
        g=self.qualified((CHALLENGER,THIEF));self.play(g,CHALLENGER);self.play(g,THIEF)
        self.assertEqual(len(g.state.kindred_history[-1].sources),2);self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(len(self.entities(g,TOKEN)),3) # Four attempts, original board has only three free slots.
        self.assertEqual(g.state.kindred_history[-1].repetitions,2);self.portable(g)
    def test_real_repeated_challenger_battlecry_installs_independent_sources(self):
        g=self.game((CHALLENGER,),board=('TIME_064',));self.play(g,CHALLENGER)
        sources=g.state.players[1].player_effects;self.assertEqual(len(sources),2);self.assertEqual(len({x.id for x in sources}),2);self.portable(g)
    def test_real_repeated_consumer_battlecries_accept_independently(self):
        g=self.qualified(('TLC_454',),board=('TIME_064',),enemy=('k68.large','k68.larger',YETI))
        self.play(g,'TLC_454');rows=[x for x in g.state.kindred_history if x.card_id=='TLC_454']
        self.assertEqual([x.repetitions for x in rows],[2,1]);self.assertEqual([len(x.sources)for x in rows],[2,0]);self.assertFalse(g.state.players[2].board);self.portable(g)
    def test_source_death_silence_control_and_bounce_do_not_revoke_player_effect(self):
        for action in('kill','silence','give','bounce'):
            with self.subTest(action=action):
                g=self.qualified((THIEF,'k68.'+action));eid=self.entities(g,CHALLENGER)[0].id;self.play(g,'k68.'+action,eid);self.play(g,THIEF)
                self.assertEqual(g.state.kindred_history[-1].repetitions,2);self.assertEqual(len(self.entities(g,TOKEN)),4)
    def test_direct_summon_does_not_run_native_kindred(self):
        g=self.qualified(('k68.summon',));before=len(g.state.kindred_history);self.play(g,'k68.summon')
        self.assertEqual(len(g.state.kindred_history),before);self.assertFalse(self.entities(g,TOKEN));self.assertEqual(len(g.state.players[1].player_effects),1)
    def test_queen_repeats_temporary_attack_and_expires_normally(self):
        g=self.qualified(('TLC_903',));self.play(g,'TLC_903');hero=g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].attack,10);g.apply(EndTurn(1));self.assertEqual(g.state.entities[hero].attack,0);self.portable(g)
    def test_self_copy_components_copy_original_without_recursive_kindred(self):
        for cid in(PRIMER,'TLC_226'):
            with self.subTest(card=cid):
                g=self.qualified((cid,));before=len(self.entities(g,cid));self.play(g,cid)
                self.assertEqual(len(self.entities(g,cid)),before+3);self.assertEqual(g.state.kindred_history[-1].started,('active','active'));self.portable(g)
    def test_firegill_repeats_only_other_friendly_rush_grants(self):
        g=self.qualified(('DINO_404',),board=(YETI,),enemy=(YETI,));eid=self.play(g,'DINO_404')
        e=self.entities(g,YETI)[0];self.assertEqual(len([a for a in e.abilities if a.keyword==Keyword.RUSH]),2)
        self.assertNotIn(Keyword.RUSH,g.state.entities[eid].keywords);self.assertNotIn(Keyword.RUSH,self.entities(g,YETI,2)[0].keywords)
    def test_drake_repeated_immune_is_same_temporary_residence(self):
        g=self.qualified(('TLC_243',));eid=self.play(g,'TLC_243');self.assertEqual(len([a for a in g.state.entities[eid].abilities if a.keyword==Keyword.IMMUNE]),2)
        g.apply(EndTurn(1));self.assertNotIn(Keyword.IMMUNE,g.state.entities[eid].keywords)
    def test_diabolus_reselects_current_edges_for_each_component(self):
        g=self.qualified(('DINO_138',),enemy=('k68.large','k68.larger'));self.play(g,'DINO_138')
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[8,8]);self.portable(g)
    def test_diabolus_dormant_endpoint_keeps_its_physical_slot_in_both_components(self):
        g=self.qualified(('DINO_138',),enemy=('k68.dormant','k68.large'));self.play(g,'DINO_138')
        self.assertFalse(self.entities(g,'k68.dormant',2)[0].active)
        self.assertEqual(self.entities(g,'k68.dormant',2)[0].health,20);self.assertEqual(self.entities(g,'k68.large',2)[0].health,8)
        self.portable(g)
    def test_kodo_replacement_reselects_highest_after_each_death(self):
        g=self.qualified(('TLC_454',),enemy=('k68.large','k68.larger',YETI));self.play(g,'TLC_454')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],['k68.large']);self.assertEqual(len(g.state.death_history),2)
    def test_razidir_replacement_discards_opponent_twice_and_no_own_card(self):
        g=self.qualified(('TLC_463',),enemy_hand=(YETI,)*4);own=len(g.state.players[1].hand);self.play(g,'TLC_463')
        self.assertEqual(len(g.state.players[1].hand),own-1);self.assertEqual(len(g.state.players[2].hand),3) # Opponent drew one at turn start.
        self.assertEqual([x.player_id for x in g.state.discard_history],[2,2]);self.portable(g)
    def test_unqualified_replacement_runs_ordinary_branch_once(self):
        g=self.game((CHALLENGER,'TLC_463',YETI),enemy_hand=(YETI,)*3);self.play(g,CHALLENGER);self.play(g,'TLC_463')
        self.assertEqual([x.player_id for x in g.state.discard_history],[1]);self.assertEqual(len(g.state.players[2].hand),3)
    def test_thrasher_draws_once_and_both_local_bonuses_stay_on_original(self):
        g=self.qualified(('TLC_223',),deck=(YETI,'CORE_CS2_029',YETI));before=len(g.state.draw_history);self.play(g,'TLC_223')
        e=self.entities(g,'CORE_CS2_029',zone='hand')[0];self.assertEqual([a.spell_damage for a in e.abilities if a.kind=='spell_damage'],[2,2])
        self.assertEqual(len(g.state.draw_history),before+1);self.play(g,'CORE_CS2_029',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20);self.portable(g)
    def test_thrasher_both_bonuses_precede_actual_cast_when_drawn(self):
        g=self.qualified(('TLC_223',),deck=(YETI,'k68.auto',YETI));self.play(g,'TLC_223')
        cast=g.state.cast_history[-1];self.assertEqual((cast.origin,len(cast.local_spell_damage)),('draw',2))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.portable(g)
    def test_hybrid_draws_each_cost_once_and_reduces_original_group_twice(self):
        cards=('CORE_EX1_008','TLC_427','TLC_251',YETI)
        g=self.qualified(('TLC_236',),primer='k68.nature',deck=(YETI,*cards));before=len(g.state.draw_history);self.play(g,'TLC_236')
        draws=g.state.draw_history[before:];self.assertEqual(len(draws),4);self.assertEqual({x.card_id for x in draws},set(cards))
        self.assertEqual([quote_cost(g.state,g.registry,g.state.entities[x.entity_id]).amount for x in draws],[0,0,1,2]);self.portable(g)
    def test_glider_discount_once_but_shield_reward_twice(self):
        g=self.qualified(('TLC_428','TLC_427'));self.play(g,'TLC_428');self.assertEqual(self.price(g,'TLC_427'),1)
        eid=self.play(g,'TLC_427');self.assertEqual(len([a for a in g.state.entities[eid].abilities if a.keyword==Keyword.DIVINE_SHIELD]),2)
        self.assertFalse(g.state.players[1].cost_modifiers);self.portable(g)
    def test_cryo_deals_four_once_and_draws_one_plus_two(self):
        g=self.qualified(('TLC_440',),primer='k68.frost');before=len(g.state.draw_history);self.play(g,'TLC_440',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.assertEqual(len(g.state.draw_history),before+3)
        self.assertEqual(g.state.kindred_history[-1].plan,('prepare',));self.portable(g)
    def test_ablating_destroys_once_then_two_fresh_damage_waves(self):
        g=self.qualified(('TLC_447',),primer='k68.fel',enemy=(YETI,'k68.large','k68.larger'))
        self.play(g,'TLC_447',self.entities(g,YETI,2)[0].id)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[16,16])
        row=g.state.kindred_history[-1];self.assertEqual((row.plan,row.finished),(('prepare','active','active'),(1,2,0)));self.portable(g)
    def test_three_intrinsic_prices_quote_twice_without_consuming(self):
        for cid,primer,expected in(('TLC_366',PRIMER,2),('TLC_600',PRIMER,4),('TLC_816','k68.holy',0)):
            with self.subTest(card=cid):
                g=self.qualified((cid,),primer=primer);saved=g.snapshot()
                self.assertEqual(self.price(g,cid),expected);self.assertEqual(self.price(g,cid),expected);self.assertEqual(g.snapshot(),saved)
    def test_whelp_pays_once_but_ordinary_battlecry_does_not_repeat(self):
        g=self.qualified(('TLC_600',));before=g.state.players[1].mana;self.play(g,'TLC_600',g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana,before-4);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.assertEqual(len(g.state.cost_use_history[-1].kindred_sources),1)
        self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_zero_price_holy_still_consumes_one_source_and_draws_two_once(self):
        g=self.qualified(('TLC_816',),primer='k68.holy');before=g.state.players[1].mana;draws=len(g.state.draw_history);self.play(g,'TLC_816')
        self.assertEqual(g.state.players[1].mana,before);self.assertEqual(len(g.state.draw_history),draws+2)
        self.assertEqual(len(g.state.cost_use_history[-1].kindred_sources),1);self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_unqualified_static_price_is_full_but_consumes_source_local_policy(self):
        g=self.game((CHALLENGER,'TLC_600'));self.play(g,CHALLENGER);self.assertEqual(self.price(g,'TLC_600'),8);self.play(g,'TLC_600',g.state.players[2].hero_id)
        self.assertEqual(g.state.play_history[-1].cost,8);self.assertFalse(g.state.players[1].player_effects);self.portable(g)
    def test_later_source_does_not_rewrite_old_empty_intrinsic_source_prefix(self):
        g=self.game((PRIMER,'TLC_600',CHALLENGER,'TLC_366'));self.play(g,PRIMER);self.cycle(g)
        self.play(g,'TLC_600',g.state.players[2].hero_id);self.play(g,CHALLENGER);self.assertEqual(self.price(g,'TLC_366'),2);self.portable(g)
    def test_actual_effect_cast_runs_kindred_without_fabricated_hand_play(self):
        g=self.qualified(('k68.cast',),primer='k68.frost');before=len(g.state.play_history);self.play(g,'k68.cast')
        self.assertEqual(len(g.state.play_history),before+1);self.assertEqual(g.state.cast_history[-1].origin,'effect')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.assertEqual(g.state.kindred_history[-1].repetitions,2);self.portable(g)
    def test_waiting_restore_clone_and_replay_keep_full_accepted_plan(self):
        g=self.waiting();other=self.portable(g,'wait');self.assertFalse(g.state.players[1].player_effects)
        self.drain(g);self.drain(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.entities(g,TOKEN)),3)
        self.assertEqual(g.state.kindred_history[-1].finished,(0,1));self.portable(g,'wait')
    def test_bad_choice_rolls_back_without_consuming_second_component(self):
        g=self.waiting();saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(1,q.id,('absent',)))
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.drain(g);self.assertTrue(g.state.kindred_history[-1].completed)
    def test_late_component_failure_rolls_back_payment_sources_rng_and_history(self):
        g=self.qualified((THIEF,),board=('k68.watch.late_fail',),mode='late_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,THIEF)
        self.assertEqual(g.snapshot(),saved)
    def test_late_static_failure_rolls_back_payment_receipt_and_source(self):
        g=self.qualified(('TLC_600',),board=('k68.watch.price_fail',),mode='price_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'TLC_600',g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),saved)
    def test_departed_original_thief_still_finishes_already_accepted_component(self):
        g=self.waiting('depart');self.choose(g,'depart');self.drain(g)
        self.assertEqual(len(self.entities(g,TOKEN)),4);self.assertEqual(len(self.entities(g,THIEF,zone='hand')),1);self.portable(g,'depart')
    def test_rehashed_waiting_truncated_second_component_is_rejected(self):
        g=self.waiting();saved=g.snapshot()
        work=[x for key in('prefix','continuation')for x in saved['resolution_frame']['fields'][key]['tuple']]
        self.assertEqual(sum(x.get('type','').endswith('.RunKindredComponent')for x in work),1)
        def remove(value):
            if isinstance(value,dict):
                for x in value.values():remove(x)
            elif isinstance(value,list):
                value[:]=[x for x in value if not(isinstance(x,dict)and x.get('type','').endswith('.RunKindredComponent'))]
                for x in value:remove(x)
        # Also remove its copied work in the original paid-hand choice boundary,
        # so this exercises the Kindred plan proof rather than only that wrapper.
        remove(saved['resolution_frame'])
        self.assertFalse(list(wires(saved['resolution_frame'],'RunKindredComponent')))
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(rehash(saved),registry('wait'))
        self.assertIn('Kindred',str(caught.exception))
    def test_rehashed_wrong_role_is_rejected_before_resume(self):
        g=self.waiting();saved=g.snapshot();item=next(wires(saved['resolution_frame'],'RunKindredComponent'));item['fields']['role']='inactive'
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry('wait'))
    def test_rehashed_dropped_root_finish_marker_is_rejected(self):
        g=self.waiting();saved=g.snapshot()
        def remove(value):
            if isinstance(value,dict):
                for x in value.values():remove(x)
            elif isinstance(value,list):
                value[:]=[x for x in value if not(isinstance(x,dict)and x.get('type','').endswith('.FinishKindred'))]
                for x in value:remove(x)
        remove(saved['resolution_frame']);self.assertFalse(list(wires(saved['resolution_frame'],'FinishKindred')))
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry('wait'))
        saved=g.snapshot();work=saved['resolution_frame']['fields']['continuation']['tuple']
        end=next(x for x in work if isinstance(x,dict)and x.get('type','').endswith('.FinishKindred'))
        work.remove(end);work.insert(0,end)
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry('wait'))
    def test_rehashed_completed_history_cannot_drop_accepted_component(self):
        g=self.qualified((THIEF,));self.play(g,THIEF);saved=g.snapshot();saved['state']['kindred_history'][-1]['plan']=['active']
        saved['state']['kindred_history'][-1]['started']=['active'];saved['state']['kindred_history'][-1]['finished']=[0]
        with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(saved),registry())
    def test_terminal_hero_death_interrupts_remaining_kindred_without_fabricated_completion(self):
        # The setup fixture uses the ordinary public damage effect, never state mutation.
        r=registry();r.register_behavior('k68.lethal_setup',lambda c:(Damage(c.state.players[2].hero_id,26,c.source_id),))
        r.register_card(CardDefinition('k68.lethal_setup','Health setup',CardType.SPELL,on_play='k68.lethal_setup',metadata=META))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('k68.frost',CHALLENGER,'TLC_440','k68.lethal_setup'),deck=(YETI,)*6,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*6)),seed=1068),r)
        self.play(g,'k68.frost');self.cycle(g);self.play(g,CHALLENGER);self.play(g,'k68.lethal_setup');before=len(g.state.draw_history)
        self.play(g,'TLC_440',g.state.players[2].hero_id);row=g.state.kindred_history[-1]
        self.assertEqual(g.state.status,'finished');self.assertFalse(row.completed);self.assertIsNotNone(row.interruption);self.assertEqual(len(g.state.draw_history),before)
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(g.clone().snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())
    def test_queries_are_pure_and_private_acceptance_state_is_not_projected(self):
        g=self.waiting();saved=g.snapshot()
        for p in(1,2):
            view=json.dumps(g.for_player(p).observe(),ensure_ascii=False);g.for_player(p).legal_actions()
            for private in('kindred_history','KindredActivation','original','repetitions','kindred_sources'):
                self.assertNotIn('"'+private+'"',view)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
