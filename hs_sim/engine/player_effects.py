"""Source-independent public effects, duplicate instances and owner-turn clocks."""
from dataclasses import dataclass, replace

from .effects import AddCostModifier, Effect
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import CardType, CostModifier, CostSpec, PlayerEffect, _int, _name
from .secrets import area_count


def timed_count(player, registry):
    return sum(registry.player_effect(e.spec_id).duration is not None for e in player.player_effects)


def activation_error(state, registry, rules, player_id, card_id):
    if (registry.card(card_id).ongoing_effect_id is not None and
            (timed_count(state.players[player_id], registry) >= rules.max_ongoing_effects or
             area_count(state.players[player_id], registry) >= rules.max_secret_zone)):
        return 'Ongoing effect area is full'
    return None


def public_effect(registry, effect):
    spec = registry.player_effect(effect.spec_id)
    # No global attachment IDs or original hidden entity identities in this DTO.
    result = dict(effect_key=spec.id, card_id=spec.card_id, effect_kind=spec.kind,
                  remaining_turns=effect.remaining_turns)
    if effect.adaptations:
        result['adaptations'] = list(effect.adaptations)
    return result


@dataclass(frozen=True)
class AddPlayerEffect(Effect):
    player_id: int
    spec_id: str
    source_id: int
    capture_health_source: bool = False

    def __post_init__(self):
        _int(self.player_id, 'player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid player')
        _name(self.spec_id, 'player effect specification')
        _int(self.source_id, 'player effect source', 1)
        if type(self.capture_health_source) is not bool:
            raise ValueError('Player effect health source capture must be boolean')


@dataclass(frozen=True)
class RemovePlayerEffect(Effect):
    player_id: int
    instance_id: int

    def __post_init__(self):
        _int(self.player_id, 'player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid player')
        _int(self.instance_id, 'player effect instance', 1)


@dataclass(frozen=True)
class TickPlayerEffect(RemovePlayerEffect):
    expected_remaining: int

    def __post_init__(self):
        super().__post_init__()
        _int(self.expected_remaining, 'captured remaining turns', 1)


@dataclass(frozen=True)
class ConsumePlayerEffect(Effect):
    """Run the continuation only when this exact live instance is consumed."""
    player_id: int
    instance: PlayerEffect
    on_success: tuple[Effect, ...] = ()

    def __post_init__(self):
        from .effects import _player
        _player(self.player_id)
        if type(self.instance) is not PlayerEffect:
            raise ValueError('Player effect consumption requires its complete original instance')
        self.instance.__post_init__()
        if type(self.on_success) is not tuple or any(not isinstance(e, Effect) for e in self.on_success):
            raise ValueError('Player effect consumption requires immutable typed success work')


def validate_consumption(state, registry, effect):
    effect.__post_init__()
    instance = effect.instance
    registry.player_effect(instance.spec_id)
    registry.card(instance.source_card_id)
    if (instance.id >= state.next_attachment_id or instance.entered_order >= state.next_order or
            instance.created_turn > state.turn or instance.source_id not in state.entities):
        raise ValueError('Player effect consumption has an unallocated original instance')
    if instance.source_allocation is not None:
        health_source(state, registry, instance, effect.player_id)
    for player in state.players.values():
        current = next((e for e in player.player_effects if e.id == instance.id), None)
        if current is not None:
            if player.id != effect.player_id or current != instance:
                raise ValueError('Player effect consumption changed its original owner or instance')
            return current
    # A previously accepted request may outlive its instance. It must skip,
    # rather than borrowing a newer instance with the same specification.
    return None


def consume(r, effect, *, pending_events=None):
    try:
        current = validate_consumption(r.state, r.registry, effect)
    except ValueError as exc:
        raise ResolutionError(str(exc)) from exc
    if current is None:
        return ()
    if pending_events is not None and (r.registry.player_effect(current.spec_id).kind != 'next_healing_damage' or
                                      effect.on_success):
        raise ResolutionError('Atomic health consumption only accepts its finite conversion with no separate payload')
    # Removal is committed before its event can capture reentrant callbacks.
    # Ordinary RemovePlayerEffect and countdown/expiry semantics stay intact.
    event = remove(r, RemovePlayerEffect(effect.player_id, current.id), atomic=pending_events is not None)
    if pending_events is not None and event is not None:
        pending_events.append(event)
    return effect.on_success


