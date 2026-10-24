"""Native paid input and an ordinary Rewind decision share the original payment."""
import json
import random
import unittest
from dataclasses import replace

from card_batch_testkit import CardBatchTestMixin
from test_yogg_controlled_turns import fixture,HERO,POWER,UNIT,SPELL,CTX
from hs_sim.cards.yogg_skills import ROOT,SKILLS
from hs_sim.engine import Game,Scenario,PlayerSetup,Keyword,RewindSpec
from hs_sim.engine.pools import PoolCard


def rewind_registry(mode='rewind',role='writer'):
    registry=fixture.__wrapped__('normal',role)
    registry._version += '.native-rewind'
    definition=replace(registry.card(SPELL),keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
    registry._cards[SPELL]=definition
    registry._pool_cards[SPELL]=PoolCard.from_definition(definition)
    return registry


class NativeRewindTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(rewind_registry)
    mode='rewind'

    def test_paid_native_rewind_keeps_once_without_second_payment_or_external_input(self):
        seed=next(i for i in range(100) if set(random.Random(i).sample(SKILLS,2))==set(SKILLS[:2]))
        game=Game.from_scenario(Scenario((
            PlayerSetup(HERO,hero_power_card_id=POWER,hand=(ROOT,),deck=(SPELL,),mana=10,max_mana=10),
            PlayerSetup(HERO,hero_power_card_id=POWER,deck=(UNIT,)*8,mana=10,max_mana=10)),
            seed=seed,generation_context=CTX),rewind_registry())
        self.play(game,ROOT)
        self.assertEqual(game.state.controlled_turn_requests[0].status,'completed')
        commands=[json.loads(v.command) for v in game.state.controlled_turn_requests[0].inputs]
        self.assertEqual(sum(c['type']=='select_choice' for c in commands),1)
        self.assertEqual(sum(p.card_id==SPELL for p in game.state.play_history),1)
        self.assertEqual(sum(e.kind=='mana_spent' and e.amount==2 for e in game.events),1)
        self.assertEqual(len([c for c in game.state.cast_history if c.card_id==SPELL]),2)
        self.assertIsNone(game._rewind)
        self.assertIsNone(game.state.pending_choice)
        self.assertEqual(len(game._history),1)
        self.portable(game)
