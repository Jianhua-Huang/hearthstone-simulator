"""A minion's actual original destruction group, frozen before the shared death checkpoint."""
from dataclasses import dataclass, replace

from .allocation_facts import SourceAllocationFact, validate_allocation
from .card_creation import CreatedMinionGrant
from .effects import DestroyBatch, Effect, _integer
from .lifecycle import active_abilities
from .model import BattlecryRecord, CardType, DeathCause, Zone
from .sacrifice import MinionReference, reference_value, same_instance

RESUMMON_GRANT = CreatedMinionGrant(attack=1, health=1)


@dataclass(frozen=True)
class DestroyedBattlecryGroup:
    battlecry: BattlecryRecord
    source: SourceAllocationFact
    first_death_id: int
    victims: tuple[MinionReference, ...]
    causes: tuple[DeathCause, ...]

    def __post_init__(self):
        if type(self.battlecry) is not BattlecryRecord or type(self.source) is not SourceAllocationFact:
            raise ValueError('Destroyed group requires its complete original Battlecry and physical source')
        self.battlecry.__post_init__(); self.source.__post_init__()
        _integer(self.first_death_id, 'original destroyed-group death boundary', 1)
        b = self.battlecry
        if (b.completed or b.interrupted or b.failure is not None or not b.payload_started or
                b.source_id != self.source.entity_id or self.source.kind != CardType.MINION):
            raise ValueError('Destroyed group changed its original accepted minion Battlecry')
        if (type(self.victims) is not tuple or type(self.causes) is not tuple or
                len(self.victims) != len(self.causes)):
            raise ValueError('Destroyed group requires complete ordered physical victims and causes')
        ids = []
        for ref, cause in zip(self.victims, self.causes):
            reference_value(ref)
            if type(cause) is not DeathCause:
                raise ValueError('Destroyed group requires original typed death causes')
            cause.__post_init__(); ids.append(ref.entity_id)
            if ref.entity_id >= self.source.next_entity_id or ref.entered_order >= self.source.next_order:
                raise ValueError('Destroyed group borrowed a future victim allocation')
            if ((cause.kind, cause.reason, cause.target_id, cause.target_card_id, cause.target_controller,
                    cause.target_zone_epoch, cause.target_entered_order, cause.turn) !=
                    ('destroy', 'Destroy', ref.entity_id, ref.card_id, b.player_id, ref.zone_epoch,
                     ref.entered_order, b.turn) or ref.player_id != b.player_id or
                    (cause.source_id, cause.source_card_id, cause.source_controller,
                     cause.source_zone_epoch, cause.source_entered_order) !=
                    (self.source.entity_id, self.source.card_id, self.source.controller,
                     self.source.zone_epoch, self.source.entered_order)):
                raise ValueError('Destroyed group substituted its original victim, controller or source')
        if len(set(ids)) != len(ids) or b.source_id in ids:
            raise ValueError('Destroyed group duplicated a victim or included its own carrier')


def validate_group(state, registry, group, *, closed=False):
    if type(group) is not DestroyedBattlecryGroup:
        raise ValueError('Expected complete original Battlecry destruction material')
    group.__post_init__(); b = group.battlecry
    spec = registry.card(b.payload.card_id).native_deathrattle
    if spec is None or spec.kind != 'destroyed_group':
        raise ValueError('Destroyed group lost its actual printed native memory declaration')
    validate_allocation(state, registry, group.source, closed=closed)
    if not closed and group.first_death_id > state.next_death_id:
        raise ValueError('Destroyed group borrowed a future death boundary')
    if not closed:
        from .battlecries import battlecry_record, validate_record
        current = battlecry_record(state, b.id); validate_record(state, registry, current)
        if replace(current, completed=False, interrupted=False) != b:
            raise ValueError('Destroyed group borrowed another original accepted Battlecry')
    from .death_causes import validate_in_state
    for ref, cause in zip(group.victims, group.causes):
        if registry.card(ref.card_id).kind != CardType.MINION or ref.entered_order >= group.source.next_order:
            raise ValueError('Destroyed group lost its original minion allocation')
        if closed:
            continue
        validate_in_state(state, registry, cause)
        entity = state.entities.get(ref.entity_id)
        dead = any(d.id >= group.first_death_id and d.zone == Zone.BOARD and d.cause == cause
            for d in state.death_history)
        pending = entity is not None and entity.doomed and entity.death_cause == cause
        if not (dead or pending):
            raise ValueError('Destroyed group lost a genuine original destruction')
    return b