def add(r, effect, *, adaptations=(), adaptation_source=None):
    player = r.player(effect.player_id)
    spec = r.registry.player_effect(effect.spec_id)
    source = r.state.entities.get(effect.source_id)
    if source is None:
        raise ResolutionError('Player effect source does not exist')
    if spec.kind == 'next_healing_damage' and (source.card_id != spec.card_id or effect.capture_health_source):
        raise ResolutionError('Next-healing program requires its own original card and no independent damage source')
    if spec.kind == 'adaptations':
        from .allocation_facts import SourceAllocationFact, validate_allocation
        from .model import validate_adaptations
        validate_adaptations(adaptations)
        if (type(adaptation_source) is not SourceAllocationFact or
                adaptation_source.entity_id != effect.source_id or adaptation_source.kind != CardType.MINION or
                effect.capture_health_source):
            raise ResolutionError('Adaptations require their original physical Battlecry source')
        validate_allocation(r.state, r.registry, adaptation_source)
    elif adaptations or adaptation_source is not None:
        raise ResolutionError('Only an Adaptation program may carry selected Adaptations')
    if spec.kind == 'aura' and (source.card_id != spec.card_id or
            source.kind != CardType.SPELL or source.controller != player.id):
        raise ResolutionError('Native Aura requires its own actual controlled spell source')
    if spec.duration is not None and (timed_count(player, r.registry) >= r.rules.max_ongoing_effects or
                                     area_count(player, r.registry) >= r.rules.max_secret_zone):
        r.emit('player_effect_failed', source_id=effect.source_id, player_id=effect.player_id,
               reason='ongoing_area_full', effect_key=spec.id)
        return
    from .allocation_facts import SourceAllocationFact
    allocation=SourceAllocationFact.capture(r.state,source).payload() if effect.capture_health_source else None
    remaining = spec.duration
    if spec.next_turn_end:
        # The end event captures countdowns before its reactions. An instance
        # installed by those reactions cannot consume that already captured end.
        remaining = 2 if player.id == r.state.active_player and not r.ending_turn else 1
    instance_id = attachment_id(r.state)
    modifier_id = r.state.next_attachment_id if spec.opponent_spell_cost else None
    instance = PlayerEffect(instance_id, spec.id, source.id,
                            adaptation_source.card_id if adaptation_source is not None else source.card_id,
                            r.state.turn, r.state.next_order, remaining,allocation,
                            effect.player_id if allocation is not None else None, modifier_id, adaptations)
    r.state.next_order += 1
    player.player_effects.append(instance)
    if modifier_id is not None:
        from .costs import modify_cost
        modify_cost(r, AddCostModifier(3-player.id,
            CostSpec(delta=spec.opponent_spell_cost, card_types=(CardType.SPELL,)), source_id=source.id),
            player_effect_id=instance.id)
        validate_cost_binding(r.state, r.registry, player.id, instance)
    r.refresh_auras()
    r.emit('player_effect_added', source_id=source.id, player_id=player.id,
           **public_effect(r.registry, instance))


def matching(r, effect):
    return next((e for e in r.player(effect.player_id).player_effects if e.id == effect.instance_id), None)


def validate_cost_binding(state, registry, player_id, instance):
    """Each active logical Aura owns precisely its ordinary, nonconsuming tax."""
    spec = registry.player_effect(instance.spec_id)
    if spec.kind == 'aura' and instance.source_card_id != spec.card_id:
        raise ValueError('Aura instance changed its original card face')
    if not spec.opponent_spell_cost:
        if instance.cost_modifier_id is not None:
            raise ValueError('Player effect invented an Aura cost contribution')
        return
    if instance.cost_modifier_id is None:
        raise ValueError('Aura lost its original cost contribution')
    modifiers = state.players[3-player_id].cost_modifiers
    rows = [m for m in modifiers if type(m) is CostModifier and m.id == instance.cost_modifier_id]
    expected = CostModifier(instance.cost_modifier_id,
        CostSpec(delta=spec.opponent_spell_cost, card_types=(CardType.SPELL,)), instance.source_id,
        player_effect_id=instance.id)
    if len(rows) != 1 or rows[0] != expected:
        raise ValueError('Aura cost contribution differs from its original instance')
    links = [e.cost_modifier_id for p in state.players.values() for e in p.player_effects
             if type(e) is PlayerEffect and e.cost_modifier_id is not None]
    if len(links) != len(set(links)):
        raise ValueError('Aura instances cannot share a cost contribution')


