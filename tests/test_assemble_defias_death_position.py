"""A real borrowed Defias body must use its carrier's original death slot."""
from functools import lru_cache
from dataclasses import asdict
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.effects import Destroy, TriggerDeathrattles
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.serialization import canonical_hash

LOOT, DEFIAS, DRAIN, TOKEN = 'CORE_EX1_096', 'CORE_EX1_131', 'CORE_GIL_622', 'EX1_131t'
P = 'fixture.defias_death_position.'
LEFT, RIGHT, KILL, ACTIVE = P+'left', P+'right', P+'kill', P+'active'
KHADGAR = 'CORE_DAL_575'
CTX = GenerationContext('k524-real-defias-death-slot', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture():
    r = build_registry()
    r._version += '.k524.defias-slot'
    # The first baseline exposed this separate, real reverse-menu dependency.
    # Enable only the existing pure Draw's Combo window to isolate the position
    # defect. The production adapter must install the same reviewed amendment.
    original = r.assemble_templates[LOOT]
    if 'combo' not in original.suffix.allowed_timings:
        r.extend_assemble_suffix_timings(LOOT, ('combo',),
            expected_template_sha256=canonical_hash(asdict(original)))
    for cid in (LEFT, RIGHT):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=10, metadata=META))
    r.register_behavior(KILL, lambda c: (Destroy(c.target_id, c.source_id),))
    r.register_card(CardDefinition(KILL, KILL, CardType.SPELL, on_play=KILL, metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.register_behavior(ACTIVE, lambda c: (TriggerDeathrattles(c.target_id, c.source_id),))
    r.register_card(CardDefinition(ACTIVE, ACTIVE, CardType.SPELL, on_play=ACTIVE, metadata=META,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    r.register_pool(PoolDefinition(POOL_ID, 'real-two-cost-death-primary-two-legal-donors-v1',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (LOOT, DEFIAS, DRAIN)), complete=True))
    return r


class DefiasDeathPositionTests(CardBatchTestMixin, unittest.TestCase):
    def test_real_assemble_bandit_is_inserted_at_carriers_original_middle_death_slot(self):
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_03', hand=(FLESH, KILL),
            board=(LEFT, RIGHT), mana=30, max_mana=30, mana_cap=30), PlayerSetup('HERO_08')),
            generation_context=CTX, seed=524), fixture())
        self.play(g, FLESH)
        q = g.state.pending_choice
        cid = AssembleRecipe(LOOT, DEFIAS, 'bottom').card_id
        option = next(row for row in q.options if row.card_id == cid)
        g.apply(SelectChoice(q.player_id, q.id, (option.id,)))
        source = self.entity(g, cid).id
        g.apply(PlayCard(1, source, position=1))
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [LEFT, cid, RIGHT])
        self.play(g, KILL, source)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [LEFT, TOKEN, RIGHT])

    def test_active_death_and_real_khadgar_quantity_keep_source_and_original_slot(self):
        for active, doubled in ((True, False), (False, True), (True, True)):
            with self.subTest(active=active, doubled=doubled):
                prefix = (KHADGAR,) if doubled else ()
                g = Game.from_scenario(Scenario((PlayerSetup('HERO_03', hand=(FLESH, KILL, ACTIVE),
                    board=prefix+(LEFT, RIGHT), mana=30, max_mana=30, mana_cap=30),PlayerSetup('HERO_08')),
                    generation_context=CTX,seed=524),fixture())
                self.play(g,FLESH)
                q=g.state.pending_choice;cid=AssembleRecipe(LOOT,DEFIAS,'bottom').card_id
                option=next(row for row in q.options if row.card_id==cid)
                g.apply(SelectChoice(q.player_id,q.id,(option.id,)))
                source=self.entity(g,cid).id
                g.apply(PlayCard(1,source,position=len(prefix)+1))
                self.play(g,ACTIVE if active else KILL,source)
                expected=prefix+(LEFT,)+((cid,)if active else())+(TOKEN,)*(2 if doubled else 1)+(RIGHT,)
                self.assertEqual(tuple(g.state.entities[i].card_id for i in g.state.players[1].board),expected)


if __name__ == '__main__':
    unittest.main()
