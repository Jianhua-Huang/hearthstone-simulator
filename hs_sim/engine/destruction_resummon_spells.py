"""A generated spell's exact original destruction group; ordinary resurrection."""
from dataclasses import dataclass

from .effects import AddToHand, DestroyBatch, Effect, _integer, _player
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, DeathCause, Zone, _name
from .sacrifice import MinionReference, reference_value


@dataclass(frozen=True)
class DestroyedSpellGroup:
    cast_id: int
    first_death_id: int
    victims: tuple[MinionReference, ...]
    causes: tuple[DeathCause, ...]

    def __post_init__(self):
        _integer(self.cast_id, 'original destruction cast', 1)
        _integer(self.first_death_id, 'original destruction boundary', 1)
        if type(self.victims) is not tuple or type(self.causes) is not tuple or len(self.victims) != len(self.causes):
            raise ValueError('Destruction spell requires its complete original ordered group')
        for ref in self.victims:
            reference_value(ref)
        if len({ref.entity_id for ref in self.victims}) != len(self.victims):
            raise ValueError('Destruction spell duplicated a physical victim')
        for ref, cause in zip(self.victims, self.causes):
            reference_value(ref)
            if type(cause) is not DeathCause:
                raise ValueError('Destruction spell requires original typed causes')
            cause.__post_init__()
            if (cause.kind, cause.reason, cause.target_id, cause.target_card_id, cause.target_controller,
                    cause.target_zone_epoch, cause.target_entered_order) != (
                    'destroy', 'Destroy', ref.entity_id, ref.card_id, ref.player_id, ref.zone_epoch, ref.entered_order):
                raise ValueError('Destruction spell substituted an original physical victim')


@dataclass(frozen=True)
class SpellResummonValue:
    card_id: str
    recipient_id: int
    group: DestroyedSpellGroup

    def __post_init__(self):
        _name(self.card_id, 'native resummoning spell'); _player(self.recipient_id)
        if type(self.group) is not DestroyedSpellGroup:
            raise ValueError('Resummoning spell requires its original complete destruction')
        self.group.__post_init__()


@dataclass(frozen=True)
class SpellResummonProfile:
    card_id: str
    source_card_id: str

    def __post_init__(self):
        _name(self.card_id, 'native resummoning spell'); _name(self.source_card_id, 'original destruction spell')


def validate_profile(registry, profile):
    if type(profile) is not SpellResummonProfile:
        raise ValueError('Expected native resummoning profile')
    profile.__post_init__()
    for card_id in (profile.card_id, profile.source_card_id):
        card = registry.card(card_id)
        if card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None:
            raise ValueError('Resummoning requires complete original and generated spell bodies')


def validate_group(state, registry, group):
    if type(group) is not DestroyedSpellGroup:
        raise ValueError('Expected the complete original destruction group')
    group.__post_init__()
    from .spell_casts import cast_record
    from .death_causes import validate_in_state
    cast = cast_record(state, group.cast_id)
    if not cast.payload_started or cast.failure is not None or group.first_death_id > state.next_death_id:
        raise ValueError('Destruction group lost its original accepted spell or death boundary')
    for ref, cause in zip(group.victims, group.causes):
        entity = state.entities.get(ref.entity_id)
        if (entity is None or registry.card(ref.card_id).kind != CardType.MINION or
                ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order):
            raise ValueError('Destruction group borrowed an unknown or future victim')
        validate_in_state(state, registry, cause)
        if (cause.source_id, cause.source_card_id, cause.source_controller, cause.turn) != (
                cast.source_id, cast.card_id, cast.player_id, cast.turn):
            raise ValueError('Destruction group borrowed another source cast')
        dead = any(d.id >= group.first_death_id and d.zone == Zone.BOARD and d.cause == cause for d in state.death_history)
        if not (dead or entity.doomed and entity.death_cause == cause):
            raise ValueError('Destruction group lost its genuine original destruction')
    return cast


def validate_value(state, registry, value):
    if type(value) is not SpellResummonValue:
        raise ValueError('Expected complete native resummoning material')
    value.__post_init__()
    profile = registry.spell_value_profiles.get(value.card_id)
    validate_profile(registry, profile)
    cast = validate_group(state, registry, value.group)
    if cast.card_id != profile.source_card_id:
        raise ValueError('Resummoning material borrowed an unrelated original spell')
    return cast


def validate_ability(state, registry, ability):
    ability.__post_init__()
    cast = validate_value(state, registry, ability.spell_resummon_value)
    if ability.kind != 'spell_resummon_value' or ability.source_id != cast.source_id:
        raise ValueError('Resummoning spell changed its original physical source')


