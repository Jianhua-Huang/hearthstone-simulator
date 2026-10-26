"""Distinct printed-set exclusions inside the original physical recruit producer.

Sequential uniform physical selection, selected-set consumption and raw printed
CARD_SET grouping are explicit local policies, not a CN timing/weight ruling.
"""
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
import hashlib
import json


@dataclass(frozen=True)
class RecruitExpansionProfile:
    id: str
    editions: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if type(self.id) is not str or not self.id.strip():
            raise ValueError('Printed-expansion recruit requires an explicit profile identity')
        if type(self.editions) is not tuple or not self.editions:
            raise ValueError('Printed-expansion recruit requires its complete immutable edition inventory')
        previous = None
        for row in self.editions:
            if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or not row[0] or
                    type(row[1]) is not int or row[1] < 1 or previous is not None and row[0] <= previous):
                raise ValueError('Printed expansion identities must be unique, ordered and positive')
            previous = row[0]

    @cached_property
    def inventory(self):
        return MappingProxyType(dict(self.editions))

    @cached_property
    def inventory_sha256(self):
        return hashlib.sha256(json.dumps(dict(self.editions), sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def request_value(spec):
    from .pools import PoolQuery
    from .model import Zone
    if spec.expansion_profile is None:
        return
    if type(spec.expansion_profile) is not str or not spec.expansion_profile.strip():
        raise ValueError('Distinct-expansion recruit requires its declared printed inventory')
    if (spec.cause is None or spec.count != 3 or spec.zone != Zone.DECK or
            spec.owner_id not in (None, spec.player_id) or spec.selection != 'random' or
            spec.query != PoolQuery() or spec.attack_basis != 'printed' or spec.cost_basis != 'printed' or
            spec.stat_group_id is not None or spec.position is not None or spec.stats is not None or spec.on_summon is not None):
        raise ValueError('Distinct-expansion recruit requires its original three own-deck physical selections')


def edition(registry, profile_id, card_id):
    from .registry import UnsupportedDefinitionError
    profile = registry.recruit_expansion_profiles.get(profile_id)
    if profile is None:
        raise UnsupportedDefinitionError('Unknown original recruit expansion inventory: ' + str(profile_id))
    if card_id not in profile.inventory:
        raise UnsupportedDefinitionError('Unreviewed original recruit printed expansion: ' + card_id)
    return profile.inventory[card_id]


def exclusions(registry, spec, rounds):
    if spec.expansion_profile is None:
        return ()
    result = []
    for row in rounds:
        if row.selected is not None:
            value = edition(registry, spec.expansion_profile, row.selected.card_id)
            if value in result:
                raise ValueError('Original recruit selected the same printed expansion twice')
            result.append(value)
    return tuple(result)


def basis_value(basis):
    if type(basis.excluded_expansions) is not tuple:
        raise ValueError('Recruit expansion exclusions require the immutable original ordered prefix')
    if basis.expansion_profile is None:
        if basis.excluded_expansions:
            raise ValueError('Ordinary recruit cannot acquire undeclared expansion exclusions')
        return
    from .model import CardType, Zone
    from .pools import PoolQuery
    if (type(basis.expansion_profile) is not str or not basis.expansion_profile.strip() or
            basis.zone != Zone.DECK or basis.owner_id != basis.player_id or
            basis.query != PoolQuery(kinds=(CardType.MINION,)) or
            basis.attack_basis != 'printed' or basis.cost_basis != 'printed' or
            len(basis.excluded_expansions) > 2 or
            any(type(v) is not int or v < 1 for v in basis.excluded_expansions) or
            len(set(basis.excluded_expansions)) != len(basis.excluded_expansions)):
        raise ValueError('Recruit expansion basis changed its original own-deck selection or distinct prefix')
