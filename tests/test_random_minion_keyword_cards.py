"""Current Core Coghammer composes existing battlecry/equipment/grant contracts."""
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.random_minion_keyword_cards import COGHAMMER, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import AddToHand, ChoiceOption, EquipWeapon, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay

YETI = 'CORE_CS2_182'


def registry():
    r = build_registry()
    r.register_behavior('k89.fail', lambda c:(AddToHand(c.player_id, 'unknown.k89'),))
    def wait(c):
        if c.event.source_id is None or c.state.entities[c.event.source_id].card_id != COGHAMMER:return ()
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok','Continue',()),
            ChoiceOption('bad','Fail',(InvokeBehavior('k89.fail',c.source_id,c.player_id),)),
        ),source_id=c.source_id),)
    r.register_behavior('k89.wait',wait)
    r.register_card(CardDefinition('k89.watch','Actual grant observer',CardType.MINION,health=8,
                                   triggers=(TriggerSpec('ability_granted','k89.wait'),)))
    r.register_card(CardDefinition('k89.sleep','Inactive body',CardType.MINION,health=8,dormant_turns=2))
    r.register_behavior('k89.equip',lambda c:(EquipWeapon(c.player_id,COGHAMMER),))
    r.register_card(CardDefinition('k89.equip','Direct equipment fixture',CardType.SPELL,on_play='k89.equip'))
    return r


class RandomMinionKeywordCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()

    def game(self,hand=(COGHAMMER,),board=(YETI,),enemy=(YETI,)):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=enemy,mana=10,max_mana=10),
        ),seed=89),self.r)

    def play(self,g,cid=COGHAMMER):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid));return eid

    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())
            for hidden in('MinionReference','RandomGrantMinionKeywords','rng_state','resolution_frame','behavior_id'):
                self.assertNotIn(hidden,public)
        return other

    def test_current_core_full_pin_weapon_face_and_historical_identity_only(self):
        data=load_batch();card=self.r.card(COGHAMMER);raw=data['cards'][0]['record']
        self.assertEqual((raw['dbf_id'],card.kind,card.cost,card.attack,card.durability),(130820,CardType.WEAPON,3,2,3))
        self.assertIsNotNone(card.battlecry);self.assertIsNone(card.on_play)
        self.assertEqual(data['evidence_only'][0]['record']['dbf_id'],raw['tags']['858'])
        self.assertNotIn('GVG_059',self.r.cards)

    def test_actual_weapon_play_grants_both_to_one_friendly_and_keeps_original_equipment(self):
        g=self.game(board=(YETI,YETI));rng=Random();rng.setstate(g._rng.getstate())
        selected=rng.choice(sorted(g.state.players[1].board));source=self.play(g)
        self.assertEqual(g.state.players[1].weapon_id,source);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(g._rng.getstate(),rng.getstate())
        for i in g.state.players[1].board:
            self.assertEqual(g.state.entities[i].keywords,{Keyword.DIVINE_SHIELD,Keyword.TAUNT}if i==selected else set())
        self.assertFalse(g.state.entities[g.state.players[2].board[0]].keywords)
        self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_empty_or_only_inactive_friendly_pool_keeps_rng_and_normal_weapon_play(self):
        for board in((),('k89.sleep',)):
            g=self.game(board=board);rng=g._rng.getstate();source=self.play(g)
            self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].weapon_id,source)
            self.assertEqual(g.state.players[1].mana,7)

    def test_actual_grants_wait_restore_failure_and_single_paid_battlecry(self):
        g=self.game(board=(YETI,'k89.watch'));self.play(g)
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        while g.state.pending_choice is not None:self.choose(g)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(len(g.state.battlecry_history),1)
        self.portable(g)

    def test_direct_equip_does_not_invent_a_played_weapon_battlecry(self):
        g=self.game(('k89.equip',));rng=g._rng.getstate();self.play(g,'k89.equip')
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].card_id,COGHAMMER)
        self.assertFalse(g.state.entities[g.state.players[1].board[0]].keywords)
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.battlecry_history)

    def test_equipped_attack_uses_original_damage_and_durability(self):
        g=self.game(board=());source=self.play(g)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[source].durability,2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
