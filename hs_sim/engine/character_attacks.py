"""Original character attack windows; combat remains in the existing resolver."""
from dataclasses import fields, is_dataclass, replace
from .errors import ResolutionError
from .model import (ActionWindow, CardType, CharacterAttackCombatFact,
    CharacterAttackRecord, CharacterAttackTerminalFact, GameState, _int, _name)


def validate_record(row):
    if type(row) is not CharacterAttackRecord or type(row.declaration) is not ActionWindow:
        raise ValueError('Character attack requires its original typed declaration')
    w = row.declaration
    w.__post_init__()
    if w.kind != 'attack' or row.source_kind not in (CardType.HERO, CardType.MINION) or type(row.source_kind) is not CardType:
        raise ValueError('Character attack requires a declared character window')
    if (row.source_kind is CardType.MINION) != (w.attack_source_presence is not None):
        raise ValueError('Character attack lost its original board presence policy')
    _name(row.source_card_id, 'original attacking card')
    for name in ('source_entered_order', 'turn'):
        _int(getattr(row, name), 'character declaration ' + name, 1)
    for name in ('source_zone_epoch', 'root_action_number', 'declaration_action', 'declaration_event_cursor'):
        _int(getattr(row, name), 'character declaration ' + name, 0)
    if row.owner_turn_id is not None:
        _int(row.owner_turn_id, 'character declaration actual interval', 1)
    if row.root_action_number > row.declaration_action:
        raise ValueError('Character attack predates its root action')
    action, cursor = row.declaration_action, row.declaration_event_cursor
    if row.delivery is None:
        if row.delivery_action is not None or row.delivery_event_cursor is not None or row.combat is not None:
            raise ValueError('Character combat has no original window delivery')
    else:
        if type(row.delivery) is not ActionWindow:
            raise ValueError('Character attack delivery requires its original typed window')
        row.delivery.__post_init__()
        if replace(w, target_id=row.delivery.target_id) != row.delivery:
            raise ValueError('Character delivery changed more than the actual selected target')
        _int(row.delivery_action, 'character delivery action', action)
        _int(row.delivery_event_cursor, 'character delivery event cursor', cursor)
        action, cursor = row.delivery_action, row.delivery_event_cursor
    if row.combat is not None:
        if type(row.combat) is not CharacterAttackCombatFact:
            raise ValueError('Character attack requires typed original combat acceptance')
        row.combat.__post_init__()
        c = row.combat
        if c.action < action or c.event_cursor < cursor or c.target_id != row.delivery.target_id:
            raise ValueError('Character combat changed its original target or chronology')
        if c.source_zone_epoch < row.source_zone_epoch or c.source_entered_order < row.source_entered_order:
            raise ValueError('Character combat predates its physical declaration')
        if c.source_zone_epoch == row.source_zone_epoch and c.source_card_id != row.source_card_id:
            raise ValueError('Character combat changed a face without a physical epoch')
        if row.source_kind is CardType.MINION and c.weapon_id is not None:
            raise ValueError('A minion attack cannot borrow a hero weapon')
        action, cursor = c.action, c.event_cursor
    if row.terminal is not None:
        if type(row.terminal) is not CharacterAttackTerminalFact:
            raise ValueError('Character attack requires a typed terminal fact')
        row.terminal.__post_init__()
        if row.terminal.action < action or row.terminal.event_cursor < cursor:
            raise ValueError('Character attack terminal predates its original phase')
        if (row.terminal.status == 'completed' and row.combat is None or
                row.terminal.status == 'cancelled' and (row.delivery is None or row.combat is not None)):
            raise ValueError('Character attack terminal differs from its actual reached phase')


def record(state, window_id):
    _int(window_id, 'original character attack window', 1)
    row = next((row for row in state.character_attack_history if row.declaration.id == window_id), None)
    if row is None:
        raise ValueError('Unknown original character attack window')
    return row


def update(state, old, **values):
    new = replace(old, **values)
    state.character_attack_history[state.character_attack_history.index(old)] = new
    return new


