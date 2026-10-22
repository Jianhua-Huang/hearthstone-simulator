"""Native attack followups and original forced-attack residence operands."""
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.attack_followup_cards import load_batch
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, EndTurn, Game,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, ForceAttack, Freeze, GrantKeyword,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.interrupts import RedirectAttack
from hs_sim.engine.model import BoardPresenceReference
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import canonical_digest

REHGAR='CORE_CATA_004'; FINJA='CORE_CFM_344'; INQ='CS3_020'; BOLT='CORE_EX1_238'
YETI='CORE_CS2_182'; TIDE='CORE_EX1_509'; HUNTER='CORE_EX1_506'; AXE='CS2_106'


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    def bare(c):
        source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==FINJA)
        return (CombatDamage(source,c.target_id),)
    def badforce(c):
        return (ForceAttack(BoardPresenceReference(c.target_id,c.state.next_order+5),c.state.players[2].hero_id),)
    scripts=dict(silence=lambda c:(Silence(c.target_id),),freeze=lambda c:(Freeze(c.target_id),),
        poison=lambda c:(GrantKeyword(c.target_id,Keyword.POISONOUS,c.source_id),),
        kill=lambda c:(Destroy(c.target_id,c.source_id),),bare=bare,badforce=badforce)
    for key,body in scripts.items():
        r.register_behavior('k29.'+key,body)
        r.register_card(CardDefinition('k29.'+key,key,CardType.SPELL,on_play='k29.'+key,
            requires_target=True,metadata=meta))
    r.register_card(CardDefinition('k29.trade','Mutual lethal fixture',CardType.MINION,attack=5,health=3,metadata=meta))
    r.register_behavior('k29.fail',lambda c:(AddToHand(c.player_id,'missing.k29'),))
    if mode:
        def watch(c):
            if mode in ('summon_wait','summon_kill'):
                if c.event.player_id!=1 or c.state.entities[c.event.target_id].card_id not in (TIDE,HUNTER):return ()
                original=next((i for i in c.state.players[1].board if c.state.entities[i].card_id==FINJA),None)
                effects=(Destroy(original,c.source_id),)if original and mode=='summon_kill'else()
            else:
                if c.state.entities[c.event.source_id].kind!=CardType.HERO:return ()
                if mode=='redirect':
                    target=next(i for i in c.state.players[2].board if c.state.entities[i].card_id==YETI)
                    return (RedirectAttack(c.state.action_windows[-1].id,target),)
                original=(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==INQ)
                          if mode in ('source_return','source_silence') else c.event.target_id)
                pid=c.state.entities[original].controller
                effects=((Silence(original),) if mode=='source_silence' else
                    (ReturnToHand(original,to_owner=True),SummonFromZone(pid,zone=Zone.HAND,selection='first',
                        source_id=c.source_id,cause=SummonCause.capture(c))))
            return (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',effects),
                ChoiceOption('fail','Fail', (InvokeBehavior('k29.fail',c.source_id,c.player_id),))),c.source_id),)
        event='minion_summoned'if mode.startswith('summon')else'attack_declared'if mode=='redirect'else'attack_finished'
        r.register_behavior('k29.watch',watch)
        r.register_card(CardDefinition('k29.watch','Original boundary observer',CardType.MINION,health=8,
            triggers=(TriggerSpec(event,'k29.watch'),),metadata=meta))
    return r


class AttackFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=(YETI,)*5,weapon=None,enemy_weapon=None,active=1,mode=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            hero_power_card_id='HERO_08bp',weapon_card_id=weapon,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*5,hero_power_card_id='HERO_08bp',
                weapon_card_id=enemy_weapon,mana=40,max_mana=40,mana_cap=40)),
            active_player=active,seed=429),registry(mode)if mode else self.r)
    def eid(self,g,cid,p=1,zone='board'):
        return next(i for i in getattr(g.state.players[p],zone) if g.state.entities[i].card_id==cid)
    def count(self,g,cid,p=1,zone='hand'):
        return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[p],zone))
    def play(self,g,cid,target=None):
        p=g.state.active_player;eid=self.eid(g,cid,p,'hand');g.apply(PlayCard(p,eid,target));return eid
    def attack(self,g,cid,target=None,p=1):
        source=g.state.players[p].hero_id if cid=='hero'else self.eid(g,cid,p)
        g.apply(Attack(p,source,target or g.state.players[3-p].hero_id))
    def choose(self,g,key='ok'):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));fresh=registry(self.mode)
        restored=Game.from_snapshot(saved,fresh)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fresh).snapshot(),saved)
        for pid in (1,2):
            public=json.dumps(g.observe(pid))+json.dumps(g.for_player(pid).legal_actions())
            for key in ('character_attack_history','resolution_frame','presence_id','damage_history'):
                self.assertNotIn('"'+key+'"',public)
        return restored

    def test_full_source_pin_named_bolt_and_explicit_finja_identity(self):
        batch=load_batch();self.assertEqual(len(batch['cards']),3)
        for row in batch['cards']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(batch['reused_dependencies'][0]['record']['dbf_id'],69625)
        self.assertEqual(self.r.card(FINJA).metadata.deck_identity,'CFM_344')
        packet_ids={row['record']['id']for row in batch['cards']}
        self.assertIn(FINJA,packet_ids)
        self.assertNotIn('CFM_344',packet_ids)
        self.assertEqual(self.r.card(FINJA).id,FINJA)

    def test_each_real_root_pays_once_and_keeps_native_keyword(self):
        for cid,keyword in ((REHGAR,None),(FINJA,Keyword.STEALTH),(INQ,Keyword.RUSH)):
            with self.subTest(card=cid):
                g=self.game((cid,));eid=self.play(g,cid);card=g.registry.card(cid)
                self.assertEqual(g.state.players[1].mana,40-card.cost)
                self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(card.attack,card.health))
                self.assertEqual(len(card.triggers),1)
                if keyword:self.assertIn(keyword,g.state.entities[eid].keywords)

    def test_rehgar_self_attack_generates_complete_bolt_damage_and_overload(self):
        g=self.game(board=(REHGAR,),enemy=(YETI,));self.attack(g,REHGAR,self.eid(g,YETI,2))
        self.assertEqual(self.count(g,BOLT),1);self.play(g,BOLT,g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].overload_owed),(39,1));self.portable(g)

    def test_rehgar_left_and_right_neighbors_each_qualify(self):
        for board in ((YETI,REHGAR),(REHGAR,YETI)):
            g=self.game(board=board);self.attack(g,YETI);self.assertEqual(self.count(g,BOLT),1)

    def test_rehgar_nonadjacent_hero_and_enemy_attack_do_not_qualify(self):
        g=self.game(board=(REHGAR,TIDE,YETI));self.attack(g,YETI);self.assertEqual(self.count(g,BOLT),0)
        g=self.game(board=(REHGAR,),weapon=AXE);self.attack(g,'hero');self.assertEqual(self.count(g,BOLT),0)
        g=self.game(board=(REHGAR,),enemy=(YETI,),active=2);self.attack(g,YETI,p=2);self.assertEqual(self.count(g,BOLT),0)

    def test_rehgar_neighbor_that_dies_keeps_original_adjacency(self):
        g=self.game(board=(REHGAR,TIDE),enemy=(YETI,));self.attack(g,TIDE,self.eid(g,YETI,2))
        self.assertEqual(self.count(g,TIDE,zone='board'),0);self.assertEqual(self.count(g,BOLT),1)

    def test_rehgar_dying_or_silenced_source_does_not_grant_reward(self):
        g=self.game(board=(REHGAR,),enemy=('k29.trade',));self.attack(g,REHGAR,self.eid(g,'k29.trade',2))
        self.assertEqual(self.count(g,BOLT),0)
        g=self.game(('k29.silence',),board=(REHGAR,));self.play(g,'k29.silence',self.eid(g,REHGAR))
        self.attack(g,REHGAR);self.assertEqual(self.count(g,BOLT),0)

    def test_rehgar_full_hand_uses_normal_burn(self):
        g=self.game((YETI,)*10,board=(REHGAR,));self.attack(g,REHGAR)
        self.assertEqual(self.count(g,BOLT),0);self.assertEqual(sum(e.kind=='card_burned'for e in g.events),1)

    def test_finja_combat_kill_recruits_original_physical_murlocs_without_battlecry(self):
        g=self.game(board=(FINJA,),enemy=(TIDE,),deck=(YETI,HUNTER,TIDE))
        originals=set(g.state.players[1].deck[1:]);self.attack(g,FINJA,self.eid(g,TIDE,2))
        self.assertTrue(originals<=set(g.state.players[1].board));self.assertEqual(len(g.state.players[1].board),3)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].deck],[YETI])
        self.assertNotIn(Keyword.STEALTH,g.state.entities[self.eid(g,FINJA)].keywords);self.portable(g)

    def test_finja_nonlethal_attack_or_defensive_kill_does_not_recruit(self):
        g=self.game(board=(FINJA,),enemy=(YETI,),deck=(HUNTER,TIDE));self.attack(g,FINJA,self.eid(g,YETI,2))
        self.assertEqual(len(g.state.players[1].deck),2)
        g=self.game(board=(FINJA,),enemy=(TIDE,),deck=(HUNTER,TIDE))
        self.attack(g,FINJA);g.apply(EndTurn(1))  # Lose Stealth through an actual attack before defending.
        self.attack(g,TIDE,self.eid(g,FINJA),2);self.assertEqual(len(g.state.players[1].deck),2)

    def test_finja_mutual_lethal_source_does_not_recruit(self):
        g=self.game(board=(FINJA,),enemy=('k29.trade',),deck=(HUNTER,TIDE))
        self.attack(g,FINJA,self.eid(g,'k29.trade',2));self.assertEqual(g.state.players[1].board,[])
        self.assertEqual(len(g.state.players[1].deck),2)

    def test_finja_actual_poison_fatal_packet_is_a_combat_kill(self):
        g=self.game(('k29.poison',),board=(FINJA,),enemy=(YETI,),deck=(HUNTER,TIDE))
        self.play(g,'k29.poison',self.eid(g,FINJA));self.attack(g,FINJA,self.eid(g,YETI,2))
        self.assertEqual(len(g.state.players[1].deck),0)
        self.assertEqual(g.state.death_history[0].cause.kind,'poison')

    def test_finja_spell_kill_and_bare_compatibility_combat_do_not_claim_attack(self):
        for spell in ('k29.kill','k29.bare'):
            g=self.game((spell,),board=(FINJA,),enemy=(TIDE,),deck=(HUNTER,TIDE))
            self.play(g,spell,self.eid(g,TIDE,2));self.assertEqual(len(g.state.players[1].deck),2)
            self.assertEqual(g.state.character_attack_history,[])

    def test_finja_no_matching_murlocs_does_not_draw_or_consume_rng(self):
        g=self.game(board=(FINJA,),enemy=(TIDE,),deck=(YETI,));before=g.snapshot()['rng_state']
        self.attack(g,FINJA,self.eid(g,TIDE,2));self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(len(g.state.players[1].deck),1)

    def test_finja_one_free_slot_recruits_only_one_physical_card(self):
        g=self.game(board=(FINJA,)+(YETI,)*5,enemy=(TIDE,),deck=(HUNTER,TIDE))
        self.attack(g,FINJA,self.eid(g,TIDE,2));self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(len(g.state.players[1].deck),1)

    def test_finja_recruits_use_existing_khadgar_quantity_source(self):
        g=self.game(board=(FINJA,'CORE_DAL_575'),enemy=(TIDE,),deck=(HUNTER,TIDE))
        self.attack(g,FINJA,self.eid(g,TIDE,2));self.assertEqual(len(g.state.players[1].board),6)
        self.assertEqual(len(g.state.players[1].deck),0)

    def test_finja_waiting_each_delivery_recovers_and_retains_plan_after_source_death(self):
        g=self.game(board=('k29.watch',FINJA),enemy=(TIDE,),deck=(HUNTER,TIDE),mode='summon_kill')
        self.attack(g,FINJA,self.eid(g,TIDE,2));self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);self.choose(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.count(g,FINJA,zone='board'),0);self.portable(g);self.choose(g)
        self.assertEqual(len(g.state.players[1].deck),0);self.portable(g)

    def test_finja_failed_pending_choice_rolls_back_original_rng_and_frame(self):
        g=self.game(board=('k29.watch',FINJA),enemy=(TIDE,),deck=(HUNTER,TIDE),mode='summon_wait')
        self.attack(g,FINJA,self.eid(g,TIDE,2));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_inquisitor_follows_hero_face_attack_without_spending_normal_attack(self):
        g=self.game((INQ,),weapon=AXE);source=self.play(g,INQ);self.attack(g,'hero')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,19)
        self.assertEqual(g.state.entities[source].attacks_this_turn,0)
        self.assertEqual([r.declaration.forced for r in g.state.character_attack_history],[False,True]);self.portable(g)

    def test_inquisitor_follows_after_using_its_ordinary_rush(self):
        g=self.game((INQ,),weapon=AXE,enemy=(YETI,));source=self.play(g,INQ)
        self.attack(g,INQ,self.eid(g,YETI,2));self.attack(g,'hero')
        self.assertEqual(g.state.entities[source].attacks_this_turn,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,19)

    def test_frozen_inquisitor_still_follows_original_forced_policy(self):
        g=self.game(('k29.freeze',),board=(INQ,),weapon=AXE,enemy=(YETI,));source=self.eid(g,INQ)
        self.play(g,'k29.freeze',source)
        with self.assertRaises(IllegalAction):self.attack(g,INQ,self.eid(g,YETI,2))
        self.attack(g,'hero');self.assertTrue(g.state.entities[source].frozen)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,19)

    def test_inquisitor_uses_final_redirected_target_and_skips_original_face(self):
        g=self.game(board=('k29.watch',INQ),weapon=AXE,enemy=(YETI,),mode='redirect')
        self.attack(g,'hero');self.assertEqual(g.state.players[2].board,[])
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)
        self.assertEqual(len(g.state.character_attack_history),2)

    def test_inquisitor_dead_target_enemy_hero_or_friendly_minion_attack_do_not_follow(self):
        g=self.game(board=(INQ,),weapon=AXE,enemy=(TIDE,));self.attack(g,'hero',self.eid(g,TIDE,2))
        self.assertEqual(len(g.state.character_attack_history),1)
        g=self.game(board=(INQ,YETI));self.attack(g,YETI);self.assertEqual(len(g.state.character_attack_history),1)
        g=self.game(board=(INQ,),enemy_weapon=AXE,active=2);self.attack(g,'hero',p=2)
        self.assertEqual(len(g.state.character_attack_history),1)

    def test_inquisitor_waiting_original_source_return_does_not_rebind_to_new_residence(self):
        g=self.game(board=('k29.watch',INQ),weapon=AXE,mode='source_return');source=self.eid(g,INQ)
        before=BoardPresenceReference.capture(g.state,source);self.attack(g,'hero');self.portable(g);self.choose(g)
        self.assertEqual(self.eid(g,INQ),source)
        self.assertNotEqual(BoardPresenceReference.capture(g.state,source),before)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);self.portable(g)

    def test_inquisitor_waiting_original_defender_return_does_not_attack_new_residence(self):
        g=self.game(board=('k29.watch',INQ),weapon=AXE,enemy=(YETI,),mode='target_return')
        target=self.eid(g,YETI,2);self.attack(g,'hero',target);self.portable(g);self.choose(g)
        self.assertEqual(self.eid(g,YETI,2),target);self.assertEqual(g.state.entities[target].health,5)
        self.assertEqual(len(g.state.character_attack_history),1);self.portable(g)

    def test_inquisitor_already_accepted_work_survives_later_silence(self):
        g=self.game(board=('k29.watch',INQ),weapon=AXE,mode='source_silence')
        self.attack(g,'hero');self.portable(g);self.choose(g)
        self.assertTrue(g.state.entities[self.eid(g,INQ)].silenced)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,19)

    def test_captured_force_codec_keeps_old_operand_shape_and_rejects_future_or_unknown(self):
        g=self.game(board=(INQ,),enemy=(YETI,));a=self.eid(g,INQ);d=self.eid(g,YETI,2)
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        effect=ForceAttack(BoardPresenceReference.capture(g.state,a),BoardPresenceReference.capture(g.state,d))
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        legacy=ForceAttack(a,d);self.assertEqual(codec.decode(codec.encode(legacy)),legacy)
        for ref in (BoardPresenceReference(a,g.state.next_order+1),BoardPresenceReference(999999,1)):
            with self.assertRaises(ValueError):codec.encode(ForceAttack(ref,d))
        with self.assertRaises(ValueError):ForceAttack(True,d)

    def test_invalid_captured_force_rolls_back_whole_paid_action(self):
        g=self.game(('k29.badforce',),board=(INQ,));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k29.badforce',self.eid(g,INQ))
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
