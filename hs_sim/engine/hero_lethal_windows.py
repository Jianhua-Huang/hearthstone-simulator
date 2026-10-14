"""Local Hero fatal episodes over the ordinary Deathrattle interpreter.

Board facts/corpses precede Hero payloads. Ordinary reactions and pre-existing
continuations remain in the real queue after one outer marker. This profile is
not a claim about China-server timing or unsigned snapshot authentication.
"""
from dataclasses import dataclass,fields,is_dataclass,replace
from collections import deque
from .effects import Effect,_integer,_player
from .model import CardType,DeathRecord,GameState,Zone,_name

PROFILE='board_death_facts_then_hero_payloads_then_terminal'
RECOVERY='keep_max_require_fits'

@dataclass(frozen=True)
class HeroLethalReference:
    root_id:int
    episode_id:int
    player_id:int
    hero_id:int
    card_id:str
    zone_epoch:int
    death_id:int
    def __post_init__(self):
        for n in ('root_id','episode_id','hero_id','death_id'):_integer(getattr(self,n),n,1)
        _integer(self.zone_epoch,'fatal Hero epoch',0);_player(self.player_id);_name(self.card_id,'fatal Hero face')
        if self.root_id>=self.episode_id:raise ValueError('Hero episode must follow its coordinating root')
    def payload(self):return tuple((f.name,getattr(self,f.name)) for f in fields(self))

@dataclass(frozen=True)
class HeroLethalEpisode:
    reference:HeroLethalReference
    parent_id:int|None
    action:int
    turn:int
    group_id:int|None=None
    phase:str='queued'
    recovered:bool=False
    def __post_init__(self):
        if type(self.reference) is not HeroLethalReference:raise ValueError('Hero episode requires its exact physical reference')
        self.reference.__post_init__();_integer(self.action,'Hero fatal action',0);_integer(self.turn,'Hero fatal turn',1)
        for n in ('parent_id','group_id'):
            if getattr(self,n) is not None:_integer(getattr(self,n),n,1)
        if self.parent_id is not None and self.parent_id>=self.reference.episode_id:raise ValueError('Hero parent must precede its child')
        if self.phase not in ('queued','running','finished') or type(self.recovered) is not bool:raise ValueError('Unknown Hero fatal progress')

@dataclass(frozen=True)
class HeroLethalRoot:
    id:int
    action:int
    turn:int
    simultaneous:tuple[HeroLethalReference,...]
    episode_ids:tuple[int,...]
    stack:tuple[int,...]=()
    initial_parked_hashes:tuple[str,...]=()
    parked_hashes:tuple[str,...]=()
    initialized:bool=False
    completed:bool=False
    profile:str=PROFILE
    interrupted_action:int|None=None
    interrupted_event:int|None=None
    def __post_init__(self):
        _integer(self.id,'Hero root',1);_integer(self.action,'Hero root action',0);_integer(self.turn,'Hero root turn',1)
        if type(self.simultaneous) is not tuple or not 1<=len(self.simultaneous)<=2 or any(type(x) is not HeroLethalReference for x in self.simultaneous):raise ValueError('Hero root requires its complete original simultaneous set')
        if len({x.player_id for x in self.simultaneous})!=len(self.simultaneous) or any(x.root_id!=self.id for x in self.simultaneous):raise ValueError('Hero simultaneous identities differ from their root')
        for n in ('episode_ids','stack'):
            value=getattr(self,n)
            if type(value) is not tuple or any(type(x) is not int or x<=self.id for x in value) or len(set(value))!=len(value):raise ValueError('Hero root has invalid episode/stack identities')
        if self.episode_ids[:len(self.simultaneous)]!=tuple(x.episode_id for x in self.simultaneous) or any(x not in self.episode_ids for x in self.stack):raise ValueError('Hero root lost original or running episodes')
        for n in ('initial_parked_hashes','parked_hashes'):
            if type(getattr(self,n)) is not tuple or any(type(x) is not str or len(x)!=64 or any(c not in '0123456789abcdef' for c in x) for x in getattr(self,n)):raise ValueError('Hero parked work requires exact byte digests')
        if type(self.initialized) is not bool or type(self.completed) is not bool or self.profile!=PROFILE:raise ValueError('Unsupported Hero coordinator profile')
        if (self.interrupted_action is None) != (self.interrupted_event is None):raise ValueError('Hero interruption requires both real terminal clocks')
        if self.interrupted_action is not None:
            _integer(self.interrupted_action,'Hero interruption action',self.action+1)
            _integer(self.interrupted_event,'Hero interruption event',1)
            if self.completed or not self.initialized:raise ValueError('Interrupted Hero root cannot claim natural completion')
        if self.completed and (self.stack or self.parked_hashes or not self.initialized):raise ValueError('Completed Hero root retains work')
        if self.initial_parked_hashes and not self.completed and self.parked_hashes[-len(self.initial_parked_hashes):]!=self.initial_parked_hashes:raise ValueError('Hero root changed its complete original parked suffix')

