"""frozen per-subject EndTurn source policies; CN calibration pending."""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _source
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, CardType, Zone, EndTurnRepeatSpec,
                    EndTurnRepeatContributor, EndTurnRepeatPlan, EndTurnSubject)


def matches(spec, subject, registry):
    from .repeat_source_conditions import validate_source_declaration
    validate_source_declaration(registry, spec)
    if type(subject) is not EndTurnSubject:
        raise ValueError('End-turn matching requires its complete accepted subject')
    subject.__post_init__()
    # The donor of a PlayerEffect is not the accepted physical subject.
    return spec.scope == 'all' or (subject.ability is not None and
                                  registry.card(subject.card_id).kind == CardType.MINION)


def capture_plan(state, registry, subject):
    from .end_turn_matching import validated_source_inventory
    from .repeat_source_conditions import validate_source_declaration, qualifying_repeat_witnesses
    validated_source_inventory(state, registry)
    if type(subject) is not EndTurnSubject:
        raise ValueError('End-turn repeat capture requires its complete subject')
    subject.__post_init__()
    owner = subject.player_id
    sources = []
    for entity_id in state.players[owner].board:
        entity = state.entities[entity_id]
        if entity.zone != Zone.BOARD or entity.controller != owner:
            raise ValueError('End-turn repeat source board membership disagrees with control')
        if entity.kind != CardType.MINION or not entity.active or entity.doomed or entity.health <= 0:
            continue
        for ability in active_abilities(entity, 'end_turn_repeat'):
            condition = validate_source_declaration(registry, ability.end_turn_repeat)
            # Complete query precedes the recipient-false intersection too.
            eligible = condition is None or bool(qualifying_repeat_witnesses(state, registry,
                player_id=owner, carrier_id=entity.id, eligibility=condition))
            if matches(ability.end_turn_repeat, subject, registry) and eligible:
                sources.append(EndTurnRepeatContributor(entity.id, entity.card_id, owner,
                                                       ability=ability))
    for instance in state.players[owner].player_effects:
        declaration = registry.player_effect(instance.spec_id)
        for index, spec in enumerate(declaration.end_turn_repeats):
            validate_source_declaration(registry, spec, allow_source=False)
            if matches(spec, subject, registry):
                sources.append(EndTurnRepeatContributor(instance.source_id, instance.source_card_id,
                    owner, player_effect=instance, spec=spec, spec_index=index))
    sources.sort(key=lambda source: source.key)
    return EndTurnRepeatPlan(max((source.spec.repetitions for source in sources), default=1),
                             tuple(sources))


def validate_plan(state, registry, plan, subject, turn):
    from .end_turn_matching import validated_source_inventory
    from .repeat_source_conditions import validate_source_declaration
    from .repeat_provenance import _static_compatible
    inventory = validated_source_inventory(state, registry)
    _integer(turn, 'End-turn acceptance turn', 1)
    if type(subject) is not EndTurnSubject or type(plan) is not EndTurnRepeatPlan:
        raise ValueError('Expected end-turn repeat plan and complete subject')
    subject.__post_init__()
    plan.__post_init__()
    for source in plan.contributors:
        validate_source_declaration(registry, source.spec, allow_source=source.ability is not None)
        if (source.player_id != subject.player_id or source.carrier_id not in state.entities or
                not matches(source.spec, subject, registry)):
            raise ValueError('End-turn repeat source differs from its accepted owner or scope')
        registry.card(source.card_id)
        if source.ability is not None:
            ability = source.ability
            if (registry.card(source.card_id).kind != CardType.MINION or
                    ability.id >= state.next_attachment_id or
                    ability.expires_turn is not None and ability.expires_turn < turn or
                    ability.source_id is not None and ability.source_id not in state.entities):
                raise ValueError('Invalid historical end-turn repeat ability')
            current = inventory.get(ability.id)
            if current is not None and (current[:2] != ('ability', source.carrier_id) or
                    not _static_compatible('ability', ability, current[2])):
                raise ValueError('End-turn repeat provenance differs from its surviving ability')
        else:
            instance = source.player_effect
            declaration = registry.player_effect(instance.spec_id)
            declaration.__post_init__()
            if (instance.id >= state.next_attachment_id or instance.created_turn > turn or
                    instance.entered_order >= state.next_order or
                    (instance.remaining_turns is None) != (declaration.duration is None) or
                    declaration.duration is not None and instance.remaining_turns > declaration.duration or
                    source.spec_index >= len(declaration.end_turn_repeats) or
                    declaration.end_turn_repeats[source.spec_index] != source.spec):
                raise ValueError('End-turn repeat player source differs from its declaration')
            current = inventory.get(instance.id)
            if current is not None and (current[:2] != ('player_effects', source.player_id) or
                    not _static_compatible('player_effects', instance, current[2])):
                raise ValueError('End-turn repeat player instance changed its historical identity')


def validate_source_history(state, registry):
    """Compact source clocks follow accepted EndTurn batch order, never live witnesses."""
    from .repeat_provenance import _static_compatible
    previous = {}
    for group in state.end_turn_batches:
        for subject, plan in zip(group.subjects, group.plans):
            validate_plan(state, registry, plan, subject, group.turn)
            for source in plan.contributors:
                identity = source.ability.id if source.ability is not None else source.player_effect.id
                family = 'ability' if source.ability is not None else 'player_effects'
                carrier = source.carrier_id if source.ability is not None else source.player_id
                value = source.ability if source.ability is not None else source.player_effect
                old = previous.get(identity)
                if old is not None and (old[:2] != (family, carrier) or
                        not _static_compatible(family, old[2], value)):
                    raise ValueError('End-turn captured source changed its identity or owner clock')
                previous[identity] = (family, carrier, value)


@dataclass(frozen=True)
class GrantEndTurnRepeatAura(Effect):
    target_id: int
    spec: EndTurnRepeatSpec = EndTurnRepeatSpec()
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'End-turn repeat carrier', 1)
        _source(self.source_id)
        if type(self.spec) is not EndTurnRepeatSpec:
            raise ValueError('Expected end-turn repeat specification')
        self.spec.__post_init__()
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'End-turn repeat expiry', 1)


def grant(r, effect):
    from .resolver import validate_attachment_source
    from .repeat_source_conditions import validate_source_declaration
    effect.__post_init__()
    validate_source_declaration(r.registry, effect.spec)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return
    ability = AbilityInstance(attachment_id(r.state), 'end_turn_repeat',
        source_id=effect.source_id, expires_turn=effect.expires_turn, end_turn_repeat=effect.spec)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def register(mechanics):
    mechanics.register(GrantEndTurnRepeatAura, grant)
