"""A lethal entry reaction must retire all remaining original budget work."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_mana_worth_cards import CARD
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario, TriggerSpec
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import DamageKind
from hs_sim.engine.replay import build_replay, replay
from test_simple_followup_p70_cards import registry as base_registry, CONTEXT, M6


@lru_cache(maxsize=4)
def registry(after, role):
    assert after in (1, 2) and role in ('writer', 'reader')
    r = base_registry(members=((M6, 1),))
    watcher = 'k162.terminal.' + str(after)
    def body(c):
        if sum(c.state.entities[i].card_id == M6 for i in c.state.players[1].board) != after: return ()
        return (Damage(c.state.players[2].hero_id, 100, c.source_id, DamageKind.MINION_ABILITY),)
    r.register_behavior(watcher, body)
    r.register_card(CardDefinition(watcher, watcher, CardType.MINION, health=30,
        triggers=(TriggerSpec('minion_summoned', watcher),)))
    r.validate(); r.freeze(); return r


class ManaWorthTerminalTests(unittest.TestCase):
    def check(self, after):
        r = registry(after, 'writer')
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_10', hand=(CARD,), board=('k162.terminal.' + str(after),),
            mana=40, max_mana=40, mana_cap=40), PlayerSetup('HERO_10')),
            generation_context=CONTEXT), r)
        source = g.state.players[1].hand[0]
        g.apply(PlayCard(1, source))
        self.assertEqual(g.state.status, 'finished'); self.assertIsNone(g.state.pending_choice)
        roots = g.state.card_summon_history
        self.assertEqual(len(roots), after); self.assertEqual(roots[-1].status, 'interrupted')
        if after == 2: self.assertEqual(roots[0].status, 'completed')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (34, 0))
        saved = json.loads(json.dumps(g.snapshot())); reader = registry(after, 'reader')
        self.assertIsNot(reader, r)
        self.assertEqual(Game.from_snapshot(saved, reader).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)

    def test_lethal_first_original_entry_cancels_all_remaining_budget_and_overload(self): self.check(1)

    def test_lethal_second_original_entry_preserves_completed_parent_and_interrupts_child(self): self.check(2)