@dataclass(frozen=True)
class BeginHeroLethalEpisode(Effect):
    reference:HeroLethalReference

@dataclass(frozen=True)
class FinishHeroLethalEpisode(Effect):
    reference:HeroLethalReference

@dataclass(frozen=True)
class FinishHeroLethalRoot(Effect):
    root_id:int
    simultaneous:tuple[HeroLethalReference,...]
    initial_parked_hashes:tuple[str,...]

@dataclass(frozen=True)
class RecoverHero(Effect):
    reference:HeroLethalReference
    health:int
    profile:str=RECOVERY
    def __post_init__(self):
        if type(self.reference) is not HeroLethalReference:raise ValueError('Recovery requires a genuine Hero fatal reference')
        self.reference.__post_init__();_integer(self.health,'Hero recovery health',1)
        if self.profile!=RECOVERY:raise ValueError('Unsupported Hero recovery profile')

CONTROL=(BeginHeroLethalEpisode,FinishHeroLethalEpisode,FinishHeroLethalRoot)

def root(state,identity=None):
    identity=state.active_hero_lethal_root_id if identity is None else identity
    return next((x for x in state.hero_lethal_roots if x.id==identity),None)

def episode(state,identity):
    return next((x for x in state.hero_lethal_history if x.reference.episode_id==identity),None)

def put_root(state,value):
    state.hero_lethal_roots=[value if x.id==value.id else x for x in state.hero_lethal_roots]

def put_episode(state,value):
    state.hero_lethal_history=[value if x.reference.episode_id==value.reference.episode_id else x for x in state.hero_lethal_history]

def validate_reference(state,registry,reference,*,active=False):
    if type(reference) is not HeroLethalReference:raise ValueError('Expected exact Hero fatal reference')
    reference.__post_init__();saved=episode(state,reference.episode_id);owner=root(state,reference.root_id)
    if saved is None or saved.reference!=reference or owner is None or reference.episode_id not in owner.episode_ids:raise ValueError('Unknown/future/borrowed Hero fatal reference')
    death=next((d for d in state.death_history if d.id==reference.death_id),None)
    entity=state.entities.get(reference.hero_id)
    if (death is None or death.zone!=Zone.HERO or (death.entity_id,death.card_id,death.controller)!=(reference.hero_id,reference.card_id,reference.player_id)
            or entity is None or reference.zone_epoch>entity.zone_epoch or registry.card(reference.card_id).kind!=CardType.HERO):raise ValueError('Hero reference differs from its frozen physical death')
    if active and (owner.completed or state.active_hero_lethal_root_id!=owner.id or saved.phase!='running' or not owner.stack or owner.stack[-1]!=reference.episode_id):raise ValueError('Hero debit requires its genuinely active fatal episode')
    return saved

def context_reference(context):
    from .resource_operations import resource_result
    result=resource_result(context.event)
    if result is not None and result.hero_lethal_reference is not None:return result.hero_lethal_reference
    if context.death is not None and context.death.zone==Zone.HERO:
        saved=next((x for x in context.state.hero_lethal_history if x.reference.death_id==context.death.id),None)
        if saved is not None:return saved.reference
    current=root(context.state)
    if current is not None and current.stack:
        saved=episode(context.state,current.stack[-1])
        if saved.reference.player_id==context.player_id:return saved.reference
    return None

def sync_recovered(state):
    current=root(state)
    if current is None:return
    for identity in current.episode_ids:
        saved=episode(state,identity);ref=saved.reference;entity=state.entities[ref.hero_id]
        changed=state.players[ref.player_id].hero_id!=ref.hero_id or entity.card_id!=ref.card_id or entity.zone_epoch!=ref.zone_epoch
        if not saved.recovered and (changed or entity.health>0 and not entity.doomed):put_episode(state,replace(saved,recovered=True))

