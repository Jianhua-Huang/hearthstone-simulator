"""Complete current Deathrattle material from live physical neighbors."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .lifecycle import active_abilities, attachment_id
from .model import AbilityInstance, CardType, Zone
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class CopiedDeathrattleSource:
    origin: SourceAllocationFact
    original: AbilityInstance
    components: tuple[str, ...]
    turn: int
    action: int
    next_attachment_id: int

    def __post_init__(self):
        if type(self.origin) is not SourceAllocationFact or type(self.original) is not AbilityInstance:
            raise ValueError('Copied Deathrattle requires typed original physical material')
        self.origin.__post_init__()
        if self.origin.kind != CardType.MINION or self.origin.zone != Zone.BOARD:
            raise ValueError('Copied Deathrattle requires an original board minion')
        _integer(self.turn, 'Deathrattle copy turn', 1)
        _integer(self.action, 'Deathrattle copy action', 0)
        _integer(self.next_attachment_id, 'Deathrattle copy attachment bound', 1)
        if (type(self.components) is not tuple or any(type(c) is not str or not c for c in self.components) or
                self.original.kind != 'deathrattle' or self.original.consumed or
                self.original.id >= self.next_attachment_id or self.original.source_id is not None and
                self.original.source_id >= self.origin.next_entity_id):
            raise ValueError('Copied Deathrattle lost its unconsumed original attachment')
        self.original.__post_init__()


def copied(original, *, identity, source_id, grant_card_id, material):
    # Only residence/lifetime/grant provenance changes. Remembered physical
    # cards and the complete original declaration remain frozen material.
    return replace(original, id=identity, origin='granted', source_id=source_id,
        deathrattle_grant_card_id=grant_card_id, expires_turn=None,
        remove_on_silence=True, consumed=False, magnetic_id=None,
        deathrattle_inherited_from=None, deathrattle_copied_from=material)


def validate_material(state, registry, material):
    material.__post_init__()
    validate_allocation(state, registry, material.origin)
    if (material.turn > state.turn or material.action > state.action_number or
            material.next_attachment_id > state.next_attachment_id):
        raise ValueError('Copied Deathrattle has future acceptance bounds')
    for cid in material.components:
        if registry.card(cid).kind != CardType.MINION:
            raise ValueError('Copied Deathrattle has a non-minion original component')
    from .crafted_faces import composition_shape
    if not composition_shape(registry.card(material.origin.card_id), material.components):
        raise ValueError('Copied Deathrattle changed its original physical composition')
    from .deathrattles import validate_ability as validate_original
    validate_original(state, registry, material.original)


def validate_ability(state, registry, ability):
    material = ability.deathrattle_copied_from
    if material is None:
        return
    ability.__post_init__()
    validate_material(state, registry, material)
    expected = copied(material.original, identity=ability.id, source_id=ability.source_id,
        grant_card_id=ability.deathrattle_grant_card_id, material=material)
    if ability != expected:
        raise ValueError('Copied Deathrattle changed its complete accepted payload')


def source_from_dict(value):
    from .serialization import _ability_from_dict, _row
    row = _row(value, CopiedDeathrattleSource)
    row['origin'] = allocation_from_dict(row['origin'])
    row['original'] = _ability_from_dict(row['original'])
    if type(row['components']) not in (list, tuple):
        raise ValueError('Copied Deathrattle components require an ordered list')
    row['components'] = tuple(row['components'])
    return CopiedDeathrattleSource(**row)


@dataclass(frozen=True)
class GainAdjacentDeathrattles(Effect):
    beneficiary: MinionReference

    def __post_init__(self):
        reference_value(self.beneficiary)

    def validate_in_state(self, state):
        self.__post_init__()
        ref = self.beneficiary
        entity = state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
            raise ValueError('Adjacent Deathrattle request has an unknown or future residence')


def gain(r, effect):
    effect.validate_in_state(r.state)
    entity = live_minion(r.state, effect.beneficiary)
    if entity is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    board = r.player(entity.controller).board
    index = board.index(entity.id)
    neighbors = tuple(board[i] for i in (index-1, index+1) if 0 <= i < len(board))
    materials = []
    # Capture the whole left/right group before allocating or notifying grants.
    for identity in neighbors:
        donor = r.state.entities[identity]
        if donor.kind != CardType.MINION or not donor.active or donor.health <= 0 or donor.doomed:
            continue
        for original in active_abilities(donor, 'deathrattle'):
            material = CopiedDeathrattleSource(SourceAllocationFact.capture(r.state, donor),
                deepcopy(original), donor.components, r.state.turn, r.state.action_number,
                r.state.next_attachment_id)
            validate_material(r.state, r.registry, material)
            materials.append(material)
    grants = tuple(copied(m.original, identity=attachment_id(r.state), source_id=entity.id,
        grant_card_id=entity.card_id, material=m) for m in materials)
    entity.abilities.extend(grants)
    r.refresh_auras()
    for ability in grants:
        r.emit('ability_granted', target_id=entity.id, source_id=entity.id,
            ability_id=ability.id, ability_kind='deathrattle')
    return ()


def register(mechanics):
    mechanics.register_payload_type(CopiedDeathrattleSource)
    mechanics.register(GainAdjacentDeathrattles, gain)
