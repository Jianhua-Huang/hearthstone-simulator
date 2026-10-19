"""A real hand spell transformed into a timed Aura, retaining its material.

The wrapper is an ordinary physical spell. Its original spell is not cast until
the Aura triggers. Targets, choices, spell values and reactions use the shared
automatic caster; owner clocks and expiry use the existing player program.
"""
from dataclasses import dataclass, replace
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .copy_materials import CapturedCardCopyMaterial, validate_captured_card_copy
from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, PlayerEffect, Zone, validate_end_turn_rng
from .zones import CardReference

EVENT = 'hand_spell_aura_created'


@dataclass(frozen=True)
class SpellAuraRecord:
    id: int
    source: SourceAllocationFact
    card: CapturedCardCopyMaterial
    aura: SourceAllocationFact
    candidates: tuple[CardReference, ...]
    costs: tuple[int, ...]
    rng_before: tuple
    rng_after: tuple
    turn: int
    action: int
    event_sequence: int

    def __post_init__(self):
        for name in ('id', 'turn', 'event_sequence'):
            _integer(getattr(self, name), 'spell Aura '+name, 1)
        _integer(self.action, 'spell Aura action', 0)
        if (type(self.source) is not SourceAllocationFact or type(self.aura) is not SourceAllocationFact or
                type(self.card) is not CapturedCardCopyMaterial):
            raise ValueError('Spell Aura requires complete original source, spell and wrapper facts')
        self.source.__post_init__(); self.aura.__post_init__(); self.card.__post_init__()
        origin = self.card.origin
        if (origin.kind != CardType.SPELL or origin.zone != Zone.HAND or self.aura.kind != CardType.SPELL or
                self.aura.zone != Zone.HAND or self.aura.entity_id != origin.entity_id or
                self.aura.zone_epoch != origin.zone_epoch+1 or self.aura.controller != origin.controller):
            raise ValueError('Spell Aura changed its original hand spell or physical transformation')
        if (type(self.candidates) is not tuple or not self.candidates or
                any(type(c) is not CardReference for c in self.candidates) or
                type(self.costs) is not tuple or len(self.costs) != len(self.candidates) or
                len(set(c.entity_id for c in self.candidates)) != len(self.candidates)):
            raise ValueError('Spell Aura requires the complete ordered physical spell candidates and costs')
        for ref, cost in zip(self.candidates, self.costs):
            ref.__post_init__(); _integer(cost, 'original spell selection cost', 0)
            if ref.zone != Zone.HAND or ref.player_id != origin.controller:
                raise ValueError('Spell Aura candidates changed their original hand')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)


def record(state, identity):
    _integer(identity, 'original spell Aura identity', 1)
    if identity > len(state.spell_aura_history):
        raise ValueError('Spell Aura lost its original transformed spell')
    row = state.spell_aura_history[identity-1]
    if type(row) is not SpellAuraRecord or row.id != identity:
        raise ValueError('Spell Aura history lost its ordinal identity')
    return row


def aura_spec(registry, card_id):
    card = registry.card(card_id)
    if card.kind != CardType.SPELL or card.ongoing_effect_id is None:
        raise ValueError('Spell wrapper requires an ordinary ongoing Aura spell')
    spec = registry.player_effect(card.ongoing_effect_id)
    if (spec.card_id != card_id or spec.kind != 'aura' or spec.duration is None or
            spec.tick_event != 'turn_ended' or spec.tick_player != 'controller' or not spec.stored_spell):
        raise ValueError('Spell wrapper requires a timed owner-end Aura program')
    return spec


def memory_id(entity):
    abilities = tuple(a for a in entity.abilities if a.kind == 'spell_aura')
    if len(abilities) > 1:
        raise ValueError('One physical Aura cannot carry multiple original spells')
    return abilities[0].spell_aura_id if abilities else None


def install(state, entity, identity, source_id):
    entity.abilities.append(AbilityInstance(attachment_id(state), 'spell_aura',
        source_id=source_id, spell_aura_id=identity))


def validate_binding(state, registry, identity, card_id):
    row = record(state, identity)
    aura_spec(registry, card_id)
    if row.aura.card_id != card_id:
        raise ValueError('Spell Aura borrowed another wrapper face')
    return row


