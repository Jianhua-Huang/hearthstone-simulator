"""Frozen board/player Deathrattle plans and accepted-face matching (R-154)."""
from dataclasses import dataclass, replace
from .effects import Effect, _integer, _player, _source
from .lifecycle import active_abilities, attachment_id
from .repeat_provenance import checked_live_attachments
from .model import (AbilityInstance,CardType,Zone,DeathrattleRepeatSpec,
                    DeathrattleRepeatContributor,DeathrattlePlayerContributor,DeathrattleRepeatPlan)




def _validate_payload(ability):
    if type(ability) is not AbilityInstance:
        raise ValueError('Deathrattle plan requires its complete payload ability')
    ability.__post_init__()
    if ability.kind != 'deathrattle' or ability.consumed:
        raise ValueError('Deathrattle plan requires an unconsumed Deathrattle payload')


def capture_plan(state, registry, player_id, recipient, ability, death=None):
    from .deathrattle_matching import (capture_recipient_from_state, validate_recipient,
                                      deathrattle_repeat_recipient_matches)
    from .repeat_source_conditions import (validate_source_declaration,
        qualifying_repeat_witnesses, qualifying_deathrattle_self_witnesses)
    _player(player_id); _validate_payload(ability)
    definition = validate_recipient(state, registry, recipient, death=death)
    if recipient != capture_recipient_from_state(state, registry, recipient.carrier_id, death=death):
        raise ValueError('Deathrattle plan must capture its original physical recipient face')
    if player_id != (death.controller if death is not None else state.entities[recipient.carrier_id].controller):
        raise ValueError('Deathrattle plan differs from its original recipient owner')
    checked_live_attachments(state)
    sources=[]
    def matches(spec, source_id=None):
        return deathrattle_repeat_recipient_matches(spec, recipient=recipient,
            recipient_definition=definition, payload_ability=ability, source_carrier_id=source_id)
    for entity_id in state.players[player_id].board:
        entity=state.entities[entity_id]
        # Validate even inactive/false declarations before any presence exit.
        for source in entity.abilities:
            if source.kind == 'deathrattle_repeat':
                source.__post_init__()
                validate_source_declaration(registry, source.deathrattle_repeat)
                if entity.kind != CardType.MINION:
                    raise ValueError('Deathrattle repeat sources require physical minion carriers')
        if entity.kind!=CardType.MINION or not entity.active or entity.doomed or entity.health<=0:
            continue
        for source in active_abilities(entity,'deathrattle_repeat'):
            condition = validate_source_declaration(registry, source.deathrattle_repeat)
            source_matches = condition is None or bool(qualifying_repeat_witnesses(
                state, registry, player_id=player_id, carrier_id=entity.id, eligibility=condition))
            recipient_matches = matches(source.deathrattle_repeat,entity.id)
            if source_matches and recipient_matches:
                sources.append(DeathrattleRepeatContributor(entity.id,entity.card_id,player_id,source))
    for instance in state.players[player_id].player_effects:
        declaration=registry.player_effect(instance.spec_id)
        for index,spec in enumerate(declaration.deathrattle_repeats):
            validate_source_declaration(registry, spec, allow_source=False)
            if matches(spec):
                sources.append(DeathrattlePlayerContributor(player_id,instance,index,spec))
    # Only explicitly self-scoped policies survive the carrier's natural removal.
    # Friendly board auras keep their previous post-removal acceptance window.
    if death is not None:
        for source in death.abilities:
            if source.kind != 'deathrattle_repeat':
                continue
            source.__post_init__()
            condition = validate_source_declaration(registry, source.deathrattle_repeat)
            if registry.card(death.card_id).kind != CardType.MINION:
                raise ValueError('Frozen Deathrattle repeat sources require minion carriers')
            if source.consumed or source.deathrattle_repeat.scope != 'self':
                continue
            source_matches = condition is None or bool(qualifying_deathrattle_self_witnesses(
                state, registry, player_id=player_id, carrier_id=recipient.carrier_id,
                eligibility=condition, death=death, source_ability=source))
            recipient_matches = matches(source.deathrattle_repeat,recipient.carrier_id)
            if source_matches and recipient_matches:
                sources.append(DeathrattleRepeatContributor(recipient.carrier_id,death.card_id,player_id,source))
    sources.sort(key=lambda s:s.key)
    return DeathrattleRepeatPlan(max((s.spec.repetitions for s in sources),default=1),tuple(sources))