def validate_modifier_owner(state, registry, player_id, modifier):
    """Validate the reverse live link, including before the one atomic install."""
    rows = [e for e in state.players[3-player_id].player_effects
            if e.id == modifier.player_effect_id]
    if len(rows) != 1:
        raise ValueError('Aura cost modifier has no original live owner')
    instance = rows[0]
    spec = registry.player_effect(instance.spec_id)
    if spec.kind != 'aura' or not spec.opponent_spell_cost or instance.cost_modifier_id != modifier.id:
        raise ValueError('Aura cost modifier borrowed another logical source')
    expected = CostModifier(instance.cost_modifier_id,
        CostSpec(delta=spec.opponent_spell_cost, card_types=(CardType.SPELL,)), instance.source_id,
        player_effect_id=instance.id)
    if modifier != expected:
        raise ValueError('Aura cost modifier changed its complete native source contribution')


def retire_cost_binding(r, player_id, instance):
    validate_cost_binding(r.state, r.registry, player_id, instance)
    if instance.cost_modifier_id is not None:
        player = r.player(3-player_id)
        player.cost_modifiers = [m for m in player.cost_modifiers if m.id != instance.cost_modifier_id]


def target_allowed(state, registry, player_id, card_kind, target_kind):
    """Actor rules constrain selection; they do not alter damage or target text."""
    from .model import CardType
    # The policy has no player-state dependency outside spell-to-hero selection.
    if card_kind != CardType.SPELL or target_kind != CardType.HERO:
        return True
    allowed = True
    for effect in state.players[player_id].player_effects:
        effect.__post_init__()
        spec = registry.player_effect(effect.spec_id)
        spec.__post_init__()
        if spec.kind == 'turn_rule':
            if effect.created_turn != state.turn:
                raise ValueError('Stale current-turn target rule')
            if spec.target_policy == 'spells_no_heroes' and card_kind == CardType.SPELL and target_kind == CardType.HERO:
                allowed = False
    return allowed


def manual_play_allowed(state, registry, player_id, card_kind):
    """Current actor/turn permission, checked before accepting a new paid hand root."""
    allowed = True
    for effect in state.players[player_id].player_effects:
        effect.__post_init__()
        spec = registry.player_effect(effect.spec_id)
        spec.__post_init__()
        if spec.kind == 'turn_rule':
            if effect.created_turn != state.turn:
                raise ValueError('Stale current-turn manual play rule')
            if spec.allowed_card_types and card_kind not in spec.allowed_card_types:
                allowed = False
    return allowed


def due_turn_rules(state, registry, turn):
    return tuple((player.id, effect) for player in state.players.values() for effect in player.player_effects
                 if registry.player_effect(effect.spec_id).kind in ('turn_rule','next_spell_damage','next_healing_damage') and effect.created_turn <= turn)


def expire_turn_rules(r, turn):
    rows = due_turn_rules(r.state, r.registry, turn)
    for player_id, effect in rows:
        r.player(player_id).player_effects.remove(effect)
    if rows:
        r.refresh_auras()
    for player_id, effect in rows:
        data = public_effect(r.registry, effect)
        data['remaining_turns'] = 0
        r.emit('player_effect_expired', source_id=effect.source_id, player_id=player_id,
               **data)
    return bool(rows)


def claim_next_spell_damage(r, record):
    """Move pending instances into one physical payload before publishing work."""
    rows = tuple(e for e in r.player(record.player_id).player_effects
                 if r.registry.player_effect(e.spec_id).kind == 'next_spell_damage')
    if not rows:
        return record
    if record.spell_damage_effects or not record.payload_started or record.failure is not None:
        raise ResolutionError('Next-spell effects require one newly accepted physical cast')
    if any(e.created_turn != record.turn for e in rows):
        raise ResolutionError('Stale pending next-spell effect')
    accepted = replace(record, spell_damage_effects=rows)
    r.state.cast_history[record.id-1] = accepted
    used = {e.id for e in rows}
    r.player(record.player_id).player_effects = [e for e in r.player(record.player_id).player_effects if e.id not in used]
    for effect in rows:
        data = public_effect(r.registry,effect); data['remaining_turns'] = 0
        r.emit('player_effect_expired',source_id=effect.source_id,player_id=record.player_id,**data)
    return accepted