def bind_deathrattle_group(state,death_id,group_id):
    saved=next((x for x in state.hero_lethal_history if x.reference.death_id==death_id),None)
    if saved is None or saved.group_id is not None:raise ValueError('Hero natural Deathrattle lacks its unique episode')
    put_episode(state,replace(saved,group_id=group_id))

def checkpoint(r):
    """Called only after the full ordinary board death facts/corpse checkpoint."""
    from .lifecycle import active_abilities
    from .deathrattles import schedule_group, triggerable_deathrattles, capture_prohibition
    sync_recovered(r.state);current=root(r.state)
    dying=[r.state.entities[p.hero_id] for p in r.state.players.values() if r.state.entities[p.hero_id].health<=0 or r.state.entities[p.hero_id].doomed]
    fresh=[e for e in dying if current is None or not any((s:=episode(r.state,i)).reference.hero_id==e.id and s.reference.card_id==e.card_id and s.reference.zone_epoch==e.zone_epoch and not s.recovered for i in current.episode_ids)]
    if not fresh:return []
    if current is None and not any(triggerable_deathrattles(r.state,e) for e in fresh):
        terminal(r);return []
    parent=current.stack[-1] if current is not None and current.stack else None
    if current is None:
        root_id=r.state.next_hero_lethal_id;r.state.next_hero_lethal_id+=1
    else:root_id=current.id
    batch=r.state.next_death_batch;r.state.next_death_batch+=1
    saved=[]
    for e in r.rules.entity_order(r.state,[e.id for e in fresh]):
        entity=r.state.entities[e];death=capture_prohibition(r,r.record_death(entity,0,batch))
        ref=HeroLethalReference(root_id,r.state.next_hero_lethal_id,entity.controller,entity.id,entity.card_id,entity.zone_epoch,death.id)
        r.state.next_hero_lethal_id+=1;saved.append(HeroLethalEpisode(ref,parent,r.state.action_number,r.state.turn));r.state.hero_lethal_history.append(saved[-1])
    if current is None:
        current=HeroLethalRoot(root_id,r.root_action_number,r.state.turn,tuple(x.reference for x in saved),tuple(x.reference.episode_id for x in saved))
        r.state.hero_lethal_roots.append(current);r.state.active_hero_lethal_root_id=root_id
    else:put_root(r.state,replace(current,episode_ids=current.episode_ids+tuple(x.reference.episode_id for x in saved)))
    result=[]
    # Freeze both faces first, then atomically consume the complete simultaneous
    # live set before ANY event/listener/DR context captures an acceptance view.
    for accepted_episode in saved:
        ref=accepted_episode.reference;entity=r.state.entities[ref.hero_id];death=next(d for d in r.state.death_history if d.id==ref.death_id)
        ids={a.id for a in death.abilities if a.kind=='deathrattle' and not a.consumed}
        entity.abilities=[replace(a,consumed=True) if a.id in ids else a for a in entity.abilities]
    for saved_episode in saved:
        ref=saved_episode.reference;entity=r.state.entities[ref.hero_id];death=next(d for d in r.state.death_history if d.id==ref.death_id)
        accepted=tuple(a for a in death.abilities if a.kind=='deathrattle' and not a.consumed)
        from .resource_operations import SourceAllocationFact
        event=r.emit('hero_died',source_id=entity.id,target_id=entity.id,player_id=ref.player_id,death_id=death.id,episode=ref.payload(),batch=batch,source_allocation=SourceAllocationFact.capture(r.state,entity).payload())
        work=schedule_group(r,entity.id,ref.player_id,accepted,event=event,death=death)
        result.extend((BeginHeroLethalEpisode(ref),*work,FinishHeroLethalEpisode(ref)))
    return result

def terminal(r):
    losers=[p.id for p in r.state.players.values() if r.state.entities[p.hero_id].health<=0 or r.state.entities[p.hero_id].doomed]
    if losers:
        r.state.status='draw' if len(losers)==2 else 'finished';r.state.winner=None if len(losers)==2 else 3-losers[0]
        r.emit('game_ended',player_id=r.state.winner,reason='hero_death',result=r.state.status)

