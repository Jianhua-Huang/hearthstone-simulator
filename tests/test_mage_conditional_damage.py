"""Real debit/target/wave entries, first-batch provenance and resumable deaths."""
from dataclasses import replace
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import mage_conditional_damage as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (AddToHand,ChangeManaCrystals,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RefreshMana,RequestChoice,ReturnToHand,Summon,Transform)
from hs_sim.engine.model import CardClass,CardDefinition,CardType,DamageKind,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_sequences import DamageMinionsRepeatIfNoDeaths,RepeatSpellBatchIfNoDeaths
from hs_sim.engine.spell_target_conditions import PreviousElementalTargetProfile
from hs_sim.engine.targeting import effective_target_spec
from hs_sim.local_pool_format import build_cn37_local_pool_format

FLAME,COMBUSTION,WAVES=native.LEAVES
P='k627.'
BIG,SMALL,MID,SHIELD,IMMUNE,SLEEP,REBORN,EL,EL_CHANGE,BONUS=(P+x for x in
    ('big','small','mid','shield','immune','sleep','reborn','elemental','elemental_change','bonus'))
WAIT,FAIL,AUTO_FLAME,AUTO_COMBUSTION,AUTO_WAVES=(P+x for x in('wait','fail','auto_flame','auto_combustion','auto_waves'))

@lru_cache(None)
def registry(mode='normal',role='writer'):
    r=opening_registry();native.register_mage_conditional_damage(r)
    for cid,health,kw in ((BIG,12,{}),(SMALL,2,{}),(MID,3,{}),(SHIELD,4,{'keywords':(Keyword.DIVINE_SHIELD,)}),
            (IMMUNE,8,{'keywords':(Keyword.IMMUNE,)}),(SLEEP,8,{'dormant_turns':2}),
            (REBORN,2,{'keywords':(Keyword.REBORN,)}),(EL,4,{}),(EL_CHANGE,4,{'battlecry':EL_CHANGE}),
            (BONUS,8,{'spell_damage':1})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,
            metadata=metadata(tribes=('elemental',)if cid in(EL,EL_CHANGE)else()),**kw))
    r.register_behavior(EL_CHANGE,lambda c:(Transform(c.source_id,BIG),))
    def fail(c):raise ResolutionError('K627 deliberate conditional-damage continuation failure')
    r.register_behavior(FAIL,fail)
    def target(c):return next(i for i in c.state.players[2].board if c.state.entities[i].card_id==BIG)
    for cid,body in ((AUTO_FLAME,lambda c:(CastSpell(c.player_id,FLAME,c.source_id,target_id=target(c),targeting='explicit'),)),
            (AUTO_COMBUSTION,lambda c:(CastSpell(c.player_id,COMBUSTION,c.source_id),)),
            (AUTO_WAVES,lambda c:(CastSpell(c.player_id,WAVES,c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(CardClass.MAGE,tribes=())))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        mana=mode=='mana'and c.event.kind=='mana_consumed'and source is not None and source.card_id==FLAME
        wave=mode=='wave'and c.event.kind=='damage_dealt'and source is not None and source.card_id==WAVES and c.state.entities[c.event.target_id].card_id==BIG
        if not(mana or wave):return ()
        options=[ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))]
        if mana:
            cast=c.state.cast_history[c.mana_result.cast_id-1]
            options.extend((ChoiceOption('refresh','Refresh after original debit',
                (ChangeManaCrystals(c.player_id,3,filled=True),RefreshMana(c.player_id,30))),
                ChoiceOption('bounce','Bounce original target',(ReturnToHand(cast.target_id),))))
        else:options.extend((ChoiceOption('summon','Summon before next wave',(Summon(c.player_id,SMALL),)),
            ChoiceOption('kill','Independent reaction death',(Destroy(c.source_id),))))
        return(RequestChoice(c.player_id,tuple(options),c.source_id),)
    r.register_behavior(WAIT,watch)
    r.register_card(CardDefinition(WAIT,WAIT,CardType.MINION,health=30,metadata=metadata(tribes=()),
        triggers=(TriggerSpec('mana_consumed',WAIT),TriggerSpec('damage_dealt',WAIT))))
    r.validate();return r


class MageConditionalDamageTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    mode='normal'
    def game(self,hand,*,board=(),enemy=(BIG,),other_hand=(),mode='normal',mana=10):
        self.mode=mode
        if mode in('mana','wave'):board=(*board,WAIT)
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=hand,board=board,deck=(BIG,)*10,
            mana=mana,max_mana=mana),PlayerSetup('warrior.hero',hand=other_hand,board=enemy,deck=(BIG,)*10,mana=10,max_mana=10)),seed=627),registry(mode))
    def enemy(self,g,cid=BIG):return self.entity(g,cid,2,'board')
    def hits(self,g,cid):return[r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]
    def rollback_wait(self,g,key='continue'):
        g=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key);return g
    def previous_elemental(self,g,cid=EL):
        self.play(g,cid);g.apply(EndTurn(1));g.apply(EndTurn(2))

    def test_full_three_rows_six_primary_faces_and_exact_printed_zero(self):
        d=native.load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        for o in d['official_observations']:
            batch.check_face(rows[o['card_id']],o['face'],o['locale'],numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        self.assertIsNone(rows[FLAME]['cost']);self.assertNotIn('COST',rows[FLAME]['tags']);self.assertEqual(registry().card(FLAME).cost,0)
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['source_scope_bound'])

    def test_flame_spends_actual_all_mana_once_and_hits_original_minion(self):
        g=self.game((FLAME,),mana=7);target=self.enemy(g).id;source=self.play(g,FLAME,target)
        self.assertEqual((g.state.players[1].mana,g.state.entities[target].damage),(0,7))
        row=g.state.mana_consumption_history[0];self.assertEqual((row.actual,row.source_id,row.cast_id),(7,source,1));self.portable(g)

    def test_flame_zero_mana_still_uses_original_spell_damage_bonus(self):
        g=self.game((FLAME,),board=(BONUS,),mana=0);target=self.enemy(g).id;self.play(g,FLAME,target)
        self.assertEqual(g.state.entities[target].damage,1);self.assertEqual(g.state.mana_consumption_history[0].actual,0)
        self.assertEqual((self.hits(g,FLAME)[0].base_amount,self.hits(g,FLAME)[0].spell_bonus),(0,1))

    def test_flame_hero_target_is_illegal_without_resource_changes(self):
        g=self.game((FLAME,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FLAME,g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),saved)

    def test_flame_zero_mana_without_bonus_is_a_real_zero_packet(self):
        g=self.game((FLAME,),mana=0);self.play(g,FLAME,self.enemy(g).id)
        self.assertEqual(self.hits(g,FLAME)[0].damage_dealt,0);self.assertEqual(len(g.state.cast_history),1)

    def test_flame_refresh_during_consumption_wait_does_not_change_original_amount(self):
        g=self.game((FLAME,),mode='mana',mana=7);target=self.enemy(g).id;self.play(g,FLAME,target)
        self.assertEqual(g.state.entities[target].damage,0);g=self.rollback_wait(g,'refresh')
        self.assertEqual(g.state.entities[target].damage,7);self.assertEqual(g.state.players[1].mana,10)

    def test_flame_departed_original_target_is_not_hit_after_consumption_wait(self):
        g=self.game((FLAME,),mode='mana',mana=7);target=self.enemy(g).id;self.play(g,FLAME,target);g=self.rollback_wait(g,'bounce')
        self.assertEqual(g.state.entities[target].zone,Zone.HAND);self.assertEqual(g.state.entities[target].damage,0)
        self.assertFalse(self.hits(g,FLAME));self.assertEqual(g.state.players[1].mana,0)

    def test_flame_automatic_cast_keeps_original_debit_and_target_origin(self):
        g=self.game((AUTO_FLAME,),mana=6);target=self.enemy(g).id;self.play(g,AUTO_FLAME)
        self.assertEqual(g.state.entities[target].damage,6);self.assertEqual(g.state.mana_consumption_history[0].cast_id,2);self.portable(g)

    def test_combustion_without_elemental_is_untargeted_random_enemy(self):
        g=self.game((COMBUSTION,));source=self.entity(g,COMBUSTION)
        self.assertIsNone(effective_target_spec(g.state,g.registry,source,g.registry.card(COMBUSTION)))
        self.play(g,COMBUSTION);rows=self.hits(g,COMBUSTION);self.assertEqual(len(rows),1)
        self.assertEqual((rows[0].target_controller,rows[0].damage_dealt),(2,4));self.portable(g)

    def test_combustion_inactive_branch_rejects_manual_arrow_before_payment(self):
        g=self.game((COMBUSTION,));saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,COMBUSTION,self.enemy(g).id)
        self.assertEqual(g.snapshot(),saved)

    def test_combustion_current_turn_elemental_is_not_previous_turn(self):
        g=self.game((EL,COMBUSTION));self.play(g,EL)
        source=self.entity(g,COMBUSTION);self.assertIsNone(effective_target_spec(g.state,g.registry,source,g.registry.card(COMBUSTION)))
        self.play(g,COMBUSTION);self.assertEqual(len(self.hits(g,COMBUSTION)),1)

    def test_combustion_previous_owner_elemental_requires_and_uses_chosen_enemy(self):
        g=self.game((EL,COMBUSTION));self.previous_elemental(g);target=self.enemy(g).id;saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,COMBUSTION)
        self.assertEqual(g.snapshot(),saved);self.play(g,COMBUSTION,target)
        self.assertEqual(g.state.entities[target].damage,4);self.portable(g)

    def test_combustion_previous_submitted_elemental_survives_original_face_change(self):
        g=self.game((EL_CHANGE,COMBUSTION));self.previous_elemental(g,EL_CHANGE)
        self.play(g,COMBUSTION,g.state.players[2].hero_id);self.assertEqual(g.state.entities[g.state.players[2].hero_id].damage,4)

    def test_combustion_active_branch_uses_declared_enemy_only_local_domain(self):
        g=self.game((EL,COMBUSTION));self.previous_elemental(g);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,COMBUSTION,g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(),saved)

    def test_combustion_automatic_cast_works_without_manual_target_requirement(self):
        g=self.game((AUTO_COMBUSTION,));self.play(g,AUTO_COMBUSTION)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(self.hits(g,COMBUSTION)[0].damage_dealt,4)

    def test_profile_rejects_invented_condition_variants(self):
        with self.assertRaises(ValueError):PreviousElementalTargetProfile(COMBUSTION,'other_condition').__post_init__()

    def test_waves_two_batches_one_cast_and_one_payment_when_none_die_first(self):
        g=self.game((WAVES,));target=self.enemy(g).id;self.play(g,WAVES)
        self.assertEqual(g.state.entities[target].damage,4);rows=self.hits(g,WAVES)
        self.assertEqual(len({r.batch_id for r in rows}),2);self.assertEqual(len(g.state.cast_history),1)
        self.assertEqual(g.state.players[1].mana,7);self.portable(g)

    def test_waves_first_batch_death_prevents_second_even_with_living_other_minion(self):
        g=self.game((WAVES,),enemy=(SMALL,BIG));big=self.enemy(g).id;self.play(g,WAVES)
        self.assertEqual(g.state.entities[big].damage,2);self.assertEqual(len({r.batch_id for r in self.hits(g,WAVES)}),1)
        self.assertEqual(len(g.state.death_history),1)

    def test_waves_first_reborn_death_still_prevents_second(self):
        g=self.game((WAVES,),enemy=(REBORN,BIG));big=self.enemy(g).id;self.play(g,WAVES)
        self.assertEqual(g.state.entities[big].damage,2);self.assertEqual(len(g.state.death_history),1)
        self.assertEqual(len(g.state.players[2].board),2)

    def test_waves_second_batch_can_kill_and_never_produces_third_wave(self):
        g=self.game((WAVES,),enemy=(MID,BIG));big=self.enemy(g).id;self.play(g,WAVES)
        self.assertEqual(g.state.entities[big].damage,4);self.assertEqual(len({r.batch_id for r in self.hits(g,WAVES)}),2)
        self.assertEqual(len(g.state.death_history),1)

    def test_waves_divine_shield_and_immunity_use_ordinary_protection(self):
        g=self.game((WAVES,),enemy=(SHIELD,IMMUNE));shield=self.enemy(g,SHIELD).id;immune=self.enemy(g,IMMUNE).id
        self.play(g,WAVES);self.assertEqual(g.state.entities[shield].damage,2);self.assertEqual(g.state.entities[immune].damage,0)

    def test_waves_dormant_and_empty_board_do_not_invent_active_targets(self):
        g=self.game((WAVES,),enemy=(SLEEP,));self.play(g,WAVES);self.assertFalse(self.hits(g,WAVES))
        g=self.game((WAVES,),enemy=());saved=g.snapshot()['rng_state'];self.play(g,WAVES)
        self.assertFalse(self.hits(g,WAVES));self.assertEqual(g.snapshot()['rng_state'],saved)

    def test_waves_spell_bonus_is_applied_by_each_ordinary_batch(self):
        g=self.game((WAVES,),board=(BONUS,));target=self.enemy(g).id;self.play(g,WAVES)
        self.assertEqual(g.state.entities[target].damage,6);self.assertEqual({r.spell_bonus for r in self.hits(g,WAVES)},{1})

    def test_waves_first_wait_and_second_wait_restore_exact_original_batch(self):
        g=self.game((WAVES,),mode='wave');self.play(g,WAVES)
        count=0
        while g.state.pending_choice:g=self.rollback_wait(g);count+=1
        self.assertEqual(count,2);self.assertEqual(self.enemy(g).damage,4)

    def test_waves_second_batch_selects_fresh_board_after_first_reaction(self):
        g=self.game((WAVES,),mode='wave');self.play(g,WAVES);g=self.rollback_wait(g,'summon')
        while g.state.pending_choice:self.choose(g)
        self.assertEqual(self.enemy(g).damage,4)
        self.assertTrue(any(d.card_id==SMALL for d in g.state.death_history))

    def test_waves_independent_reaction_death_is_not_original_first_batch_death(self):
        g=self.game((WAVES,),mode='wave');self.play(g,WAVES);g=self.rollback_wait(g,'kill')
        self.assertEqual(self.enemy(g).damage,4);self.assertEqual(len({r.batch_id for r in self.hits(g,WAVES)}),2)

    def test_pending_wave_rejects_missing_batch_changed_amount_and_wrong_cast(self):
        g=self.game((WAVES,),mode='wave');source=self.play(g,WAVES);row=self.hits(g,WAVES)[0]
        actual=RepeatSpellBatchIfNoDeaths(1,1,source,row.batch_id,2);actual.validate_in_state(g.state,g.registry)
        for bad in(replace(actual,batch_id=row.batch_id+999),replace(actual,amount=3),replace(actual,cast_id=999)):
            with self.subTest(request=bad),self.assertRaises((ValueError,ResolutionError)):bad.validate_in_state(g.state,g.registry)

    def test_waves_automatic_cast_keeps_one_independent_child_and_two_batches(self):
        g=self.game((AUTO_WAVES,));self.play(g,AUTO_WAVES)
        self.assertEqual(len(g.state.cast_history),2);self.assertEqual(self.enemy(g).damage,4);self.portable(g)

    def test_real_local_host_executes_all_three_card_entries(self):
        f=build_cn37_local_pool_format()
        for cid,targeted in((FLAME,True),(COMBUSTION,False),(WAVES,False)):
            g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(cid,),mana=10,max_mana=10),
                PlayerSetup('HERO_01',board=('CORE_CS2_182',))),generation_context=f.context),f.registry)
            target=g.state.players[2].board[0]if targeted else None;self.play(g,cid,target)
            self.assertEqual(g.state.entities[g.state.cast_history[-1].source_id].card_id,cid)
