"""A finite held-card condition sharing the original Corrupt price comparison.

The source has no Corrupt keyword or upgraded face. Actual completed hand plays
provide witnesses; a cast/history keeps its original condition independently of
later movement of the physical source. Current copies inherit earned witnesses.
"""
from dataclasses import replace

from .model import HandProgressCandidate, HeldHigherCostProgress, higher_cost_witness


def ability(entity):
    return next((a for a in entity.abilities if a.kind == 'hand_progress' and
                 a.hand_progress.kind == 'higher_cost_play'), None)


def reset_entry(entity):
    a = ability(entity)
    if a is not None:
        entity.abilities[entity.abilities.index(a)] = replace(a, progress_value=0,
            progress_completions=0, progress_keys=(), progress_units=(), consumed=False)


def capture(state, entity):
    a = ability(entity)
    return None if a is None else HeldHigherCostProgress(a.hand_progress, a.progress_keys,
                                                        len(state.play_history)+1)


def validate_progress(state, registry, progress):
    if type(progress) is not HeldHigherCostProgress:
        raise ValueError('Expected original held higher-cost facts')
    progress.__post_init__()
    registry.validate_hand_progress(progress.spec)
    if progress.before_play_id > len(state.play_history)+1:
        raise ValueError('Higher-cost condition exceeds actual hand-play history')
    from .play_history import play_record
    for key in progress.keys:
        play_id, source_id, ability_id, player_id = higher_cost_witness(key)
        play = play_record(state, play_id)
        if (not play.completed or
                HandProgressCandidate(source_id, ability_id, player_id) not in play.corrupt_candidates):
            raise ValueError('Higher-cost condition lost its exact completed comparison witness')


def validate_ability(state, registry, a):
    if a.hand_progress.kind != 'higher_cost_play': return
    progress = HeldHigherCostProgress(a.hand_progress, a.progress_keys, len(state.play_history)+1)
    validate_progress(state, registry, progress)
    if (a.progress_value != len(progress.keys) or a.progress_units != (1,)*len(progress.keys) or
            a.progress_completions != int(progress.completed) or a.consumed != progress.completed):
        raise ValueError('Higher-cost condition differs from its original comparison witness')


def validate_play(state, registry, play):
    spec = registry.card(play.card_id).hand_progress
    required = spec is not None and spec.kind == 'higher_cost_play'
    progress = play.held_higher_cost
    if required != (progress is not None):
        raise ValueError('Hand play lost its original higher-cost declaration')
    if progress is not None:
        validate_progress(state, registry, progress)
        if progress.spec != spec or progress.before_play_id != play.id:
            raise ValueError('Higher-cost condition differs from its original hand submission')


def validate_cast(state, registry, cast):
    spec = registry.card(cast.card_id).hand_progress
    required = spec is not None and spec.kind == 'higher_cost_play'
    progress = cast.held_higher_cost
    if required != (progress is not None):
        raise ValueError('Spell cast lost its original higher-cost condition')
    if progress is not None:
        validate_progress(state, registry, progress)
        if progress.spec != spec:
            raise ValueError('Higher-cost spell borrowed another declaration')
        if cast.play_id is not None and progress != state.play_history[cast.play_id-1].held_higher_cost:
            raise ValueError('Hand cast changed its original submitted higher-cost facts')


def install(state, registry, entity, progress):
    if progress is None: return
    validate_progress(state, registry, progress)
    a = ability(entity)
    if a is None or a.hand_progress != progress.spec:
        raise ValueError('Historical higher-cost condition requires its original source declaration')
    entity.abilities[entity.abilities.index(a)] = replace(a, progress_keys=progress.keys,
        progress_units=(1,)*len(progress.keys), progress_value=len(progress.keys),
        progress_completions=int(progress.completed), consumed=progress.completed)


def inherit_play(r, entity, original_state, play_id):
    from .play_history import play_record
    original = play_record(original_state, play_id)
    if original.card_id != entity.card_id:
        raise ValueError('Higher-cost history borrowed a different hand occurrence')
    install(r.state, r.registry, entity, original.held_higher_cost)


def satisfied(context):
    from .errors import ResolutionError
    if context.cast is None or context.cast.source_id != context.source_id:
        raise ResolutionError('Higher-cost spell requires its actual frozen cast condition')
    progress = context.cast.held_higher_cost
    if progress is None:
        raise ResolutionError('Higher-cost spell lost its original frozen facts')
    return progress.completed
