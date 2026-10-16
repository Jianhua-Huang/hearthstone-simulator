"""Source-independent public effects, duplicate instances and owner-turn clocks."""
from dataclasses import dataclass, replace

from .effects import Effect
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import PlayerEffect, _int, _name
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
    return dict(effect_key=spec.id, card_id=spec.card_id, effect_kind=spec.kind,
                remaining_turns=effect.remaining_turns)


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


def add(r, effect):
    player = r.player(effect.player_id)
    spec = r.registry.player_effect(effect.spec_id)
    source = r.state.entities.get(effect.source_id)
    if source is None:
        raise ResolutionError('Player effect source does not exist')
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
    instance = PlayerEffect(attachment_id(r.state), spec.id, source.id, source.card_id,
                            r.state.turn, r.state.next_order, remaining,allocation,
                            effect.player_id if allocation is not None else None)
    r.state.next_order += 1
    player.player_effects.append(instance)
    r.refresh_auras()
    r.emit('player_effect_added', source_id=source.id, player_id=player.id,
           **public_effect(r.registry, instance))


def matching(r, effect):
    return next((e for e in r.player(effect.player_id).player_effects if e.id == effect.instance_id), None)


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
                 if registry.player_effect(effect.spec_id).kind in ('turn_rule','next_spell_damage') and effect.created_turn <= turn)


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


def remove(r, effect):
    instance = matching(r, effect)
    if instance is None:
        return
    r.player(effect.player_id).player_effects.remove(instance)
    r.refresh_auras()
    r.emit('player_effect_removed', source_id=instance.source_id, player_id=effect.player_id,
           **public_effect(r.registry, instance))


def turn_countdowns(r, player, event):
    # Capture before emitting the boundary: effects added by that boundary's
    # reactions start counting at a later boundary. These guarded ticks survive
    # choices but cannot tick a replacement/new instance by accident.
    return [TickPlayerEffect(player.id, e.id, e.remaining_turns) for e in player.player_effects
            if r.registry.player_effect(e.spec_id).tick_event == event]


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
