"""Native target requirements for a pure, targeted Kindred minion body."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .model import CardType, TargetMode, Zone, _name
from .owner_turns import query_for_definition, query_previous_owner_turn, validate_history


@dataclass(frozen=True)
class KindredTargetProfile:
    card_id: str

    def __post_init__(self):
        _name(self.card_id, 'native targeted Kindred')


def validate_profile(registry, profile):
    if type(profile) is not KindredTargetProfile:
        raise ValueError('Expected native targeted Kindred profile')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    native = registry.kindred_profiles.get(card.id)
    from .targeting import target_spec
    spec = target_spec(card)
    if (card.kind != CardType.MINION or not card.hand_playable or card.choice_only
            or card.battlecry is not None or card.combo is not None or card.choose_one is not None
            or card.target_condition is not None or card.target_rule != 'any_entity'
            or native is None or native.mode != 'body' or native.wrapper != card.on_play
            or native.active is None or native.prepare is not None or native.inactive is not None
            or spec is None or spec.mode != TargetMode.IF_AVAILABLE or spec.zones != (Zone.BOARD,)
            or spec.kinds != (CardType.MINION,) or spec.relation != 'enemy'):
        raise ValueError('Targeted Kindred requires its pure native enemy-minion play body')
    from .kindred import validate_profile as validate_native
    validate_native(registry, native)
    query_for_definition(card).__post_init__()


def matched(state, registry, source, definition):
    profile = registry.kindred_target_profiles.get(definition.id)
    if profile is None:
        raise ValueError('Missing native targeted Kindred profile')
    validate_profile(registry, profile)
    if not state.owner_turn_history and state.opening is not None and state.opening.stage != 'complete':
        return False
    return query_previous_owner_turn(state, source.controller,
        query_for_definition(registry.card(profile.card_id))).matched


def effective_spec(state, registry, source, definition, spec):
    if definition.id not in registry.kindred_target_profiles or spec is None:
        return spec
    return spec if matched(state, registry, source, definition) else None


def restore_original_history(original, current, registry, play):
    """Rebuild only the already retained original prefix for native target proofs.

    This stays inside the host; no history is added to the player observation.
    Later closure of the play's own interval cannot make it its prior turn.
    """
    if play.card_id not in registry.kindred_target_profiles:
        return
    face = play.played_face
    if face is None or face.owner_turn_id is None:
        raise ValueError('Paid Kindred targets require their genuine owner interval')
    prefix = list(current.owner_turn_history[:face.owner_turn_id])
    if not prefix or prefix[-1].turn != play.turn:
        raise ValueError('Original Kindred target lost its actual interval prefix')
    last = prefix[-1]
    changes = dict(closed_action=None, closed_event=None, end_action=None, end_event=None,
                   start_interruption=None)
    if last.publication_action is not None and last.publication_action > play.action:
        changes.update(publication_action=None, publication_event=None)
    prefix[-1] = replace(last, **changes)
    original.owner_turn_history = prefix
    original.play_history = list(current.play_history[:play.id-1])
    original.opening = deepcopy(current.opening)
    original.active_player = prefix[-1].player_id
    validate_history(original, registry)