def begin(r,work):
    saved=validate_reference(r.state,r.registry,work.reference);current=root(r.state)
    if current is None or saved.phase!='queued' or saved.parent_id!=(current.stack[-1] if current.stack else None):raise ValueError('Hero episode begin differs from its original parent')
    put_episode(r.state,replace(saved,phase='running'));put_root(r.state,replace(current,stack=current.stack+(saved.reference.episode_id,)))

def finish_episode(r,work):
    saved=validate_reference(r.state,r.registry,work.reference,active=True);current=root(r.state)
    if saved.group_id is not None:
        from .deathrattles import FinishDeathrattleBatch
        if any(type(w) is FinishDeathrattleBatch and w.batch.id==saved.group_id for w in r._work_queue):raise ValueError('Hero episode cannot precede its original Deathrattle acceptance tail')
        rows=[x for x in r.state.deathrattle_history if x.capture.group_id==saved.group_id]
        if not rows or any(not x.completed or x.interrupted for x in rows):raise ValueError('Hero episode lost accepted Deathrattle payloads')
    sync_recovered(r.state);saved=episode(r.state,saved.reference.episode_id)
    put_episode(r.state,replace(saved,phase='finished'));put_root(r.state,replace(current,stack=current.stack[:-1]))

def digest(r,work):
    from .continuations import FrameCodec
    from .serialization import canonical_hash
    return canonical_hash(FrameCodec(r.game.mechanics,r.registry).encode(work))

def install_marker(r,queue,parked):
    current=root(r.state);hashes=tuple(digest(r,w) for w in parked)
    put_root(r.state,replace(current,initialized=True,initial_parked_hashes=hashes,parked_hashes=hashes))
    marker=FinishHeroLethalRoot(current.id,current.simultaneous,hashes)
    queue.clear();queue.extend((marker,*parked))

def park(r,queue,ordinary):
    if not ordinary:return
    current=root(r.state);positions=[i for i,w in enumerate(queue) if type(w) is FinishHeroLethalRoot]
    if len(positions)!=1:raise ValueError('Hero barrier requires its unique real queue marker')
    index=positions[0];items=list(queue);hashes=tuple(digest(r,w) for w in ordinary)
    put_root(r.state,replace(current,parked_hashes=hashes+current.parked_hashes))
    queue.clear();queue.extend((*items[:index+1],*ordinary,*items[index+1:]))

def route(r,queue,triggers,ordinary,continuation,hero_work,*,new_root):
    current=root(r.state)
    if current is None:return r.rules.reactions(triggers,ordinary,continuation)
    if new_root:
        install_marker(r,queue,(*r.rules.reactions(triggers,ordinary,continuation),*queue));return hero_work
    park(r,queue,r.rules.reactions(triggers,ordinary,[]));return [*hero_work,*continuation]

def finish_root(r,work):
    current=root(r.state)
    if current is None or work.root_id!=current.id or work.simultaneous!=current.simultaneous or work.initial_parked_hashes!=current.initial_parked_hashes:raise ValueError('Hero root marker differs from its original complete batch')
    if current.stack or any(episode(r.state,i).phase!='finished' for i in current.episode_ids):raise ValueError('Hero root cannot finish before siblings/children')
    if tuple(digest(r,w) for w in r._work_queue)!=current.parked_hashes:raise ValueError('Hero root lost complete parked ordinary work/tails')
    put_root(r.state,replace(current,completed=True,parked_hashes=()));r.state.active_hero_lethal_root_id=None
    terminal(r)
    # New ordinary end-game reactions also belong to the original interrupted
    # queue, so none may disappear before the shared terminal validators run.
    r._work_queue.extendleft(reversed(r._captured));r._captured=[]

def interrupt_concession(r,queue,event):
    current=root(r.state)
    if current is None:return
    validate_queue(r.game,r.state,queue)
    if event.kind!='game_ended' or dict(event.data).get('reason')!='concede' or event.action!=r.state.action_number:raise ValueError('Hero interruption requires the actual concession')
    put_root(r.state,replace(current,interrupted_action=event.action,interrupted_event=event.sequence))
    r.state.active_hero_lethal_root_id=None