def remove(r, effect, *, atomic=False):
    instance = matching(r, effect)
    if instance is None:
        return
    if atomic and r.registry.player_effect(instance.spec_id).kind != 'next_healing_damage':
        raise ResolutionError('Only the stat-free next-healing program has atomic batch removal')
    retire_cost_binding(r, effect.player_id, instance)
    r.player(effect.player_id).player_effects.remove(instance)
    if not atomic:
        r.refresh_auras()
    data = dict(source_id=instance.source_id, player_id=effect.player_id,
                **public_effect(r.registry, instance))
    if not atomic:
        r.emit('player_effect_removed', **data)
    else:
        # No numeric or aura contribution exists on this finite kind. Leave
        # both derived-stat refresh and reactions at the normal batch boundary.
        return 'player_effect_removed', data


def turn_countdowns(r, player, event):
    # Capture before emitting the boundary: effects added by that boundary's
    # reactions start counting at a later boundary. These guarded ticks survive
    # choices but cannot tick a replacement/new instance by accident.
    rows = [(owner.id, e) for owner in r.state.players.values() for e in owner.player_effects
            if (spec := r.registry.player_effect(e.spec_id)).tick_event == event and
            (owner.id if spec.tick_player == 'controller' else 3-owner.id) == player.id]
    return [TickPlayerEffect(owner_id, e.id, e.remaining_turns)
            for owner_id, e in sorted(rows, key=lambda row: row[1].entered_order)]


def tick(r, effect):
    instance = matching(r, effect)
    if instance is None or instance.remaining_turns != effect.expected_remaining:
        return
    spec = r.registry.player_effect(instance.spec_id)
    remaining = instance.remaining_turns - 1
    player = r.player(effect.player_id)
    if remaining:
        updated = replace(instance, remaining_turns=remaining)
        player.player_effects[player.player_effects.index(instance)] = updated
        r.emit('player_effect_ticked', source_id=instance.source_id, player_id=player.id,
               **public_effect(r.registry, updated))
    else:
        # Expiry frees the slot before reactions and the optional payload.
        retire_cost_binding(r, effect.player_id, instance)
        player.player_effects.remove(instance)
        r.refresh_auras()
        data = public_effect(r.registry, instance)
        data['remaining_turns'] = 0
        event = r.emit('player_effect_expired', source_id=instance.source_id, player_id=player.id, **data)
        if spec.on_expire is not None:
            return [r.call(spec.on_expire, instance.source_id, player.id, event=event, player_effect=instance)]


@dataclass(frozen=True)
class PlayerEffectDamage(Effect):
    """An accepted logical player source, independent of its old physical carrier."""
    player_id: int
    instance: PlayerEffect
    target_id: int
    amount: int

    def __post_init__(self):
        from .effects import _player
        _player(self.player_id);_int(self.target_id,'player damage target',1);_int(self.amount,'player damage amount',0)
        if type(self.instance) is not PlayerEffect or self.instance.source_allocation is None:
            raise ValueError('Player damage requires the complete captured player effect source')
        self.instance.__post_init__()


def health_source(state,registry,instance,player_id):
    from .effects import _player
    from .allocation_facts import allocation_from_payload,validate_allocation
    _player(player_id)
    if type(instance) is not PlayerEffect or instance.source_allocation is None:
        raise ValueError('Player health request lost its original source capture')
    instance.__post_init__();registry.player_effect(instance.spec_id)
    if instance.source_player_id!=player_id:raise ValueError('Player health source changed its original beneficiary')
    fact=allocation_from_payload(instance.source_allocation);validate_allocation(state,registry,fact)
    if instance.id>=state.next_attachment_id or instance.created_turn>state.turn:
        raise ValueError('Player health source has a future effect identity')
    for player in state.players.values():
        current=next((e for e in player.player_effects if e.id==instance.id),None)
        if current is not None and (player.id!=player_id or current!=instance):
            raise ValueError('Player health source differs from the original accepted instance')
    return fact


def player_damage(r,effect):
    from .effects import Damage
    from .resolver import settle_health_batch
    health_source(r.state,r.registry,effect.instance,effect.player_id)
    return settle_health_batch(r,(Damage(effect.target_id,effect.amount,effect.instance.source_id),),
        player_effect=effect.instance,player_effect_owner=effect.player_id)


def register_player_effects(mechanics):
    for effect, handler in ((AddPlayerEffect, add), (RemovePlayerEffect, remove), (TickPlayerEffect, tick)):
        mechanics.register(effect, handler)
    mechanics.register(PlayerEffectDamage,player_damage)
    mechanics.register(ConsumePlayerEffect, consume)
