"""Player commands and their strict, JSON-compatible wire representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Mapping, TypeAlias


def _id(value: object, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _player(value: object) -> None:
    _id(value, "player_id")
    if value not in (1, 2):
        raise ValueError("player_id must be 1 or 2")


@dataclass(frozen=True)
class PlayBodyTarget:
    family: str
    ability_id: int
    declaration_card_id: str
    behavior_id: str
    origin: str
    grant_source_id: int | None
    expires_turn: int | None
    carrier_card_id: str
    zone_epoch: int
    target_id: int | None

    def __post_init__(self):
        if type(self.family) is not str or self.family not in ('battlecry', 'combo'):
            raise ValueError('Body selection requires its exact family')
        _id(self.ability_id, 'body ability')
        for name in ('declaration_card_id', 'behavior_id', 'carrier_card_id'):
            v = getattr(self, name)
            if type(v) is not str or not v.strip(): raise ValueError('Invalid body ' + name)
        if type(self.origin) is not str or self.origin not in ('printed', 'granted'):
            raise ValueError('Unknown body physical origin')
        for name in ('grant_source_id', 'expires_turn', 'target_id'):
            v = getattr(self, name)
            if v is not None: _id(v, name)
        if type(self.zone_epoch) is not int or self.zone_epoch < 0:
            raise ValueError('Invalid original hand epoch')


@dataclass(frozen=True)
class PlayCard:
    player_id: int
    entity_id: int
    target_id: int | None = None
    position: int | None = None

    branch_id: str | None = None
    body_target_profile_id: str | None = None
    body_targets: tuple[PlayBodyTarget, ...] = ()
    board_player_id: int | None = None

    def __post_init__(self) -> None:
        if self.body_target_profile_id is not None and (type(self.body_target_profile_id) is not str or not self.body_target_profile_id.strip()):
            raise ValueError('Body target profile must be an exact nonempty string')
        if type(self.body_targets) is not tuple or any(type(v) is not PlayBodyTarget for v in self.body_targets):
            raise ValueError('Body action requires a typed immutable vector')
        for v in self.body_targets: v.__post_init__()
        if self.body_targets and self.body_target_profile_id is None:
            raise ValueError('A physical body target vector requires its explicit policy')
        if len({v.ability_id for v in self.body_targets}) != len(self.body_targets):
            raise ValueError('Duplicate physical body target')
        if self.branch_id is not None and (type(self.branch_id) is not str or not self.branch_id.strip()):
            raise ValueError('branch_id must be a nonempty string')
        _player(self.player_id)
        if self.board_player_id is not None:
            _player(self.board_player_id)
        _id(self.entity_id, "entity_id")
        if self.target_id is not None:
            _id(self.target_id, "target_id")
        if self.position is not None and (type(self.position) is not int or self.position < 0):
            raise ValueError("position must be a non-negative integer or None")


@dataclass(frozen=True)
class UseHeroPower:
    player_id: int
    entity_id: int
    target_id: int | None = None

    branch_id: str | None = None

    def __post_init__(self):
        if self.branch_id is not None and (type(self.branch_id) is not str or not self.branch_id.strip()):
            raise ValueError('branch_id must be a nonempty string')
        _player(self.player_id)
        _id(self.entity_id, 'entity_id')
        if self.target_id is not None:
            _id(self.target_id, 'target_id')


@dataclass(frozen=True)
class UseInteractable:
    player_id: int
    entity_id: int
    card_entity_id: int

    def __post_init__(self):
        _player(self.player_id)
        _id(self.entity_id, 'interactable entity_id')
        _id(self.card_entity_id, 'invested card_entity_id')


@dataclass(frozen=True)
class UseLocation:
    player_id: int
    entity_id: int
    target_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _id(self.entity_id, 'entity_id')
        if self.target_id is not None:
            _id(self.target_id, 'target_id')


@dataclass(frozen=True)
class UseMinionAbility:
    player_id: int
    entity_id: int
    ability_id: str
    target_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _id(self.entity_id, 'entity_id')
        if type(self.ability_id) is not str or not self.ability_id.strip():
            raise ValueError('ability_id must be a nonempty string')
        if self.target_id is not None:
            _id(self.target_id, 'target_id')


@dataclass(frozen=True)
class UseHandAction:
    player_id: int
    entity_id: int
    action_id: str

    def __post_init__(self):
        _player(self.player_id)
        _id(self.entity_id, 'entity_id')
        if type(self.action_id) is not str or not self.action_id.strip():
            raise ValueError('action_id must be a nonempty string')


@dataclass(frozen=True)
class LaunchStarship:
    player_id: int
    entity_id: int

    def __post_init__(self):
        _player(self.player_id)
        _id(self.entity_id, 'entity_id')


@dataclass(frozen=True)
class Attack:
    player_id: int
    attacker_id: int
    defender_id: int

    def __post_init__(self) -> None:
        _player(self.player_id)
        _id(self.attacker_id, "attacker_id")
        _id(self.defender_id, "defender_id")


@dataclass(frozen=True)
class EndTurn:
    player_id: int

    def __post_init__(self) -> None:
        _player(self.player_id)


@dataclass(frozen=True)
class SelectChoice:
    player_id: int
    choice_id: int
    option_ids: tuple[str, ...]

    def __post_init__(self):
        _player(self.player_id)
        _id(self.choice_id, 'choice_id')
        if (not isinstance(self.option_ids, tuple) or any(not isinstance(i, str) or not i.strip() for i in self.option_ids) or
                len(set(self.option_ids)) != len(self.option_ids)):
            raise ValueError('option_ids must be a unique tuple of nonempty strings')


@dataclass(frozen=True)
class Concede:
    player_id: int

    def __post_init__(self):
        _player(self.player_id)


Action: TypeAlias = PlayCard | UseHeroPower | UseLocation | UseMinionAbility | UseHandAction | LaunchStarship | Attack | EndTurn | SelectChoice | UseInteractable | Concede

_ACTION_TYPES = {"play_card": PlayCard, "use_hero_power": UseHeroPower, "attack": Attack, "end_turn": EndTurn,
                 "select_choice": SelectChoice, "use_hand_action": UseHandAction, "launch_starship": LaunchStarship,
                 "use_location": UseLocation, "use_minion_ability": UseMinionAbility, "use_interactable": UseInteractable, "concede": Concede}
_ACTION_NAMES = {cls: name for name, cls in _ACTION_TYPES.items()}
_REQUIRED_FIELDS = {
    "concede": {"player_id"},
    "use_interactable": {"player_id", "entity_id", "card_entity_id"},
    "use_minion_ability": {"player_id", "entity_id", "ability_id"},
    "use_location": {"player_id", "entity_id"},
    "launch_starship": {"player_id", "entity_id"},
    "use_hand_action": {"player_id", "entity_id", "action_id"},
    "play_card": {"player_id", "entity_id"},
    "use_hero_power": {"player_id", "entity_id"},
    "attack": {"player_id", "attacker_id", "defender_id"},
    "end_turn": {"player_id"},
    "select_choice": {"player_id", "choice_id", "option_ids"},
}
_OPTIONAL_FIELDS = {"concede": set(), "use_interactable": set(), "use_minion_ability": {"target_id"}, "use_location": {"target_id"}, "launch_starship": set(), "use_hand_action": set(), "play_card": {"target_id", "position", "branch_id", "body_target_profile_id", "body_targets", "board_player_id"}, "use_hero_power": {"target_id", "branch_id"}, "attack": set(),
                    "end_turn": set(), "select_choice": set()}


def action_to_dict(action: Action) -> dict[str, object]:
    kind = _ACTION_NAMES.get(type(action))
    if kind is None:
        raise ValueError(f"unsupported action type: {type(action).__name__}")
    result = {"type": kind, **asdict(action)}
    if type(action) is PlayCard:
        if action.board_player_id is None:
            result.pop('board_player_id')
        if action.body_target_profile_id is None:
            result.pop('body_target_profile_id'); result.pop('body_targets')
        else:
            result['body_targets'] = [asdict(v) for v in action.body_targets]
    if isinstance(action, SelectChoice):
        result['option_ids'] = list(action.option_ids)
    return result


def action_from_dict(data: Mapping[str, object]) -> Action:
    if not isinstance(data, Mapping):
        raise ValueError("an action must be a mapping")
    kind = data.get("type")
    if not isinstance(kind, str) or kind not in _ACTION_TYPES:
        raise ValueError(f"unsupported action type: {kind!r}")
    keys = set(data)
    required = _REQUIRED_FIELDS[kind] | {"type"}
    allowed = required | _OPTIONAL_FIELDS[kind]
    missing = required - keys
    unknown = keys - allowed
    if missing:
        raise ValueError(f"missing action fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown action fields: {sorted(map(str, unknown))}")
    values = {key: value for key, value in data.items() if key != "type"}
    if kind == 'play_card':
        if ('body_target_profile_id' in values) != ('body_targets' in values):
            raise ValueError('Body profile and full JSON vector must appear together')
        if 'body_targets' in values:
            if type(values['body_targets']) is not list:
                raise ValueError('Body targets must be a JSON array')
            expected = {f.name for f in fields(PlayBodyTarget)}
            if any(type(v) is not dict or set(v) != expected for v in values['body_targets']):
                raise ValueError('Body target entries require every exact declared field')
            values['body_targets'] = tuple(PlayBodyTarget(**v) for v in values['body_targets'])
    if kind == 'select_choice':
        if not isinstance(values['option_ids'], list):
            raise ValueError('Choice option_ids must be a JSON array')
        values['option_ids'] = tuple(values['option_ids'])
    return _ACTION_TYPES[kind](**values)
