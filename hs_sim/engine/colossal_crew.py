"""Three original discoveries retained on a native Colossal's physical Ship.

Pool selection, choice history, ordinary native memory and hand delivery stay
with their existing executors. A later same-ID board entry is not the Ship.
"""
from dataclasses import dataclass, fields, replace

from .effects import _integer
from .model import AppendageSpec, CardType, ChoicePurpose, NativeDeathrattleSpec, Zone, _name
from .pools import DiscoverFromPool, PoolQuery
from .sacrifice import MinionReference, live_minion, reference_value

PROFILE = NativeDeathrattleSpec('colossal_crew')
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', tribes_any=('pirate',))
PROMPT = '发现一名奈利的海盗船员'


@dataclass(frozen=True)
class ColossalCrewProfile:
    id: str
    root_card_id: str
    ship_card_id: str
    producer_behavior_id: str
    deathrattle_behavior_id: str
    pool_id: str = 'constructed.cards'


def validate_profile(registry, profile):
    if type(profile) is not ColossalCrewProfile: raise ValueError('Typed native Colossal crew required')
    for f in fields(profile): _name(getattr(profile, f.name), 'native crew '+f.name)
    root, ship = registry.card(profile.root_card_id), registry.card(profile.ship_card_id)
    if (root.kind != CardType.MINION or root.battlecry != profile.producer_behavior_id or
            root.colossal != (AppendageSpec(ship.id, 'right'),) or
            ship.kind != CardType.MINION or ship.metadata is None or ship.metadata.collectible is not False or
            ship.native_deathrattle != PROFILE or ship.deathrattle != profile.deathrattle_behavior_id):
        raise ValueError('Crew requires its exact native producer, single original Ship and Deathrattle')
    registry.behavior(profile.producer_behavior_id); registry.behavior(profile.deathrattle_behavior_id)


@dataclass(frozen=True)
class ColossalCrewTarget:
    profile_id: str
    battlecry_id: int
    colossal_id: int | None
    reference: MinionReference | None
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        _name(self.profile_id, 'native crew profile'); _integer(self.battlecry_id, 'original crew Battlecry', 1)
        if self.colossal_id is not None: _integer(self.colossal_id, 'original crew Colossal', 1)
        if self.reference is not None:
            reference_value(self.reference)
            if self.colossal_id is None or self.reference.zone_epoch != 0:
                raise ValueError('Crew requires the original newly minted appendage residence')
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Crew requires distinct original native memory abilities')
        for identity in self.ability_ids: _integer(identity, 'original crew ability', 1)
        if self.reference is None and self.ability_ids: raise ValueError('A missing Ship cannot claim later abilities')


def validate_spec(spec):
    if type(spec) is not DiscoverFromPool or type(spec.memory_target) is not ColossalCrewTarget:
        raise ValueError('Crew requires its typed original discovery target')
    spec.memory_target.__post_init__()
    plain = DiscoverFromPool(spec.player_id, spec.pool_id, QUERY, source_id=spec.source_id,
        prompt=PROMPT, discoveries=3)
    if (spec.destination != 'memory' or spec.source_id is None or any(
            getattr(spec, f.name) != getattr(plain, f.name) for f in fields(spec)
            if f.name not in ('destination', 'memory_target'))):
        raise ValueError('Native crew supports exactly three ordinary current-class Pirate selections')


def validate_target(state, registry, spec, *, active=True):
    validate_spec(spec); target = spec.memory_target
    profile = registry.colossal_crew_profiles.get(target.profile_id)
    from .battlecries import battlecry_record
    from .deathrattle_memory import validate_reference
    row = battlecry_record(state, target.battlecry_id)
    if (profile is None or (row.payload.card_id, row.payload.behavior_id) !=
            (profile.root_card_id, profile.producer_behavior_id) or
            (row.source_id, row.player_id) != (spec.source_id, spec.player_id) or
            spec.pool_id != profile.pool_id or not row.payload_started or row.failure is not None or
            active and (row.completed or row.interrupted)):
        raise ValueError('Crew lost its exact original native Battlecry')
    if target.colossal_id is not None:
        from .colossal import record_at
        entry = record_at(state, target.colossal_id)
        if ((entry.entity_id, entry.card_id) != (row.source_id, profile.root_card_id) or
                not entry.completed or entry.canceled or len(entry.limbs) != 1 or
                (entry.turn, entry.action) > (row.turn, row.action)):
            raise ValueError('Crew borrowed a different original Colossal entry')
        if target.reference is not None:
            ref = target.reference
            if ref.entity_id != entry.limbs[0] or ref.card_id != profile.ship_card_id:
                raise ValueError('Crew borrowed a different original appendage')
            validate_reference(state, ref, target.ability_ids)
    return row


