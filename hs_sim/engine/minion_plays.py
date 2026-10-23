"""Hand minions: paid commitment, counter window, then physical entry.

The pending zone is neither a hand nor a board/graveyard. No summons, deaths,
magnetic contributions or Battlecry budgets exist until the window accepts entry.
R-116 records the provisional interaction windows requiring CN calibration.
"""
from dataclasses import dataclass, replace

from .errors import ResolutionError
from .interrupts import WindowEffect, close_window, find_window
from .model import Zone


@dataclass(frozen=True)
class MinionCounterPhase(WindowEffect):
    pass


@dataclass(frozen=True)
class ResolveMinionPlay(WindowEffect):
    pass


def counter_phase(r, effect):
    window = find_window(r.state, effect.window_id)
    if window is None or window.kind != 'minion' or window.counter_phase or r.state.action_windows[-1] != window:
        raise ResolutionError('Invalid minion counter phase')
    window = replace(window, counter_phase=True)
    r.state.action_windows[-1] = window
    if not window.countered:
        r.emit('minion_counter_check', source_id=window.source_id, target_id=window.target_id,
               player_id=window.player_id, window_id=window.id, play_id=window.play_id)
    return [ResolveMinionPlay(window.id)]


def resolve(r, effect):
    from .play_history import play_record, update_play
    window = find_window(r.state, effect.window_id)
    if window is None or window.kind != 'minion' or not window.counter_phase:
        raise ResolutionError('Invalid pending minion resolution')
    record = play_record(r.state, window.play_id)
    entity = r.state.entities[window.source_id]
    if entity.zone != Zone.PLAY or entity.controller != record.player_id or record.minion_result is not None:
        raise ResolutionError('Pending minion lost its source or already entered')
    close_window(r, window.id)
    if window.countered:
        r.move(entity, Zone.GRAVEYARD)
        update_play(r.state, record.id, minion_result='countered')
        from .rewind_outcomes import canceled_combos
        return canceled_combos(r,play_record(r.state,record.id),'countered')
    from .magnetic import host_eligible, merge
    host = r.state.entities.get(record.magnetic_target_id)
    if host is not None and host_eligible(r.state, r.registry, entity, host):
        from .summon_entry_stats import apply_paid_play
        apply_paid_play(r,record,entity)
        from .costs import install_paid_minion_keywords
        install_paid_minion_keywords(r, record, entity)
        from .adapt_memory import install_paid
        install_paid(r, record, entity)
        merge(r, entity, host, record)
        update_play(r.state, record.id, minion_result='magnetized')
        r.emit('minion_play_accepted', source_id=entity.id, target_id=host.id,
               player_id=record.player_id, play_id=record.id)
        r.emit('magnetized', source_id=entity.id, target_id=host.id, player_id=record.player_id, play_id=record.id)
        from .rewind_outcomes import canceled_combos
        return canceled_combos(r,play_record(r.state,record.id),'magnetized')
    from .disguised import play_destination
    board_player_id = play_destination(r.registry, record)
    if len(r.player(board_player_id).board) >= r.rules.max_board:
        r.move(entity, Zone.GRAVEYARD)
        update_play(r.state, record.id, minion_result='board_full')
        r.emit('minion_entry_failed', source_id=entity.id, player_id=record.player_id, play_id=record.id, reason='board_full')
        from .rewind_outcomes import canceled_combos
        return canceled_combos(r,play_record(r.state,record.id),'board_full')
    from .costs import install_paid_minion_keywords
    from .summon_entry_stats import apply_paid_play
    apply_paid_play(r,record,entity)
    install_paid_minion_keywords(r, record, entity)
    from .adapt_memory import install_paid
    install_paid(r, record, entity)
    r.move(entity, Zone.BOARD, record.position, controller_id=board_player_id)
    update_play(r.state, record.id, minion_result='summoned')
    r.refresh_auras()
    r.emit('minion_play_accepted', source_id=entity.id, target_id=entity.id,
           player_id=record.player_id, play_id=record.id)
    from .colossal import enter_minion, ColossalBattlecry
    from .summon_completions import paid_tail
    completion=paid_tail(r,record,entity)
    result = enter_minion(r, entity, 'play',play_id=record.id)
    if result:
        result.append(ColossalBattlecry(r.state.colossal_history[-1].id, record.id))
    else:
        from .lifecycle import active_abilities
        from .battlecries import capture
        from .rewind_outcomes import payload
        result.extend(payload(r, entity.id, record.player_id, record.target_id,
            tuple(a.behavior_id for a in active_abilities(entity, 'on_play')),
            play=play_record(r.state, record.id), battlecries=capture(entity)))
    return [*result,*completion]


def validate_boundary(game):
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    windows = [w for w in game._state.action_windows if w.kind == 'minion']
    expected = [(ResolveMinionPlay if w.counter_phase else MinionCounterPhase)(w.id) for w in reversed(windows)]
    actual = [w for w in queue if type(w) in (MinionCounterPhase, ResolveMinionPlay)]
    if actual != expected:
        raise ValueError('Pending minion windows and continuation markers disagree')
    from .resolver import FinishPlay
    from .combo_acceptance import FinishComboAcceptance
    from .play_history import play_record
    for window in windows:
        play=play_record(game._state,window.play_id)
        finishers=[(i,w) for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id==play.id]
        proofs=[(i,w) for i,w in enumerate(queue) if type(w) is FinishComboAcceptance and
                w.context.play.id==play.id and w.phase=='play']
        marker=(ResolveMinionPlay if window.counter_phase else MinionCounterPhase)(window.id)
        if (len(finishers)!=1 or len(proofs)!=1 or
                not queue.index(marker)<proofs[0][0]<finishers[0][0] or
                (finishers[0][1].source_id,finishers[0][1].player_id,finishers[0][1].target_id)!=(
                    play.source_id,play.player_id,play.target_id)):
            raise ValueError('Pending minion must resolve and close its submission proof before its unique completion')


def register(mechanics):
    mechanics.register(MinionCounterPhase, counter_phase)
    mechanics.register(ResolveMinionPlay, resolve)
