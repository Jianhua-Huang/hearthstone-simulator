"""Recorded physical draws, spell replacement chains and after-draw continuations."""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import CastWhenDrawnSpec, DrawRecord, Keyword, Zone
from .zones import CardReference, MoveCard, reference_entity, source_exists


def draw_record(state, draw_id):
    _integer(draw_id, 'draw ID', 1)
    if draw_id > len(state.draw_history): raise ValueError('Unknown draw record')
    return state.draw_history[draw_id-1]


def drawn_cards(state, player_id, *, outcome=None, turn=None, completed=None):
    """Trusted attempt query. Opening dealing, moves and copies are not draws."""
    _player(player_id)
    if outcome is not None and outcome not in ('hand','burned','cast','fatigue'):
        raise ValueError('Unknown draw outcome filter')
    if turn is not None: _integer(turn,'draw turn',1)
    if completed is not None and type(completed) is not bool: raise ValueError('Invalid draw completion filter')
    return tuple(d for d in state.draw_history if d.player_id == player_id and
        (outcome is None or d.outcome == outcome) and (turn is None or d.turn == turn) and
        (completed is None or d.completed == completed))


def update(state, record, **changes):
    value = replace(record, **changes)
    state.draw_history[record.id-1] = value
    return value


def active_after_draw(state, source_id, player_id):
    return next((d for d in reversed(state.draw_history) if d.entity_id == source_id and
        d.player_id == player_id and d.phase == 'after_draw' and not d.interrupted), None)


@dataclass(frozen=True)
class DrawMarker(Effect):
    draw_id: int
    def __post_init__(self): _integer(self.draw_id,'draw continuation',1)


@dataclass(frozen=True)
class CastDrawnSpell(DrawMarker): pass


@dataclass(frozen=True)
class AfterDrawnSpell(DrawMarker): pass


@dataclass(frozen=True)
class ReplacementDraw(DrawMarker): pass


@dataclass(frozen=True)
class AfterReplacement(DrawMarker): pass


@dataclass(frozen=True)
class FinishDraw(DrawMarker): pass


def require_phase(r, draw_id, phase):
    record = draw_record(r.state, draw_id)
    if record.phase != phase or record.interrupted:
        raise ResolutionError('Draw continuation does not match its phase')
    return record


def draw_one(r, player_id, *, card=None, source_id=None, parent_id=None, reset=False, deck_owner_id=None, deathrattle_memory=None):
    player = r.player(player_id); source_exists(r, source_id)
    if deathrattle_memory is not None:
        from .deathrattle_memory import validate_draw_request
        validate_draw_request(r,deathrattle_memory)
        if (player_id,source_id)!=(deathrattle_memory.player_id,deathrattle_memory.reference.entity_id):
            raise ResolutionError('Remembered draw substituted its actual player or source')
    deck_owner = player if deck_owner_id is None else r.player(deck_owner_id)
    if card is not None:
        entity = reference_entity(r, card)
        if entity is None: return ()
        if entity.zone != Zone.DECK or deck_owner_id is not None and entity.controller != deck_owner.id:
            raise ResolutionError('A physical draw must select an original deck card')
    else:
        entity = r.state.entities[deck_owner.deck[0]] if deck_owner.deck else None
    spec = None; grant = None
    if entity is None: outcome = 'fatigue'
    elif len(player.hand) >= hand_capacity(player, r.rules): outcome = 'burned'
    else:
        definition = r.registry.card(entity.card_id)
        if definition.cast_when_drawn is not None and Keyword.CASTS_WHEN_DRAWN in entity.keywords:
            spec = definition.cast_when_drawn
        else:
            from .draw_cast_grants import capture as capture_grant
            grant = capture_grant(r.state, r.registry, entity)
            if grant is not None: spec = CastWhenDrawnSpec()
        outcome = 'cast' if spec is not None else 'hand'
    record = DrawRecord(len(r.state.draw_history)+1, player_id, r.state.turn, r.state.action_number,
        outcome, entity.id if entity else None, entity.card_id if entity else None,
        source_id, parent_id, spec=spec, phase='pending_cast' if spec else 'drawing', cast_grant=grant,
        observer=deathrattle_memory if outcome in ('hand','cast') else None)
    r.state.draw_history.append(record)
    if parent_id is not None:
        parent = require_phase(r,parent_id,'replacing')
        if parent.player_id != player_id or parent.replacement_id is not None:
            raise ResolutionError('Invalid replacement draw parent')
        update(r.state,parent,replacement_id=record.id)
    if entity is None:
        from .fatigue import advance
        packet, _ = advance(r, player.id, draw_id=record.id)
        return (packet, FinishDraw(record.id))
    if spec is None:
        from .zones import move_physical_card
        move_physical_card(r,MoveCard(CardReference.capture(entity),player_id,Zone.HAND,
            draw=True,reset=reset,source_id=source_id),draw_id=record.id,deathrattle_memory=deathrattle_memory)
        from .overdraw_returns import capture as capture_overdraw
        capture_overdraw(r,record)
        return (FinishDraw(record.id),)
    if reset:
        from .lifecycle import reset_to_definition
        reset_to_definition(r.state,entity,r.registry.card(entity.card_id),r.registry)
    if entity.controller == player_id:
        r.move(entity,Zone.GRAVEYARD)
    else:
        r.move(entity,Zone.GRAVEYARD,controller_id=player_id,draw_id=record.id)
    # A drawn spell is a draw, but never a successful hand acquisition.
    from .draw_cast_grants import event_data as grant_event_data
    from .draw_transformations import observer_event_data
    r.emit('card_drawn',source_id=source_id,target_id=entity.id,player_id=player_id,
           draw_id=record.id,casts_when_drawn=True,**grant_event_data(grant),**observer_event_data(record))
    return (CastDrawnSpell(record.id),AfterDrawnSpell(record.id),FinishDraw(record.id))


