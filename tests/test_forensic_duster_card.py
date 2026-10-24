"""Actual Duster entry through existing pending owner-start prices."""
import unittest
from functools import lru_cache

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.forensic_duster_card import ROOT,TAX,register_forensic_duster_card
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.mimiron_reported_tech_cards import load_batch
from hs_sim.engine import (CardDefinition,CardMetadata,CardClass,CardType,Game,PlayerSetup,
    Scenario,Registry,TargetSpec,TargetMode,TriggerSpec,ResolutionError)
from hs_sim.engine.actions import EndTurn,UseHeroPower
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.player_effects import RemovePlayerEffect,timed_count
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.secrets import area_count
from hs_sim.engine.turn_scheduling import QueueTurns,SkipTurns
from tools import card_batch as batch

P='k504.'
HERO,POWER,UNIT,SPELL,WEAPON,LOCATION,WATCH,FORM=(P+s for s in
    ('hero','power','unit','spell','weapon','location','watch','form'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None)


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=Registry(P+mode);register_forensic_duster_card(r)
    r.register_behavior(P+'noop',lambda c:())
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=1000,metadata=META))
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,cost=2,attack=2,health=4,metadata=META))
    r.register_card(CardDefinition(FORM,FORM,CardType.MINION,cost=1,attack=1,health=2,metadata=META))
    r.register_card(CardDefinition(SPELL,SPELL,CardType.SPELL,cost=2,on_play=P+'noop',metadata=META))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=2,attack=1,durability=2,metadata=META))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=2,durability=2,on_use=P+'noop',metadata=META))
    def prepare(c):
        if mode=='destroy':return (Destroy(c.target_id,c.source_id),)
        if mode=='return':return (ReturnToHand(c.target_id),)
        if mode=='silence':return (Silence(c.target_id),)
        if mode=='transform':return (Transform(c.target_id,FORM),)
        if mode=='control':return (ChangeControl(c.target_id,3-c.player_id),)
        if mode=='extra_caster':return (QueueTurns((c.player_id,c.player_id,3-c.player_id),c.source_id),)
        if mode=='extra_target':return (QueueTurns((3-c.player_id,3-c.player_id),c.source_id),)
        if mode=='skip':return (SkipTurns(3-c.player_id,1,c.source_id),)
        if mode=='indirect':return (TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),)
        if mode=='remove':return (RemovePlayerEffect(3-c.player_id,c.state.players[3-c.player_id].player_effects[0].id),)
        return ()
    r.register_behavior(P+'prepare',prepare)
    r.register_card(CardDefinition(POWER,POWER,CardType.HERO_POWER,on_use=P+'prepare',metadata=META,
        targeting=TargetSpec(TargetMode.REQUIRED,kinds=(CardType.MINION,),relation='any')))
    def fail(c):raise ResolutionError('K504 intentional continuation failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode=='end_install' and c.event.kind=='turn_ended' and c.event.player_id==c.player_id:
            source=next(c.state.entities[i] for i in c.state.players[c.player_id].board
                if c.state.entities[i].card_id==ROOT)
            return (TriggerBattlecry(MinionReference.capture(source),c.source_id),)
        if mode=='end_wait' and c.event.kind=='turn_ended' and c.event.player_id==2:
            return (RequestChoice(1,(ChoiceOption('continue','Continue'),),source_id=c.source_id),)
        source=c.state.entities.get(c.event.source_id)
        if c.event.kind!='battlecry_finished' or source is None or source.card_id!=ROOT:return ()
        if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode in ('wait','fail_choice'):
            return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),),source_id=c.source_id,
                on_select=P+'fail' if mode=='fail_choice' else None),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,attack=0,health=8,metadata=META,
        triggers=tuple(TriggerSpec(event,P+'watch') for event in ('battlecry_finished','turn_ended'))))
    return r


class ForensicDusterTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)
    mode='normal'

    def game(self,hand=(ROOT,),mode='normal',player=1,own=(),enemy=(),
            enemy_hand=(UNIT,SPELL,WEAPON,LOCATION),rules=None):
        self.mode=mode
        if mode in ('end_install','end_wait','wait','fail','fail_choice'):own=(*own,WATCH)
        players=tuple(PlayerSetup(HERO,hero_power_card_id=POWER,
            hand=hand if p==player else enemy_hand,board=own if p==player else enemy,
            deck=(UNIT,)*10,mana=30,max_mana=30,mana_cap=30) for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=504),fixture(mode),rules)

    def price(self,g,cid=UNIT,player=2):
        return quote_cost(g.state,g.registry,self.entity(g,cid,player)).amount

    def power(self,g,target,player=1):
        g.apply(UseHeroPower(player,g.state.players[player].hero_power_id,target))

    def test_complete_reused_primary_faces_actual_body_and_unimplemented_producer(self):
        data=load_batch();raw=next(v['record'] for v in data['evidence_only'] if v['record']['id']==ROOT)
        faces=[o for o in data['official_observations'] if o['card_id']==ROOT]
        self.assertEqual(len(faces),2)
        for o in faces:batch.check_face(raw,o['face'],o['locale'])
        r=batch.registration_prefix(build_registry,
            'hs_sim.cards.forensic_duster_card.register_forensic_duster_card',
            register_forensic_duster_card,after=True);d=r.card(ROOT)
        self.assertEqual((d.cost,d.attack,d.health,d.metadata),(raw['cost'],raw['attack'],raw['health'],metadata_from_record(raw)))
        self.assertEqual((d.cost,d.attack,d.health),(3,3,4))
        self.assertIn(ROOT,r.pool_cards)
        for cid in ('BE_588','AV_135'):
            with self.assertRaises(UnsupportedDefinitionError):r.card(cid)

    def test_both_players_pay_three_and_tax_only_opponents_next_turn_minions(self):
        for p in (1,2):
            with self.subTest(player=p):
                g=self.game(hand=(ROOT,UNIT),player=p);other=3-p;source=self.play(g,ROOT,player=p)
                self.assertEqual(g.state.players[p].mana,27)
                pending=g.state.players[other].player_effects
                self.assertEqual([(e.spec_id,e.source_id,e.source_card_id) for e in pending],[(TAX,source,ROOT)])
                self.assertEqual(self.price(g,player=other),2)
                g.apply(EndTurn(p));self.assertFalse(g.state.players[other].player_effects)
                self.assertEqual((self.price(g,player=other),self.price(g,player=p)),(3,2))
                for cid in (SPELL,WEAPON,LOCATION):self.assertEqual(self.price(g,cid,other),2)
                power=g.state.entities[g.state.players[other].hero_power_id]
                self.assertEqual(quote_cost(g.state,g.registry,power).amount,0)
                g.apply(EndTurn(other));self.assertEqual(self.price(g,player=other),2)

    def test_two_minion_payments_in_one_interval_do_not_consume_tax(self):
        g=self.game(enemy_hand=(UNIT,UNIT,UNIT));self.play(g,ROOT);g.apply(EndTurn(1))
        before=g.state.players[2].mana
        self.play(g,UNIT,player=2);self.play(g,UNIT,player=2)
        self.assertEqual(g.state.players[2].mana,before-6)
        self.assertEqual(self.price(g),3)
        self.assertIsNone(g.state.players[2].cost_modifiers[0].uses_remaining)

    def test_caster_extra_turns_do_not_activate_or_spend_pending_tax(self):
        g=self.game(mode='extra_caster');source=self.play(g,ROOT);self.power(g,source)
        for _ in range(2):
            g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)
            self.assertEqual(self.price(g),2);self.assertEqual(len(g.state.players[2].player_effects),1)
        g.apply(EndTurn(1));self.assertEqual((g.state.active_player,self.price(g)),(2,3))

    def test_skipped_target_slot_preserves_program_for_next_actual_start(self):
        g=self.game(mode='skip');source=self.play(g,ROOT);self.power(g,source)
        g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)
        self.assertEqual(self.price(g),2);self.assertEqual(len(g.state.players[2].player_effects),1)
        g.apply(EndTurn(1));self.assertEqual((g.state.active_player,self.price(g)),(2,3))

    def test_target_extra_turn_receives_tax_once_and_next_extra_is_untaxed(self):
        g=self.game(mode='extra_target');source=self.play(g,ROOT);self.power(g,source)
        g.apply(EndTurn(1));self.assertEqual((g.state.active_player,self.price(g)),(2,3))
        g.apply(EndTurn(2));self.assertEqual((g.state.active_player,self.price(g)),(2,2))

    def test_duplicate_battlecries_stack_without_consuming_secret_or_ongoing_capacity(self):
        g=self.game(hand=(ROOT,ROOT),rules=Ruleset(max_ongoing_effects=1,max_secret_zone=1))
        sources=(self.play(g,ROOT),self.play(g,ROOT));p=g.state.players[2]
        self.assertEqual(len(p.player_effects),2)
        self.assertEqual((timed_count(p,g.registry),area_count(p,g.registry)),(0,0))
        g.apply(EndTurn(1));self.assertEqual(self.price(g),4)
        self.assertEqual(tuple(m.source_id for m in g.state.players[2].cost_modifiers),sources)
        g.apply(EndTurn(2));self.assertEqual(self.price(g),2)
        self.assertFalse(g.state.players[2].cost_modifiers)

    def test_removing_one_pending_source_keeps_other_source_contribution(self):
        g=self.game(hand=(ROOT,ROOT),mode='remove');first=self.play(g,ROOT);second=self.play(g,ROOT)
        self.power(g,first);self.assertEqual(len(g.state.players[2].player_effects),1)
        g.apply(EndTurn(1));self.assertEqual(self.price(g),3)
        self.assertEqual(g.state.players[2].cost_modifiers[0].source_id,second)

    def test_source_death_return_silence_transform_and_control_leave_original_tax_owner(self):
        for mode in ('destroy','return','silence','transform','control'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);source=self.play(g,ROOT)
                self.power(g,source);self.assertEqual(self.price(g),2)
                if mode=='control':self.assertEqual(g.state.entities[source].controller,2)
                g.apply(EndTurn(1));self.assertEqual(self.price(g),3)
                self.assertEqual(g.state.players[2].cost_modifiers[0].source_id,source)
                self.assertFalse(g.state.players[1].cost_modifiers)

    def test_indirect_enemy_battlecry_during_targets_turn_waits_for_next_real_start(self):
        g=self.game(hand=(UNIT,),enemy=(ROOT,),mode='indirect');source=self.entity(g,ROOT,2,'board').id
        self.power(g,source);self.assertEqual(self.price(g,player=1),2)
        self.assertEqual(len(g.state.players[1].player_effects),1)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,player=1),2)
        g.apply(EndTurn(2));self.assertEqual(self.price(g,player=1),3)
        g.apply(EndTurn(1));self.assertEqual(self.price(g,player=1),2)

    def test_end_reaction_install_activates_at_upcoming_opponent_start(self):
        g=self.game(hand=(),own=(ROOT,),mode='end_install');g.apply(EndTurn(1))
        self.assertEqual((g.state.active_player,self.price(g)),(2,3))
        self.assertEqual(g.state.battlecry_history[-1].origin,'effect')

    def test_pending_paid_choice_restores_clones_replays_and_preserves_private_hand(self):
        g=self.game(mode='wait');self.play(g,ROOT);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana,27);self.portable(g)
        other=g.for_player(1).observe()['observation']['players'][1]['hand']
        self.assertTrue(all(row['card_id'] is None for row in other))
        self.choose(g);g.apply(EndTurn(1));self.assertEqual(self.price(g),3)

    def test_active_tax_restore_clone_replay_and_end_wait_expire_once(self):
        g=self.game(mode='end_wait');self.play(g,ROOT);g.apply(EndTurn(1))
        self.assertEqual(self.price(g),3);self.portable(g)
        g.apply(EndTurn(2));self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.price(g),3);self.portable(g)
        self.choose(g);self.assertEqual(self.price(g),2)
        self.assertFalse(g.state.players[2].cost_modifiers)

    def test_late_root_failure_restores_payment_program_and_opponent_view(self):
        g=self.game(mode='fail');before=g.snapshot();view=g.for_player(2).observe()
        with self.assertRaises(ResolutionError):self.play(g,ROOT)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.for_player(2).observe(),view)

    def test_failed_post_body_choice_preserves_paid_pending_program(self):
        g=self.game(mode='fail_choice');self.play(g,ROOT);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,27)
        self.assertEqual(len(g.state.players[2].player_effects),1)
