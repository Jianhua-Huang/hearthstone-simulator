"""Independent, captured hand-play Combo activation (provisional R-127).

The pre-play condition belongs to PlayRecord. A disabled declaration is not an
activation; repetition never means replaying the enclosing generic on_play.
"""
from dataclasses import dataclass,replace
from copy import deepcopy
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import ComboPayload,ComboRecord,CardType


def capture(entity):
    return tuple(ComboPayload(a.id,a.behavior_id,a.combo_card_id) for a in active_abilities(entity,'combo'))


def combo_record(state,record_id):
    _integer(record_id,'Combo record',1)
    if record_id>len(state.combo_history): raise ValueError('Unknown Combo activation')
    return state.combo_history[record_id-1]


def active_combo(state,source_id,player_id):
    return next((b for b in reversed(state.combo_history) if b.source_id==source_id and b.player_id==player_id
        and not b.completed and not b.interrupted),None)


def activated_combos(state,player_id,*,completed=None,turn=None,before_id=None):
    """Trusted host query; card declarations and actual Combo executions differ."""
    _player(player_id)
    if completed is not None and type(completed) is not bool: raise ValueError('Combo completion filter must be boolean')
    for value in (turn,before_id):
        if value is not None:_integer(value,'Combo history bound',1)
    return tuple(b for b in state.combo_history if b.player_id==player_id and
        (completed is None or b.completed==completed) and (turn is None or b.turn==turn) and
        (before_id is None or b.id<before_id))


@dataclass(frozen=True)
class BeginCombo(Effect):
    play_id: int
    player_id: int
    payload: ComboPayload
    batch_id: int = 1
    repeat_index: int = 1
    outcome_id: int | None = None
    iteration: int = 1

    def __post_init__(self):
        _integer(self.play_id,'Combo play',1);_player(self.player_id);_integer(self.iteration,'Combo iteration',1)
        _integer(self.batch_id,'Combo batch',1);_integer(self.repeat_index,'Combo repeat index',1)
        if type(self.payload) is not ComboPayload: raise ValueError('Expected ComboPayload')
        self.payload.__post_init__()
        if self.outcome_id is not None:_integer(self.outcome_id,'Combo outcome',1)
        elif self.iteration!=1:raise ValueError('Extra Combo iteration requires retained outcomes')


@dataclass(frozen=True)
class FinishCombo(Effect):
    record_id: int
    def __post_init__(self):_integer(self.record_id,'Combo completion',1)


def key(record):
    origin = ('generated', record.physical_child_id) if record.physical_child_id is not None else ('paid', record.batch_id)
    return (*origin, *((record.iteration,) if record.physical_child_id is not None else ()), record.payload.ability_id, record.repeat_index)


def validate_payload(state,registry,payload):
    if type(payload) is not ComboPayload:raise ValueError('Expected ComboPayload')
    payload.__post_init__();registry.behavior(payload.behavior_id)
    if payload.ability_id>=state.next_attachment_id or registry.card(payload.card_id).combo!=payload.behavior_id:
        raise ValueError('Invalid captured Combo declaration')


def validate_record(state,registry,record):
    if record.physical_child_id is not None:
        from .generated_combo_repeats import validate_record as validate_generated
        return validate_generated(state, registry, record)
    from .play_history import play_record
    record.__post_init__();play=play_record(state,record.play_id)
    from .paid_body_targets import body_target
    if record.failure is not None and (play.body_targets is None or record.target_id is None):
        raise ValueError('Failed paid Combo requires its actual independent target receipt')
    validate_payload(state,registry,record.payload)
    if (not play.combo or play.countered or play.minion_result in ('countered','board_full','magnetized') or
        record.source_id not in state.entities or record.target_id is not None and record.target_id not in state.entities or
        (record.source_id,record.card_id,record.target_id,record.turn)!=(play.source_id,play.card_id,body_target(play,record.payload,'combo'),play.turn) or
        record.player_id!=play.player_id or record.action<play.action or
        play.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO) or
        record.interrupted and state.status=='playing' or play.completed and not record.completed or
        play.interrupted and not(record.completed or record.interrupted)):
        raise ValueError('Combo activation differs from its enabled enclosing hand play')
    from .combo_repeats import batch_record
    batch=batch_record(state,record.batch_id)
    if ((record.play_id,record.player_id,record.outcome_id,record.iteration)!=(batch.play_id,batch.player_id,batch.outcome_id,batch.iteration) or
            record.payload not in batch.payloads or record.repeat_index>batch.plan.repetitions):
        raise ValueError('Combo activation differs from its batch')
    if record.outcome_id is not None:
        from .rewind_outcomes import outcome
        retained=outcome(state,record.outcome_id)
        if (retained.play_id!=record.play_id or retained.cast_id is not None or retained.power_id is not None or
            retained.player_id!=record.player_id or record.payload not in retained.combos or record.iteration>retained.total or
            record.iteration>retained.completed+int(retained.running or retained.interrupted) or
            not(record.completed or record.interrupted) and not retained.running):
            raise ValueError('Combo and retained outcome disagree')


def planned_record(state,work):
    from .play_history import play_record
    work.__post_init__();play=play_record(state,work.play_id)
    from .paid_body_targets import body_target
    return ComboRecord(len(state.combo_history)+1,play.source_id,work.player_id,play.card_id,state.turn,
        state.action_number,body_target(play,work.payload,'combo'),play.id,work.payload,work.batch_id,work.repeat_index,work.outcome_id,work.iteration)


