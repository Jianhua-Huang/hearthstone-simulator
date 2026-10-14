"""R-132: accepted physical casts witnessed by spell-progress cards in hand.

Reuse hand progress and its copying rules. Entry to a new physical hand resets
this condition; an explicit current copy inherits earned card state. Plays keep
a frozen condition so later movement cannot rewrite a played/history Battlecry.
"""
from copy import deepcopy
from dataclasses import replace

from .errors import ResolutionError
from .model import HeldSpellProgress


def ability(entity):
    return next((a for a in entity.abilities if a.kind=='hand_progress' and a.hand_progress.kind=='spell_cast'),None)


def reset_entry(entity):
    a=ability(entity)
    if a is not None:
        entity.abilities[entity.abilities.index(a)]=replace(a,progress_value=0,progress_completions=0,
            progress_keys=(),progress_units=(),consumed=False)


def capture(state,entity):
    a=ability(entity)
    if a is None:return None
    return HeldSpellProgress(a.hand_progress,tuple(int(k.split(':')[1]) for k in a.progress_keys),len(state.cast_history)+1)


def note_cast(r,cast):
    """Atomic facts at payload acceptance, before this cast can acquire more cards."""
    if not cast.payload_started or cast.failure is not None:return
    from .registry import RuleContext
    from .hand_progress import advance_value
    from .lifecycle import refresh_entity
    updates=[]
    for entity_id in r.player(cast.player_id).hand:
        entity=r.state.entities[entity_id];a=ability(entity)
        if a is None or a.consumed:continue
        key=f'cast:{cast.id}'
        if key in a.progress_keys:continue
        context=RuleContext(deepcopy(r.state),entity.id,entity.controller,cast.target_id,trigger=a,cast=cast)
        eligible=r.registry.trigger_condition(a.hand_progress.condition_id)(context)
        if type(eligible) is not bool:raise ResolutionError('Held-spell condition must return bool')
        if eligible:updates.append((entity,a,advance_value(a,key)))
    for entity,a,updated in updates:
        entity.abilities[entity.abilities.index(a)]=updated
        refresh_entity(entity)
    for entity,a,updated in updates:
        r.emit('hand_progressed',target_id=entity.id,player_id=entity.controller,
            amount=updated.progress_value,progress_kind='spell_cast')


def satisfied(context):
    """Frozen hand/played-history facts; direct activation reads its real carrier.

Historical effect activations lack a recorded hand condition and are rejected.
Do not substitute the caster's hand history for a borrowed Battlecry's facts.
"""
    from .play_history import play_record
    from .battlecries import battlecry_record
    record=context.battlecry
    historical=False
    while record is not None and record.origin=='history':
        historical=True
        original=battlecry_record(context.state,record.history_id)
        if original.id>=record.id:raise ResolutionError('Cyclic held-spell Battlecry provenance')
        record=original
    play=context.play
    if record is not None:
        if record.origin=='hand':play=play_record(context.state,record.play_id)
        elif record.origin=='played_history':play=play_record(context.state,record.history_play_id)
        elif historical:raise ResolutionError('Historical effect Battlecry has no frozen held-spell facts')
        else:play=None
    if play is not None:
        if play.held_spells is None:raise ResolutionError('Played source has no held-spell condition declaration')
        return play.held_spells.completed
    entity=context.state.entities.get(context.source_id)
    a=ability(entity) if entity is not None else None
    if a is None:raise ResolutionError('Battlecry carrier has no held-spell condition declaration')
    return a.consumed


def validate_progress(state,registry,progress,play=None):
    if type(progress) is not HeldSpellProgress:raise ValueError('Invalid frozen held-spell progress')
    progress.__post_init__();registry.validate_hand_progress(progress.spec)
    if progress.before_cast_id>len(state.cast_history)+1:raise ValueError('Held-spell bound exceeds cast history')
    from .spell_casts import cast_record
    for cast_id in progress.cast_ids:
        cast=cast_record(state,cast_id)
        if not cast.payload_started or cast.failure is not None:
            raise ValueError('Held-spell witness requires accepted spell payload')
        if play is not None and (cast.turn>play.turn or cast.action>play.action):
            raise ValueError('Held-spell witness postdates its play')


def validate_ability(state,registry,a):
    if a.hand_progress.kind!='spell_cast':return
    if any(not k.startswith('cast:') for k in a.progress_keys):raise ValueError('Held-spell progress requires cast witnesses')
    progress=HeldSpellProgress(a.hand_progress,tuple(int(k[5:]) for k in a.progress_keys),len(state.cast_history)+1)
    validate_progress(state,registry,progress)
    if (a.progress_value!=len(progress.cast_ids) or a.progress_completions!=int(progress.completed)
            or a.consumed!=progress.completed):raise ValueError('Held-spell progress disagrees with witnesses')