def validate_plan(state, registry, plan, player_id, turn, recipient, ability, death=None):
    from .deathrattle_matching import validate_recipient, deathrattle_repeat_recipient_matches
    from .repeat_source_conditions import validate_source_declaration
    _player(player_id); _integer(turn, 'Deathrattle acceptance turn', 1); _validate_payload(ability)
    definition = validate_recipient(state, registry, recipient, death=death)
    if type(plan) is not DeathrattleRepeatPlan:
        raise ValueError('Expected captured Deathrattle repeat plan')
    plan.__post_init__()
    live = checked_live_attachments(state)
    for source in plan.contributors:
        board_source = type(source) is DeathrattleRepeatContributor
        validate_source_declaration(registry, source.spec, allow_source=board_source)
        if (source.player_id!=player_id or not deathrattle_repeat_recipient_matches(source.spec,
                recipient=recipient, recipient_definition=definition, payload_ability=ability,
                source_carrier_id=source.carrier_id if board_source else None)):
            raise ValueError('Invalid Deathrattle repeat contributor scope')
        if board_source and source.spec.scope=='self' and death is not None and source.ability not in death.abilities:
            raise ValueError('Self Deathrattle contributor differs from frozen death abilities')
        if type(source) is DeathrattlePlayerContributor:
            instance=source.instance;declaration=registry.player_effect(instance.spec_id)
            registry.card(instance.source_card_id)
            from .aura_duration import maximum_duration
            maximum = maximum_duration(registry, instance, state)
            if (instance.id>=state.next_attachment_id or instance.source_id not in state.entities or
                    instance.created_turn>turn or instance.entered_order>=state.next_order or
                    (declaration.duration is None)!=(instance.remaining_turns is None) or
                    declaration.duration is not None and instance.remaining_turns>maximum or
                    source.spec_index>=len(declaration.deathrattle_repeats) or
                    declaration.deathrattle_repeats[source.spec_index]!=source.spec):
                raise ValueError('Invalid captured player Deathrattle source or specification')
            surviving = live.get(instance.id)
            if surviving is not None:
                family, owner, current = surviving
                if (family != 'player_effects' or owner != source.player_id or
                        replace(current,remaining_turns=instance.remaining_turns)!=instance or
                        (current.remaining_turns is None)!=(instance.remaining_turns is None) or
                        current.remaining_turns is not None and current.remaining_turns>instance.remaining_turns):
                    raise ValueError('Captured player Deathrattle source changed its surviving identity')
            continue
        if (source.carrier_id not in state.entities or source.player_id!=player_id or
                registry.card(source.card_id).kind!=CardType.MINION or
                source.ability.id>=state.next_attachment_id or
                source.ability.expires_turn is not None and source.ability.expires_turn<turn):
            raise ValueError('Invalid captured Deathrattle repeat source')
        if source.ability.source_id is not None and source.ability.source_id not in state.entities:
            raise ValueError('Unknown captured Deathrattle repeat grant source')
        # A later removal/reset may erase a frozen source, and control transfer
        # may move its carrier. A surviving global attachment ID still denotes
        # this exact ability on this carrier, irrespective of its live owner.
        surviving = live.get(source.ability.id)
        if surviving is not None:
            family, carrier, current = surviving
            if (family != 'ability' or carrier != source.carrier_id or
                    replace(current,consumed=source.ability.consumed)!=source.ability):
                raise ValueError('Captured Deathrattle source changed its surviving ability identity')


@dataclass(frozen=True)
class GrantDeathrattleRepeatAura(Effect):
    target_id: int
    spec: DeathrattleRepeatSpec = DeathrattleRepeatSpec()
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id,'Deathrattle repeat carrier',1);_source(self.source_id)
        if type(self.spec) is not DeathrattleRepeatSpec: raise ValueError('Expected Deathrattle repeat specification')
        self.spec.__post_init__()
        if self.expires_turn is not None: _integer(self.expires_turn,'Deathrattle repeat expiry',1)


def grant(r, effect):
    from .resolver import validate_attachment_source
    from .repeat_source_conditions import validate_source_declaration
    validate_source_declaration(r.registry, effect.spec)
    validate_attachment_source(r,effect.source_id,effect.expires_turn)
    entity=r.state.entities.get(effect.target_id)
    if entity is None or entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD or not entity.active:
        r.stale(effect,effect.target_id);return
    ability=AbilityInstance(attachment_id(r.state),'deathrattle_repeat',source_id=effect.source_id,
        deathrattle_repeat=effect.spec,expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted',target_id=entity.id,source_id=effect.source_id,ability_id=ability.id,ability_kind=ability.kind)


def register(mechanics):
    mechanics.register(GrantDeathrattleRepeatAura,grant)