def validate_instance(state, registry, instance):
    instance.__post_init__()
    if registry.player_effect(instance.spec_id).stored_spell != (instance.spell_aura_id is not None):
        raise ValueError('Stored Aura program lost its original spell')
    if instance.spell_aura_id is None:
        if instance.spell_aura_card_id is not None:
            raise ValueError('Public Aura spell requires its original private material')
        return
    row = validate_binding(state, registry, instance.spell_aura_id, instance.source_card_id)
    if (registry.player_effect(instance.spec_id).card_id != row.aura.card_id or
            instance.spell_aura_card_id != row.card.origin.card_id or
            instance.id >= state.next_attachment_id or instance.entered_order >= state.next_order or
            instance.created_turn > state.turn or instance.source_id not in state.entities):
        raise ValueError('Player Aura changed its original spell or registered program')


def validate_state(state, registry):
    if type(state.spell_aura_history) is not list:
        raise ValueError('Spell Aura history requires an ordered list')
    previous = (0, 0, 0)
    for index, row in enumerate(state.spell_aura_history, 1):
        if type(row) is not SpellAuraRecord or row.id != index:
            raise ValueError('Spell Aura history lost its complete ordinal inventory')
        row.__post_init__()
        validate_allocation(state, registry, row.source)
        validate_allocation(state, registry, row.aura)
        validate_captured_card_copy(state, registry, row.card)
        aura_spec(registry, row.aura.card_id)
        if (row.turn, row.action, row.event_sequence) <= previous or row.turn > state.turn or row.action > state.action_number:
            raise ValueError('Spell Aura changed its original acceptance order or future clock')
        previous = row.turn, row.action, row.event_sequence
        for ref in row.candidates:
            entity = state.entities.get(ref.entity_id)
            if (registry.card(ref.card_id).kind != CardType.SPELL or entity is None or ref.zone_epoch > entity.zone_epoch):
                raise ValueError('Spell Aura candidate lost its physical spell allocation')
        choices = tuple(ref for ref, cost in zip(row.candidates, row.costs) if cost == max(row.costs))
        rng = Random(); rng.setstate(row.rng_before)
        selected = choices[0] if len(choices) == 1 else rng.choice(choices)
        origin = row.card.origin
        if (selected.entity_id, selected.card_id, selected.zone_epoch) != (
                origin.entity_id, origin.card_id, origin.zone_epoch) or rng.getstate() != row.rng_after:
            raise ValueError('Spell Aura differs from its original highest-cost selection')
        for ability in row.card.local.abilities:
            if ability.spell_aura_id is not None:
                if ability.spell_aura_id >= row.id:
                    raise ValueError('Spell Aura cannot recursively borrow its own or a future payload')
                validate_binding(state, registry, ability.spell_aura_id, row.card.origin.card_id)
    for entity in state.entities.values():
        identity = memory_id(entity)
        if identity is not None:
            validate_binding(state, registry, identity, entity.card_id)
    for cast in state.cast_history:
        definition = registry.card(cast.card_id)
        if (cast.payload_started and definition.ongoing_effect_id is not None and
                registry.player_effect(definition.ongoing_effect_id).stored_spell and cast.spell_aura_id is None):
            raise ValueError('Executed Aura wrapper lost its original spell material')
        if cast.spell_aura_id is not None:
            validate_binding(state, registry, cast.spell_aura_id, cast.card_id)
    for player in state.players.values():
        for instance in player.player_effects:
            validate_instance(state, registry, instance)
            if instance.spell_aura_id is not None and instance.spell_aura_player_id != player.id:
                raise ValueError('Player Aura changed its original beneficiary')


@dataclass(frozen=True)
class CastHighestHandSpellAsAura(Effect):
    player_id: int
    aura_card_id: str
    source_id: int

    def __post_init__(self):
        from .model import _name
        _player(self.player_id); _name(self.aura_card_id, 'spell Aura wrapper')
        _integer(self.source_id, 'spell Aura source', 1)


def create(r, effect):
    from .costs import quote_cost
    from .cross_zone import reset_stored_entity, announce_stored_transform
    from .spell_casts import CastStoredSpell
    effect.__post_init__(); aura_spec(r.registry, effect.aura_card_id)
    source = r.state.entities.get(effect.source_id)
    if source is None:
        raise ResolutionError('Spell Aura lost its original casting source')
    # The beneficiary is the actual Battlecry actor, even for borrowed text.
    source_fact = SourceAllocationFact.capture(r.state, source)
    spells = tuple(r.state.entities[eid] for eid in r.player(effect.player_id).hand
                   if r.state.entities[eid].kind == CardType.SPELL)
    if not spells:
        return ()
    candidates = tuple(CardReference.capture(entity) for entity in spells)
    costs = tuple(quote_cost(r.state, r.registry, entity).amount for entity in spells)
    top = tuple(entity for entity, cost in zip(spells, costs) if cost == max(costs))
    before = r.game._rng.getstate()
    entity = top[0] if len(top) == 1 else r.game._rng.choice(top)
    after = r.game._rng.getstate()
    material = CapturedCardCopyMaterial.capture(r.state, entity)
    old = entity.card_id
    reset_stored_entity(r, entity, r.registry.card(effect.aura_card_id))
    identity = len(r.state.spell_aura_history)+1
    row = SpellAuraRecord(identity, source_fact, material, SourceAllocationFact.capture(r.state, entity),
        candidates, costs, before, after, r.state.turn, r.state.action_number, len(r.game._events)+1)
    r.state.spell_aura_history.append(row)
    install(r.state, entity, identity, source.id)
    r.emit(EVENT, source_id=source.id, target_id=entity.id, player_id=effect.player_id,
        aura_id=identity, record_hash=record_hash(row), _capture=False)
    announce_stored_transform(r, entity, old, source_id=source.id)
    return (CastStoredSpell(CardReference.capture(entity), effect.player_id, source.id),)


