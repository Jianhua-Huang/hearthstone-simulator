"""Five real public-fact consumers, full Discover and one ordinary persistent family."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json,unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_history_spell_cost_treants as native
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    Draw,GainArmor,InvokeBehavior,RandomDamage,ReplaceHeroPower,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.model import (BattlecryRepeatSpec,CardDefinition,CardType,DamageKind,Keyword,
    TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerationContext,PoolCard,resolve_candidates
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.local_pool_format import build_cn37_local_pool_format
from tools import card_batch as cb

KELIDAN,MORDRESH,KALECGOS,KAELTHAS,GORU=native.ROOTS
TREE=native.EXISTING[0];P='k722.'
A,B,SLEEP,AMPLIFIER,REPEAT,AUTO=(P+x for x in('a','b','sleep','amplifier','repeat','auto'))
DRAW1,CREATE,KILL,HUSH,BOUNCE,CONTROL,BOOST,COPY,REVIVE,SUMMON2,REPLACE,SPELL10,S0,S3=(
    P+x for x in('draw1','create','kill','hush','bounce','control','boost','copy','revive','summon2','replace','spell10','s0','s3'))
POWER9,POWER10,WATCH,FAIL=(P+x for x in('power9','power10','watch','fail'))
CTX=GenerationContext(P+'original-public-facts-fixture','experimental')


@lru_cache(None)
def fixture(role='writer',host=False):
    h=build_cn37_local_pool_format()if host else None;r=h.registry if h else defaults()
    if not host:
        raw=native.load_batch()['existing_dependencies'][0]['record']
        r.register_card(CardDefinition(TREE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
            health=raw['health'],metadata=metadata_from_record(raw)))
        r.register_pool_card(PoolCard.from_definition(r.card(TREE)))
        native.register_past_history_spell_cost_treants(r)
    meta=metadata(collectible=False,tribes=())
    for cid,attack,hp,fields in((A,2,6,{}),(B,4,8,{}),(SLEEP,1,3,dict(dormant_turns=2)),
            (AMPLIFIER,0,12,dict(spell_damage=4)),(REPEAT,0,20,dict(battlecry_repeats=(BattlecryRepeatSpec(2),))),
            (AUTO,1,5,dict(on_play=AUTO))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=hp,metadata=meta,**fields))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,S0,c.source_id),CastSpell(c.player_id,S0,c.source_id)))
    for cid,amount in((POWER9,9),(POWER10,10)):
        r.register_behavior(cid,lambda c,n=amount:(Damage(c.target_id,n,c.source_id,DamageKind.HERO_POWER),))
        r.register_card(CardDefinition(cid,cid,CardType.HERO_POWER,cost=2,on_use=cid,targeting=TargetSpec(),metadata=meta))
    def revive(c):
        death=next(x for x in reversed(c.state.death_history)if x.card_id==TREE)
        return(ResurrectMinion(c.player_id,death.id,source_id=c.source_id,cause=SummonCause.capture(c)),)
    bodies={DRAW1:lambda c:(Draw(c.player_id,1,c.source_id),),CREATE:lambda c:(AddToHand(c.player_id,KELIDAN,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),CONTROL:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        BOOST:lambda c:(Buff(c.target_id,3,4,c.source_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),REVIVE:revive,
        SUMMON2:lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))for cid in(A,B)),
        REPLACE:lambda c:(ReplaceHeroPower(c.player_id,POWER9,source_id=c.source_id),),
        SPELL10:lambda c:(Damage(c.target_id,10,c.source_id,DamageKind.SPELL),),
        S0:lambda c:(GainArmor(c.player_id,1),),S3:lambda c:(GainArmor(c.player_id,1),)}
    targeted={KILL,HUSH,BOUNCE,CONTROL,BOOST,COPY,SPELL10}
    for cid,body in bodies.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3 if cid==S3 else 0,
            on_play=cid,metadata=meta,**({'targeting':TargetSpec()}if cid in targeted else {})))
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ResolutionError('K722 deliberate rollback')))
    def wait(c):
        source=c.state.entities.get(c.event.source_id)
        active=any(row.card_id==KELIDAN and row.payload_started and not row.completed for row in c.state.battlecry_history)
        qualifies=(c.event.kind=='minion_died'and active or c.event.kind=='damage_dealt'and source is not None and source.card_id==MORDRESH or
            c.event.kind=='player_effect_added'and source is not None and source.card_id==GORU)
        aura=next((c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id in(KALECGOS,KAELTHAS)),None)
        if c.event.kind=='card_committed'and source is not None and source.card_id==S3 and aura is not None:qualifies=True
        if not qualifies:return ()
        options=(ChoiceOption('continue','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fault','Fault after RNG',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))))
        if aura is not None:options+=(ChoiceOption('remove','Remove original cost source',(Destroy(aura.id,c.source_id),)),)
        return(RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.WEAPON,attack=0,durability=30,metadata=meta,
        triggers=tuple(TriggerSpec(k,WATCH)for k in('minion_died','damage_dealt','player_effect_added','card_committed'))))
    r.validate();return r,h.context if h else CTX


class PastHistorySpellCostTreantTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:fixture(role,mode=='host')[0])
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=None,watch=False,host=False,power=POWER10,hero='HERO_08'):
        self.mode='host'if host else'small';r,context=fixture('writer',host)
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(A,)*12 if deck is None else deck,
            mana=40,max_mana=40,mana_cap=40,armor=500,hero_power_card_id=power,weapon_card_id=WATCH if watch else None),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12,mana=40,max_mana=40,mana_cap=40,
                armor=500,hero_power_card_id=POWER10)),seed=722,generation_context=context),r)
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def armor(self,g,p=2):return g.state.entities[g.state.players[p].hero_id].armor
    def finish(self,g):
        count=0
        while g.state.pending_choice is not None:
            count+=1;self.assertLess(count,30);choice=g.state.pending_choice
            ids={o.id for o in choice.options};self.choose(g,'continue'if'continue'in ids else choice.options[0].id)
    def fault(self,g):
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved)
    def power(self,g,target=None,p=1):g.apply(UseHeroPower(p,g.state.players[p].hero_power_id,target or g.state.players[3-p].hero_id))

    def test_complete_rows_twelve_faces_full_29_predicate_and_no_coverage_filter(self):
        d=native.load_batch();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),12);self.assertEqual(len(d['treant_family']['card_ids']),29)
        self.assertEqual(len(d['treant_family']['known_missing_definition_ids']),7)
        self.assertTrue(set(d['treant_family']['known_missing_definition_ids'])<=set(d['treant_family']['card_ids']))
        self.assertFalse(d['complete_past_source_bound']);self.assertNotIn('MIS_701',fixture()[0].cards)
        for cid in native.ROOTS:self.assertEqual(fixture()[0].card(cid),fixture('independent-reader')[0].card(cid))

    def test_only_exact_Mordresh_complete_display_markers_are_accepted(self):
        d=native.load_batch();raw=next(x['record']for x in d['cards']if x['record']['id']==MORDRESH)
        for locale in('zh_CN','en_US'):
            face=next(x['face']for x in d['official_observations']if(x['card_id'],x['locale'])==(MORDRESH,locale))
            before=deepcopy(raw);cb.check_face(raw,face,locale,{'@':'','{0}':''});self.assertEqual(raw,before)
            for mapping in(None,{'@':''},{'@':'','{0}':'9'}):
                with self.assertRaises(ValueError):cb.check_face(raw,face,locale,mapping)
            changed=deepcopy(raw)
            for key in('text','text_en'):changed[key]=changed[key].replace('10','9')
            with self.assertRaises(ValueError):cb.check_face(changed,face,locale,{'@':'','{0}':''})
            changed=deepcopy(face);changed['attack']+=1
            with self.assertRaises(ValueError):cb.check_face(raw,changed,locale,{'@':'','{0}':''})

    def test_Kelidan_normal_paid_hand_destroys_only_selected_minion(self):
        g=self.game((KELIDAN,),board=(A,),enemy=(B,));target=self.unit(g,B,2).id
        source=self.play(g,KELIDAN,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history),1);self.assertEqual(self.unit(g,A).attack,2)
        self.assertEqual(g.state.players[1].mana,40-g.registry.card(KELIDAN).cost);self.assertEqual(g.state.entities[source].zone,Zone.BOARD)

    def test_Kelidan_undrawn_missing_arrow_rejects_before_payment_and_empty_board_is_known_empty(self):
        g=self.game((KELIDAN,),enemy=(B,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,KELIDAN)
        self.assertEqual(g.snapshot(),saved)
        g=self.game((KELIDAN,));source=self.play(g,KELIDAN);self.assertEqual(g.state.players[1].board,[source])

    def test_Kelidan_actual_same_turn_draw_has_no_arrow_and_destroys_both_boards_except_source(self):
        g=self.game((DRAW1,),board=(A,),enemy=(B,SLEEP),deck=(KELIDAN,A))
        self.play(g,DRAW1);source=self.play(g,KELIDAN)
        self.assertEqual(g.state.players[1].board,[source]);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],[SLEEP])
        self.assertEqual({d.card_id for d in g.state.death_history},{A,B})

    def test_Kelidan_generated_and_previous_turn_draws_do_not_enable_area_mode(self):
        for created in(False,True):
            with self.subTest(created=created):
                g=self.game((CREATE if created else DRAW1,),board=(A,),enemy=(B,),deck=(KELIDAN,A))
                self.play(g,CREATE if created else DRAW1)
                if not created:g.apply(EndTurn(1));g.apply(EndTurn(2))
                self.play(g,KELIDAN,self.unit(g,B,2).id);self.assertEqual(self.unit(g,A).attack,2)

    def test_Kelidan_bounce_reentry_does_not_borrow_original_draw(self):
        g=self.game((DRAW1,BOUNCE,SUMMON2),enemy=(B,),deck=(KELIDAN,A));self.play(g,DRAW1)
        source=self.play(g,KELIDAN);self.play(g,BOUNCE,source);self.play(g,SUMMON2)
        self.play(g,KELIDAN,self.unit(g,A).id);self.assertEqual(self.unit(g,B).zone,Zone.BOARD)

    def test_Kelidan_actual_area_death_wait_restores_and_failure_keeps_original_paid_draw(self):
        g=self.game((DRAW1,),board=(A,),enemy=(B,),deck=(KELIDAN,A),watch=True)
        self.play(g,DRAW1);source=self.play(g,KELIDAN);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(g.state.players[1].board,[source])

    def test_Mordresh_uses_actual_power_damage_threshold_not_nominal_card_play(self):
        for power,expected in((POWER9,491),(POWER10,480)):
            with self.subTest(power=power):
                g=self.game((MORDRESH,),enemy=(B,),power=power);self.power(g);self.play(g,MORDRESH)
                self.assertEqual(self.armor(g),expected)
                self.assertEqual(bool(g.state.players[2].board),power==POWER9)

    def test_Mordresh_old_power_slot_and_friendly_target_credit_remain_original(self):
        g=self.game((REPLACE,MORDRESH),enemy=(B,));self.power(g,g.state.players[1].hero_id)
        self.play(g,REPLACE);self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER9)
        self.play(g,MORDRESH);self.assertEqual(self.armor(g),490);self.assertFalse(g.state.players[2].board)

    def test_Mordresh_spell_and_opponent_power_damage_do_not_count_for_actor(self):
        g=self.game((SPELL10,MORDRESH),enemy=(B,));self.play(g,SPELL10,g.state.players[2].hero_id)
        g.apply(EndTurn(1));self.power(g,p=2);g.apply(EndTurn(2));before=self.armor(g)
        self.play(g,MORDRESH);self.assertEqual(self.armor(g),before);self.assertEqual(self.unit(g,B,2).health,8)

    def test_Mordresh_damage_is_not_spell_damage_and_group_wait_recovers_once(self):
        g=self.game((MORDRESH,),board=(AMPLIFIER,),enemy=(B,),watch=True);self.power(g)
        self.play(g,MORDRESH);self.assertIsNotNone(g.state.pending_choice)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.armor(g),480)

    def test_Kalecgos_real_host_discovery_uses_complete_current_class_spell_domain_and_private_menu(self):
        for hero in('HERO_08','HERO_06'):
            with self.subTest(hero=hero):
                g=self.game((KALECGOS,),host=True,hero=hero);self.play(g,KALECGOS)
                choice=g.state.pending_choice;self.assertIsNotNone(choice)
                candidates=resolve_candidates(g.registry,fixture('writer',True)[1],'constructed.cards',native.SPELLS,
                    current_class=g.state.players[1].hero_class,source_card_id=KALECGOS,player_id=1)
                eligible={c.card_id for c in candidates};self.assertGreater(len(eligible),3)
                offered={o.card_id for o in choice.options};self.assertEqual(len(offered),3);self.assertTrue(offered<=eligible)
                hidden=json.dumps(g.for_player(2).observe())
                for cid in offered:self.assertNotIn(cid,hidden)
                saved=g.snapshot()
                with self.assertRaises(IllegalAction):self.choose(g,'not-offered')
                self.assertEqual(g.snapshot(),saved);g=self.portable(g);self.finish(g)
                self.assertEqual(len(g.state.players[1].hand),1)
                self.assertIn(g.state.entities[g.state.players[1].hand[0]].card_id,offered)

    def test_Kalecgos_first_spell_zero_then_printed_cost_and_owner_turn_reset(self):
        g=self.game((S3,S3,S3),board=(KALECGOS,));self.play(g,S3);self.play(g,S3)
        self.assertEqual([p.cost for p in g.state.play_history],[0,3]);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,S3)
        self.assertEqual(g.state.play_history[-1].cost,0)

    def test_Kalecgos_entering_after_first_spell_does_not_reset_player_prefix(self):
        g=self.game((S3,KALECGOS,S3),host=True);self.play(g,S3);self.play(g,KALECGOS);self.finish(g);self.play(g,S3)
        self.assertEqual(g.state.play_history[-1].cost,3)

    def test_Kalecgos_preserves_existing_paid_hand_policy_for_automatic_spell_origins(self):
        g=self.game((AUTO,S3),board=(KALECGOS,));self.play(g,AUTO);self.assertEqual(len(g.state.cast_history),2)
        self.play(g,S3);self.assertEqual(g.state.play_history[-1].cost,0)

    def test_Kaelthas_actual_third_sixth_and_zero_cost_third_spell_follow_original_cast_ordinal(self):
        for cid,expected in((S3,[3,3,1,3,3,1]),(S0,[0,0,1])):
            with self.subTest(spell=cid):
                g=self.game((cid,)*len(expected),board=(KAELTHAS,))
                for _ in expected:self.play(g,cid)
                self.assertEqual([p.cost for p in g.state.play_history],expected)

    def test_Kaelthas_automatic_casts_count_and_entering_after_them_does_not_reset(self):
        g=self.game((AUTO,KAELTHAS,S3));self.play(g,AUTO);self.play(g,KAELTHAS);self.play(g,S3)
        self.assertEqual(g.state.play_history[-1].cost,1)

    def test_Kaelthas_silence_removes_discount_and_new_turn_ordinal_resets(self):
        g=self.game((AUTO,HUSH,S3),board=(KAELTHAS,));self.play(g,AUTO);self.play(g,HUSH,self.unit(g,KAELTHAS).id)
        self.play(g,S3);self.assertEqual(g.state.play_history[-1].cost,3)
        g=self.game((AUTO,S3),board=(KAELTHAS,));self.play(g,AUTO);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,S3)
        self.assertEqual(g.state.play_history[-1].cost,3)

    def test_both_native_cost_sources_keep_already_paid_price_through_wait_and_source_death(self):
        for cid,expected in((KALECGOS,0),(KAELTHAS,1)):
            with self.subTest(source=cid):
                g=self.game((AUTO,S3,S3),board=(cid,),watch=True)
                if cid==KAELTHAS:self.play(g,AUTO)
                source=self.unit(g,cid).id;self.play(g,S3);self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(g.state.play_history[-1].cost,expected)
                g=self.portable(g);self.fault(g);self.choose(g,'remove');self.finish(g)
                self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
                self.play(g,S3);self.assertEqual(g.state.play_history[-1].cost,3)

    def test_Goru_real_paid_program_buffs_existing_controlled_hand_deck_board_only(self):
        g=self.game((GORU,TREE),board=(TREE,A),enemy=(TREE,),deck=(TREE,A));source=self.play(g,GORU)
        for zone in('hand','deck','board'):
            entity=next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==TREE)
            self.assertEqual((entity.attack,entity.max_health),(3,3))
        self.assertEqual(self.unit(g,TREE,2).attack,2);self.assertEqual(self.unit(g,A).attack,2)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(5,10))
        self.assertEqual(len(g.state.players[1].player_effects),1)

    def test_Goru_actual_repeated_Battlecries_stack_and_source_control_death_silence_do_not_remove(self):
        g=self.game((GORU,CONTROL,KILL,HUSH),board=(TREE,REPEAT),enemy=(TREE,));source=self.play(g,GORU)
        self.assertEqual(len(g.state.players[1].player_effects),2);self.assertEqual(self.unit(g,TREE).attack,4)
        self.play(g,CONTROL,source);self.play(g,KILL,source);self.play(g,HUSH,self.unit(g,TREE).id)
        self.assertEqual(self.unit(g,TREE).attack,4);self.assertEqual(self.unit(g,TREE,2).attack,2)

    def test_Goru_current_copy_resurrection_and_bounce_reentry_do_not_double_derived_aura(self):
        g=self.game((GORU,COPY,KILL,REVIVE,BOUNCE),board=(TREE,));self.play(g,GORU);target=self.unit(g,TREE).id
        self.play(g,COPY,target);self.assertEqual([g.state.entities[i].attack for i in g.state.players[1].board if g.state.entities[i].card_id==TREE],[3,3])
        self.play(g,KILL,target);self.play(g,REVIVE)
        self.assertTrue(all(g.state.entities[i].attack==3 for i in g.state.players[1].board if g.state.entities[i].card_id==TREE))
        target=self.unit(g,TREE).id;self.play(g,BOUNCE,target);self.assertEqual(g.state.entities[target].attack,3)
        self.play(g,TREE);self.assertEqual(g.state.entities[target].attack,3)

    def test_Goru_program_added_wait_recovers_with_original_full_family_and_rng_rollback(self):
        g=self.game((GORU,),board=(TREE,),watch=True);self.play(g,GORU);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.unit(g,TREE).attack,3);g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(tuple(g.registry.player_effect(native.PROGRAM).auras[0].card_ids),tuple(native.load_batch()['treant_family']['card_ids']))

    def test_all_five_actual_standard_host_paid_entries_execute_their_real_bodies(self):
        for cid in native.ROOTS:
            with self.subTest(card=cid):
                g=self.game((cid,S3,S3,S3),board=(TREE,),enemy=(B,),host=True)
                if cid==MORDRESH:self.power(g)
                source=self.play(g,cid,self.unit(g,B,2).id if cid==KELIDAN else None);self.finish(g)
                if cid==KELIDAN:self.assertFalse(g.state.players[2].board)
                elif cid==MORDRESH:self.assertEqual(self.armor(g),480)
                elif cid==GORU:self.assertEqual(self.unit(g,TREE).attack,3)
                elif cid==KALECGOS:
                    self.play(g,S3);self.assertEqual(g.state.play_history[-1].cost,0)
                else:
                    for _ in range(3):self.play(g,S3)
                    self.assertEqual(g.state.play_history[-1].cost,1)
                self.assertEqual(g.state.entities[source].controller,1)


if __name__=='__main__':unittest.main()
