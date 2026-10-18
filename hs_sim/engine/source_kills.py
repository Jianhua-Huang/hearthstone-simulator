"""Exact physical kill provenance, consumed by ordinary death resurrection."""
from dataclasses import dataclass

from .effects import Effect, _behavior, _integer, _player
from .errors import ResolutionError
from .model import CardType, DamageKind, DeathrattleCapture, Zone
from .summon_quantities import SummonCause


@dataclass(frozen=True)
class KillSourceReference:
    entity_id: int
    card_id: str
    kind: CardType
    zone_epoch: int
    death_id: int | None = None

    def __post_init__(self):
        _integer(self.entity_id, 'kill source', 1)
        _behavior(self.card_id)
        _integer(self.zone_epoch, 'kill source incarnation', 0)
        if self.kind not in (CardType.MINION, CardType.WEAPON) or type(self.kind) is not CardType:
            raise ValueError('Kill source requires a minion or weapon')
        if self.death_id is not None:
            _integer(self.death_id, 'original kill source death', 1)

    @classmethod
    def capture(cls, context):
        activation = context.deathrattle
        if activation is None:
            raise ResolutionError('Kill resurrection requires its native Deathrattle')
        death = context.death
        link = activation.ability.deathrattle_inherited_from
        # Inheritance preserves the original native payload's parameters.
        while link is not None:
            death = context.state.death_history[link[0] - 1]
            ability = next(a for a in death.abilities if a.id == link[1])
            link = ability.deathrattle_inherited_from
        if death is None and activation.origin == 'history':
            data = dict(activation.historical_root.data)
            index = data['carriers'].index(activation.carrier_id)
            death = context.state.death_history[data['selected'][index] - 1]
        if death is not None:
            kind = CardType.WEAPON if death.zone == Zone.WEAPON else CardType.MINION
            return cls(death.entity_id, death.card_id, kind, death.cause.target_zone_epoch, death.id)
        source = context.source
        return cls(source.id, source.card_id, source.kind, source.zone_epoch)


def validate_reference(state, registry, source):
    if type(source) is not KillSourceReference:
        raise ValueError('Kill query requires its original typed source')
    source.__post_init__()
    current = state.entities.get(source.entity_id)
    if (current is None or source.zone_epoch > current.zone_epoch
            or registry.card(source.card_id).kind != source.kind):
        raise ValueError('Kill source is unknown, future or has another printed kind')
    if source.death_id is not None:
        death = next((d for d in state.death_history if d.id == source.death_id), None)
        zone = Zone.WEAPON if source.kind == CardType.WEAPON else Zone.BOARD
        if death is None or (death.entity_id, death.card_id, death.zone, death.cause.target_zone_epoch) != (
                source.entity_id, source.card_id, zone, source.zone_epoch):
            raise ValueError('Kill source differs from its original immutable death')


def killed_minion_deaths(state, registry, source, *, events=()):
    """No current-health inference, controller filter, name deduplication or RNG."""
    validate_reference(state, registry, source)
    epochs = {source.zone_epoch}
    if source.kind == CardType.WEAPON:
        from .equipment import weapon_transfer_reference
        from .hero_health_history import effective_events
        for event in reversed(tuple(effective_events(events))):
            if event.kind != 'weapon_transferred':
                continue
            ref = weapon_transfer_reference(event)
            if (ref.entity_id, ref.card_id) == (source.entity_id, source.card_id):
                if dict(event.data)['new_zone_epoch'] in epochs:
                    epochs.add(ref.zone_epoch)
    result = []
    for death in state.death_history:
        if death.zone != Zone.BOARD or registry.card(death.card_id).kind != CardType.MINION:
            continue
        cause = death.cause
        if source.kind == CardType.MINION:
            matches = (cause.source_id, cause.source_card_id, cause.source_zone_epoch) == (
                source.entity_id, source.card_id, source.zone_epoch)
        else:
            health = cause.health_result
            matches = (cause.kind in ('damage', 'poison') and health is not None
                and health.damage_kind == DamageKind.COMBAT.value
                and health.weapon_id == source.entity_id and health.weapon_zone_epoch in epochs)
        if matches:
            result.append(death)
    return tuple(result)


@dataclass(frozen=True)
class ResurrectKilledMinions(Effect):
    player_id: int
    source: KillSourceReference
    deathrattle_id: int
    cause: SummonCause
    position: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.deathrattle_id, 'kill resurrection activation', 1)
        if type(self.source) is not KillSourceReference or type(self.cause) is not SummonCause:
            raise ValueError('Kill resurrection requires its original source and ordinary summon cause')
        self.source.__post_init__()
        self.cause.__post_init__()
        if self.position is not None:
            _integer(self.position, 'kill resurrection position', 0)


def validate_effect(state, registry, effect):
    effect.__post_init__()
    validate_reference(state, registry, effect.source)
    from .deathrattles import record
    row = record(state, effect.deathrattle_id)
    if (row.execution_order is None or row.completed or row.interrupted
            or (row.capture.player_id, row.capture.carrier_id) !=
               (effect.player_id, effect.cause.source.entity_id)):
        raise ValueError('Kill resurrection lost its actual running native Deathrattle')


def resurrect(r, effect):
    validate_effect(r.state, r.registry, effect)
    deaths = killed_minion_deaths(r.state, r.registry, effect.source, events=r.game._events)
    ids = tuple(d.id for d in deaths)
    r.emit('killed_minions_selected', source_id=effect.cause.source.entity_id,
        player_id=effect.player_id, _capture=False, deathrattle_id=effect.deathrattle_id,
        original_source=(effect.source.entity_id, effect.source.card_id, effect.source.zone_epoch), death_ids=ids)
    if not ids:
        return ()
    from .summon_sources import DeathQuery, Resurrect
    return (Resurrect(effect.player_id, len(ids), DeathQuery(side='both'), selection='first',
        source_id=effect.cause.source.entity_id, position=effect.position,
        cause=effect.cause, death_ids=ids),)


def register(mechanics):
    mechanics.register_payload_type(KillSourceReference)
    mechanics.register(ResurrectKilledMinions, resurrect)
