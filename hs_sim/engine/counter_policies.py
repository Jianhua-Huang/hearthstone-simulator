"""Private, finite counters attached to one live minion incarnation.

RequestChoice owns the private decision. These effects own its durable result
and recheck both the carrier and pending play before spending a use.
"""
from dataclasses import dataclass, fields, replace

from .effects import Effect, ChoiceOption
from .errors import ResolutionError
from .interrupts import find_window, mark_counter, announce_counter
from .lifecycle import active_abilities, attachment_id
from .model import AbilityInstance, CardType, CounterPolicySpec, _int, _optional_id
from .sacrifice import MinionReference, reference_value, live_minion


@dataclass(frozen=True)
class GrantCounterPolicy(Effect):
    carrier: MinionReference
    spec: CounterPolicySpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        reference_value(self.carrier)
        if type(self.spec) is not CounterPolicySpec:
            raise ValueError('Counter grant requires CounterPolicySpec')
        self.spec.__post_init__()
        _optional_id(self.source_id, 'counter source')
        _optional_id(self.expires_turn, 'counter expiry')


@dataclass(frozen=True)
class CheckCounterPolicy(Effect):
    carrier: MinionReference
    ability_id: int
    window_id: int
    kind: CardType

    def __post_init__(self):
        reference_value(self.carrier)
        _int(self.ability_id, 'counter ability', 1)
        _int(self.window_id, 'counter window', 1)
        CounterPolicySpec(self.kind)


def fact(ability):
    return dict(kind=ability.counter_policy.kind.value,
                uses_remaining=ability.uses_remaining, expires_turn=ability.expires_turn)


def private_policies(entity):
    # Do not publish count, keys, source IDs, or unused policies to opponents.
    return [fact(a) for a in entity.abilities if a.kind == 'counter_policy']


def eligible(window, controller, kind):
    return (window is not None and not window.countered and window.player_id != controller
            and window.kind == kind.value
            and (window.counter_phase if kind == CardType.MINION else not window.target_phase))


def capture(r, entity, ability, event):
    kind = ability.counter_policy.kind
    if event.kind != ('minion_counter_check' if kind == CardType.MINION else 'card_committed'):
        return None
    reference = MinionReference.capture(entity)
    window = find_window(r.state, dict(event.data).get('window_id'))
    if live_minion(r.state, reference) is None or not eligible(window, entity.controller, kind):
        return None
    return CheckCounterPolicy(reference, ability.id, window.id, kind)


def check(r, effect):
    entity = live_minion(r.state, effect.carrier)
    if entity is None:
        return
    ability = next((a for a in active_abilities(entity, 'counter_policy')
                    if a.id == effect.ability_id and a.counter_policy.kind == effect.kind), None)
    window = find_window(r.state, effect.window_id)
    if ability is None or not eligible(window, entity.controller, effect.kind):
        return
    # Mark the play and spend the policy before any reveal reaction is captured.
    # An earlier secret/policy can make this candidate stale without spending it.
    marked = mark_counter(r, window.id, (effect.kind.value,))
    if marked is None:
        return
    updated = replace(ability, uses_remaining=ability.uses_remaining - 1,
                      consumed=ability.uses_remaining == 1)
    entity.abilities[entity.abilities.index(ability)] = updated
    r.emit('counter_policy_used', source_id=entity.id, player_id=entity.controller,
           amount=updated.uses_remaining, counter_kind=effect.kind.value,
           uses_remaining=updated.uses_remaining, expires_turn=updated.expires_turn)
    announce_counter(r, marked)


def grant(r, effect):
    validate_reference(r.state, r.registry, effect.carrier)
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = live_minion(r.state, effect.carrier)
    if entity is None:
        r.stale(effect, effect.carrier.entity_id)
        return
    spec = effect.spec
    if spec.key is not None:
        entity.abilities[:] = [a for a in entity.abilities if not (a.kind == 'counter_policy'
            and (a.counter_policy.key, a.counter_policy.kind) == (spec.key, spec.kind))]
    ability = AbilityInstance(attachment_id(r.state), 'counter_policy', source_id=effect.source_id,
        counter_policy=spec, uses_remaining=spec.uses, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('counter_policy_added', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, amount=ability.uses_remaining, counter_kind=spec.kind.value,
           uses_remaining=ability.uses_remaining, expires_turn=ability.expires_turn)


def validate_reference(state, registry, reference):
    entity = state.entities.get(reference.entity_id)
    if (entity is None or registry.card(reference.card_id).kind != CardType.MINION
            or reference.zone_epoch > entity.zone_epoch or reference.entered_order >= state.next_order):
        raise ValueError('Invalid counter carrier provenance')


def validate_frame(game):
    """Check live queue provenance, allowing an old but genuine carrier to expire."""
    from .resolver import ResolutionFrame
    def visit(work):
        if isinstance(work, (GrantCounterPolicy, CheckCounterPolicy)):
            validate_reference(game._state, game.registry, work.carrier)
            if isinstance(work, CheckCounterPolicy):
                window = find_window(game._state, work.window_id)
                if (window is None or window.kind != work.kind.value
                        or window.player_id == work.carrier.player_id
                        or work.ability_id >= game._state.next_attachment_id):
                    raise ValueError('Invalid suspended counter check')
                for entity in game._state.entities.values():
                    for ability in entity.abilities:
                        if ability.id == work.ability_id and (entity.id != work.carrier.entity_id
                                or ability.kind != 'counter_policy' or ability.counter_policy.kind != work.kind):
                            raise ValueError('Counter check differs from its ability')
            elif work.source_id is not None and work.source_id not in game._state.entities:
                raise ValueError('Missing suspended counter source')
        if isinstance(work, (Effect, ChoiceOption, ResolutionFrame)):
            for field in fields(work): visit(getattr(work, field.name))
        elif isinstance(work, (tuple, list)):
            for item in work: visit(item)
    visit(game._frame)


def register(mechanics):
    mechanics.register(GrantCounterPolicy, grant)
    mechanics.register(CheckCounterPolicy, check)