def recover(r,work):
    work.__post_init__();saved=validate_reference(r.state,r.registry,work.reference)
    ref=work.reference;entity=r.state.entities[ref.hero_id];current=root(r.state)
    if saved.recovered or state_hero_changed(r.state,ref) or entity.health>0 and not entity.doomed:
        r.emit('effect_skipped',target_id=ref.hero_id,effect='RecoverHero',reason='known_stale_hero_episode');return
    if current is None or current.id!=ref.root_id or saved.phase!='running' or not current.stack or current.stack[-1]!=ref.episode_id:raise ValueError('Recovery requires the active original Hero episode')
    if work.health>entity.max_health:raise ValueError('Unsupported Hero recovery above current maximum health')
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(entity)
    entity.damage=entity.max_health-work.health;entity.doomed=False;entity.death_cause=None
    put_episode(r.state,replace(saved,recovered=True))
    r.emit('hero_recovered',source_id=ref.hero_id,target_id=ref.hero_id,player_id=ref.player_id,amount=work.health,
        episode=ref.payload(),profile=work.profile,_hero_health_before=health_before)

def state_hero_changed(state,ref):
    entity=state.entities[ref.hero_id]
    return state.players[ref.player_id].hero_id!=ref.hero_id or entity.zone!=Zone.HERO or entity.card_id!=ref.card_id or entity.zone_epoch!=ref.zone_epoch

def validate_state(state,registry):
    _integer(state.next_hero_lethal_id,'Hero fatal allocation counter',1)
    if state.active_hero_lethal_root_id is not None:_integer(state.active_hero_lethal_root_id,'active Hero fatal root',1)
    if type(state.hero_lethal_roots) is not list or type(state.hero_lethal_history) is not list:raise ValueError('Hero fatal history requires explicit lists')
    previous=0;all_ids=set()
    for current in state.hero_lethal_roots:
        if type(current) is not HeroLethalRoot:raise ValueError('Expected HeroLethalRoot')
        current.__post_init__()
        if current.id<=previous or current.id>=state.next_hero_lethal_id or current.action>state.action_number or current.turn>state.turn:raise ValueError('Hero root has future allocation/chronology')
        previous=current.id;all_ids.add(current.id)
    previous=0
    for saved in state.hero_lethal_history:
        if type(saved) is not HeroLethalEpisode:raise ValueError('Expected HeroLethalEpisode')
        saved.__post_init__();ref=saved.reference
        if ref.episode_id<=previous or ref.episode_id>=state.next_hero_lethal_id or saved.action>state.action_number or saved.turn>state.turn:raise ValueError('Hero episode has future allocation/chronology')
        previous=ref.episode_id;all_ids.add(ref.episode_id);validate_reference(state,registry,ref)
        death=next(d for d in state.death_history if d.id==ref.death_id)
        consumed_ids={a.id for a in death.abilities if a.kind=='deathrattle' and not a.consumed}
        if any(not a.consumed for a in state.entities[ref.hero_id].abilities if a.id in consumed_ids):raise ValueError('Hero fatal acceptance reversed its original one-time attachment consumption')
        if saved.parent_id is not None:
            parent=episode(state,saved.parent_id)
            if parent is None or parent.reference.root_id!=ref.root_id:raise ValueError('Hero child borrowed another root parent')
        if saved.group_id is not None:
            batch=next((b for b in state.deathrattle_batches if b.id==saved.group_id),None)
            if batch is None or any(x.capture.death_id!=ref.death_id for x in state.deathrattle_history if x.capture.group_id==saved.group_id):raise ValueError('Hero episode borrowed another natural Deathrattle group')
    if len(all_ids)!=len(state.hero_lethal_roots)+len(state.hero_lethal_history):raise ValueError('Hero roots/episodes reused one allocation identity')
    for current in state.hero_lethal_roots:
        if tuple(s.reference.episode_id for s in state.hero_lethal_history if s.reference.root_id==current.id)!=current.episode_ids:raise ValueError('Hero root changed its full accepted episode inventory')
        running=tuple(s.reference.episode_id for s in state.hero_lethal_history if s.reference.root_id==current.id and s.phase=='running')
        if running!=current.stack or current.completed and any(episode(state,i).phase!='finished' for i in current.episode_ids):raise ValueError('Hero root stack/progress differs')
    active=[x.id for x in state.hero_lethal_roots if not x.completed and x.interrupted_event is None]
    if active!=([state.active_hero_lethal_root_id] if state.active_hero_lethal_root_id is not None else []):raise ValueError('Hero active coordinator differs from unfinished roots')

