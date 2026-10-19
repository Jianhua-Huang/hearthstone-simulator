"""Real Podling/Ascendance consumers obey the published upper tier boundary."""
import unittest

import test_m5_cross_zone as base
from hs_sim.cards.plucky_podling_card import CARD, register_plucky_podling_card
from hs_sim.cards.ascendance_card import register_ascendance_card
from hs_sim.engine import Game, PlayCard
from hs_sim.engine.effects import Transform
from hs_sim.engine.replay import build_replay,replay


def fixture(cost):
    x=base.CrossZoneTests();x.setUp()
    register_plucky_podling_card(x.r);register_ascendance_card(x.r)
    x.card('requested',cost=cost);x.card('t10',cost=10);x.card('t11',cost=11);x.card('t12',cost=12)
    x.card('origin10',cost=10)
    x.pool('constructed.cards',('t10','t11','t12'))
    x.script(lambda c:(Transform(c.state.players[1].board[0],'requested'),))
    return x


class EvolveCardLimitsTests(unittest.TestCase):
    def test_real_podling_replacement_caps_requested_nine_and_ten_at_ten(self):
        for cost in (9,10):
            with self.subTest(requested_cost=cost):
                x=fixture(cost);g=x.game(hand=('script',),deck=(),board=(CARD,));x.play(g)
                self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id,'t10')
                s=g.snapshot();reader=fixture(cost).r
                self.assertEqual(Game.from_snapshot(s,reader).snapshot(),s)
                self.assertEqual(replay(build_replay(g),reader).snapshot(),s)

    def test_real_ascendance_at_ten_keeps_its_original_return_grant(self):
        x=fixture(9);g=x.game(hand=('CATA_567',),deck=(),board=('origin10',));source=g.state.players[1].board[0]
        g.apply(PlayCard(1,g.state.players[1].hand[0]));body=g.state.entities[source]
        self.assertEqual(body.card_id,'t10')
        memory=next(a.deathrattle_memory for a in body.abilities if a.deathrattle_memory is not None)
        self.assertEqual(memory.summon_copy.card_id,'origin10')
        self.assertFalse(g.state.death_history)


if __name__=='__main__':unittest.main()