def discover(context, registry, profile_id):
    profile = registry.colossal_crew_profiles[profile_id]
    row = context.battlecry
    if row is None: raise ValueError('Crew requires its original accepted Battlecry')
    source = context.state.entities[row.source_id]
    entry = next((v for v in reversed(context.state.colossal_history) if
        (v.entity_id, v.card_id, v.zone_epoch, v.entered_order) ==
        (row.source_id, profile.root_card_id, source.zone_epoch, source.entered_order)
        and v.completed and not v.canceled), None)
    ship = None if entry is None or entry.limbs[0] is None else context.state.entities[entry.limbs[0]]
    # Colossal creates a new physical entity directly on BOARD at epoch zero.
    # Moving or transforming it retires that original residence permanently.
    if ship is not None and (ship.zone != Zone.BOARD or ship.card_id != profile.ship_card_id or
            ship.zone_epoch != 0 or not ship.active or ship.health <= 0 or ship.doomed): ship = None
    from .lifecycle import active_abilities
    abilities = () if ship is None else tuple(a.id for a in active_abilities(ship, 'deathrattle')
        if a.deathrattle_memory is not None and a.deathrattle_memory.spec == PROFILE)
    target = ColossalCrewTarget(profile.id, row.id, None if entry is None else entry.id,
        None if ship is None else MinionReference.capture(ship), abilities)
    spec = DiscoverFromPool(row.player_id, profile.pool_id, QUERY, source_id=row.source_id,
        prompt=PROMPT, discoveries=3, destination='memory', memory_target=target)
    validate_target(context.state, registry, spec)
    return (spec,)


def is_crew_link(state, registry, link):
    if not 1 <= link.battlecry_id <= len(state.battlecry_history): return False
    cid = state.battlecry_history[link.battlecry_id-1].payload.card_id
    return any(p.root_card_id == cid for p in registry.colossal_crew_profiles.values())


def validate_link(state, registry, link, *, ship_card_id=None):
    from .model import RememberedDiscovery
    from .battlecries import battlecry_record
    if type(link) is not RememberedDiscovery: raise ValueError('Typed original crew selection required')
    link.__post_init__(); row = battlecry_record(state, link.battlecry_id)
    profiles = [p for p in registry.colossal_crew_profiles.values() if p.root_card_id == row.payload.card_id]
    if len(profiles) != 1 or not 1 <= link.discovery_id <= len(state.card_discovery_history):
        raise ValueError('Crew lost its original source or actual discovery')
    profile, = profiles; discovery = state.card_discovery_history[link.discovery_id-1]
    result = discovery.result
    if (ship_card_id is not None and ship_card_id != profile.ship_card_id or
            row.payload.behavior_id != profile.producer_behavior_id or not row.payload_started or row.failure is not None or
            discovery.id != link.discovery_id or discovery.is_control or
            result.choice.purpose != ChoicePurpose.POOL_DISCOVERY or
            (result.choice.source_id, result.choice.player_id) != (row.source_id, row.player_id) or
            len(result.selected) != 1 or result.selected[0].card_id != link.card_id or
            registry.card(link.card_id).kind != CardType.MINION):
        raise ValueError('Crew differs from its original native Pirate selection')
    return row, discovery


def apply_selection(r, effect):
    spec = effect.batch.spec; row = validate_target(r.state, r.registry, spec)
    profile = r.registry.colossal_crew_profiles[spec.memory_target.profile_id]
    from .card_discoveries import require_original_result
    from .model import RememberedDiscovery
    from .deathrattle_memory import validate_ability
    original = require_original_result(r.state, effect.choice_result)
    link = RememberedDiscovery(row.id, original.id, effect.selection.card_id)
    validate_link(r.state, r.registry, link, ship_card_id=profile.ship_card_id)
    target = spec.memory_target
    ship = None if target.reference is None else live_minion(r.state, target.reference)
    if ship is not None:
        replacements = {}
        for ability in ship.abilities:
            if ability.id not in target.ability_ids: continue
            validate_ability(r.state, r.registry, ability)
            memory = ability.deathrattle_memory
            if memory is None or memory.spec != PROFILE: raise ValueError('Original Ship lost its crew memory')
            updated = replace(memory, discoveries=(*memory.discoveries, link)); updated.__post_init__()
            replacements[ability.id] = replace(ability, deathrattle_memory=updated)
        ship.abilities = [replacements.get(a.id, a) for a in ship.abilities]
        if replacements:
            r.emit('colossal_crew_remembered', source_id=row.source_id, target_id=ship.id,
                player_id=ship.controller, card_id=link.card_id, discovery_id=link.discovery_id)
    from .discovery_delivery import DiscoveryCompletion, FinishCardDiscovery, queue
    return (queue(r, FinishCardDiscovery(DiscoveryCompletion(effect.choice_result, None))),)