def declare(r, window):
    source = r.state.entities[window.source_id]
    interval = r.state.owner_turn_history[-1] if r.state.owner_turn_history else None
    r.state.character_attack_history.append(CharacterAttackRecord(window, source.card_id, source.kind,
        source.zone_epoch, source.entered_order, r.state.turn, None if interval is None else interval.id,
        r.root_action_number, r.state.action_number, len(r.game._events)))


def delivery(r, window):
    old = record(r.state, window.id)
    if old.delivery is not None or old.terminal is not None:
        raise ResolutionError('Character attack window was already delivered or closed')
    update(r.state, old, delivery=window, delivery_action=r.state.action_number,
           delivery_event_cursor=len(r.game._events))
    return window.id


def window_id(combat):
    value = combat.attack_window_id
    hero = combat.hero_attack
    if hero is not None:
        original = hero.identity.window_id
        if value is not None and value != original:
            raise ResolutionError('Character combat borrowed another hero window')
        value = original
    return value


def require_link(state, combat, *, accepted=False):
    ident = window_id(combat)
    if ident is None:
        return None  # Existing bare minion damage is not a declared attack.
    old = record(state, ident)
    validate_record(old)
    if (old.delivery is None or old.terminal is not None or old.combat is not None and not accepted or
            (combat.attacker_id, combat.defender_id, combat.combat_relation) !=
            (old.delivery.source_id, old.delivery.target_id, old.delivery.combat_relation) or
            hasattr(combat, 'forced') and combat.forced != old.delivery.forced):
        raise ResolutionError('Foreign, duplicated or closed character attack reference')
    return old


def cancel(r, combat, reason):
    old = require_link(r.state, combat)
    if old is not None:
        update(r.state, old, terminal=CharacterAttackTerminalFact('cancelled', reason,
            r.state.action_number, len(r.game._events)))


def accept(r, combat):
    if combat is None:
        return
    old = require_link(r.state, combat)
    if old is None:
        return
    source, target = (r.state.entities[e] for e in (combat.attacker_id, combat.defender_id))
    update(r.state, old, combat=CharacterAttackCombatFact(source.controller, source.card_id,
        source.zone_epoch, source.entered_order, target.id, target.controller, target.card_id,
        combat.weapon_id, r.state.action_number, len(r.game._events)))


def complete(r, combat):
    old = require_link(r.state, combat, accepted=True)
    if old is not None:
        if old.combat is None or old.combat.weapon_id != combat.weapon_id:
            raise ResolutionError('Character finish lost its original combat acceptance')
        update(r.state, old, terminal=CharacterAttackTerminalFact('completed', 'intrinsic_finish',
            r.state.action_number, len(r.game._events)))