def begin(r,work):
    record=planned_record(r.state,work);validate_record(r.state,r.registry,record)
    if any(key(b)==key(record) for b in r.state.combo_history):raise ResolutionError('Combo activation already exists')
    from .play_history import play_record
    from .paid_body_targets import available
    play = play_record(r.state, record.play_id)
    context = None
    if play.body_targets is not None and r.registry.target_visibility(r.registry.card(record.payload.card_id).target_rule) == 'player':
        from .player_target_inputs import live_factory
        source = deepcopy(r.state.entities[play.source_id]); source.controller = play.player_id
        context = live_factory(r, source)
    if not available(r.state, r.registry, play, record.payload, 'combo', context_factory=context):
        record=replace(record,failure='invalid_target')
    r.state.combo_history.append(record)
    r.emit('combo_started',source_id=record.source_id,target_id=record.target_id,player_id=record.player_id,
        combo_id=record.id,play_id=record.play_id)
    if record.failure is not None:
        r.emit('body_target_skipped', source_id=record.source_id, target_id=record.target_id,
            player_id=record.player_id, family='combo', record_id=record.id, play_id=record.play_id)
        return [FinishCombo(record.id)]
    return [r.call(record.payload.behavior_id,record.source_id,record.player_id,record.target_id,
        play=play_record(r.state,record.play_id),combo=record),FinishCombo(record.id)]


def finish(r,work):
    record=combo_record(r.state,work.record_id)
    if record.completed or record.interrupted:raise ResolutionError('Combo is already settled')
    r.state.combo_history[record.id-1]=replace(record,completed=True)
    r.emit('combo_finished',source_id=record.source_id,target_id=record.target_id,player_id=record.player_id,
        combo_id=record.id,play_id=record.play_id)


def validate_history(state,registry):
    from .combo_repeats import validate_history as validate_batches
    from .combo_modifiers import validate_receipts
    validate_receipts(state,registry);validate_batches(state,registry)
    from .combo_acceptance import validate_history as validate_acceptance_history
    validate_acceptance_history(state,registry)
    if type(state.combo_history) is not list:raise ValueError('Combo history requires a list')
    previous=(0,0);keys=set()
    for index,record in enumerate(state.combo_history,1):
        if type(record) is not ComboRecord:raise ValueError('Invalid Combo history record')
        validate_record(state,registry,record)
        if record.id!=index or key(record) in keys or not previous<=(record.turn,record.action)<=(state.turn,state.action_number):
            raise ValueError('Invalid Combo chronology or duplicate activation')
        previous=(record.turn,record.action);keys.add(key(record))


def validate_boundary(game):
    from .combo_repeats import validate_boundary as validate_batches
    validate_batches(game)
    from .resolver import FinishPlay
    from .rewind_outcomes import FinishRewindOutcome
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    pending=[b for b in game._state.combo_history if not b.completed and not b.interrupted]
    if [w.record_id for w in queue if type(w) is FinishCombo]!=[b.id for b in reversed(pending)]:
        raise ValueError('Combo progress and completion markers differ')
    def enclosing(record,position):
        if record.physical_child_id is not None:
            from .whole_card_physical import AdvancePhysicalBody, FinishPhysicalBody, child_for
            progress = child_for(game._state, record.physical_child_id).physical
            end=next((i for i,w in enumerate(queue) if type(w) is FinishPhysicalBody
                and w.proof.accepted.child_id==record.physical_child_id),None)
            advance=next((i for i,w in enumerate(queue) if type(w) is AdvancePhysicalBody
                and w.proof.accepted.child_id==record.physical_child_id),None)
            if (progress is None or progress.active_combo_id != record.id or end is None or advance is None
                    or not position < advance < end):
                raise ValueError('Generated Combo must finish before its actual physical body')
            if record.outcome_id is not None:
                closer = FinishRewindOutcome(record.outcome_id)
                if closer not in queue or not position < advance < queue.index(closer) < end:
                    raise ValueError('Generated Combo must finish inside its actual retained result')
            return
        end=next((i for i,w in enumerate(queue) if type(w) is FinishPlay and w.play_id==record.play_id),None)
        if end is None or position>=end:raise ValueError('Combo must finish before its hand play')
        if record.outcome_id is not None:
            closer=FinishRewindOutcome(record.outcome_id)
            if closer not in queue or position>=queue.index(closer):raise ValueError('Combo must precede its retained outcome')
    for record in pending:enclosing(record,queue.index(FinishCombo(record.id)))
    keys={key(b) for b in game._state.combo_history}
    from .generated_combo_repeats import BeginGeneratedCombo
    if any(type(w) is BeginGeneratedCombo for w in queue):
        raise ValueError('Generated Combo starts are owned by the actual physical advance')
    for index,work in enumerate(queue):
        if type(work) is not BeginCombo:continue
        record=planned_record(game._state,work);validate_record(game._state,game.registry,record)
        if key(record) in keys:raise ValueError('Duplicate queued Combo activation')
        keys.add(key(record));enclosing(record,index)


def register(mechanics):
    from .combo_repeats import register as register_repeats
    register_repeats(mechanics)
    from .combo_acceptance import register as register_acceptance
    register_acceptance(mechanics)
    from .generated_combo_repeats import register as register_generated
    register_generated(mechanics)
    mechanics.register(BeginCombo,begin);mechanics.register(FinishCombo,finish)
