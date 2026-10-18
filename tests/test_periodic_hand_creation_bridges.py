"""Actual Circadiamancer pauses at its first generated-card notification."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

import test_periodic_hand_cost_cards as f
import test_native_held_opponent_copy_cards as core
from hs_sim.engine.effects import ChoiceOption,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec

P='k198_birth.';WATCH=P+'watch'


@lru_cache(maxsize=None)
def registry():
    r=f.registry.__wrapped__(P)
    def eligible(c):
        source=c.state.entities.get(c.event.source_id)
        return source is not None and source.card_id==f.CIRCADIA and c.event.player_id==c.player_id
    def pause(c):
        target=c.state.entities[c.event.target_id]
        if len(f.stamps(target))!=1:raise ResolutionError('Birth notification lost its atomic hand grant')
        return(RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,1),)),
            ChoiceOption('fail','Rollback',(
                RandomDamage(tuple(c.state.players[p].hero_id for p in(1,2)),1,c.source_id),
                InvokeBehavior(f.P+'fail',c.source_id,c.player_id))),
        ),c.source_id),)
    r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'pause',pause)
    r.register_card(core.CardDefinition(WATCH,WATCH,core.CardType.MINION,health=20,
        limited_triggers=(LimitedTriggerSpec('card_created',P+'pause',condition_id=P+'eligible'),)))
    r.validate();return r


class PeriodicHandCreationBridgeTests(unittest.TestCase):
    def game(self):
        own=core.PlayerSetup(core.HERO,hand=(f.CIRCADIA,),deck=(f.EXP,)*5,board=(WATCH,),mana=100,max_mana=100,mana_cap=100)
        other=core.PlayerSetup(core.HERO,deck=(f.EXP,)*5,mana=100,max_mana=100,mana_cap=100)
        return core.Game.from_scenario(core.Scenario((own,other),seed=198,generation_context=f.CONTEXT),registry())

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__()
        self.assertEqual(core.Game.from_snapshot(deepcopy(s),reader).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(core.replay(core.build_replay(g),reader).snapshot(),s)

    def choose(self,g,key):
        c=g.state.pending_choice;g.apply(core.SelectChoice(c.player_id,c.id,(key,)))

    def begin(self):
        g=self.game();source=g.state.players[1].hand[0];g.apply(core.PlayCard(1,source))
        self.assertIsNotNone(g.state.pending_choice)
        generated=[e for e in g.state.entities.values()if e.owner==1 and e.card_id in(f.A,f.B)]
        self.assertEqual(len(generated),1);self.assertEqual(len(f.stamps(generated[0])),1)
        return g,generated[0].id

    def test_birth_wait_restores_one_paid_generated_card_and_original_future_grant(self):
        g,eid=self.begin();self.assertEqual(g.state.players[1].mana,97);self.portable(g)
        self.choose(g,'ok');self.assertIn(eid,g.state.players[1].hand)
        self.assertEqual(sum(e.card_id in(f.A,f.B)and e.owner==1 for e in g.state.entities.values()),1)
        self.portable(g);g.apply(core.EndTurn(1));g.apply(core.EndTurn(2))
        self.assertEqual(core.quote_unselected_cost(g.state,g.registry,g.state.entities[eid]).amount,7);self.portable(g)

    def test_failed_birth_choice_restores_chosen_card_grant_rng_and_paid_prefix(self):
        g,eid=self.begin();s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual(g.state.players[1].mana,97);self.assertEqual(len(f.stamps(g.state.entities[eid])),1)
        self.assertIsNone(f.stamps(g.state.entities[eid])[0].hand_discount_turn);self.portable(g)