def note_cast(r, draw_id, cast_id):
    record = require_phase(r,draw_id,'pending_cast')
    update(r.state,record,phase='casting',cast_id=cast_id)


def cast(r, effect):
    record = require_phase(r,effect.draw_id,'pending_cast')
    if record.transformation is not None:
        update(r.state,record,phase='converted')
        return ()
    entity = r.state.entities[record.entity_id]
    if (entity.card_id,entity.controller,entity.zone) != (record.card_id,record.player_id,Zone.GRAVEYARD):
        raise ResolutionError('Drawn spell left its captured cast position')
    from .spell_casts import CastSpell, automatic
    spec = CastSpell(record.player_id,record.card_id,record.source_id,choices=record.spec.choices)
    return automatic(r,spec,entity,Zone.DECK,origin='draw',draw_id=record.id)


def after_cast(r, effect):
    record = draw_record(r.state,effect.draw_id)
    if record.transformation is not None:
        require_phase(r,record.id,'converted')
        update(r.state,record,phase='after_draw')
        return ()
    record = require_phase(r,effect.draw_id,'casting')
    from .spell_casts import cast_record
    if not cast_record(r.state,record.cast_id).completed:
        raise ResolutionError('Replacement draw cannot precede spell completion')
    if record.spec.replacement:
        update(r.state,record,phase='pending_replacement')
        return (ReplacementDraw(record.id),AfterReplacement(record.id))
    return after_draw(r,record)


def replacement(r, effect):
    record = require_phase(r,effect.draw_id,'pending_replacement')
    update(r.state,record,phase='replacing')
    return draw_one(r,record.player_id,source_id=record.entity_id,parent_id=record.id)


def after_replacement(r, effect):
    record = require_phase(r,effect.draw_id,'replacing')
    if record.replacement_id is None or not draw_record(r.state,record.replacement_id).completed:
        raise ResolutionError('After-draw callback requires a completed replacement chain')
    return after_draw(r,record)


def after_draw(r, record):
    record = update(r.state,record,phase='after_draw')
    if record.spec.after_draw is not None:
        return (r.call(record.spec.after_draw,record.entity_id,record.player_id,draw=record),)
    return ()


def finish(r, effect):
    record = draw_record(r.state,effect.draw_id)
    expected = 'after_draw' if record.outcome == 'cast' else 'drawing'
    require_phase(r,record.id,expected)
    update(r.state,record,phase='done')
    from .overdraw_returns import finish_draw as finish_overdraw
    return finish_overdraw(r,record)


def validate_declaration(state, registry, record):
    if type(record) is not DrawRecord or record.outcome != 'cast':
        raise ValueError('Expected the actual original draw-cast record')
    if record.cast_grant is not None:
        from .draw_cast_grants import validate_record as validate_granted_draw
        validate_granted_draw(state, registry, record)
    elif record.spec != registry.card(record.card_id).cast_when_drawn:
        raise ValueError('Draw cast declaration does not match its card')