@dataclass(frozen=True)
class DestroyForDeathrattleGroup(Effect):
    battlecry_id: int
    reference: MinionReference | None
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        _integer(self.battlecry_id, 'original group Battlecry', 1)
        if self.reference is not None: reference_value(self.reference)
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Destruction memory requires unique original attachment identities')
        for identity in self.ability_ids: _integer(identity, 'original group memory attachment', 1)
        if self.reference is None and self.ability_ids:
            raise ValueError('Departed original source cannot acquire a later memory attachment')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        from .battlecries import battlecry_record, validate_record
        from .deathrattle_memory import validate_reference
        b = battlecry_record(state, self.battlecry_id); validate_record(state, registry, b)
        spec = registry.card(b.payload.card_id).native_deathrattle
        if (b.completed or b.interrupted or b.failure is not None or not b.payload_started or
                spec is None or spec.kind != 'destroyed_group' or self.reference is not None and
                self.reference.entity_id != b.source_id):
            raise ValueError('Destroyed-group request lost its original running minion Battlecry')
        if self.reference is not None: validate_reference(state, self.reference, self.ability_ids)
        return b


def destroy_group(r, request):
    b = request.validate_in_state(r.state, r.registry)
    source = SourceAllocationFact.capture(r.state, r.state.entities[b.source_id])
    victims = tuple(MinionReference.capture(r.state.entities[eid]) for eid in r.player(b.player_id).board
        if eid != b.source_id and r.state.entities[eid].kind == CardType.MINION and
        r.state.entities[eid].active and r.state.entities[eid].health > 0 and not r.state.entities[eid].doomed
        and r.registry.card(r.state.entities[eid].card_id).interactable is None)
    first = r.state.next_death_id
    from .resolver import destroy_batch
    destroy_batch(r, DestroyBatch(tuple(v.entity_id for v in victims), b.source_id))
    group = DestroyedBattlecryGroup(b, source, first, victims,
        tuple(r.state.entities[v.entity_id].death_cause for v in victims))
    validate_group(r.state, r.registry, group)
    carrier = None if request.reference is None else same_instance(r.state, request.reference)
    if carrier is None: return ()
    replacements = {}
    from .deathrattle_memory import validate_ability
    for ability in active_abilities(carrier, 'deathrattle'):
        if ability.id not in request.ability_ids: continue
        validate_ability(r.state, r.registry, ability); memory = ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'destroyed_group':
            raise ValueError('Original destruction attachment changed its native memory profile')
        replacements[ability.id] = replace(ability, deathrattle_memory=replace(memory,
            destroyed_groups=(*memory.destroyed_groups, group)))
    carrier.abilities = [replacements.get(a.id, a) for a in carrier.abilities]
    return ()


@dataclass(frozen=True)
class ResummonDestroyedGroups(Effect):
    deathrattle_id: int

    def __post_init__(self):
        _integer(self.deathrattle_id, 'actual original destroyed-group Deathrattle', 1)

    def validate_in_state(self, state, registry):
        self.__post_init__()
        from .deathrattles import record, validate_capture
        row = record(state, self.deathrattle_id); validate_capture(state, registry, row.capture)
        memory = row.capture.ability.deathrattle_memory
        if (row.execution_order is None or row.completed or row.interrupted or memory is None or
                memory.spec.kind != 'destroyed_group'):
            raise ValueError('Resummon lost its actual active destroyed-group Deathrattle')
        for group in memory.destroyed_groups: validate_group(state, registry, group)
        return row


def resummon(r, request):
    row = request.validate_in_state(r.state, r.registry)
    from .registry import RuleContext
    from .summon_quantities import SummonCause
    from .summon_sources import ResurrectMinion
    cause = SummonCause.capture(RuleContext(r.state, row.capture.carrier_id, row.capture.player_id))
    result = []
    for group in row.capture.ability.deathrattle_memory.destroyed_groups:
        for original in group.causes:
            death = next((d for d in r.state.death_history if d.id >= group.first_death_id and
                d.zone == Zone.BOARD and d.cause == original), None)
            if death is None:
                raise ValueError('Original destruction has not reached its actual recorded minion death')
            result.append(ResurrectMinion(row.capture.player_id, death.id, source_id=row.capture.carrier_id,
                cause=cause, entry_grant=RESUMMON_GRANT))
    return tuple(result)


def group_from_dict(value):
    from .serialization import _row, _list, battlecry_record_from_dict, _death_cause_from_dict
    from .allocation_facts import allocation_from_dict
    row = _row(value, DestroyedBattlecryGroup)
    row['battlecry'] = battlecry_record_from_dict(row['battlecry'])
    row['source'] = allocation_from_dict(row['source'])
    row['victims'] = tuple(MinionReference(**_row(x, MinionReference)) for x in _list(row['victims'], 'original destroyed victims'))
    row['causes'] = tuple(_death_cause_from_dict(x) for x in _list(row['causes'], 'original destruction causes'))
    return DestroyedBattlecryGroup(**row)


def register(mechanics):
    mechanics.register(DestroyForDeathrattleGroup, destroy_group)
    mechanics.register(ResummonDestroyedGroups, resummon)
    mechanics.register_payload_type(DestroyedBattlecryGroup)
