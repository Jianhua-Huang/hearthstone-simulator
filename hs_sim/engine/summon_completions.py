"""Original after-summon windows, after a played/generated body's payloads."""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .effects import Effect, _integer
from .model import BoardPresenceReference, CardType, Zone

AFTER = 'minion_summon_finished'
CLOSED = 'minion_summon_completion_closed'


def enabled(r):
    value = getattr(r, '_summon_completion_enabled', None)
    if value is None:
        value = any(t.event == AFTER for p in r.registry.player_effects.values() for t in p.triggers)
        r._summon_completion_enabled = value
    return value


@dataclass(frozen=True)
class CompleteMinionSummon(Effect):
    minion: SourceAllocationFact
    origin: str
    origin_id: int

    def __post_init__(self):
        if type(self.minion) is not SourceAllocationFact:
            raise ValueError('Summon completion requires its original physical entry')
        self.minion.__post_init__(); _integer(self.origin_id, 'summon completion origin', 1)
        if (self.minion.kind != CardType.MINION or self.minion.zone != Zone.BOARD or
                self.origin not in ('summon', 'play', 'physical')):
            raise ValueError('Unknown original summon completion origin')

    def validate_in_state(self, state):
        self.__post_init__(); fact = self.minion
        if (fact.entity_id not in state.entities or fact.next_entity_id > state.next_entity_id or
                fact.next_order > state.next_order or fact.zone_epoch > state.entities[fact.entity_id].zone_epoch):
            raise ValueError('Summon completion borrowed a future physical entry')
        if self.origin == 'summon':
            if not 1 <= self.origin_id <= len(state.successful_summon_history):
                raise ValueError('Unknown original successful summon')
            if state.successful_summon_history[self.origin_id-1].minion != fact:
                raise ValueError('Summon completion substituted its successful entry')
        elif self.origin == 'play':
            from .play_history import play_record
            play = play_record(state, self.origin_id)
            if (play.source_id, play.kind, play.minion_result) != (fact.entity_id, CardType.MINION, 'summoned'):
                raise ValueError('Summon completion substituted its original paid minion')
        else:
            from .whole_card_physical import child_for
            child = child_for(state, self.origin_id); progress = child.physical
            if progress is None or progress.kind != CardType.MINION or progress.phase != 'completed' or progress.source != fact:
                raise ValueError('Summon completion precedes its complete generated body')


def key(request):
    return request.origin, request.origin_id, request.minion.entity_id, request.minion.entered_order


def physical_primary_pending(r, entity):
    from .replay_entry_material import PhysicalReplayEntryMaterial
    for root in reversed(r.state.card_summon_history):
        primary=root.deliveries[0].entity if root.deliveries else None
        if (root.selected is None or type(root.request.materials[root.selected]) is not PhysicalReplayEntryMaterial or
                primary is None or (primary.entity_id,primary.zone_epoch,primary.entered_order)!=
                    (entity.id,entity.zone_epoch,entity.entered_order)):
            continue
        # Quantity extras have no on-play/Battlecry body; only the first
        # actual delivery waits for the generated physical activation.
        material = root.request.materials[root.selected]
        progress = r.state.whole_card_replay_ledger.children[material.child_id-1].physical
        return progress is not None and progress.phase != 'completed'
    return False


def announced(r, entity, event):
    if not enabled(r) or physical_primary_pending(r, entity): return
    row = next((s for s in reversed(r.state.successful_summon_history) if s.event_sequence == event.sequence), None)
    if row is None: raise ValueError('After-summon window lost its original publication')
    r._captured.append(CompleteMinionSummon(row.minion, 'summon', row.id))


def paid_tail(r, play, entity):
    return (CompleteMinionSummon(SourceAllocationFact.capture(r.state,entity),'play',play.id),) if enabled(r) else ()


def physical_tail(r, progress):
    return (CompleteMinionSummon(progress.source,'physical',progress.child_id),) if (
        enabled(r) and progress.kind == CardType.MINION and progress.source is not None) else ()


