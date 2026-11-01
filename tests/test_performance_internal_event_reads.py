"""Internal event audits retain complete validation and public copy isolation."""
from copy import deepcopy
import unittest
from unittest.mock import PropertyMock, patch

from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Registry, Scenario
from hs_sim.engine.model import Event
from hs_sim.engine import (minion_play_entries, discovered_spell_casts, draw_transformations,
                           kidnap_custody, discovery_cost_swaps, secret_expirations)


def game():
    registry=Registry('internal-event-audit')
    registry.register_card(CardDefinition('hero','Hero',CardType.HERO,health=30))
    return Game.from_scenario(Scenario((PlayerSetup('hero'),PlayerSetup('hero'))),registry)


class InternalEventReadPerformanceTests(unittest.TestCase):
    def test_all_six_audits_read_without_public_full_log_copy(self):
        g=game();before=g.snapshot()
        with patch.object(Game,'events',new_callable=PropertyMock,
                          side_effect=AssertionError('public full log copy')):
            for module in (minion_play_entries,discovered_spell_casts,draw_transformations,
                           kidnap_custody,discovery_cost_swaps,secret_expirations):
                with self.subTest(module=module.__name__):module.validate_boundary(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_minion_history_cannot_hide_a_forged_event(self):
        g=game()
        g._events.append(Event(len(g._events)+1,0,'minion_play_accepted',data=(('play_id',1),)))
        before=deepcopy(g._events)
        with self.assertRaises(ValueError):minion_play_entries.validate_boundary(g)
        self.assertEqual(g._events,before)

    def test_missing_secret_history_cannot_hide_a_corrupt_original_proof(self):
        g=game()
        g._events.append(Event(len(g._events)+1,0,'probe',data=((secret_expirations.KEY,True),)))
        before=deepcopy(g._events)
        with self.assertRaises(ValueError):secret_expirations.validate_boundary(g)
        self.assertEqual(g._events,before)

    def test_public_events_still_deeply_detach_nested_values(self):
        g=game();payload={'values':[1]}
        g._events.append(Event(len(g._events)+1,0,'probe',data=(('payload',payload),)))
        exposed=g.events
        dict(exposed[-1].data)['payload']['values'].append(2)
        self.assertEqual(payload,{'values':[1]})
        self.assertIsNot(exposed[-1],g._events[-1])


if __name__=='__main__':unittest.main()
