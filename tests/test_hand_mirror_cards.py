"""Actual hidden-hand disruption and copy-bound private damage death."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.hand_mirror_cards import PREFIX,load_batch
from hs_sim.engine import Game,PlayCard,PlayerSetup,Scenario,SelectChoice,CardDefinition,CardType,Keyword,TriggerSpec,Zone
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,GainArmor,GrantDeathrattle,
    GrantKeyword,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.hand_identity_shuffle import ShuffleSharedHandCard
from hs_sim.engine.copy_followups import ContinueCopiedMinion,followup_record,original_copy_reference,validate_followup_events
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause,validate_queue
from hs_sim.engine.model import SummonQuantitySpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference

YETI='CORE_CS2_182';ILLUSION='EDR_780';ASSAILANT='EDR_524'


def registry():
    r=build_registry()
    def copied(c,mode='current',followup=None):
        return CopyMinion(c.target_id,c.player_id,mode=mode,cause=SummonCause.capture(c),on_summon=followup)
    r.register_behavior('m39.buff',lambda c:(Buff(c.target_id,2,3,c.source_id),))
    r.register_behavior('m39.waitbuff',lambda c:(RequestChoice(1,(
        ChoiceOption('ok','Buff original copy',(Buff(c.target_id,2,3,c.source_id),)),
        ChoiceOption('bad','Rollback choice',(InvokeBehavior('m39.fail',c.source_id,1),))),c.source_id),))
    r.register_behavior('m39.dr',lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior('m39.fail',lambda c:(AddToHand(1,'missing.m39'),))
    scripts={
        'ping':lambda c:(Damage(c.target_id,1,c.source_id),),
        'zero':lambda c:(Damage(c.target_id,0,c.source_id),),
        'heal':lambda c:(Heal(c.target_id,1,c.source_id),),
        'shield':lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),
        'immune':lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'steal':lambda c:(ChangeControl(c.target_id,2),),
        'arm':lambda c:(GrantDeathrattle(c.target_id,'m39.dr',c.source_id),),
        'copy':lambda c:(copied(c),),'base':lambda c:(copied(c,'base'),),
        'follow':lambda c:(copied(c,followup='m39.buff'),),
        'waitfollow':lambda c:(copied(c,followup='m39.waitbuff'),),
        'copyfail':lambda c:(copied(c,followup='m39.buff'),AddToHand(1,'missing.m39')),
        'unknown':lambda c:(copied(c,followup='missing.m39'),),
        'shufflefail':lambda c:(ShuffleSharedHandCard(1,c.source_id),AddToHand(1,'missing.m39')),
        'handbuff':lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]),3,4,c.source_id),),
    }
    for key,body in scripts.items():
        r.register_behavior('m39.'+key,body)
        r.register_card(CardDefinition('m39.'+key,key,CardType.SPELL,on_play='m39.'+key,
            requires_target=key not in('shufflefail','handbuff')))
    r.register_card(CardDefinition('m39.double','Quantity fixture',CardType.MINION,health=8,summon_quantities=(SummonQuantitySpec(),)))
    for key in('a','b'):
        r.register_card(CardDefinition('m39.'+key,key,CardType.MINION,attack=1,health=5,
            metadata=replace(r.card(YETI).metadata,deck_identity='shared.deck.identity')))
    def watch(c,mode):
        entity=c.state.entities[c.event.target_id]
        if entity.origin_entity_id is None:return ()
        if mode=='waiter':return(RequestChoice(1,(
            ChoiceOption('ok','Continue original copy',()),ChoiceOption('bad','Rollback choice',(InvokeBehavior('m39.fail',c.source_id,1),))),c.source_id),)
        if mode=='morpher':return(Transform(entity.id,YETI),)
        if mode=='noise':return(Summon(1,YETI),)
        return(ReturnToHand(entity.origin_entity_id),)
    for key in('waiter','morpher','noise','returner'):
        r.register_behavior('m39.'+key,lambda c,mode=key:watch(c,mode))
        r.register_card(CardDefinition('m39.'+key,key,CardType.MINION,health=8,
            triggers=(TriggerSpec('minion_summoned','m39.'+key),)))
    return r


class HandMirrorCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),deck=(),seed=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,mana=40,max_mana=40,mana_cap=40)),seed=seed),self.registry)
    def play(self,g,cid,target=None):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));h=Game.from_snapshot(saved,registry())
        self.assertEqual(h.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return h
    def fragile(self,g):
        return next(e for e in g.state.entities.values()if e.zone==Zone.BOARD and any(a.behavior_id==PREFIX+'fragile'for a in e.abilities))
    def added_triggers(self,e):return[a for a in e.abilities if a.kind=='trigger'and a.behavior_id.startswith(PREFIX)]

    def test_complete_printed_faces_and_raw_enchantments_are_not_blank_definitions(self):
        for cid,stats in((ASSAILANT,(4,3,5)),(ILLUSION,(3,2,4))):
            c=self.registry.card(cid);self.assertEqual((c.cost,c.attack,c.health),stats);self.assertTrue(c.battlecry)
            self.assertEqual(c.metadata.tribes,('demon',))
        data=load_batch();self.assertEqual(len(data['raw_only_enchantment_evidence']),2)
        self.assertNotIn('EDR_780e',self.registry.cards);self.assertNotIn('EDR_780e1',self.registry.cards)

    def test_assailant_one_physical_match_only_and_preserves_original_local_state(self):
        g=self.game((ASSAILANT,YETI,'m39.handbuff'),enemy_hand=(YETI,YETI,'CORE_CS2_023'))
        original=set(g.state.players[2].hand);self.play(g,'m39.handbuff');self.play(g,ASSAILANT)
        self.assertEqual(len(g.state.players[2].hand),2);self.assertEqual(len(g.state.players[2].deck),1)
        moved=g.state.players[2].deck[0];self.assertIn(moved,original);self.assertEqual(g.state.entities[moved].card_id,YETI)
        self.assertEqual(g.state.entities[moved].owner,2);self.assertEqual(g.state.entities[moved].controller,2)
        self.assertFalse(g.state.discard_history);self.assertFalse(g.state.death_history);self.portable(g)

    def test_assailant_same_face_ignores_buffs_but_not_deck_copy_limit_alias(self):
        g=self.game((ASSAILANT,YETI,'m39.handbuff'),enemy_hand=(YETI,));self.play(g,'m39.handbuff');eid=g.state.players[2].hand[0]
        self.play(g,ASSAILANT);self.assertEqual(g.state.players[2].deck,[eid]);self.assertEqual(g.state.entities[eid].attack,7)
        other=self.game((ASSAILANT,'m39.a'),enemy_hand=('m39.b',));rng=other._rng.getstate();self.play(other,ASSAILANT)
        self.assertEqual(len(other.state.players[2].hand),1);self.assertEqual(other._rng.getstate(),rng)

    def test_assailant_played_source_not_still_held_and_empty_pool_no_rng(self):
        for hand,enemy in(((ASSAILANT,),(ASSAILANT,)),((ASSAILANT,YETI),()),((ASSAILANT,YETI),('CORE_CS2_023',))):
            g=self.game(hand,enemy_hand=enemy);rng=g._rng.getstate();self.play(g,ASSAILANT)
            self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.players[2].deck)

    def test_assailant_hidden_opponent_cards_do_not_become_known(self):
        g=self.game((ASSAILANT,YETI),enemy_hand=(YETI,'CORE_CS2_023'));self.play(g,ASSAILANT)
        view=g.observe(1);text=json.dumps(view,ensure_ascii=False)
        self.assertNotIn('CORE_CS2_023',text);self.assertNotIn('source_sha256',text)
        self.assertFalse(any(e['kind']=='card_revealed'for e in g.player_events(1)))

    def test_assailant_late_failure_restores_cards_knowledge_and_rng(self):
        g=self.game(('m39.shufflefail',YETI),enemy_hand=(YETI,YETI));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'m39.shufflefail')
        self.assertEqual(g.snapshot(),saved)

    def test_illusion_first_pair_one_fragile_actual_copy_and_both_views_hide_assignment(self):
        games=[self.game((ILLUSION,),seed=i)for i in(0,1)]
        for g in games:
            source=self.play(g,ILLUSION);self.assertEqual(len(g.state.players[1].board),2)
            copies=[g.state.entities[e]for e in g.state.players[1].board if e!=source]
            self.assertEqual(copies[0].origin_entity_id,source)
            self.assertEqual(len(self.added_triggers(g.state.entities[source])),1);self.assertEqual(len(self.added_triggers(copies[0])),1)
            self.assertEqual(len([e for e in g.state.entities.values()if any(a.behavior_id==PREFIX+'fragile'for a in e.abilities)]),1)
            self.portable(g)
        self.assertNotEqual(self.fragile(games[0]).id,self.fragile(games[1]).id)
        for p in(1,2):self.assertEqual(games[0].observe(p),games[1].observe(p))

    def test_illusion_damage_death_uses_actual_minion_death_and_original_deathrattle(self):
        g=self.game((ILLUSION,'m39.arm','m39.ping'));self.play(g,ILLUSION);e=self.fragile(g)
        self.play(g,'m39.arm',e.id);self.play(g,'m39.ping',e.id)
        self.assertEqual(g.state.entities[e.id].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].board),1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)
        self.assertEqual(g.state.death_history[-1].card_id,ILLUSION);self.portable(g)

    def test_illusion_zero_heal_shield_immune_and_silence_follow_normal_rules(self):
        g=self.game((ILLUSION,'m39.zero','m39.heal','m39.shield','m39.immune','m39.silence')+('m39.ping',)*3);self.play(g,ILLUSION);e=self.fragile(g)
        self.play(g,'m39.zero',e.id);self.play(g,'m39.heal',e.id);self.play(g,'m39.shield',e.id);self.play(g,'m39.ping',e.id)
        self.assertIn(e.id,g.state.players[1].board);self.assertEqual(g.state.entities[e.id].health,4)
        self.play(g,'m39.immune',e.id);self.play(g,'m39.ping',e.id);self.assertIn(e.id,g.state.players[1].board)
        self.play(g,'m39.silence',e.id);self.play(g,'m39.ping',e.id);self.assertEqual(g.state.entities[e.id].health,3);self.portable(g)

    def test_illusion_return_resets_marker_and_control_change_keeps_current_body(self):
        g=self.game((ILLUSION,'m39.bounce'));self.play(g,ILLUSION);e=self.fragile(g);self.play(g,'m39.bounce',e.id)
        self.assertEqual(g.state.entities[e.id].zone,Zone.HAND);self.assertFalse(self.added_triggers(g.state.entities[e.id]));self.portable(g)
        g=self.game((ILLUSION,'m39.steal','m39.ping'));self.play(g,ILLUSION);e=self.fragile(g);self.play(g,'m39.steal',e.id);self.play(g,'m39.ping',e.id)
        self.assertEqual(g.state.entities[e.id].zone,Zone.GRAVEYARD);self.assertEqual(g.state.death_history[-1].controller,2);self.portable(g)

    def test_illusion_current_copy_inherits_fragility_base_copy_does_not(self):
        g=self.game((ILLUSION,'m39.copy','m39.base','m39.ping'));self.play(g,ILLUSION);weak=self.fragile(g);before=set(g.state.players[1].board)
        self.play(g,'m39.copy',weak.id);current=next(e for e in g.state.players[1].board if e not in before);before.add(current)
        self.assertTrue(any(a.behavior_id==PREFIX+'fragile'for a in g.state.entities[current].abilities))
        self.play(g,'m39.base',weak.id);base=next(e for e in g.state.players[1].board if e not in before)
        self.assertFalse(self.added_triggers(g.state.entities[base]));self.play(g,'m39.ping',current)
        self.assertEqual(g.state.entities[current].zone,Zone.GRAVEYARD);self.portable(g)

    def test_copy_followup_never_marks_unrelated_later_summon(self):
        g=self.game((ILLUSION,),board=('m39.noise',));source=self.play(g,ILLUSION)
        yeti=next(g.state.entities[e]for e in g.state.players[1].board if g.state.entities[e].card_id==YETI)
        self.assertFalse(self.added_triggers(yeti));self.assertEqual(len(self.added_triggers(g.state.entities[source])),1);self.portable(g)

    def test_copy_transformed_before_followup_does_not_mark_replacement(self):
        g=self.game((ILLUSION,),board=('m39.morpher',));self.play(g,ILLUSION)
        self.assertFalse(any(self.added_triggers(g.state.entities[e])for e in g.state.players[1].board));self.portable(g)

    def test_copy_source_return_before_followup_never_marks_hand_incarnation(self):
        g=self.game((ILLUSION,),board=('m39.returner',));source=self.play(g,ILLUSION)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertFalse(self.added_triggers(g.state.entities[source]));self.portable(g)

    def test_full_board_copy_failure_has_no_pair_assignment_or_rng(self):
        g=self.game((ILLUSION,),board=(YETI,)*6);rng=g._rng.getstate();self.play(g,ILLUSION)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g._rng.getstate(),rng)
        self.assertFalse(any(self.added_triggers(g.state.entities[e])for e in g.state.players[1].board));self.portable(g)

    def test_copy_reaction_wait_restores_original_owed_followup_and_bad_choice_rolls_back(self):
        g=self.game((ILLUSION,),board=('m39.waiter',));self.play(g,ILLUSION);self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(any(self.added_triggers(g.state.entities[e])for e in g.state.players[1].board));h=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot());self.portable(g)

    def test_copy_queue_cannot_omit_followup_or_borrow_original_as_beneficiary(self):
        g=self.game((ILLUSION,),board=('m39.waiter',));self.play(g,ILLUSION)
        work=(*g._frame.prefix,*g._frame.continuation);effect=next(x for x in work if type(x)is ContinueCopiedMinion)
        with self.assertRaises(ValueError):validate_queue(g.state,g.registry,tuple(x for x in work if x is not effect))
        original=g.state.entities[next(e for e in g.state.players[1].board if g.state.entities[e].card_id==ILLUSION and g.state.entities[e].origin_entity_id is None)]
        with self.assertRaises(ValueError):followup_record(g.state,g.registry,replace(effect,beneficiary=MinionReference.capture(original)))

    def test_public_copy_followup_each_actual_quantity_body_and_original_source_preserved(self):
        g=self.game(('m39.follow',),board=('m39.double',YETI));target=g.state.players[1].board[-1];self.play(g,'m39.follow',target)
        copies=[g.state.entities[e]for e in g.state.players[1].board if g.state.entities[e].origin_entity_id==target]
        self.assertEqual(len(copies),2);self.assertTrue(all((e.attack,e.max_health)==(6,8)for e in copies))
        self.assertEqual(g.state.entities[target].max_health,5);self.portable(g)

    def test_public_copy_callback_wait_is_accepted_once_and_missing_receipt_rejected(self):
        g=self.game(('m39.waitfollow',),board=(YETI,));self.play(g,'m39.waitfollow',g.state.players[1].board[0]);h=self.portable(g)
        saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(h);self.assertEqual(g.snapshot(),h.snapshot())
        clone=g.clone();clone._events=[e for e in clone._events if e.kind!='copy_followup_started']
        with self.assertRaises(ValueError):validate_followup_events(clone)
        self.portable(g)

    def test_public_copy_unknown_callback_and_late_failure_are_atomic(self):
        for cid in('m39.unknown','m39.copyfail'):
            g=self.game((cid,),board=(YETI,));saved=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,cid,g.state.players[1].board[0])
            self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ValueError):CopyMinion(1,1,on_summon='m39.buff')

    def test_original_copy_context_rejects_forged_beneficiary_even_when_header_matches(self):
        from hs_sim.engine.registry import RuleContext
        g=self.game(('m39.waitfollow',),board=(YETI,));source=g.state.players[1].board[0]
        self.play(g,'m39.waitfollow',source)
        event=next(e for e in g.events if e.kind=='copy_followup_started')
        context=RuleContext(g.state,event.source_id,event.player_id,target_id=event.target_id,event=event)
        self.assertEqual(original_copy_reference(context).entity_id,source)
        data=dict(event.data);payload=json.loads(data['followup']);payload['beneficiary']['entity_id']=source
        data['followup']=json.dumps(payload)
        forged=replace(context,event=replace(event,data=tuple(sorted(data.items()))))
        with self.assertRaises(ValueError):original_copy_reference(forged)


if __name__=='__main__':unittest.main()