def validate_history(state, registry=None, event_limit=None):
    if type(state) is not GameState or type(state.character_attack_history) is not list:
        raise ValueError('Character attacks require the original typed history')
    previous = action = cursor = 0
    for row in state.character_attack_history:
        validate_record(row)
        w = row.declaration
        if (not previous < w.id < state.next_window_id or not action <= row.declaration_action <= state.action_number or
                row.turn > state.turn or row.source_entered_order >= state.next_order or
                row.declaration_event_cursor < cursor):
            raise ValueError('Character attack lost its ordered original allocation or clock')
        source = state.entities.get(w.source_id)
        if (source is None or w.source_id >= state.next_entity_id or w.target_id not in state.entities or
                row.source_zone_epoch > source.zone_epoch):
            raise ValueError('Character attack borrowed an unknown or future physical source')
        if source.zone_epoch == row.source_zone_epoch and (source.card_id, source.kind) != (row.source_card_id, row.source_kind):
            raise ValueError('Character attack rewrote an unchanged physical source face')
        if row.owner_turn_id is None:
            if state.opening is None or row.turn != 1:
                raise ValueError('Pre-turn character attack has no match opening origin')
        else:
            if row.owner_turn_id > len(state.owner_turn_history):
                raise ValueError('Character attack borrowed a future actual interval')
            owner = state.owner_turn_history[row.owner_turn_id-1]
            if owner.turn != row.turn or not w.forced and owner.player_id != w.player_id:
                raise ValueError('Character declaration changed its actual original interval')
        if registry is not None:
            if registry.card(row.source_card_id).kind is not row.source_kind:
                raise ValueError('Character declaration changed its original card kind')
        if row.delivery is not None and row.delivery.target_id not in state.entities:
            raise ValueError('Character delivery lost its original target')
        if row.combat is not None:
            c = row.combat
            if c.source_zone_epoch > source.zone_epoch or c.source_entered_order >= state.next_order or c.target_id not in state.entities:
                raise ValueError('Character combat borrowed future or unknown original material')
            if c.weapon_id is not None and c.weapon_id not in state.entities:
                raise ValueError('Character combat lost its original weapon')
            if registry is not None and (registry.card(c.source_card_id).kind is not row.source_kind or
                    registry.card(c.target_card_id).kind not in (CardType.HERO, CardType.MINION)):
                raise ValueError('Character combat changed its original character kinds')
        latest_action = row.terminal.action if row.terminal else row.combat.action if row.combat else row.delivery_action if row.delivery else row.declaration_action
        latest_cursor = row.terminal.event_cursor if row.terminal else row.combat.event_cursor if row.combat else row.delivery_event_cursor if row.delivery else row.declaration_event_cursor
        if latest_action > state.action_number or event_limit is not None and latest_cursor > event_limit:
            raise ValueError('Character attack contains a future original phase')
        previous, action, cursor = w.id, row.declaration_action, row.declaration_event_cursor


def validate_tails(state, work):
    from .interrupts import ResolveAttack
    from .resolver import CombatDamage
    from .effects import DamageBatch
    tails = {}
    for item in work:
        if type(item) is ResolveAttack:
            row = record(state, item.window_id)
            if row.delivery is not None or row.terminal is not None:
                raise ValueError('Character declaration lost its original control phase')
            tails.setdefault(item.window_id, []).append('declared')
        elif type(item) is CombatDamage or type(item) is DamageBatch and item.combat is not None:
            combat = item if type(item) is CombatDamage else item.combat
            row = require_link(state, combat)
            if row is not None:
                tails.setdefault(row.declaration.id, []).append('delivery_pending')
    for row in state.character_attack_history:
        expected = [] if row.terminal else ['declared' if row.delivery is None else 'delivery_pending']
        if row.combat is not None and row.terminal is None or tails.get(row.declaration.id, []) != expected:
            raise ValueError('Character attack lost its unique original control tail')
        windows = [w for w in state.action_windows if w.id == row.declaration.id]
        if bool(windows) != (row.delivery is None and row.terminal is None):
            raise ValueError('Character attack original window lifecycle mismatch')
        if windows and replace(row.declaration, target_id=windows[0].target_id) != windows[0]:
            raise ValueError('Character window changed its original source or policy')


