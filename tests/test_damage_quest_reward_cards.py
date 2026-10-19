"""Actual Quest packets, permanent player sources and bounded Gorishi damage."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.damage_quest_reward_cards import (ENCHANTMENT, QUEST, REWARD, RULE, load_batch,
    register_damage_quest_reward_cards)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, DamageBatch, Destroy,
    GrantKeyword, Heal, InvokeBehavior, RequestChoice, ReturnToHand, SetStats, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import (PlayerHealthOrigin, health_result, result_from_payload,
    validate_player_origin)
from hs_sim.engine.model import DamageKind, PlayerEffectSpec
from hs_sim.engine.player_effects import AddPlayerEffect, PlayerEffectDamage, validate_player_damage
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'gorishi.test.'
AVATAR, TINY, FIGHT, SMALL, SHIELD, IMMUNE, WATCH = (
    P+x for x in ('avatar','tinyhero','fight','small','shield','immune','watch'))
TWO, ONE, THREE, MANY, ELEVEN, BATCH, FRIEND, UNKNOWN, HEAL, WOUND, LIFE, SP, KILL, SILENCE, CONTROL, STATS = (
    P+x for x in ('two','one','three','many','eleven','batch','friend','unknown','heal','wound','life','sp','kill','silence','control','stats'))
OPS = (TWO,ONE,THREE,MANY,ELEVEN,BATCH,FRIEND,UNKNOWN,HEAL,WOUND,LIFE,SP,KILL,SILENCE,CONTROL,STATS)


def registry(mode=None):
    r = Registry('gorishi-native-tests-v1.'+str(mode));register_damage_quest_reward_cards(r)
    r.register_card(CardDefinition(AVATAR,AVATAR,CardType.HERO,health=500))
    r.register_card(CardDefinition(TINY,TINY,CardType.HERO,health=4))
    for cid,hp,flags in ((FIGHT,50,()),(SMALL,1,()),(SHIELD,50,(Keyword.DIVINE_SHIELD,)),(IMMUNE,50,(Keyword.IMMUNE,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2 if cid==FIGHT else 0,health=hp,keywords=flags))
    def shots(c,n):
        return tuple(Damage(c.state.players[3-c.player_id].hero_id,2,c.source_id,DamageKind.SPELL) for _ in range(n))
    bodies = {
        TWO:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        ONE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        THREE:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),),
        MANY:lambda c:shots(c,13),ELEVEN:lambda c:shots(c,11),
        BATCH:lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL) for i in c.state.players[3-c.player_id].board)),),
        FRIEND:lambda c:(Damage(c.state.players[c.player_id].hero_id,2,c.source_id,DamageKind.SPELL),),
        UNKNOWN:lambda c:(Damage(c.target_id,2),),
        HEAL:lambda c:(Heal(c.state.players[c.player_id].hero_id,2,c.source_id),),
        WOUND:lambda c:(Damage(c.state.players[c.player_id].hero_id,5,c.source_id),),
        LIFE:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        SP:lambda c:(AddPlayerEffect(c.player_id,P+'spell_bonus',c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),
        CONTROL:lambda c:(ChangeControl(c.target_id,3-c.state.entities[c.target_id].controller),),
        STATS:lambda c:(SetStats(c.target_id,2,8,c.source_id),),
    }
    targeted = (TWO,ONE,THREE,UNKNOWN,LIFE,KILL,SILENCE,CONTROL,STATS)
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1 if cid in (MANY,ELEVEN) else 0,
            on_play=cid,targeting=TargetSpec() if cid in targeted else None,
            keywords=(Keyword.LIFESTEAL,) if cid==LIFE else ()))
    r.register_player_effect(PlayerEffectSpec(P+'spell_bonus',SP,spell_damage=1))
    def fail(c):raise ResolutionError('Gorishi deliberate reaction failure')
    def reenter(c):
        return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,
            cause=SummonCause.capture(c)),)
    r.register_behavior(P+'fail',fail);r.register_behavior(P+'reenter',reenter)
    def watch(c):
        if mode=='quest':
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=QUEST:return ()
            target=None
        else:
            h=health_result(c.event)
            if (h is None or h.damage_dealt!=2 or h.target_controller!=3-c.player_id or h.source_controller!=c.player_id):return ()
            if mode=='parent' and h.player_origin is not None:return ()
            if mode in ('extra','fail') and (h.player_origin is None or h.player_origin.spec_id!=RULE):return ()
            target=c.state.entities[h.target_id]
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        options=(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)))
        if mode=='parent' and target.kind==CardType.MINION and target.health>0:
            options+=(ChoiceOption('cycle','Return and reenter original target',(
                ReturnToHand(target.id),InvokeBehavior(P+'reenter',target.id,target.controller,target.id))),)
        return (RequestChoice(c.player_id,options,c.source_id),)
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=100,
        triggers=(TriggerSpec('quest_completed' if mode=='quest' else 'health_resolved',P+'watch'),)))
    r.validate();return r


class DamageQuestRewardTests(unittest.TestCase):
    def game(self,hand=(QUEST,),mode=None,pid=1,enemy_board=(FIGHT,),armor=0,enemy_hero=AVATAR):
        self.mode,self.pid=mode,pid
        actor=PlayerSetup(AVATAR,deck=(FIGHT,)*8,hand=(*hand,*OPS,*OPS),board=(FIGHT,*((WATCH,) if mode else ())),
            mana=30,max_mana=30,mana_cap=30,hand_cap=40)
        other=PlayerSetup(enemy_hero,deck=(FIGHT,)*8,hand=OPS,board=enemy_board,
            armor=armor,mana=30,max_mana=30,mana_cap=30,hand_cap=40)
        return Game.from_scenario(Scenario((actor,other) if pid==1 else (other,actor),active_player=pid,seed=29),registry(mode))

    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target_id=target));return eid

    def enemy(self,g):return g.state.players[3-self.pid].hero_id
    def hp(self,g,eid):return g.state.entities[eid].health
    def programs(self,g):return [e for e in g.state.players[self.pid].player_effects if e.spec_id==RULE]
    def progress(self,g,q):return g.state.entities[q].quest_progress.value
    def select(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));r=registry(self.mode)
        restored=Game.from_snapshot(saved,r);self.assertEqual(restored.snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),r).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in ('player_origin','original_target_result','source_allocation','damage_history','resolution_frame'):
                self.assertNotIn('"'+field+'"',public)
        return restored

    def test_a00_complete_sources_faces_metadata_reward_and_evidence_only_enchantment(self):
        d=load_batch();r=build_registry()
        for row in (*d['cards'],*d['dependencies']):
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual(r.card(raw['id']).metadata,metadata_from_record(raw))
        self.assertEqual((r.card(QUEST).cost,r.card(QUEST).quest.stages[0].goal),(1,12))
        self.assertEqual((r.card(REWARD).cost,r.card(REWARD).attack,r.card(REWARD).health),(5,8,8))
        self.assertNotIn(ENCHANTMENT,r.cards);self.assertEqual(len(d['official_observations']),4)

    def test_a01_actual_paid_quest_finishes_once_then_paid_reward_installs_program(self):
        g=self.game();q=self.play(g,QUEST);self.play(g,MANY)
        self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)
        rewards=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==REWARD]
        self.assertEqual(len(rewards),1);self.assertEqual(len(g.state.damage_history),13)
        self.assertEqual(g.state.players[1].mana,28);self.play(g,REWARD)
        self.assertEqual(g.state.players[1].mana,23);self.assertEqual(len(self.programs(g)),1)
        self.play(g,TWO,self.enemy(g));self.assertEqual(self.hp(g,self.enemy(g)),470);self.portable(g)

    def test_a02_eleven_is_not_twelve_and_current_final_packet_completes(self):
        g=self.game();q=self.play(g,QUEST);self.play(g,ELEVEN)
        self.assertEqual(self.progress(g,q),11);self.assertFalse(any(g.state.entities[i].card_id==REWARD for i in g.state.players[1].hand))
        self.play(g,TWO,self.enemy(g));self.assertEqual(g.state.entities[q].zone,Zone.GRAVEYARD)

    def test_a03_wrong_amount_friendly_damage_and_healing_are_not_quest_progress(self):
        g=self.game();q=self.play(g,QUEST)
        self.play(g,ONE,self.enemy(g));self.play(g,THREE,self.enemy(g));self.play(g,FRIEND);self.play(g,HEAL)
        self.assertEqual(self.progress(g,q),0)

    def test_a04_opponent_turn_retaliation_does_not_count_for_quest(self):
        g=self.game();q=self.play(g,QUEST);g.apply(EndTurn(1))
        a=g.state.players[2].board[0];b=g.state.players[1].board[0];g.apply(Attack(2,a,b))
        self.assertEqual(self.progress(g,q),0);g.apply(EndTurn(2));self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.progress(g,q),1)

    def test_a05_actual_armor_damage_counts_shield_and_immunity_prevention_do_not(self):
        g=self.game(enemy_board=(SHIELD,IMMUNE),armor=10);q=self.play(g,QUEST);self.play(g,BATCH)
        self.assertEqual(self.progress(g,q),0);self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.progress(g,q),1);self.assertEqual(self.hp(g,self.enemy(g)),500)
        self.play(g,TWO,g.state.players[2].board[0]);self.assertEqual(self.progress(g,q),2)

    def test_a06_quest_uses_settled_amount_after_spell_bonus(self):
        g=self.game();q=self.play(g,QUEST);self.play(g,SP)
        self.play(g,ONE,self.enemy(g));self.assertEqual(self.progress(g,q),1)
        self.play(g,TWO,self.enemy(g));self.assertEqual(self.progress(g,q),1)

    def test_a07_unknown_positive_source_ownership_fails_atomically(self):
        for card in (QUEST,REWARD):
            with self.subTest(card=card):
                g=self.game(hand=(card,));self.play(g,card);before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'known original source ownership') as caught:
                    self.play(g,UNKNOWN,self.enemy(g))
                self.assertIsInstance(caught.exception.__cause__,UnsupportedDefinitionError)
                self.assertEqual(g.snapshot(),before)

    def test_b00_physical_reward_damage_is_distinct_from_its_own_logical_output(self):
        g=self.game(hand=(REWARD,));source=self.play(g,REWARD);self.play(g,STATS,source)
        g.apply(EndTurn(1));g.apply(EndTurn(2));g.apply(Attack(1,source,self.enemy(g)))
        self.assertEqual(self.hp(g,self.enemy(g)),496)
        rows=[d.health_result for d in g.state.damage_history if d.health_result.damage_dealt>0]
        self.assertEqual([r.source_card_id for r in rows],[REWARD,REWARD])
        self.assertIsNone(rows[0].player_origin);self.assertEqual(rows[1].player_origin.spec_id,RULE)

    def test_b01_reward_works_on_opponent_turn_for_original_friendly_retaliation(self):
        g=self.game(hand=(REWARD,));self.play(g,REWARD);g.apply(EndTurn(1))
        a=g.state.players[2].board[0];b=g.state.players[1].board[0];g.apply(Attack(2,a,b))
        self.assertEqual(self.hp(g,a),46);self.assertEqual(self.hp(g,b),48)
        self.assertTrue(any(r.health_result.player_origin is not None and r.health_result.active_player==2 for r in g.state.damage_history))

    def test_b02_two_persistent_instances_each_add_once_without_cross_instance_echo(self):
        g=self.game(hand=(REWARD,REWARD));self.play(g,REWARD);self.play(g,REWARD);self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.hp(g,self.enemy(g)),494);self.assertEqual(len(g.state.damage_history),3)
        origins=[r.health_result.player_origin for r in g.state.damage_history if r.health_result.player_origin]
        self.assertEqual(len({p.instance_id for p in origins}),2);self.assertEqual({p.spec_id for p in origins},{RULE});self.portable(g)

    def test_b03_additional_packet_does_not_inherit_original_lifesteal(self):
        g=self.game(hand=(REWARD,));self.play(g,REWARD);self.play(g,WOUND);self.play(g,LIFE,self.enemy(g))
        self.assertEqual(self.hp(g,g.state.players[1].hero_id),497)
        self.assertEqual(self.hp(g,self.enemy(g)),496)

    def test_b04_additional_packet_does_not_inherit_spell_bonus_or_trigger_on_three(self):
        g=self.game(hand=(REWARD,));self.play(g,REWARD);self.play(g,SP);self.play(g,ONE,self.enemy(g))
        self.assertEqual(self.hp(g,self.enemy(g)),496)
        extra=g.state.damage_history[-1].health_result;self.assertEqual((extra.base_amount,extra.modified_amount,extra.spell_bonus),(2,2,0))
        self.play(g,TWO,self.enemy(g));self.assertEqual(self.hp(g,self.enemy(g)),493)

    def test_b05_source_silence_transfer_and_death_keep_original_beneficiary_program(self):
        g=self.game(hand=(REWARD,));source=self.play(g,REWARD)
        self.play(g,SILENCE,source);self.play(g,CONTROL,source);self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.hp(g,self.enemy(g)),496);self.play(g,KILL,source);self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.hp(g,self.enemy(g)),492);self.assertEqual(len(self.programs(g)),1);self.portable(g)

    def test_b06_original_lethal_minion_target_does_not_retarget_another_body(self):
        g=self.game(hand=(REWARD,),enemy_board=(SMALL,FIGHT));self.play(g,REWARD)
        victim,other=g.state.players[2].board;self.play(g,TWO,victim)
        self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g,other),50)
        self.assertEqual(len(g.state.damage_history),1)

    def test_b07_quest_completion_wait_restores_before_single_reward_delivery(self):
        g=self.game(mode='quest');self.play(g,QUEST);self.play(g,MANY)
        self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        self.select(g);self.select(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(sum(g.state.entities[i].card_id==REWARD for i in g.state.players[1].hand),1)

    def test_c00_original_packet_wait_restores_and_finishes_exactly_one_bonus(self):
        g=self.game(hand=(REWARD,),mode='parent');self.play(g,REWARD);victim=g.state.players[2].board[0]
        self.play(g,TWO,victim);self.assertIsNotNone(g.state.pending_choice);restored=self.portable(g)
        self.select(g);self.select(restored);self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(self.hp(g,victim),46);self.assertEqual(len(g.state.damage_history),2);self.portable(g)

    def test_c01_old_target_result_cannot_follow_same_id_return_and_reentry(self):
        g=self.game(hand=(REWARD,),mode='parent');self.play(g,REWARD);victim=g.state.players[2].board[0]
        self.play(g,TWO,victim);self.portable(g);self.select(g,'cycle')
        self.assertEqual(g.state.entities[victim].zone,Zone.BOARD);self.assertEqual(self.hp(g,victim),50)
        self.assertEqual(len(g.state.damage_history),1);self.portable(g)

    def test_c02_logical_output_wait_preserves_origin_without_retriggering(self):
        g=self.game(hand=(REWARD,),mode='extra');self.play(g,REWARD);self.play(g,TWO,self.enemy(g))
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.damage_history),2)
        restored=self.portable(g);self.select(g);self.select(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hp(g,self.enemy(g)),496);self.portable(g)

    def test_c03_failed_choices_preserve_each_original_or_logical_waiting_boundary(self):
        for mode in ('parent','extra'):
            with self.subTest(mode=mode):
                g=self.game(hand=(REWARD,),mode=mode);self.play(g,REWARD);self.play(g,TWO,self.enemy(g));before=g.snapshot()
                with self.assertRaisesRegex(ResolutionError,'deliberate'):self.select(g,'bad')
                self.assertEqual(g.snapshot(),before);self.select(g);self.assertEqual(self.hp(g,self.enemy(g)),496)

    def test_c04_additional_packet_failure_rolls_back_entire_original_spell(self):
        g=self.game(hand=(REWARD,),mode='fail');self.play(g,REWARD);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.play(g,TWO,self.enemy(g))
        self.assertEqual(g.snapshot(),before)

    def test_c05_strict_origin_parent_codec_and_old_schema_rejection(self):
        g=self.game(hand=(REWARD,));self.play(g,REWARD);self.play(g,TWO,self.enemy(g))
        parent,extra=(r.health_result for r in g.state.damage_history);origin=extra.player_origin
        self.assertEqual(result_from_payload(extra.payload()),extra)
        with self.assertRaises(ValueError):PlayerHealthOrigin(True,origin.instance_id,RULE)
        with self.assertRaises(ValueError):replace(extra,player_origin=replace(origin,player_id=2))
        with self.assertRaises(ValueError):validate_player_origin(g.state,replace(extra,player_origin=replace(origin,instance_id=g.state.next_attachment_id)),g.registry)
        with self.assertRaises(ValueError):validate_player_origin(g.state,replace(extra,player_origin=replace(origin,spec_id='missing.gorishi')),g.registry)
        with self.assertRaises(ValueError):result_from_payload(tuple(r for r in parent.payload() if r[0]!='player_origin'))
        instance=self.programs(g)[0];request=PlayerEffectDamage(1,instance,parent.target_id,2,original_target_result=parent.payload())
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(request)))),request)
        fake=replace(parent,target_zone_epoch=parent.target_zone_epoch+1)
        with self.assertRaises(ValueError):validate_player_damage(g.state,g.registry,replace(request,original_target_result=fake.payload()))
        with self.assertRaises(ValueError):validate_player_damage(g.state,g.registry,replace(request,original_target_result=extra.payload()))
        old=deepcopy(g.snapshot());old['schema_version']=445
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,registry())

    def test_d00_additional_damage_can_be_the_real_lethal_packet(self):
        g=self.game(hand=(REWARD,),enemy_hero=TINY);self.play(g,REWARD);self.play(g,TWO,self.enemy(g))
        self.assertNotEqual(g.state.status,'playing');self.assertLessEqual(self.hp(g,self.enemy(g)),0)
        self.assertEqual(sum(e.kind=='game_ended' for e in g.events),1);self.portable(g)

    def test_d01_second_player_uses_own_persistent_source_and_original_enemy(self):
        g=self.game(hand=(REWARD,),pid=2);self.play(g,REWARD);self.play(g,TWO,self.enemy(g))
        self.assertEqual(self.hp(g,self.enemy(g)),496)
        self.assertEqual(g.state.damage_history[-1].health_result.player_origin.player_id,2);self.portable(g)


if __name__=='__main__':unittest.main()
