"""Keep the existing native Arcane relation in the generated-price pipeline."""
import unittest
from test_nefarian_native_dependencies import fixture
from hs_sim.cards.arcane_dragon_fabled_cards import QUEEN,KING
from hs_sim.engine import Game,PlayerSetup,Scenario
from hs_sim.engine.costs import capture_generated_quote_fact
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact


class PolarityGeneratedPriceRelationTests(unittest.TestCase):
    def test_existing_friendly_arcane_source_keeps_generated_price_and_enemy_scope(self):
        fmt=fixture('normal','polarity-arcane-generated-price-reader');r=fmt.registry
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=(QUEEN,KING)),
            PlayerSetup('HERO_08')),seed=56301,generation_context=fmt.context),r)
        saved=g.snapshot()
        own=capture_generated_quote_fact(g.state,r,1,'CORE_CS2_023')
        enemy=capture_generated_quote_fact(g.state,r,2,'CORE_CS2_023')
        validate_generated_quote_fact(r,own);validate_generated_quote_fact(r,enemy)
        self.assertEqual((own.amount,enemy.amount),(1,3))
        self.assertEqual(len(own.contributions),1);self.assertFalse(enemy.contributions)
        self.assertEqual(own.contributions[0].ability.cost_aura.relation,'friendly_arcane_spells')
        self.assertIsNone(own.contributions[0].polarity_basis)
        self.assertEqual(g.snapshot(),saved)


if __name__=='__main__':unittest.main()