def validate_boundary(game):
    validate_history(game._state, game.registry, len(game._events))
    from .hero_health_history import effective_events
    effective = effective_events(game._events)
    declared = [dict(event.data).get('window_id') for event in effective if event.kind == 'attack_declared']
    if any(type(ident) is not int for ident in declared) or declared != [row.declaration.id for row in game._state.character_attack_history]:
        raise ValueError('Character history lost a complete original declaration')
    for row in game._state.character_attack_history:
        w = row.declaration
        event = next((e for e in effective if e.sequence == row.declaration_event_cursor+1), None)
        if (event is None or event.kind != 'attack_declared' or
                (event.source_id, event.target_id, event.player_id) != (w.source_id, w.target_id, w.player_id) or
                event.action != row.declaration_action or dict(event.data).get('window_id') != w.id or
                type(dict(event.data).get('forced', False)) is not bool or dict(event.data).get('forced', False) != w.forced):
            raise ValueError('Character attack lost its original declaration event')
        if row.terminal is not None and row.terminal.status != 'interrupted':
            event = next((e for e in effective if e.sequence == row.terminal.event_cursor+1), None)
            kind = 'attack_finished' if row.terminal.status == 'completed' else 'attack_cancelled'
            if (event is None or event.kind != kind or
                    (event.source_id, event.target_id, event.action) != (w.source_id, row.delivery.target_id, row.terminal.action)):
                raise ValueError('Character attack lost its original terminal event')
    frame = game._frame
    work = () if frame is None else (*frame.prefix, *frame.continuation)
    validate_tails(game._state, work)
    if frame is None:
        return
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .interrupts import ResolveAttack
    from .resolver import CombatDamage
    from .effects import DamageBatch
    def walk(value, state, control_tail=False):
        if type(value) is GameState:
            validate_history(value, game.registry, len(game._events))
            return
        if type(value) is PaidHandChoiceBoundaryProof:
            validate_history(value.state, game.registry, value.event.sequence)
            validate_tails(value.state, value.work)
            for item in value.work:
                walk(item, value.state, True)
            return
        if type(value) is RuleContext:
            state = value.state
        if not control_tail and (type(value) is ResolveAttack or
                type(value) is CombatDamage and window_id(value) is not None or
                type(value) is DamageBatch and value.combat is not None and window_id(value.combat) is not None):
            raise ValueError('Character attack control tails cannot be offered or nested')
        if is_dataclass(value):
            for field in fields(value):
                walk(getattr(value, field.name), state)
        elif type(value) in (tuple, list):
            for item in value:
                walk(item, state)
    for item in work:
        walk(item, game._state, True)
    for field in fields(frame):
        if field.name not in ('prefix', 'continuation'):
            walk(getattr(frame, field.name), game._state)


def interrupt(r, queue):
    validate_tails(r.state, tuple(queue))
    for row in tuple(r.state.character_attack_history):
        if row.terminal is None:
            update(r.state, row, terminal=CharacterAttackTerminalFact('interrupted', 'game_terminal',
                r.state.action_number, len(r.game._events)))


def character_attacks(state, player_id, *, phase='completed', turn=None, forced=None, before_window_id=None):
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Character attack query requires an actual original player')
    if type(phase) is not str or phase not in ('declared', 'combat_accepted', 'completed', 'cancelled', 'interrupted'):
        raise ValueError('Unsupported character attack query phase')
    for name, value in (('turn', turn), ('before window', before_window_id)):
        if value is not None:
            _int(value, 'character attack query ' + name, 1)
    if forced is not None and type(forced) is not bool:
        raise ValueError('Character attack origin selector requires bool or None')
    validate_history(state)
    return tuple(row for row in state.character_attack_history
        if row.declaration.player_id == player_id and
        (turn is None or row.turn == turn) and (forced is None or row.declaration.forced == forced) and
        (before_window_id is None or row.declaration.id < before_window_id) and
        (phase == 'declared' or phase == 'combat_accepted' and row.combat is not None or
         row.terminal is not None and row.terminal.status == phase))


def character_attack_count(state, player_id, **scope):
    return len(character_attacks(state, player_id, **scope))


def record_from_dict(value):
    from .serialization import _list, _row
    from .model import BoardPresenceReference, TriggerCandidate
    def window(raw):
        fields = _row(raw, ActionWindow)
        if fields['attack_source_presence'] is not None:
            fields['attack_source_presence'] = BoardPresenceReference(**_row(fields['attack_source_presence'], BoardPresenceReference))
        fields['spellburst_candidates'] = tuple(TriggerCandidate(**_row(item, TriggerCandidate))
            for item in _list(fields['spellburst_candidates'], 'original attack Spellburst candidates'))
        return ActionWindow(**fields)
    row = _row(value, CharacterAttackRecord)
    row['declaration'] = window(row['declaration'])
    row['source_kind'] = CardType(row['source_kind'])
    if row['delivery'] is not None:
        row['delivery'] = window(row['delivery'])
    if row['combat'] is not None:
        row['combat'] = CharacterAttackCombatFact(**_row(row['combat'], CharacterAttackCombatFact))
    if row['terminal'] is not None:
        row['terminal'] = CharacterAttackTerminalFact(**_row(row['terminal'], CharacterAttackTerminalFact))
    return CharacterAttackRecord(**row)
