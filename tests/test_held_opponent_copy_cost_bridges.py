"""Original conditional quote in paid waiting and existing repeat-cost windows."""
from copy import deepcopy
import json
import unittest

import test_native_held_opponent_copy_cards as f
from hs_sim.engine.model import RepeatCostFilter, RepeatMatchSpec, SpellRepeatSpec


SOURCE='k195.bridge'


def registry(mode):
    r=f.registry.__wrapped__()
    if mode=='wait':
        r.register_trigger_condition(SOURCE,lambda c:c.state.entities[c.event.source_id].card_id==f.CARD and c.event.player_id==c.player_id)
        r.register_behavior(SOURCE,lambda c:(f.RequestChoice(c.player_id,(
            f.ChoiceOption('ok','Continue'),
            f.ChoiceOption('fail','Rollback',(f.RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),f.InvokeBehavior(f.P+'fail',c.source_id,c.player_id))),
        ),c.source_id),))
        fields={'limited_triggers':(f.LimitedTriggerSpec('card_committed',SOURCE,condition_id=SOURCE),)}
    else:
        fields={'spell_repeats':(SpellRepeatSpec(class_mode='any',match=RepeatMatchSpec(
            recipient_cost=RepeatCostFilter('window_quote',maximum=1,quote_profile_id='repeat.cost.accepted_hand'))),)}
    r.register_card(f.CardDefinition(SOURCE,SOURCE,f.CardType.MINION,health=20,**fields));r.validate()
    return r


class HeldOpponentCopyCostBridgeTests(unittest.TestCase):
    def game(self,mode,qualified):
        self.mode=mode
        return f.Game.from_scenario(f.Scenario((
            f.PlayerSetup(f.HERO,hand=(f.CARD,f.P+'copy')if qualified else(f.CARD,),board=(SOURCE,),mana=100,max_mana=100,mana_cap=100),
            f.PlayerSetup(f.HERO,deck=(f.B,),board=(f.A,f.A),mana=100,max_mana=100,mana_cap=100)),seed=1951),registry(mode))

    def play(self,g,cid,target=None,entity=None):
        eid=entity if entity is not None else next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(f.PlayCard(1,eid,target));return eid

    def qualify(self,g):
        self.play(g,f.P+'copy')
        copy=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].copy_origin is not None)
        self.play(g,f.B,entity=copy.id)

    def choose(self,g,key):
        c=g.state.pending_choice;g.apply(f.SelectChoice(c.player_id,c.id,(key,)))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry(self.mode)
        self.assertIsNot(reader,g.registry);self.assertEqual(f.Game.from_snapshot(deepcopy(s),reader).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(f.replay(f.build_replay(g),reader).snapshot(),s)

    def test_native_conditional_paid_wait_restores_original_quote_and_choice_rollback(self):
        for qualified,amount in((False,5),(True,1)):
            with self.subTest(qualified=qualified):
                g=self.game('wait',qualified)
                if qualified:self.qualify(g)
                mana=g.state.players[1].mana;target=g.state.players[2].board[0];source=self.play(g,f.CARD,target)
                self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].zone,f.Zone.BOARD)
                self.assertEqual(g.state.players[1].mana,mana-amount)
                row=g.state.play_history[-1];match=row.submitted_cost.quote.intrinsic.condition_facts[0]
                self.assertEqual((row.source_id,row.cost,match.matched),(source,amount,qualified));self.portable(g)
                before=g.snapshot()
                with self.assertRaisesRegex(f.ResolutionError,'K195 deliberate'):self.choose(g,'fail')
                self.assertEqual(g.snapshot(),before);self.portable(g);self.choose(g,'ok')
                self.assertEqual(g.state.players[1].mana,mana-amount);self.assertEqual(g.state.entities[target].zone,f.Zone.GRAVEYARD)
                self.portable(g)

    def test_actual_accepted_hand_window_quote_controls_existing_spell_repeat(self):
        for qualified,amount,casts in((False,5,1),(True,1,2)):
            with self.subTest(qualified=qualified):
                g=self.game('repeat',qualified)
                if qualified:self.qualify(g)
                mana=g.state.players[1].mana;self.play(g,f.CARD,g.state.players[2].board[0])
                actual=[row for row in g.state.cast_history if row.card_id==f.CARD]
                self.assertEqual(len(actual),casts);self.assertEqual(g.state.players[1].mana,mana-amount)
                self.assertEqual(g.state.play_history[-1].cost,amount);self.portable(g)
