"""Source-independent public effects, duplicate instances and owner-turn clocks."""
from dataclasses import dataclass, replace

from .effects import AddCostModifier, Effect
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, CostModifier, CostSpec, Event, HandInvestigation, PlayerEffect, Zone, _int, _name
from .allocation_facts import SourceAllocationFact
from .secrets import area_count


def spell_effect_values(state, registry, cast, base_value):
    """Quote primary value and internal effect count once for an actual CAST.

    These units stay within the same cast. They are not additional casts or
    payments; actual target queries still run for each delivered effect.
    """
    from .effects import _integer
    from .model import SpellCastRecord
    from .spell_casts import active_cast
    _integer(base_value, 'printed spell primary value', 0)
    if (type(cast) is not SpellCastRecord or not cast.payload_started or cast.completed or cast.interrupted or
            cast.failure is not None or active_cast(state, cast.source_id, cast.player_id) != cast):
        raise ResolutionError('Spell effect values require their original active CAST')
    value, count = base_value, 1
    for instance in state.players[cast.player_id].player_effects:
        for declaration in registry.player_effect(instance.spec_id).spell_effects:
            if cast.card_id in declaration.card_ids:
                value += declaration.value_add
                count += declaration.additional_effects
    return value, count


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
    from .sham_trials import public_recipe as public_trial_recipe
    trial = public_trial_recipe(spec.card_id)
    if trial is not None: result['trial_recipe'] = trial
    if effect.adaptations:
        result['adaptations'] = list(effect.adaptations)
    if effect.spell_aura_card_id is not None:
        result['cast_card_id'] = effect.spell_aura_card_id
    return result


@dataclass(frozen=True)
class AddPlayerEffect(Effect):
    player_id: int
    spec_id: str
    source_id: int
    capture_health_source: bool = False
    aura_duration_cast_id: int | None = None
    spell_aura_id: int | None = None
    aura_duration_grants: tuple[AbilityInstance, ...] = ()
    investigation: HandInvestigation | None = None
    issued_spell_set: object | None = None
    ability_event: Event | None = None
    ability_source: SourceAllocationFact | None = None

    def __post_init__(self):
        _int(self.player_id, 'player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid player')
        _name(self.spec_id, 'player effect specification')
        if self.issued_spell_set is not None:
            from .issued_spell_sets import IssuedSpellSet
            if type(self.issued_spell_set)is not IssuedSpellSet:raise ValueError('Issued spell installation requires its typed original set')
            self.issued_spell_set.__post_init__()
        if self.investigation is not None:
            if type(self.investigation) is not HandInvestigation:
                raise ValueError('Investigation requires its complete typed private material')
            self.investigation.__post_init__()
        _int(self.source_id, 'player effect source', 1)
        if type(self.capture_health_source) is not bool:
            raise ValueError('Player effect health source capture must be boolean')
        if self.aura_duration_cast_id is not None:
            _int(self.aura_duration_cast_id, 'Aura original duration cast', 1)
        if self.spell_aura_id is not None:
            _int(self.spell_aura_id, 'Aura original spell', 1)
        from .aura_duration import validate_grants
        validate_grants(self.aura_duration_grants)
        if self.aura_duration_grants and self.aura_duration_cast_id is not None:
            raise ValueError('Aura duration cannot combine cast and direct-entry proofs')
        if (self.ability_event is None) != (self.ability_source is None):
            raise ValueError('Native ability installation requires both original event and source')
        if self.ability_event is not None:
            e, source = self.ability_event, self.ability_source
            if (type(e) is not Event or type(source) is not SourceAllocationFact or
                    e.kind != 'minion_ability_started' or
                    (e.source_id,e.player_id) != (self.source_id,self.player_id) or
                    (source.entity_id,source.controller,source.kind,source.zone) !=
                    (self.source_id,self.player_id,CardType.MINION,Zone.BOARD)):
                raise ValueError('Native ability installation changed its original board source')
            source.__post_init__()
            if (self.capture_health_source or self.aura_duration_cast_id is not None or
                    self.spell_aura_id is not None or self.aura_duration_grants or
                    self.investigation is not None or self.issued_spell_set is not None):
                raise ValueError('Native ability installation cannot combine unrelated program material')


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
    if pending_events is not None and (r.registry.player_effect(current.spec_id).kind not in ('next_healing_damage', 'next_healing_damage_until_used') or
                                      effect.on_success):
        raise ResolutionError('Atomic health consumption only accepts its finite conversion with no separate payload')
    # Removal is committed before its event can capture reentrant callbacks.
    # Ordinary RemovePlayerEffect and countdown/expiry semantics stay intact.
    event = remove(r, RemovePlayerEffect(effect.player_id, current.id), atomic=pending_events is not None)
    if pending_events is not None and event is not None:
        pending_events.append(event)
    return effect.on_success