def complete(r, request):
    request.validate_in_state(r.state); validate_allocation(r.state,r.registry,request.minion)
    from .hero_health_history import effective_events
    identity = key(request)
    if any(e.kind == CLOSED and dict(e.data).get('completion') == identity for e in effective_events(r.game._events)):
        raise ValueError('Original summon completion was already closed')
    if request.origin == 'play':
        from .play_history import play_record
        if play_record(r.state,request.origin_id).completed:
            raise ValueError('After-summon window must precede the original play completion')
    from .board_presence import resolve_board_presence
    entity = resolve_board_presence(r.state,BoardPresenceReference(request.minion.entity_id,request.minion.entered_order))
    live = entity is not None and entity.active and entity.health > 0 and not entity.doomed
    r.emit(CLOSED,source_id=request.minion.entity_id,player_id=request.minion.controller,
        completion=identity,minion=request.minion.payload(),live=live,_capture=False)
    if live:
        r.emit(AFTER,source_id=entity.id,target_id=entity.id,player_id=request.minion.controller,
            _summon_completion=identity,_summon_birth=request.minion.payload())


def original_receiver(context):
    if context.event is None or context.event.kind != AFTER:
        raise ValueError('After-summon consumer requires its actual completion event')
    fact = allocation_from_payload(dict(context.event.data)['_summon_birth'])
    from .board_presence import resolve_board_presence
    entity = resolve_board_presence(context.state,BoardPresenceReference(fact.entity_id,fact.entered_order))
    if (entity is None or not entity.active or entity.health <= 0 or entity.doomed or
            entity.controller != context.player_id or context.event.player_id != context.player_id): return None
    if context.player_effect is not None and context.player_effect.entered_order >= fact.entered_order:
        return None
    return entity


def validate_boundary(game):
    from .hero_health_history import effective_events
    closed = {}; notifications = set()
    for event in effective_events(game._events):
        data = dict(event.data)
        if event.kind == CLOSED:
            fact = allocation_from_payload(data['minion']); identity = data['completion']
            request = CompleteMinionSummon(fact,identity[0],identity[1]); request.validate_in_state(game._state)
            if (identity != key(request) or identity in closed or type(data['live'])is not bool or
                    (event.source_id,event.player_id)!=(fact.entity_id,fact.controller)):
                raise ValueError('Summon completion lost its unique original closure')
            closed[identity]=(data['live'],event.sequence,fact)
        elif event.kind == AFTER:
            identity=data['_summon_completion']; fact=allocation_from_payload(data['_summon_birth'])
            if (identity not in closed or not closed[identity][0] or identity in notifications or
                    closed[identity][1]>=event.sequence or closed[identity][2]!=fact or
                    (event.source_id,event.target_id,event.player_id)!=(fact.entity_id,fact.entity_id,fact.controller)):
                raise ValueError('After-summon notification lost its actual original completion')
            notifications.add(identity)
    if notifications != {k for k,v in closed.items()if v[0]}:
        raise ValueError('Summon completion lost its after-summon notification')
    frame=game._frame
    if frame is None:return
    queue=(*frame.prefix,*frame.continuation); pending=set()
    for index,work in enumerate(queue):
        if type(work)is not CompleteMinionSummon:continue
        work.validate_in_state(game._state); identity=key(work)
        if identity in pending or identity in closed:raise ValueError('Duplicate queued summon completion')
        pending.add(identity)
        if work.origin=='play':
            from .resolver import FinishPlay
            closer=next((i for i,w in enumerate(queue)if type(w)is FinishPlay and w.play_id==work.origin_id),None)
            if closer is None or closer<=index or any(type(w).__name__ not in (
                    'FinishComboAcceptance','FinishBattlecryAcceptance')for w in queue[index+1:closer]):
                raise ValueError('After-summon marker precedes unfinished original minion bodies')
    if any(t.event==AFTER for p in game.registry.player_effects.values()for t in p.triggers):
        from .resolver import FinishPlay
        from .play_history import play_record
        for work in queue:
            if type(work)is not FinishPlay:continue
            play=play_record(game._state,work.play_id)
            if play.kind!=CardType.MINION or play.minion_result!='summoned' or play.completed:continue
            windows=sum(identity[:2]==('play',play.id)for identity in (*pending,*closed))
            if windows!=1:raise ValueError('Pending minion lost its original after-summon completion')
    from .summon_quantities import walk_work
    if any(type(w)is CompleteMinionSummon for w in walk_work(frame.options)):
        raise ValueError('A choice cannot invent an internal summon completion')


def register(mechanics):mechanics.register(CompleteMinionSummon,complete)
