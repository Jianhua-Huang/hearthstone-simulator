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

    def __post_init__(self):
        _int(self.player_id, 'player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid player')
        _name(self.spec_id, 'player effect specification')
        _int(self.source_id, 'player effect source', 1)


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
    instance = PlayerEffect(attachment_id(r.state), spec.id, source.id, source.card_id,
                            r.state.turn, r.state.next_order, spec.duration)
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


def register_player_effects(mechanics):
    for effect, handler in ((AddPlayerEffect, add), (RemovePlayerEffect, remove), (TickPlayerEffect, tick)):
        mechanics.register(effect, handler)
