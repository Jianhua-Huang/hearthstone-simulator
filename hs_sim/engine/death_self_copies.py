"""Self-copy bodies use original natural death material and ordinary summons.

Only the missing allocation/flag fields are added to a DeathRecord. Its existing
ordered attachments remain the single frozen source. Full health, copied local
attachments and original death position are explicit internal policies pending CN.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .model import CardType, ChooseBranchSelection, HandLifetime, Zone


@dataclass(frozen=True)
class DeathCopySource:
    origin: SourceAllocationFact
    silenced: bool
    hand_lifetime: HandLifetime | None
    choose_branch: ChooseBranchSelection | None
    dormant_entry: bool
    turn: int
    action: int
    next_attachment_id: int

    def __post_init__(self):
        if type(self.origin) is not SourceAllocationFact:
            raise ValueError('Death copy requires its original physical allocation')
        self.origin.__post_init__()
        if self.origin.zone != Zone.BOARD or self.origin.kind != CardType.MINION:
            raise ValueError('Death copy source requires the original board minion')
        if type(self.silenced) is not bool or type(self.dormant_entry) is not bool:
            raise ValueError('Death copy source requires typed original flags')
        if self.hand_lifetime is not None:
            if type(self.hand_lifetime) is not HandLifetime:
                raise ValueError('Death copy requires its typed temporary lifetime')
            self.hand_lifetime.__post_init__()
        if self.choose_branch is not None:
            if type(self.choose_branch) is not ChooseBranchSelection:
                raise ValueError('Death copy requires its typed original branch')
            self.choose_branch.__post_init__()
        _integer(self.turn, 'death copy turn', 1)
        _integer(self.action, 'death copy action', 0)
        _integer(self.next_attachment_id, 'death copy attachment bound', 1)

    @classmethod
    def capture(cls, state, entity):
        if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
            return None
        return cls(SourceAllocationFact.capture(state, entity), entity.silenced,
            entity.hand_lifetime, entity.choose_branch, entity.dormancy is not None,
            state.turn, state.action_number, state.next_attachment_id)


def validate_death_source(death, state=None, registry=None, *, closed=False):
    source = death.copy_source
    if source is None:
        return
    if type(source) is not DeathCopySource:
        raise ValueError('Death requires its complete typed original copy facts')
    source.__post_init__()
    origin = source.origin
    if (death.zone != Zone.BOARD or source.turn != death.turn or
            (origin.entity_id, origin.card_id, origin.owner, origin.controller) !=
            (death.entity_id, death.card_id, death.owner, death.controller) or
            any(a.id >= source.next_attachment_id or a.source_id is not None and
                a.source_id >= origin.next_entity_id for a in (*death.abilities, *death.enchantments))):
        raise ValueError('Death copy facts differ from their original frozen death')
    if state is not None:
        validate_allocation(state, registry, origin, closed=closed)
        if (source.turn > state.turn or source.action > state.action_number or
                source.next_attachment_id > state.next_attachment_id):
            raise ValueError('Death copy facts exceed their original allocation window')


def source_from_dict(value):
    if value is None:
        return None
    from .serialization import _row
    from .choose_branch_state import selection_from_dict
    row = _row(value, DeathCopySource)
    row['origin'] = allocation_from_dict(row['origin'])
    row['hand_lifetime'] = None if row['hand_lifetime'] is None else HandLifetime(
        **_row(row['hand_lifetime'], HandLifetime))
    row['choose_branch'] = None if row['choose_branch'] is None else selection_from_dict(row['choose_branch'])
    return DeathCopySource(**row)


def local_from_death(death):
    from .copy_materials import CopyLocalState
    validate_death_source(death)
    source = death.copy_source
    if source is None:
        raise ValueError('Self-copy requires complete original death copy facts')
    return CopyLocalState(death.base_attack, death.base_health, death.base_cost, 0,
        death.corpse_value, source.silenced, death.frozen_until_owner_turn is not None,
        death.herald_rank, source.hand_lifetime, death.enchantments, death.abilities,
        source.choose_branch)


def validate_entry_shape(material):
    from .model import DeathRecord
    from .permanent_minion_stats import value
    death = material.self_copy_death
    if type(death) is not DeathRecord:
        raise ValueError('Death self-copy requires its complete frozen original death')
    death.__post_init__()
    local = local_from_death(death)
    source = death.copy_source
    if (material.card_id != death.card_id or material.origin != source.origin or
            material.profile != 'death_copy' or material.mode != 'current' or
            (material.captured_turn, material.captured_action, material.next_attachment_id) !=
            (source.turn, source.action, source.next_attachment_id) or
            material.local != local or material.stats is not None or
            material.entry_herald_count is not None or material.jade_size != death.jade_size or
            material.discard is not None or material.dormant_entry != source.dormant_entry or
            material.on_summon is not None or material.minion_grant is not None or
            material.grant_source_id is not None or material.stored_components != death.components or
            material.permanent_stats != value(local)):
        raise ValueError('Death self-copy changed the full original material or full-health policy')


def entry_from_death(death):
    from .copy_materials import CopyEntryMaterial
    from .permanent_minion_stats import value
    source = death.copy_source
    local = local_from_death(death)
    return CopyEntryMaterial(death.card_id, source.origin, 'death_copy', 'current',
        source.turn, source.action, source.next_attachment_id, local,
        jade_size=death.jade_size, dormant_entry=source.dormant_entry,
        stored_components=death.components, permanent_stats=value(local), self_copy_death=death)


def validate_entry_scope(state, registry, material, *, closed=False):
    validate_entry_shape(material)
    from .resurrection_summons import validate_death
    validate_death(state, registry, material.self_copy_death, closed=closed)
    validate_death_source(material.self_copy_death, state, registry, closed=closed)


@dataclass(frozen=True)
class SummonDeathrattleSelfCopy(Effect):
    invocation_id: int
    cause: object

    def __post_init__(self):
        from .summon_quantities import SummonCause
        _integer(self.invocation_id, 'self-copy original Deathrattle', 1)
        if type(self.cause) is not SummonCause or self.cause.origin != 'card_effect':
            raise ValueError('Death self-copy requires its original minion effect cause')
        self.cause.__post_init__()

    def validate_in_state(self, state, registry):
        return invocation_death(state, registry, self)


def invocation_death(state, registry, effect):
    from .deathrattles import record, validate_capture
    from .summon_quantities import validate_cause
    effect.__post_init__()
    row = record(state, effect.invocation_id)
    capture = row.capture
    validate_capture(state, registry, capture)
    validate_cause(state, registry, effect.cause)
    if (row.execution_order is None or row.completed or row.interrupted or
            capture.origin != 'death' or capture.kind != CardType.MINION or
            capture.carrier_id != effect.cause.source.entity_id or
            capture.player_id != effect.cause.player_id):
        raise ValueError('Death self-copy lost its running actual natural invocation')
    death = next(d for d in state.death_history if d.id == capture.death_id)
    material = entry_from_death(death)
    validate_entry_scope(state, registry, material)
    return death


def summon(r, effect):
    from .summon_quantities import SummonByCard
    death = invocation_death(r.state, r.registry, effect)
    material = entry_from_death(death)
    return (SummonByCard(effect.cause.player_id, (material,), effect.cause, position=death.position),)


def copy_body(context):
    """An actual Deathrattle body, without creating a second death or paid play."""
    from .summon_quantities import SummonCause
    from .effects import CopyMinion
    from .board_presence import capture_board_presence
    from .summon_sources import CopyStoredMinion
    from .zones import CardReference
    from .errors import ResolutionError
    if context.deathrattle is None:
        raise ValueError('Deathrattle self-copy requires its actual accepted body')
    cause = SummonCause.capture(context)
    if context.death is not None:
        return (SummonDeathrattleSelfCopy(context.deathrattle.id, cause),)
    source = context.source
    if source.zone == Zone.BOARD:
        return (CopyMinion(capture_board_presence(context.state, source.id), context.player_id,
            cause=cause),) if source.active and source.health > 0 and not source.doomed else ()
    if source.zone in (Zone.HAND, Zone.DECK):
        return (CopyStoredMinion(CardReference.capture(source), context.player_id, cause=cause),)
    raise ResolutionError('Self-copy has no current board/stored source or original natural death')


def register(mechanics):
    mechanics.register_payload_type(DeathCopySource)
    mechanics.register(SummonDeathrattleSelfCopy, summon)
