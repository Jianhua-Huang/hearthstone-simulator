"""Removable physical additions to one known logical native effect unit."""
from collections import Counter
from dataclasses import dataclass

from .lifecycle import active_abilities
from .effects import _player
from .model import CardType, ProducerQuantitySpec, _name

CANNONEER_SHOT = 'cannoneer.shot'


@dataclass(frozen=True)
class NativeProducerQuantityProfile:
    card_id: str
    receiver_card_id: str
    unit: ProducerQuantitySpec

    def __post_init__(self):
        _name(self.card_id, 'native quantity provider')
        _name(self.receiver_card_id, 'native logical receiver')
        if type(self.unit) is not ProducerQuantitySpec:
            raise ValueError('Native quantity requires a complete logical unit declaration')
        self.unit.__post_init__()
        if self.unit.unit_id != CANNONEER_SHOT or self.unit.additional < 1:
            raise ValueError('Unsupported native additional producer unit')


def validate_profile(registry, profile):
    if type(profile) is not NativeProducerQuantityProfile: raise ValueError('Expected native quantity profile')
    profile.__post_init__()
    source, receiver = registry.card(profile.card_id), registry.card(profile.receiver_card_id)
    if (source.kind != CardType.MINION or source.choice_only or source.starship_for or
            receiver.kind != CardType.MINION or receiver.choice_only or
            not any(t.end_turn is not None for t in receiver.triggers)):
        raise ValueError('Native shot quantity requires a physical minion and classified receiver body')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'native_producer_quantity')
    if not rows: return
    if kind != CardType.MINION: raise ValueError('Native quantity requires its original minion carrier')
    allowed, counts = Counter((card_id, *components)), Counter()
    for ability in rows:
        ability.__post_init__()
        profile = registry.native_producer_quantity_profiles.get(ability.native_producer_quantity_card_id)
        if profile is None: raise ValueError('Native quantity lost its original declaration')
        validate_profile(registry, profile)
        counts[profile.card_id] += 1
        if counts[profile.card_id] > allowed[profile.card_id]:
            raise ValueError('Native quantity duplicated or borrowed another native source')


def count(state, registry, player_id, receiver_card_id, unit_id):
    """One body's frozen state accepts independent shots; no mutation or RNG."""
    _player(player_id); _name(receiver_card_id, 'native logical receiver')
    if unit_id != CANNONEER_SHOT: raise ValueError('Unknown native producer logical unit')
    if registry.card(receiver_card_id).kind != CardType.MINION:
        raise ValueError('Native shot quantity requires a known physical minion receiver')
    total = 1
    for eid in state.players[player_id].board:
        source = state.entities[eid]
        if source.kind != CardType.MINION or not source.active or source.health <= 0 or source.doomed: continue
        rows = active_abilities(source, 'native_producer_quantity')
        validate_carrier(registry, source.card_id, source.kind, rows, source.components)
        for ability in rows:
            profile = registry.native_producer_quantity_profiles[ability.native_producer_quantity_card_id]
            if profile.receiver_card_id == receiver_card_id and profile.unit.unit_id == unit_id:
                total += profile.unit.additional
    return total
