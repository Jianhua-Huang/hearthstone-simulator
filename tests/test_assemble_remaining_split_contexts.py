"""Two shared non-native body contexts through actual reviewed producers."""
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from test_assemble_remaining_split_minions import fixture as source_fixture
from hs_sim.cards.assemble_remaining_split_minions import SCRYER, SERPENT
from hs_sim.cards.native_assemble_entry_cards import FLESH, SHAPER, POOL_ID
from hs_sim.engine import Attack, EndTurn, Game, PlayerSetup, Scenario, SelectChoice
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember

CTX = GenerationContext('k523-shared-body-contexts-diagnostic', 'experimental')
MACE, DOOM, DRAIN, COIN = 'EDR_253', 'CORE_NEW1_021', 'CORE_GIL_622', 'GAME_005'


@lru_cache(maxsize=None)
def fixture(kind):
    source = SERPENT if kind == 'attack' else SCRYER
    donor = MACE if kind == 'attack' else DOOM
    r = source_fixture(source, role='contexts-'+kind)
    r.register_pool(PoolDefinition(POOL_ID, 'three-complete-shared-context-sources-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (source, donor, DRAIN)), complete=True))
    return r


class RemainingSplitContextTests(CardBatchTestMixin, unittest.TestCase):
    def manufacture(self, kind):
        source, donor, root, hero = ((SERPENT, MACE, SHAPER, 'HERO_04')
            if kind == 'attack' else (SCRYER, DOOM, FLESH, 'HERO_08'))
        g = Game.from_scenario(Scenario((PlayerSetup(hero, hand=(root,),
            weapon_card_id=MACE if kind == 'attack' else None,
            deck=(COIN,)*12, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', deck=(COIN,)*12)),
            seed=523, generation_context=CTX), fixture(kind))
        self.play(g, root)
        q = g.state.pending_choice
        cid = AssembleRecipe(source, donor, 'top').card_id
        selected = next(option for option in q.options if option.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (selected.id,)))
        entity = self.play(g, cid)
        return g, entity

    def test_draw_two_uses_completed_hero_attack_without_old_serpent_end_gate(self):
        g, source = self.manufacture('attack')
        self.assertFalse(any(row.source_id == source for row in g.state.draw_history))
        hero = g.state.players[1].hero_id
        g.apply(Attack(1, hero, g.state.players[2].hero_id))
        self.assertEqual(len([row for row in g.state.draw_history if row.source_id == source]), 2)
        self.assertEqual(g.registry.card(g.state.entities[source].card_id).triggers[0].event, 'attack_finished')
        g.apply(EndTurn(1))
        self.assertEqual(len([row for row in g.state.draw_history if row.source_id == source]), 2)

    def test_draw_spell_runs_at_owner_start_without_original_death_or_doomsayer_body(self):
        g, source = self.manufacture('start')
        self.assertIsNone(g.registry.card(g.state.entities[source].card_id).deathrattle)
        g.apply(EndTurn(1))
        self.assertFalse(any(row.source_id == source for row in g.state.draw_history))
        g.apply(EndTurn(2))
        rows = [row for row in g.state.draw_history if row.source_id == source]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].card_id, COIN)
        self.assertIn(source, g.state.players[1].board)


if __name__ == '__main__':
    unittest.main()
