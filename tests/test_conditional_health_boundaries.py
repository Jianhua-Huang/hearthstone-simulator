"""New cost operands at real waiting boundaries and the other player seat."""
from dataclasses import replace
import unittest
import test_conditional_health_cards as cards
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, TriggerSpec
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, quote_cost
from hs_sim.engine.effects import AddToHand, ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.intrinsic_costs import validate_intrinsic_origin
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.model import Rarity


def edge_registry():
    r = cards.registry()
    def watch(c):
        if c.state.entities[c.event.source_id].card_id != 'CORE_BT_801': return ()
        return (RequestChoice(1, (
            ChoiceOption('ok', 'Receive another physical hand card', (AddToHand(1, 'CORE_CS2_182'),)),
            ChoiceOption('bad', 'Rollback', (InvokeBehavior('k16.fail', c.source_id, 1),)),
        ), c.source_id),)
    r.register_behavior('k16.edge_watch', watch)
    r.register_card(CardDefinition('k16.edge_watch', 'Observer', CardType.MINION, health=8,
        metadata=r.card('k16.big').metadata, triggers=(TriggerSpec('damage_dealt', 'k16.edge_watch'),)))
    return r


class ConditionalHealthBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry = cards.registry()
    game = cards.ConditionalHealthCardTests.game
    play = cards.ConditionalHealthCardTests.play
    price = cards.ConditionalHealthCardTests.price
    eid = cards.ConditionalHealthCardTests.eid
    choose = cards.ConditionalHealthCardTests.choose

    def portable(self, g, factory):
        saved = g.snapshot(); other = Game.from_snapshot(saved, factory())
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), factory()).snapshot(), saved); return other

    def test_edge_price_keeps_original_order_after_payment_and_choice_acquisition(self):
        g = Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=('CORE_BT_801', 'k16.noop'), board=('k16.edge_watch',),
                        mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=('k16.big',))), seed=243), edge_registry())
        self.play(g, 'CORE_BT_801', g.state.players[2].board[0])
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.players[1].mana, 9)
        other = self.portable(g, edge_registry)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(len(g.state.players[1].hand), 2)
        self.portable(g, edge_registry)

    def test_controlled_price_wait_preserves_original_qualifier_after_both_deaths(self):
        g = self.game(('CATA_308', 'CATA_308'), board=('CORE_EX1_012', 'k16.watch'),
                      enemy=('CORE_CS2_182',), mode='death')
        self.play(g, 'CATA_308'); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, 29)
        self.assertEqual(self.price(g, 'CATA_308'), 5)
        other = self.portable(g, lambda: cards.registry('death'))
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.portable(g, lambda: cards.registry('death'))

    def test_controlled_origin_rejects_truncation_after_a_true_legendary_row(self):
        g = self.game(('CATA_308',), board=('k16.legend', 'CAP_107t')); state = g.state
        fact = capture_quote_fact(state, g.registry, capture_cost_input(state.entities[self.eid(g, 'CATA_308')]))
        match = fact.intrinsic.condition_facts[0]
        reduced = tuple(row for row in match.boards[0] if g.registry.card(row.card_id).metadata.rarity == Rarity.LEGENDARY)
        bad = replace(fact.intrinsic, condition_facts=(replace(match, boards=(reduced, ())),))
        with self.assertRaises(ValueError): validate_intrinsic_origin(bad, state, g.registry)

    def test_second_player_cost_uses_own_controlled_inventory_and_pays_that_quote(self):
        for weapon, expected in ((None, 5), ('k16.weapon', 1)):
            g = Game.from_scenario(Scenario((
                PlayerSetup('HERO_08', board=('k16.legend',)),
                PlayerSetup('HERO_08', hand=('CATA_308',), weapon_card_id=weapon,
                            mana=10, max_mana=10)), active_player=2, seed=243), self.registry)
            eid = g.state.players[2].hand[0]; state = g.state
            self.assertEqual(quote_cost(state, g.registry, state.entities[eid]).amount, expected)
            g.apply(PlayCard(2, eid)); self.assertEqual(g.state.players[2].mana, 10-expected)


if __name__ == '__main__': unittest.main()