def validate_history(state, registry):
    if type(state.draw_history) is not list: raise ValueError('Draw history must be a list')
    last_turn = last_action = 0
    for index,record in enumerate(state.draw_history,1):
        if type(record) is not DrawRecord: raise ValueError('Invalid draw record')
        record.__post_init__()
        if (record.id != index or not last_turn <= record.turn <= state.turn or
                not last_action <= record.action <= state.action_number or
                any(i is not None and i not in state.entities for i in (record.entity_id,record.source_id)) or
                record.interrupted and state.status == 'playing'):
            raise ValueError('Invalid draw provenance or chronology')
        if record.card_id is not None: registry.card(record.card_id)
        from .draw_transformations import validate_draw_links
        validate_draw_links(state,registry,record)
        if record.parent_id is not None:
            parent = draw_record(state,record.parent_id)
            if (parent.replacement_id != record.id or parent.outcome != 'cast' or
                    parent.player_id != record.player_id or record.source_id != parent.entity_id or
                    parent.turn > record.turn or parent.action > record.action):
                raise ValueError('Draw parent and child disagree')
        if record.outcome == 'cast':
            validate_declaration(state, registry, record)
            if record.cast_id is not None:
                from .spell_casts import cast_record
                spell = cast_record(state,record.cast_id)
                if ((spell.source_id,spell.card_id,spell.player_id,spell.draw_id,spell.origin) !=
                        (record.entity_id,record.card_id,record.player_id,record.id,'draw') or
                        spell.caster_id != record.source_id or spell.choices != record.spec.choices or
                        record.phase not in ('pending_cast','casting') and not spell.completed):
                    raise ValueError('Draw and cast history disagree')
            if record.replacement_id is not None:
                child = draw_record(state,record.replacement_id)
                if child.parent_id != record.id or record.phase in ('pending_cast','casting','pending_replacement'):
                    raise ValueError('Unexpected replacement child')
                if record.phase in ('after_draw','done') and not child.completed:
                    raise ValueError('Draw settled before its replacement')
            elif record.transformation is None and record.spec.replacement and record.phase in ('replacing','after_draw','done'):
                raise ValueError('Missing replacement draw')
        last_turn,last_action = record.turn,record.action
    for cast in state.cast_history:
        if cast.origin == 'draw' and draw_record(state,cast.draw_id).cast_id != cast.id:
            raise ValueError('Unlinked draw-cast history')


def validate_boundary(game):
    queue = (*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    pending = [d for d in reversed(game._state.draw_history) if not d.completed and not d.interrupted]
    actual = [w for w in queue if isinstance(w,DrawMarker)]
    expected = []
    for record in pending:
        if record.phase == 'pending_cast':
            expected.extend((CastDrawnSpell(record.id),AfterDrawnSpell(record.id)))
        elif record.phase == 'converted':
            expected.append(AfterDrawnSpell(record.id))
        elif record.phase == 'casting':
            expected.append(AfterDrawnSpell(record.id))
            from .spell_casts import cast_record, FinishSpellCast
            cast = cast_record(game._state,record.cast_id)
            if not cast.completed:
                closer = next(w for w in queue if type(w) is FinishSpellCast and w.cast_id == cast.id)
                if queue.index(closer) > queue.index(AfterDrawnSpell(record.id)):
                    raise ValueError('Draw replacement precedes cast completion')
        elif record.phase == 'pending_replacement':
            expected.extend((ReplacementDraw(record.id),AfterReplacement(record.id)))
        elif record.phase == 'replacing': expected.append(AfterReplacement(record.id))
        expected.append(FinishDraw(record.id))
    if actual != expected:
        raise ValueError('Draw phase and continuation markers disagree')
    from .draw_cast_grants import validate_boundary as validate_granted_boundary
    validate_granted_boundary(game)
    from .draw_transformations import validate_boundary as validate_transformations
    validate_transformations(game)


def register(mechanics):
    from .draw_transformations import register as register_transformations
    register_transformations(mechanics)
    from .draw_cast_grants import GrantedDrawCastBasis
    mechanics.register_payload_type(GrantedDrawCastBasis)
    for effect,handler in ((CastDrawnSpell,cast),(AfterDrawnSpell,after_cast),
            (ReplacementDraw,replacement),(AfterReplacement,after_replacement),(FinishDraw,finish)):
        mechanics.register(effect,handler)