def add(r, effect, *, adaptations=(), adaptation_source=None):
    spec_for_material = r.registry.player_effect(effect.spec_id)
    from .issued_spell_sets import validate_install as validate_issued_install
    validate_issued_install(r.state,r.registry,effect)
    if spec_for_material.kind == 'hand_investigation':
        from .hand_inspection import validate_investigation
        validate_investigation(r.state, r.registry, effect.player_id, effect.investigation)
    elif effect.investigation is not None:
        raise ResolutionError('Only an investigation program may retain a private selected face')
    player = r.player(effect.player_id)
    spec = r.registry.player_effect(effect.spec_id)
    native_bonus_origin=None
    if effect.ability_event is not None and spec.kind!='next_spell_bonus':
        raise ResolutionError('Only a native next-spell bonus accepts minion ability origin')
    if spec.kind=='next_spell_bonus':
        from .next_spell_bonuses import install_origin
        native_bonus_origin=install_origin(r,spec,player.id,effect.source_id,
            effect.ability_event,effect.ability_source)
    source = r.state.entities.get(effect.source_id)
    if source is None:
        raise ResolutionError('Player effect source does not exist')
    if spec.capture_health_source and (source.kind != CardType.SPELL or source.card_id != spec.card_id
            or source.controller != player.id):
        raise ResolutionError('Captured Sigil requires its actual controlled spell source')
    if spec.kind in ('next_healing_damage', 'next_healing_damage_until_used') and (source.card_id != spec.card_id or effect.capture_health_source):
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
    if spec.stored_spell != (effect.spell_aura_id is not None):
        raise ResolutionError('Aura program requires its original stored spell material')
    if effect.aura_duration_grants:
        from .aura_duration import validate_carrier
        from .model import Zone
        validate_carrier(r.state, r.registry, source.card_id, source.kind, effect.aura_duration_grants)
        if (source.zone != Zone.GRAVEYARD or tuple(a for a in source.abilities if a.kind == 'aura_duration_bonus') !=
                effect.aura_duration_grants):
            raise ResolutionError('Direct Aura duration lost its original physical grants')
    if spec.duration is not None and (timed_count(player, r.registry) >= r.rules.max_ongoing_effects or
                                     area_count(player, r.registry) >= r.rules.max_secret_zone):
        r.emit('player_effect_failed', source_id=effect.source_id, player_id=effect.player_id,
               reason='ongoing_area_full', effect_key=spec.id)
        return
    from .allocation_facts import SourceAllocationFact
    allocation=SourceAllocationFact.capture(r.state,source).payload() if effect.capture_health_source or spec.capture_health_source else None
    from .aura_duration import duration as original_aura_duration
    remaining = original_aura_duration(r.state, r.registry, spec, source.id, player.id,
                                      effect.aura_duration_cast_id, grants=effect.aura_duration_grants)
    if spec.next_turn_end:
        # The end event captures countdowns before its reactions. An instance
        # installed by those reactions cannot consume that already captured end.
        remaining = 2 if player.id == r.state.active_player and not r.ending_turn else 1
    instance_id = attachment_id(r.state)
    modifier_id = r.state.next_attachment_id if spec.opponent_spell_cost or spec.kind=='next_spell_bonus' else None
    spell_card_id = None
    if effect.spell_aura_id is not None:
        from .spell_auras import validate_binding, memory_id
        row = validate_binding(r.state, r.registry, effect.spell_aura_id, source.card_id)
        if memory_id(source) != row.id or spec.card_id != row.aura.card_id:
            raise ResolutionError('Aura installation lost its original physical spell material')
        spell_card_id = row.card.origin.card_id
    instance = PlayerEffect(instance_id, spec.id, source.id,
                            (effect.issued_spell_set.source_card_id if effect.issued_spell_set is not None else
                             spec.card_id if spec.kind=='next_spell_bonus' else
                             adaptation_source.card_id if adaptation_source is not None else source.card_id),
                            r.state.turn, r.state.next_order, remaining,allocation,
                            effect.player_id if allocation is not None else None, modifier_id, adaptations,
                            effect.aura_duration_cast_id, effect.spell_aura_id, spell_card_id,
                            player.id if effect.spell_aura_id is not None else None, effect.aura_duration_grants,
                            effect.investigation,effect.issued_spell_set)
    r.state.next_order += 1
    player.player_effects.append(instance)
    if instance.issued_spell_set is not None:
        from .issued_spell_sets import note_program
        note_program(r,instance,'installed')
    from .minion_base_programs import install as install_minion_base_program
    install_minion_base_program(r,player.id,instance)
    from .named_minion_boons import install as install_named_boon
    install_named_boon(r,player.id,instance)
    from .summon_entry_stats import install as install_summon_entry_stats
    install_summon_entry_stats(r,player.id,instance)
    from .coin_replacements import install as install_coin_replacement
    install_coin_replacement(r,player.id,instance)
    if modifier_id is not None:
        from .costs import modify_cost
        modify_cost(r, AddCostModifier(player.id if spec.kind=='next_spell_bonus' else 3-player.id,
            CostSpec(delta=-spec.next_spell_cost_reduction if spec.kind=='next_spell_bonus' else spec.opponent_spell_cost, card_types=(CardType.SPELL,)), source_id=source.id),
            player_effect_id=instance.id)
        validate_cost_binding(r.state, r.registry, player.id, instance)
    if native_bonus_origin is not None:
        from .next_spell_bonuses import note_install
        note_install(r,instance,native_bonus_origin)
    r.refresh_auras()
    added = r.emit('player_effect_added', source_id=source.id, player_id=player.id,
                   **public_effect(r.registry, instance))
    from .sham_trials import note_install as note_trial_install
    note_trial_install(r, instance)
    from .next_spell_bodies import note_install as note_next_spell_body_install
    note_next_spell_body_install(r, instance)
    if instance.aura_duration_cast_id is not None:
        from .aura_duration import BIND_EVENT
        r.emit(BIND_EVENT, source_id=source.id, player_id=player.id, instance_id=instance.id,
               cast_id=instance.aura_duration_cast_id, added_event=added.sequence)
    if instance.aura_duration_grants:
        from .aura_duration import DIRECT_BIND_EVENT, grants_json
        r.emit(DIRECT_BIND_EVENT, source_id=source.id, player_id=player.id, instance_id=instance.id,
            added_event=added.sequence, grants_json=grants_json(instance.aura_duration_grants), _capture=False)