def validate_queue(game,state,queue,*,closing=None):
    validate_state(state,game.registry);current=root(state);controls=[w for w in queue if type(w) in CONTROL]
    if current is None:
        if controls:raise ValueError('Hero control work has no active coordinator')
        return
    markers=[w for w in controls if type(w) is FinishHeroLethalRoot]
    if closing is not None:markers.insert(0,closing)
    if len(markers)!=1 or markers[0].root_id!=current.id or markers[0].simultaneous!=current.simultaneous or markers[0].initial_parked_hashes!=current.initial_parked_hashes or not current.initialized:raise ValueError('Hero fatal boundary requires the unique complete original root marker')
    pending=[episode(state,i) for i in current.episode_ids if episode(state,i).phase!='finished']
    for saved in pending:
        ref=saved.reference;begins=[w for w in controls if type(w) is BeginHeroLethalEpisode and w.reference==ref];finishes=[w for w in controls if type(w) is FinishHeroLethalEpisode and w.reference==ref]
        if len(begins)!=int(saved.phase=='queued') or len(finishes)!=1:raise ValueError('Hero episode lost/duplicated its complete Begin/Finish tails')
        death=next(d for d in state.death_history if d.id==ref.death_id)
        if saved.group_id is None and not death.deathrattles_blocked and any(a.kind=='deathrattle' and not a.consumed for a in death.abilities):raise ValueError('Hero fatal boundary lost its accepted natural Deathrattle plan')
    expected_count=1+sum(1+int(s.phase=='queued') for s in pending)
    if len(controls)!=expected_count-(1 if closing is not None else 0):raise ValueError('Hero queue contains foreign/extra episode control')
    for w in controls:
        if type(w) is not FinishHeroLethalRoot:validate_reference(state,game.registry,w.reference)
    # Prove the actual ordered program, not just matching marker counts.
    # Running ancestors are already entered; queued siblings/children must enter
    # in original acceptance order and finish only after their own DR tail.
    from .deathrattles import InvokeDeathrattle,FinishDeathrattle,FinishDeathrattleBatch,record as dr_record
    stack=list(current.stack);entered=set(stack);finished={s.reference.episode_id for s in state.hero_lethal_history if s.phase=='finished'}
    for w in queue:
        if type(w) is BeginHeroLethalEpisode:
            saved=episode(state,w.reference.episode_id);parent=stack[-1] if stack else None
            siblings=[s.reference.episode_id for s in pending if s.parent_id==parent and s.phase=='queued' and s.reference.episode_id not in entered]
            if saved.parent_id!=parent or not siblings or siblings[0]!=saved.reference.episode_id:raise ValueError('Hero Begin reordered its original sibling/child program')
            entered.add(saved.reference.episode_id);stack.append(saved.reference.episode_id)
        elif type(w) is FinishHeroLethalEpisode:
            identity=w.reference.episode_id
            if not stack or stack[-1]!=identity or any(s.parent_id==identity and s.reference.episode_id not in finished for s in pending):raise ValueError('Hero Finish lost its complete child/ancestor order')
            stack.pop();finished.add(identity)
        elif type(w) in (InvokeDeathrattle,FinishDeathrattle,FinishDeathrattleBatch):
            if type(w) is InvokeDeathrattle:capture=w.context.deathrattle
            elif type(w) is FinishDeathrattle:capture=dr_record(state,w.record_id).capture
            else:capture=w.context.deathrattle
            if capture.kind==CardType.HERO:
                saved=next((s for s in pending if s.reference.death_id==capture.death_id),None)
                if saved is None or not stack or stack[-1]!=saved.reference.episode_id:raise ValueError('Hero episode Finish/Begin crossed its original Deathrattle tail')
        elif type(w) is FinishHeroLethalRoot and stack:raise ValueError('Hero terminal marker crossed unfinished episode stack')
    items=list(queue);index=next((i for i,w in enumerate(items) if type(w) is FinishHeroLethalRoot),-1)
    if closing is None:
        if any(type(w) in CONTROL for w in items[index+1:]):raise ValueError('Hero payload tail was moved behind the terminal barrier')
        parked=items[index+1:]
    else:parked=items
    from .continuations import FrameCodec
    from .serialization import canonical_hash
    if tuple(canonical_hash(FrameCodec(game.mechanics,game.registry).encode(w)) for w in parked)!=current.parked_hashes:raise ValueError('Hero parked ordinary/continuation work differs from its full accepted queue')

