"""Current timeline overload facts must survive actual native Rewind retries."""
from copy import deepcopy
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, RewindSpec, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.effects import Overload, InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.overload_history import overloaded_crystals
from hs_sim.engine.hero_health_history import effective_events
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from opening_fixtures import registry as opening_registry

REWIND, PRELOAD = 'k162.rewind', 'k162.preload'


def registry(fail_retry=False):
    r = opening_registry()
    def body(c):
        return (Overload(c.player_id, 3), InvokeBehavior('k162.fail', c.source_id, c.player_id)) if fail_retry and c.rewind_attempt else (Overload(c.player_id, 3),)
    def fail(c): raise ResolutionError('K162 deliberate retry failure')
    r.register_behavior('k162.fail', fail)
    r.register_behavior(REWIND, body)
    r.register_behavior(PRELOAD, lambda c: (Overload(c.player_id, 2),))
    r.register_card(CardDefinition(PRELOAD, PRELOAD, CardType.SPELL, on_play=PRELOAD))
    r.register_card(CardDefinition(REWIND, REWIND, CardType.SPELL, cost=2, on_play=REWIND,
        keywords=(Keyword.REWIND,), rewind=RewindSpec(retries=2)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class OverloadRewindBoundaryTests(unittest.TestCase):
    def game(self, fail_retry=False):
        self.fail_retry = fail_retry
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=(PRELOAD, REWIND), mana=10, max_mana=10),
            PlayerSetup('warrior.hero', deck=('card.1',) * 8))), registry(fail_retry))

    def play(self, g, cid):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid))

    def choose(self, g, key):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        r = registry(self.fail_retry)
        self.assertEqual(Game.from_snapshot(saved, r).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)

    def test_real_retries_keep_prior_committed_increment_and_only_current_attempt(self):
        g = self.game(); self.play(g, PRELOAD); self.play(g, REWIND)
        self.portable(g)
        for attempt in (1, 2):
            self.choose(g, 'retry')
            self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (8, 5))
            self.assertEqual(overloaded_crystals(g.state, 1), 5)
            self.assertEqual(len(g.state.overload_history), 2)
            self.assertEqual(len([e for e in g.events if e.kind == 'overload_added']), attempt + 2)
            self.assertEqual(tuple(e.sequence for e in effective_events(g.events) if e.kind == 'overload_added'),
                tuple(row.event_sequence for row in g.state.overload_history))
            self.portable(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (2, 2))

    def test_keep_first_attempt_leaves_complete_original_event_pairs(self):
        g = self.game(); self.play(g, REWIND); self.choose(g, 'keep')
        self.assertEqual((overloaded_crystals(g.state, 1), g.state.players[1].overload_owed), (3, 3))
        self.assertEqual(len(g.state.overload_history), 1); self.portable(g)

    def test_discarded_same_amount_event_pair_cannot_witness_current_occurrence(self):
        g = self.game(); self.play(g, REWIND)
        old = g.state.overload_history[0]
        self.choose(g, 'retry'); saved = g.snapshot()
        self.assertNotEqual(old.event_sequence, g.state.overload_history[0].event_sequence)
        bad = deepcopy(saved); row = bad['state']['overload_history'][0]
        row['event_sequence'], row['mana_event_sequence'], row['action'] = old.event_sequence, old.mana_event_sequence, old.action
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        bad = deepcopy(saved); bad['state']['overload_history'] = []; bad['state']['next_overload_id'] = 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        self.portable(g)

    def test_current_original_pair_cannot_change_its_overload_operation(self):
        g = self.game(); self.play(g, REWIND); self.choose(g, 'retry')
        saved = g.snapshot(); bad = deepcopy(saved)
        index = g.state.overload_history[0].mana_event_sequence - 1
        bad['events'][index]['data']['operation'] = 'RefreshMana'
        with self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry())
        self.portable(g)

    def test_failed_retry_rolls_back_to_original_completed_result_and_wait(self):
        g = self.game(True); self.play(g, PRELOAD); self.play(g, REWIND); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'retry')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'keep'); self.assertEqual(overloaded_crystals(g.state, 1), 5); self.portable(g)