def matching(r, effect):
    return next((e for e in r.player(effect.player_id).player_effects if e.id == effect.instance_id), None)


def validate_cost_binding(state, registry, player_id, instance):
    """Each active logical Aura owns precisely its ordinary, nonconsuming tax."""
    spec = registry.player_effect(instance.spec_id)
    if spec.kind=='next_spell_bonus':
        from .next_spell_bonuses import validate_binding
        validate_binding(state,registry,player_id,instance)
        return
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
    from .next_spell_bonuses import modifier_owner
    if modifier_owner(state,registry,player_id,modifier):return
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
    if r.registry.player_effect(instance.spec_id).kind=='next_spell_bonus':
        r.player(player_id).cost_modifiers[:]=[m for m in r.player(player_id).cost_modifiers if m.id!=instance.cost_modifier_id]
        return
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
                 if registry.player_effect(effect.spec_id).kind in ('turn_rule','next_spell_damage','next_healing_damage','next_power_damage') and effect.created_turn <= turn)


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
                 if r.registry.player_effect(e.spec_id).kind in ('next_spell_damage', 'next_spell_damage_until_cast'))
    if not rows:
        return record
    if record.spell_damage_effects or not record.payload_started or record.failure is not None:
        raise ResolutionError('Next-spell effects require one newly accepted physical cast')
    if any(e.created_turn > record.turn or
           r.registry.player_effect(e.spec_id).kind == 'next_spell_damage' and e.created_turn != record.turn
           for e in rows):
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
    if atomic and r.registry.player_effect(instance.spec_id).kind not in ('next_healing_damage', 'next_healing_damage_until_used'):
        raise ResolutionError('Only the stat-free next-healing program has atomic batch removal')
    retire_cost_binding(r, effect.player_id, instance)
    r.player(effect.player_id).player_effects.remove(instance)
    from .next_spell_bodies import note_removal as note_next_spell_body_removal
    note_next_spell_body_removal(r, effect.player_id, instance)
    from .coin_replacements import note_remove as note_coin_removal
    note_coin_removal(r,effect.player_id,instance)
    if r.registry.player_effect(instance.spec_id).kind=='next_spell_bonus':
        from .next_spell_bonuses import note_removal
        note_removal(r,effect.player_id,instance)
    if instance.issued_spell_set is not None:
        from .issued_spell_sets import note_program
        note_program(r,instance,'removed')
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
        if spec.kind == 'ritual':
            from .rituals import prepare as prepare_ritual_completion
            data.update(prepare_ritual_completion(r, player.id, instance))
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
    original_target_result: tuple | None = None

    def __post_init__(self):
        from .effects import _player
        _player(self.player_id);_int(self.target_id,'player damage target',1);_int(self.amount,'player damage amount',0)
        if type(self.instance) is not PlayerEffect or self.instance.source_allocation is None:
            raise ValueError('Player damage requires the complete captured player effect source')
        self.instance.__post_init__()
        if self.original_target_result is not None:
            from .health_outcomes import result_from_payload
            original = result_from_payload(self.original_target_result)
            if original.target_id != self.target_id or original.damage_dealt <= 0:
                raise ValueError('Player damage changed its original settled target')


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