def validate_boundary(game):
    frame=game._frame;state=game._state;queue=(*frame.prefix,*frame.continuation) if frame else ()
    validate_queue(game,state,queue)
    if root(state) is not None and (frame is None or state.pending_choice is None):raise ValueError('An idle playing match cannot retain a Hero fatal barrier')
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    def visit(value,scope,forbid=False,depth=0):
        if depth>64:raise ValueError('Hero fatal frame nesting exceeds codec limit')
        if type(value) in CONTROL and forbid:raise ValueError('Hero internal control cannot be forged in a choice')
        if type(value) is HeroLethalReference:validate_reference(scope,game.registry,value);return
        if type(value) is RecoverHero:validate_reference(scope,game.registry,value.reference)
        if type(value) is RuleContext:
            bind_original_prefix(scope,value.state)
            validate_state(value.state,game.registry)
            for f in fields(value):
                if f.name!='state':visit(getattr(value,f.name),value.state,forbid,depth+1)
            return
        if type(value) is PaidHandChoiceBoundaryProof:
            bind_original_prefix(scope,value.state)
            validate_queue(game,value.state,value.work)
            visit(value.work,value.state,False,depth+1);return
        if type(value) is GameState:return
        if isinstance(value,(list,tuple)):
            for x in value:visit(x,scope,forbid,depth+1)
        elif isinstance(value,dict):
            for x in value.values():visit(x,scope,forbid,depth+1)
        elif is_dataclass(value) and not isinstance(value,type):
            for f in fields(value):visit(getattr(value,f.name),scope,forbid,depth+1)
    if frame:
        visit((*frame.prefix,*frame.continuation),state);visit(frame.options,state,True);visit(frame.paid_hand_choice_boundary,state)

def bind_original_prefix(state,original):
    """Bind historical identities/progress, without imposing today's health or
    active barrier on the older RuleContext / paid request state/work scope."""
    if state.next_hero_lethal_id<original.next_hero_lethal_id:raise ValueError('Hero original proof moved its allocator backwards')
    ranks={'queued':0,'running':1,'finished':2}
    for old in original.hero_lethal_roots:
        current=root(state,old.id)
        if current is None or (current.id,current.action,current.turn,current.simultaneous,current.profile)!=(old.id,old.action,old.turn,old.simultaneous,old.profile) or current.episode_ids[:len(old.episode_ids)]!=old.episode_ids:raise ValueError('Hero original proof changed its complete simultaneous/episode prefix')
        if old.initialized and (not current.initialized or current.initial_parked_hashes!=old.initial_parked_hashes) or old.completed and not current.completed:raise ValueError('Hero original proof rewrote its initialized/completed root')
    for old in original.hero_lethal_history:
        current=episode(state,old.reference.episode_id)
        if current is None or (current.reference,current.parent_id,current.action,current.turn)!=(old.reference,old.parent_id,old.action,old.turn) or old.group_id is not None and current.group_id!=old.group_id or ranks[current.phase]<ranks[old.phase] or old.recovered and not current.recovered:raise ValueError('Hero original proof changed immutable episode or reversed progress')

def permits_dying_wait(game):
    if game._frame is None or game._state.pending_choice is None or root(game._state) is None:return False
    validate_boundary(game);current=root(game._state)
    return all(any((s:=episode(game._state,i)).reference.hero_id==p.hero_id and not s.recovered for i in current.episode_ids) for p in game._state.players.values() if game._state.entities[p.hero_id].health<=0 or game._state.entities[p.hero_id].doomed)

def resume_work(r,frame,triggers,chosen):
    queue=deque((*frame.prefix,*chosen,*frame.continuation))
    if root(r.state) is not None:park(r,queue,triggers)
    else:queue=deque((*frame.prefix,*triggers,*chosen,*frame.continuation))
    return tuple(queue)

