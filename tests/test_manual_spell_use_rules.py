"""Dynamic targetless spell admission shares public rules without rechecking payment."""
from dataclasses import replace
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, IllegalAction, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, Destroy, GainArmor, RequestChoice
from hs_sim.engine.registry import PlayerRuleContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.engine.spell_casts import CastSpell


def registry(*, wait=False, predicate=None, visibility='player'):
    r = Registry('manual-spell-use-tests-v1')
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    r.register_card(CardDefinition('unit','Unit',CardType.MINION,health=4))
    def allowed(c):
        enemy = c.observation['players'][2-c.player_id]
        return bool(enemy['board'])
    r.register_use_rule('gate',predicate or allowed,visibility=visibility)
    r.register_behavior('body',lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition('spell','Spell',CardType.SPELL,cost=2,on_play='body',use_rule='gate'))
    r.register_behavior('auto',lambda c:(CastSpell(c.player_id,'spell',c.source_id),))
    def bypass(c):
        source = next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == 'spell')
        return (PlayFromHand(PlayCard(c.player_id,source)),)
    r.register_behavior('bypass',bypass)
    for cid in ('auto','bypass'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    if wait:
        def watch(c):
            if c.state.entities[c.event.source_id].card_id != 'spell':return ()
            target = c.state.players[3-c.player_id].board[0]
            return (RequestChoice(c.player_id,(ChoiceOption('remove','Remove last enemy',(Destroy(target,c.source_id),)),),c.source_id),)
        r.register_behavior('watch',watch)
        r.register_card(CardDefinition('watch','Watch',CardType.MINION,health=4,triggers=(TriggerSpec('card_committed','watch'),)))
    r.validate();return r


class ManualSpellUseRuleTests(unittest.TestCase):
    def game(self,*,enemy=False,wait=False,hand=('spell',),r=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=('watch',)if wait else (),mana=10,max_mana=10),
            PlayerSetup('hero',board=('unit',)if enemy else (),hand=('unit',)),),seed=601),r or registry(wait=wait))

    def source(self,g,cid='spell'):
        return next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)

    def test_false_gate_rejects_raw_and_player_enumeration_before_payment_and_rng(self):
        g = self.game();before = g.snapshot();port = g.for_player(1)
        self.assertFalse(any(isinstance(a,PlayCard) for a in g.legal_actions()))
        listing = port.legal_actions();self.assertIsNone(listing['error'])
        self.assertFalse(any(a['type'] == 'play_card'for a in listing['actions']))
        with self.assertRaisesRegex(IllegalAction,'use condition'):g.apply(PlayCard(1,self.source(g)))
        self.assertEqual(g.snapshot(),before)

    def test_true_gate_uses_detached_player_context_and_hides_enemy_hand(self):
        calls = []
        def allowed(c):
            self.assertIsInstance(c,PlayerRuleContext);self.assertIsNone(c.target)
            self.assertEqual(c.source['card_id'],'spell')
            self.assertIsNone(c.observation['players'][1]['hand'][0].get('card_id'))
            c.observation['players'][0]['hand'].clear();calls.append(True);return True
        g = self.game(r=registry(predicate=allowed));source = self.source(g)
        self.assertTrue(any(isinstance(a,PlayCard) for a in g.legal_actions()))
        self.assertIn(source,g.state.players[1].hand);g.apply(PlayCard(1,source))
        self.assertTrue(calls);self.assertEqual((g.state.players[1].mana,g.state.entities[g.state.players[1].hero_id].armor),(8,1))

    def test_private_predicate_is_rejected_by_player_port_before_it_runs(self):
        calls = [];g = self.game(r=registry(predicate=lambda c:calls.append(True)or True,visibility='omniscient'))
        port = g.for_player(1);before = g.snapshot();listing = port.legal_actions()
        self.assertEqual(listing['error'],'unsupported_rule')
        card = listing['observation']['players'][0]['hand'][0]['ref']
        result = port.submit({'revision':listing['revision'],'action':{'type':'play_card','card':card}})
        self.assertEqual(result['error'],'unsupported_rule');self.assertEqual(calls,[]);self.assertEqual(g.snapshot(),before)

    def test_internal_hand_route_cannot_bypass_gate_and_rolls_back_outer_action(self):
        g = self.game(hand=('bypass','spell'));before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'use condition'):g.apply(PlayCard(1,self.source(g,'bypass')))
        self.assertEqual(g.snapshot(),before)

    def test_automatic_cast_keeps_separate_admission(self):
        g = self.game(hand=('auto',));g.apply(PlayCard(1,self.source(g,'auto')))
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1)

    def test_original_acceptance_survives_wait_restore_replay_and_loss_of_last_enemy(self):
        g = self.game(enemy=True,wait=True);g.apply(PlayCard(1,self.source(g)))
        self.assertEqual(g.state.players[1].mana,8);self.assertIsNotNone(g.state.pending_choice)
        copies = (g.clone(),Game.from_snapshot(g.snapshot(),registry(wait=True)),replay(build_replay(g),registry(wait=True)))
        for other in (g,*copies):
            self.assertEqual(other.snapshot(),g.snapshot())
        for other in (g,*copies):
            choice = other.state.pending_choice;other.apply(SelectChoice(1,choice.id,('remove',)))
            self.assertEqual(other.state.players[2].board,[])
            self.assertEqual((other.state.players[1].mana,other.state.entities[other.state.players[1].hero_id].armor),(8,1))
        for other in copies:self.assertEqual(other.snapshot(),g.snapshot())

    def test_bad_rule_result_or_exception_fails_atomically(self):
        def fail(c):raise ValueError('deliberate predicate failure')
        for predicate in (lambda c:1,fail):
            g = self.game(r=registry(predicate=predicate));before = g.snapshot()
            with self.assertRaises(ResolutionError):g.apply(PlayCard(1,self.source(g)))
            self.assertEqual(g.snapshot(),before)

    def test_spell_gate_does_not_reinterpret_active_limits_and_missing_rules_stay_explicit(self):
        spell = CardDefinition('s','S',CardType.SPELL,use_rule='missing')
        r = Registry('invalid-spell-use');r.register_card(spell)
        with self.assertRaises(ValueError):r.validate()
        for card in (replace(spell,on_use='body'),replace(spell,uses_per_turn=2),replace(spell,requires_board_space=True),
                replace(spell,kind=CardType.MINION,health=2)):
            with self.assertRaises(ValueError):Registry._validate_card(card)