def validate_player_damage(state, registry, effect):
    effect.__post_init__()
    health_source(state, registry, effect.instance, effect.player_id)
    if effect.original_target_result is None: return None
    from .health_outcomes import result_from_payload
    original = result_from_payload(effect.original_target_result)
    if not any(row.health_result == original for row in state.damage_history):
        raise ValueError('Player damage lost its genuine original damage result')
    if original.player_origin is not None and original.player_origin.spec_id == effect.instance.spec_id:
        raise ValueError('A bounded player response cannot echo its own program family')
    return original


def player_damage(r,effect):
    from .effects import Damage
    from .resolver import settle_health_batch
    original=validate_player_damage(r.state,r.registry,effect)
    if original is not None:
        from .model import Zone
        target=r.state.entities.get(effect.target_id)
        expected_zone=Zone.HERO if original.target_kind==CardType.HERO.value else Zone.BOARD
        if target is None or (target.zone,target.kind.value,target.zone_epoch,target.entered_order)!=(
                expected_zone,original.target_kind,original.target_zone_epoch,original.target_entered_order):
            r.stale(effect,effect.target_id);return ()
    return settle_health_batch(r,(Damage(effect.target_id,effect.amount,effect.instance.source_id),),
        player_effect=effect.instance,player_effect_owner=effect.player_id)


def register_player_effects(mechanics):
    from .health_outcomes import PlayerHealthOrigin
    mechanics.register_payload_type(PlayerHealthOrigin)
    for effect, handler in ((AddPlayerEffect, add), (RemovePlayerEffect, remove), (TickPlayerEffect, tick)):
        mechanics.register(effect, handler)
    mechanics.register(PlayerEffectDamage,player_damage)
    mechanics.register(ConsumePlayerEffect, consume)