def install(state, registry, entity, value):
    cast = validate_value(state, registry, value)
    from .native_spell_values import VALUE_KINDS
    if (entity.kind != CardType.SPELL or entity.card_id != value.card_id or
            any(a.kind in VALUE_KINDS for a in entity.abilities)):
        raise ValueError('Resummoning material requires one matching physical spell carrier')
    entity.abilities.append(AbilityInstance(attachment_id(state), 'spell_resummon_value',
        source_id=cast.source_id, spell_resummon_value=value))


@dataclass(frozen=True)
class DestroyForResummonSpells(Effect):
    cast_id: int
    card_id: str

    def __post_init__(self):
        _integer(self.cast_id, 'original destruction spell cast', 1)
        _name(self.card_id, 'native resummoning reward')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        from .spell_casts import cast_record, active_cast
        cast = cast_record(state, self.cast_id)
        profile = registry.spell_value_profiles.get(self.card_id); validate_profile(registry, profile)
        if (cast.card_id != profile.source_card_id or not cast.payload_started or cast.failure is not None or
                cast.completed or cast.interrupted or active_cast(state, cast.source_id, cast.player_id) != cast):
            raise ValueError('Destruction request lost its original running spell')
        return cast


@dataclass(frozen=True)
class CompleteResummonSpells(Effect):
    card_id: str
    group: DestroyedSpellGroup
    next_recipient: int = 0

    def __post_init__(self):
        _name(self.card_id, 'native resummoning reward')
        if type(self.group) is not DestroyedSpellGroup:
            raise ValueError('Native reward requires its complete original destruction group')
        self.group.__post_init__()
        if type(self.next_recipient) is not int or self.next_recipient not in (0, 1):
            raise ValueError('Native reward requires its original finite delivery position')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        cast = validate_value(state, registry, SpellResummonValue(self.card_id, 1, self.group))
        if cast.completed or cast.interrupted:
            raise ValueError('Native reward lost its original running spell')
        return cast


def begin(r, request):
    cast = request.validate_in_state(r.state, r.registry)
    refs = tuple(MinionReference.capture(r.state.entities[eid])
        for pid in (cast.player_id, 3-cast.player_id) for eid in r.player(pid).board
        if (r.state.entities[eid].kind == CardType.MINION and r.state.entities[eid].active and
            r.state.entities[eid].health > 0 and not r.state.entities[eid].doomed))
    first = r.state.next_death_id
    from .resolver import destroy_batch
    destroy_batch(r, DestroyBatch(tuple(ref.entity_id for ref in refs), cast.source_id))
    group = DestroyedSpellGroup(cast.id, first, refs,
        tuple(r.state.entities[ref.entity_id].death_cause for ref in refs))
    validate_group(r.state, r.registry, group)
    return (CompleteResummonSpells(request.card_id, group),)


def complete(r, request):
    cast = request.validate_in_state(r.state, r.registry)
    recipient = cast.player_id if request.next_recipient == 0 else 3-cast.player_id
    from .opening import create_hand_card
    create_hand_card(r, AddToHand(recipient, request.card_id, cast.source_id),
        native_spell_value=SpellResummonValue(request.card_id, recipient, request.group))
    return (CompleteResummonSpells(request.card_id, request.group, 1),) if request.next_recipient == 0 else ()


def resummon(context, registry):
    cast = context.cast
    if (cast is None or cast.native_spell_value is None or
            (cast.source_id, cast.player_id) != (context.source_id, context.player_id)):
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Resummoning requires its original bound physical spell')
    ability = cast.native_spell_value; validate_ability(context.state, registry, ability)
    value = ability.spell_resummon_value
    if cast.card_id != value.card_id:
        raise ValueError('Resummoning borrowed another spell face')
    from .summon_quantities import SummonCause
    from .summon_sources import ResurrectMinion
    cause = SummonCause.capture(context)
    result = []
    for original in value.group.causes:
        if original.target_controller != value.recipient_id:
            continue
        death = next((d for d in context.state.death_history
            if d.id >= value.group.first_death_id and d.zone == Zone.BOARD and d.cause == original), None)
        if death is not None:
            result.append(ResurrectMinion(context.player_id, death.id, source_id=context.source_id, cause=cause))
    return tuple(result)


def value_from_dict(raw):
    from .serialization import _row, _list, _death_cause_from_dict
    value = _row(raw, SpellResummonValue); group = _row(value['group'], DestroyedSpellGroup)
    group['victims'] = tuple(MinionReference(**_row(ref, MinionReference))
        for ref in _list(group['victims'], 'original destroyed minions'))
    group['causes'] = tuple(_death_cause_from_dict(cause)
        for cause in _list(group['causes'], 'original destruction causes'))
    value['group'] = DestroyedSpellGroup(**group)
    return SpellResummonValue(**value)


def register(mechanics):
    mechanics.register_payload_type(DestroyedSpellGroup)
    mechanics.register_payload_type(SpellResummonValue)
    mechanics.register(DestroyForResummonSpells, begin)
    mechanics.register(CompleteResummonSpells, complete)
