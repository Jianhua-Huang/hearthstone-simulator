"""Ordered occurrence values for a whole summon group.

These are a declaration and selection component, not a kernel acceptance root.
The future executor must bind an actual root window, amount fact, child links,
Finish work, state/event proofs and private codecs before registering the effect.
Member order and extra selection are explicit local policy, pending CN evidence.
"""
from dataclasses import dataclass
from random import Random

from .effects import _integer, _player
from .model import validate_end_turn_rng
from .summon_quantities import SummonCause, SummonEntryMaterial, validate_material


def _name(value, label):
    if type(value) is not str or not value:
        raise ValueError(label + ' requires a nonempty identity')


@dataclass(frozen=True)
class OrderedGroupMember:
    occurrence_key: str
    material: SummonEntryMaterial
    position: int | None = None
    extra_weight: int = 1

    def __post_init__(self):
        _name(self.occurrence_key, 'Ordered group member')
        if type(self.material) is not SummonEntryMaterial:
            raise ValueError('Ordered groups require a typed plain entry recipe')
        self.material.__post_init__()
        if self.position is not None:
            _integer(self.position, 'Ordered member position', 0)
        _integer(self.extra_weight, 'Ordered member extra selection weight', 0)


@dataclass(frozen=True)
class OrderedSummonGroupSpec:
    player_id: int
    cause: SummonCause
    members: tuple[OrderedGroupMember, ...]
    extra_policy: str = 'none'
    extra_position: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.cause) is not SummonCause:
            raise ValueError('Whole groups require explicit card attribution')
        self.cause.__post_init__()
        if type(self.members) is not tuple or any(type(m) is not OrderedGroupMember for m in self.members):
            raise ValueError('Complete immutable ordered group members required')
        for member in self.members:
            member.__post_init__()
        keys = [m.occurrence_key for m in self.members]
        if len(keys) != len(set(keys)):
            raise ValueError('Group occurrence identities must be unique even when card faces repeat')
        if self.extra_policy not in ('none', 'weighted_occurrence_with_replacement'):
            raise ValueError('Unknown whole-group extra selection policy')
        if self.extra_position is not None:
            _integer(self.extra_position, 'Extra group member position', 0)
        if self.extra_policy == 'none' and self.extra_position is not None:
            raise ValueError('No-extra groups cannot borrow an extra position policy')


@dataclass(frozen=True)
class GroupSummonEntryLink:
    """Reserved distinct namespace; requires explicit future codec integration."""
    group_id: int
    index: int

    def __post_init__(self):
        _integer(self.group_id, 'Whole summon group identity', 1)
        _integer(self.index, 'Whole summon occurrence index', 0)


@dataclass(frozen=True)
class SelectedGroupOccurrence:
    index: int
    member_key: str
    material: SummonEntryMaterial
    position: int | None
    extra_ordinal: int | None = None

    def __post_init__(self):
        _integer(self.index, 'Selected group occurrence index', 0)
        _name(self.member_key, 'Selected original member')
        if type(self.material) is not SummonEntryMaterial:
            raise ValueError('Selected group occurrence requires its complete original recipe')
        self.material.__post_init__()
        if self.position is not None:
            _integer(self.position, 'Selected group position', 0)
        if self.extra_ordinal is not None:
            _integer(self.extra_ordinal, 'Additional logical member ordinal', 0)


def _selected_occurrences(spec, additional, rng):
    """Base occurrences never draw RNG; extra draws are over physical members."""
    _integer(additional, 'Additional whole-group members', 0)
    if additional:
        if spec.extra_policy != 'weighted_occurrence_with_replacement':
            raise ValueError('Additional group members require an explicit extra selection policy')
        if not spec.members or not any(m.extra_weight for m in spec.members):
            raise ValueError('Additional group members require a nonempty positive-weight occurrence domain')
    result = [SelectedGroupOccurrence(i, m.occurrence_key, m.material, m.position)
              for i, m in enumerate(spec.members)]
    total_weight = sum(m.extra_weight for m in spec.members)
    for ordinal in range(additional):
        ticket = rng.randrange(total_weight)
        for member in spec.members:
            ticket -= member.extra_weight
            if ticket < 0:
                result.append(SelectedGroupOccurrence(len(result), member.occurrence_key,
                    member.material, spec.extra_position, ordinal))
                break
    return tuple(result)


@dataclass(frozen=True)
class OrderedGroupSelection:
    """A reproducible value; contains no authenticated kernel/window acceptance."""
    spec: OrderedSummonGroupSpec
    additional: int
    occurrences: tuple[SelectedGroupOccurrence, ...]
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.spec) is not OrderedSummonGroupSpec:
            raise ValueError('Selection requires its full original ordered request')
        self.spec.__post_init__()
        _integer(self.additional, 'Original additional group member count', 0)
        if type(self.occurrences) is not tuple or any(type(m) is not SelectedGroupOccurrence for m in self.occurrences):
            raise ValueError('Complete typed selected group occurrence sequence required')
        for occurrence in self.occurrences:
            occurrence.__post_init__()
        validate_end_turn_rng(self.rng_before)
        validate_end_turn_rng(self.rng_after)
        local = Random()
        local.setstate(self.rng_before)
        expected = _selected_occurrences(self.spec, self.additional, local)
        if self.occurrences != expected or local.getstate() != self.rng_after:
            raise ValueError('Whole-group members or extra selection differ from their original request and RNG')


def validate_selection(registry, selection):
    if type(selection) is not OrderedGroupSelection:
        raise ValueError('Typed complete ordered group selection required')
    selection.__post_init__()
    for member in selection.spec.members:
        # Zero-weight members remain required original bodies and cannot be dropped.
        validate_material(registry, member.material)


def select(registry, spec, additional, rng):
    """Resolve known complete recipes before any random draw; no engine checkpoint."""
    if type(spec) is not OrderedSummonGroupSpec or type(rng) is not Random:
        raise ValueError('Typed ordered request and isolated kernel RNG required')
    spec.__post_init__()
    _integer(additional, 'Additional whole-group members', 0)
    for member in spec.members:
        validate_material(registry, member.material)
    before = rng.getstate()
    occurrences = _selected_occurrences(spec, additional, rng)
    return OrderedGroupSelection(spec, additional, occurrences, before, rng.getstate())


def from_dict(cls, value):
    from .serialization import _list, _row, end_turn_rng_from_json
    from .summon_quantities import from_dict as entry_from_dict
    if cls not in (OrderedGroupMember, SelectedGroupOccurrence, OrderedSummonGroupSpec,
                   OrderedGroupSelection, GroupSummonEntryLink):
        raise ValueError('Unknown whole-group value codec type')
    row = _row(value, cls)
    if cls is OrderedGroupMember or cls is SelectedGroupOccurrence:
        row['material'] = entry_from_dict(SummonEntryMaterial, row['material'])
    elif cls is OrderedSummonGroupSpec:
        row['cause'] = entry_from_dict(SummonCause, row['cause'])
        row['members'] = tuple(from_dict(OrderedGroupMember, m)
                               for m in _list(row['members'], 'Original group members'))
    elif cls is OrderedGroupSelection:
        row['spec'] = from_dict(OrderedSummonGroupSpec, row['spec'])
        row['occurrences'] = tuple(from_dict(SelectedGroupOccurrence, m)
                                   for m in _list(row['occurrences'], 'Selected group occurrences'))
        for name in ('rng_before', 'rng_after'):
            row[name] = end_turn_rng_from_json(row[name])
    elif cls is not GroupSummonEntryLink:
        raise ValueError('Unknown whole-group value codec type')
    return cls(**row)