def capture_cast(r, cast):
    identity = memory_id(r.state.entities[cast.source_id])
    if identity is None:
        return cast
    validate_binding(r.state, r.registry, identity, cast.card_id)
    cast = replace(cast, spell_aura_id=identity)
    r.state.cast_history[cast.id-1] = cast
    return cast


@dataclass(frozen=True)
class CastAuraSpell(Effect):
    player_id: int
    instance: PlayerEffect

    def __post_init__(self):
        _player(self.player_id)
        if type(self.instance) is not PlayerEffect or self.instance.spell_aura_id is None:
            raise ValueError('Aura trigger requires its complete original player instance')
        self.instance.__post_init__()


def cast(r, effect):
    from .spell_casts import CastSpell, automatic
    from .zones import copy_current_stored_state
    effect.__post_init__()
    instance = effect.instance
    validate_instance(r.state, r.registry, instance)
    if effect.player_id != instance.spell_aura_player_id:
        raise ResolutionError('Aura trigger changed its original program beneficiary')
    row = record(r.state, instance.spell_aura_id)
    # Already captured triggers keep their original body after removal/expiry.
    entity = r.create_entity(effect.player_id, row.card.origin.card_id, Zone.GRAVEYARD)
    entity.origin_entity_id = row.card.origin.entity_id
    copy_current_stored_state(r.state, row.card.entity(), entity)
    return automatic(r, CastSpell(effect.player_id, entity.card_id, instance.source_id), entity, None)


def validate_boundary(game):
    from .hero_health_history import effective_events
    events = tuple(e for e in effective_events(game._events) if e.kind == EVENT)
    rows = game._state.spell_aura_history
    if len(events) != len(rows):
        raise ValueError('Spell Aura lost its complete original transformation inventory')
    for event, row in zip(events, rows):
        if (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount,
                dict(event.data)) != (row.event_sequence, row.action, row.source.entity_id,
                row.card.origin.entity_id, row.card.origin.controller, 0,
                {'aura_id': row.id, 'record_hash': record_hash(row)}):
            raise ValueError('Spell Aura changed its original physical transformation fact')


def record_hash(row):
    from dataclasses import asdict
    from .serialization import canonical_hash
    return canonical_hash(asdict(row))


def rows_from_dict(value):
    from .serialization import _row, _list, rng_from_json
    from .copy_materials import CopyLocalState, from_dict
    from .model import HandPreparation
    rows = []
    for raw in _list(value['spell_aura_history'], 'original spell Aura history'):
        row = _row(raw, SpellAuraRecord)
        for name in ('source', 'aura'):
            row[name] = allocation_from_dict(row[name])
        material = _row(row['card'], CapturedCardCopyMaterial)
        material['origin'] = allocation_from_dict(material['origin'])
        material['local'] = from_dict(CopyLocalState, material['local'])
        material['components'] = tuple(_list(material['components'], 'original Aura spell components'))
        if material['preparation'] is not None:
            material['preparation'] = HandPreparation(**_row(material['preparation'], HandPreparation))
        row['card'] = CapturedCardCopyMaterial(**material)
        row['candidates'] = tuple(CardReference(**dict(ref, zone=Zone(ref['zone']))) for ref in row['candidates'])
        row['costs'] = tuple(row['costs'])
        for name in ('rng_before', 'rng_after'):
            row[name] = rng_from_json(row[name])
        rows.append(SpellAuraRecord(**row))
    value['spell_aura_history'] = rows


def register(mechanics):
    mechanics.register_payload_type(SpellAuraRecord)
    mechanics.register(CastHighestHandSpellAsAura, create)
    mechanics.register(CastAuraSpell, cast)