def reject_choice_control(value):
    def visit(v,depth):
        if depth>64:raise ValueError('Hero choice nesting exceeds codec limit')
        if type(v) in CONTROL:raise ValueError('Hero internal control cannot be offered in a choice')
        if type(v) is GameState:return
        if isinstance(v,(list,tuple)):
            for x in v:visit(x,depth+1)
        elif isinstance(v,dict):
            for x in v.values():visit(x,depth+1)
        elif is_dataclass(v) and not isinstance(v,type):
            for f in fields(v):visit(getattr(v,f.name),depth+1)
    visit(value,0)

def reference_from_dict(value):
    if type(value) is not dict or set(value)!={f.name for f in fields(HeroLethalReference)}:raise ValueError('Hero reference requires exactly its declared fields')
    return HeroLethalReference(**value)

def reference_from_payload(value):
    if type(value) is not tuple or any(type(x) is not tuple or len(x)!=2 or type(x[0]) is not str for x in value):raise ValueError('Hero reference requires immutable declared fields')
    result=dict(value)
    if len(result)!=len(value):raise ValueError('Hero reference contains duplicate fields')
    return reference_from_dict(result)

def state_rows_from_dict(value):
    _integer(value['next_hero_lethal_id'],'Hero fatal allocation counter',1)
    if value['active_hero_lethal_root_id'] is not None:_integer(value['active_hero_lethal_root_id'],'active Hero root',1)
    for name,kind in (('hero_lethal_roots',HeroLethalRoot),('hero_lethal_history',HeroLethalEpisode)):
        if type(value[name]) is not list:raise ValueError('Hero fatal tables require explicit arrays')
        rows=[]
        for item in value[name]:
            if type(item) is not dict or set(item)!={f.name for f in fields(kind)}:raise ValueError('Hero fatal table requires exactly declared fields')
            row=dict(item)
            if kind is HeroLethalEpisode:row['reference']=reference_from_dict(row['reference'])
            else:
                for field_name in ('simultaneous','episode_ids','stack','initial_parked_hashes','parked_hashes'):
                    if type(row[field_name]) is not list:raise ValueError('Hero fatal frozen fields require arrays')
                    row[field_name]=tuple(reference_from_dict(x) for x in row[field_name]) if field_name=='simultaneous' else tuple(row[field_name])
            rows.append(kind(**row))
        value[name]=rows

def validate_committed_events(game):
    """True outer restore only; Retry may remove a later Hero/episode history."""
    from .resource_operations import allocation_from_payload
    state=game._state;facts={}
    for event in game._events:
        if event.kind!='hero_died':continue
        data=dict(event.data)
        if set(data)!={'death_id','episode','batch','source_allocation'}:raise ValueError('Hero death event lost its complete declared fact')
        ref=reference_from_payload(data['episode']);allocation=allocation_from_payload(data['source_allocation'])
        _integer(data['batch'],'Hero death batch',1)
        if not(ref.root_id<ref.episode_id<state.next_hero_lethal_id and ref.death_id<state.next_death_id and data['batch']<state.next_death_batch) or event.action>state.action_number:raise ValueError('Committed Hero episode has future allocation/event clock')
        if (event.source_id,event.target_id,event.player_id,event.amount,data['death_id'])!=(ref.hero_id,ref.hero_id,ref.player_id,0,ref.death_id):raise ValueError('Hero death event borrowed another physical reference')
        if allocation is None or (allocation.entity_id,allocation.card_id,allocation.kind,allocation.controller,allocation.zone,allocation.zone_epoch)!=(ref.hero_id,ref.card_id,CardType.HERO,ref.player_id,Zone.HERO,ref.zone_epoch) or allocation.next_entity_id>state.next_entity_id or allocation.next_order>state.next_order or game.registry.card(ref.card_id).kind!=CardType.HERO:raise ValueError('Committed Hero fact has unknown/future original allocation')
        if ref.episode_id in facts:raise ValueError('Committed Hero episode was announced twice')
        facts[ref.episode_id]=ref
    return facts

def register(mechanics):
    for kind,handler in ((BeginHeroLethalEpisode,begin),(FinishHeroLethalEpisode,finish_episode),(FinishHeroLethalRoot,finish_root),(RecoverHero,recover)):mechanics.register(kind,handler)
    for kind in (HeroLethalReference,HeroLethalEpisode,HeroLethalRoot):mechanics.register_payload_type(kind)
