"""Fixed public match boards and explicit finite printed minion forms."""
from dataclasses import dataclass

from .errors import ResolutionError
from .model import CardDefinition, CardType, _int, _name


def validate_board_id(value):
    if value is not None:
        _int(value, 'game board ID', 1)


@dataclass(frozen=True)
class BoardCardForm:
    board_id: int
    card_id: str

    def __post_init__(self):
        _int(self.board_id, 'form game board ID', 1)
        _name(self.card_id, 'board form card')


@dataclass(frozen=True)
class BoardCardFamily:
    id: str
    version: str
    base: str
    forms: tuple[BoardCardForm, ...]

    def __post_init__(self):
        for name in ('id', 'version', 'base'):
            _name(getattr(self, name), 'board family ' + name)
        if type(self.forms) is not tuple or not self.forms:
            raise ValueError('Board family requires a nonempty immutable form table')
        for row in self.forms:
            if type(row) is not BoardCardForm:
                raise ValueError('Board family requires exact BoardCardForm entries')
            row.__post_init__()
            if row.card_id == self.base:
                raise ValueError('Board form cannot use its unresolved base')
        if len({row.board_id for row in self.forms}) != len(self.forms):
            raise ValueError('Duplicate game board in a form family')

    @property
    def members(self):
        return frozenset((self.base, *(row.card_id for row in self.forms)))


def validate_families(registry):
    used = set()
    for key, family in registry.board_card_families.items():
        if type(family) is not BoardCardFamily or family.id != key:
            raise ValueError('Board family differs from its registered identity')
        family.__post_init__()
        if used & family.members:
            raise ValueError('Board families cannot share physical forms')
        used.update(family.members)
        base = registry.card(family.base)
        blank = CardDefinition(base.id, base.name, CardType.MINION, cost=base.cost,
            attack=base.attack, health=base.health, metadata=base.metadata)
        if base != blank or not base.hand_playable:
            raise ValueError('Board-dependent base must be a plain playable minion')
        for row in family.forms:
            form = registry.card(row.card_id)
            if (not form.hand_playable or (form.kind, form.cost, form.attack, form.health) !=
                    (base.kind, base.cost, base.attack, base.health) or form.starship_for):
                raise ValueError('Board family requires complete minion forms with the same printed stats')
            if form.metadata is not None and form.metadata.collectible:
                raise ValueError('Board family results must be noncollectible printed forms')


def resolve_card_id(state, registry, card_id):
    registry.card(card_id)  # Unknown input is never dropped or treated as blank.
    family = registry.board_card_family(card_id)
    if family is None:
        return card_id
    validate_board_id(state.board_id)
    if state.board_id is None:
        raise ResolutionError('Board-dependent card requires a specified game board')
    form = next((row for row in family.forms if row.board_id == state.board_id), None)
    if form is None:
        raise ResolutionError(f'Unsupported game board {state.board_id} for card family {family.id}')
    return form.card_id


def validate_state(state, registry):
    validate_board_id(state.board_id)
    for entity in state.entities.values():
        if registry.board_card_family(entity.card_id) is not None:
            if resolve_card_id(state, registry, entity.card_id) != entity.card_id:
                raise ValueError('Physical board-dependent card has another game board form')
