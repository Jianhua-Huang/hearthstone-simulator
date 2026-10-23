"""Shared real-action/recovery helpers, executed only inside managed tests."""
import json

from hs_sim.engine import Game, PlayCard, SelectChoice
from hs_sim.engine.replay import build_replay, replay


def event_player(context):
    event = context.event
    if event.player_id is not None:
        return event.player_id
    target = context.state.entities.get(event.target_id)
    return None if target is None else target.controller


class CardBatchTestMixin:
    """A subclass supplies registry_factory(mode, role) and sets its mode."""

    def entity(self, game, card_id, player=1, zone='hand'):
        return next(game.state.entities[i] for i in getattr(game.state.players[player], zone)
            if game.state.entities[i].card_id == card_id)

    def play(self, game, card_id, target=None, player=1):
        entity_id = self.entity(game, card_id, player).id
        game.apply(PlayCard(player, entity_id, target))
        return entity_id

    def choose(self, game, key='continue'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (key,)))

    def portable(self, game):
        saved = json.loads(json.dumps(game.snapshot()))
        registry = self.registry_factory(self.mode, 'independent-reader')
        restored = Game.from_snapshot(saved, registry)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for player in (1, 2):
            view = json.dumps(game.for_player(player).observe())
            for key in ('rng_state', 'resolution_frame', 'submitted_cost', 'hand_entry_id'):
                self.assertNotIn('"'+key+'"', view)
        return restored
