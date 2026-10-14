"""Versioned prototype policy, deliberately separate from card behavior."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Ruleset:
    id: str = 'prototype-v302'
    max_board: int = 7
    max_quests: int = 5
    max_ongoing_effects: int = 5
    max_secret_zone: int = 5
    max_hand: int = 10
    max_mana: int = 10
    max_resolution_steps: int = 1000
    max_turns: int = 200
    draw_after_turn: int | None = None
    max_choice_options: int = 32
    max_choice_combinations: int = 4096

    def __post_init__(self):
        if self.id != 'prototype-v302':
            raise ValueError(f'Unsupported ruleset: {self.id}')
        for name in ('max_secret_zone', 'max_ongoing_effects', 'max_quests', 'max_board', 'max_hand', 'max_mana', 'max_resolution_steps', 'max_turns',
                     'max_choice_options', 'max_choice_combinations'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.draw_after_turn is not None and (type(self.draw_after_turn) is not int or self.draw_after_turn < 1):
            raise ValueError('draw_after_turn must be a positive integer or None')

    def entity_order(self, state, entity_ids):
        return sorted(entity_ids, key=lambda i: (
            state.entities[i].controller != state.active_player,
            state.entities[i].entered_order, i,
        ))

    def reactions(self, triggers, deathrattles, continuation):
        # This is an explicit prototype contract, NOT a claim about every
        # Hearthstone timing window. Changing it requires a new ruleset version.
        return [*triggers, *deathrattles, *continuation]
