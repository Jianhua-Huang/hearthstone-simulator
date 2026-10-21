"""Immutable successful physical hand discards, on the original zone path.

Private consistency facts do not authenticate unsigned saved history. Original
event/reveal/checkpoint semantics remain owned by zones and the interpreter.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import AbilityInstance, CardType, Event, Zone, _int, _bool, _optional_id


@dataclass(frozen=True)
class DiscardRecord:
    id: int
    player_id: int
    turn: int
    action: int
    event_sequence: int
    card: SourceAllocationFact
    hand_entry_id: int
    source: SourceAllocationFact | None
    reveal: bool
    components: tuple[str, ...] = ()
    jade_size: int | None = None

    def __post_init__(self):
        for name in ('id','player_id','turn','event_sequence','hand_entry_id'):
            _int(getattr(self,name),'discard '+name,1)
        _int(self.action,'discard action',0);_bool(self.reveal,'discard reveal')
        if self.player_id not in (1,2) or type(self.card) is not SourceAllocationFact:
            raise ValueError('Discard requires an original physical hand card and player')
        self.card.__post_init__()
        if self.card.zone != Zone.HAND or self.card.controller != self.player_id:
            raise ValueError('Discard belongs to the original hand controller')
        if self.source is not None:
            if type(self.source) is not SourceAllocationFact:raise ValueError('Discard cause requires a typed original allocation')
            self.source.__post_init__()
            if (self.source.next_entity_id,self.source.next_order)!=(self.card.next_entity_id,self.card.next_order):
                raise ValueError('Discard card and cause require one original capture window')
        if type(self.components) is not tuple or any(type(cid) is not str or not cid for cid in self.components):
            raise ValueError('Discard base material requires ordered component identities')
        if self.jade_size is not None:_int(self.jade_size,'discard innate Jade size',0)
        if self.kind != CardType.MINION and (self.components or self.jade_size is not None):
            raise ValueError('Only discarded minions carry innate minion material')

    @property
    def entity_id(self):return self.card.entity_id
    @property
    def card_id(self):return self.card.card_id
    @property
    def kind(self):return self.card.kind
    @property
    def source_id(self):return None if self.source is None else self.source.entity_id


def validate_state(state, registry=None):
    if type(state.discard_history) is not list or any(type(row) is not DiscardRecord for row in state.discard_history):
        raise ValueError('Discard history requires immutable typed occurrences')
    _int(state.next_discard_id,'next discard ID',1)
    if state.next_discard_id != len(state.discard_history)+1:raise ValueError('Discard history lost its complete allocation cursor')
    last_turn=last_action=last_event=0;seen=set()
    for index,row in enumerate(state.discard_history,1):
        row.__post_init__();card=row.card
        if registry is not None:validate_base_recipe(registry,row)
        if (row.id!=index or not last_turn<=row.turn<=state.turn or not last_action<=row.action<=state.action_number or
                row.event_sequence<=last_event or row.hand_entry_id>len(state.hand_entries)):
            raise ValueError('Discard history changed its original chronology or acquisition')
        entry=state.hand_entries[row.hand_entry_id-1];entity=state.entities.get(row.entity_id)
        if (entity is None or entity.owner!=card.owner or card.zone_epoch>=entity.zone_epoch or
                (entry.id,entry.entity_id,entry.player_id)!=(row.hand_entry_id,row.entity_id,row.player_id) or
                entry.zone_epoch>card.zone_epoch or entry.turn>row.turn or entry.action>row.action or
                (row.entity_id,row.hand_entry_id) in seen):
            raise ValueError('Discard occurrence lost its original physical hand acquisition')
        for allocation in (card,row.source):
            if allocation is None:continue
            if registry is not None:validate_allocation(state,registry,allocation)
            elif (allocation.entity_id not in state.entities or allocation.next_entity_id>state.next_entity_id or
                    allocation.next_order>state.next_order or allocation.zone_epoch>state.entities[allocation.entity_id].zone_epoch):
                raise ValueError('Discard history borrowed an unknown or future original allocation')
        if registry is not None and not registry.card(row.card_id).hand_playable:
            raise ValueError('Discard history requires a physical hand-playable original card')
        seen.add((row.entity_id,row.hand_entry_id));last_turn,last_action,last_event=row.turn,row.action,row.event_sequence


def discarded_cards(state, player_id, *, kind=None, turn=None):
    """Trusted ordered occurrences; successful burns, plays and moves are excluded."""
    _int(player_id,'discard query player',1)
    if player_id not in (1,2):raise ValueError('Invalid discard query player')
    if kind is not None and type(kind) is not CardType:raise ValueError('Discard kind filter requires CardType')
    if turn is not None:_int(turn,'discard query turn',1)
    validate_state(state)
    return tuple(row for row in state.discard_history if row.player_id==player_id and
        (kind is None or row.kind==kind) and (turn is None or row.turn==turn))


def _validate_event(row,event):
    if type(event) is not Event:raise ValueError('Discard requires its original event')
    for name in ('sequence','target_id','player_id'):_int(getattr(event,name),'discard event '+name,1)
    _int(event.action,'discard event action',0);_int(event.amount,'discard event amount',0)
    _optional_id(event.source_id,'discard event source')
    if (event.kind!='card_discarded' or event.data!=() or event.amount!=0 or
            (event.sequence,event.action,event.player_id,event.target_id,event.source_id)!=
            (row.event_sequence,row.action,row.player_id,row.entity_id,row.source_id)):
        raise ValueError('Discard history disagrees with its actual original event')


def validate_base_recipe(registry,row):
    """The small printed recovery recipe, independent of later entity movement."""
    definition=registry.card(row.card_id)
    from .crafted_faces import composition_shape
    if not composition_shape(definition,row.components):
        raise ValueError('Discarded composite material differs from its original body kind')
    for cid in row.components:
        part=registry.card(cid)
        if part.kind != CardType.MINION or part.starship_for:
            raise ValueError('Discarded composition requires ordinary minion components')
    from .jade import family_for
    family=family_for(registry,row.card_id) if registry.jade_families else None
    if family is None:
        if row.jade_size is not None:raise ValueError('Discarded innate size requires its registered Jade family')
    elif row.jade_size is None or family.card_for(row.jade_size)!=row.card_id:
        raise ValueError('Discarded Jade material changed its original printed form')


def validate_base_copy(state,registry,row):
    if type(row) is not DiscardRecord:raise ValueError('Discard base copy requires a successful typed occurrence')
    row.__post_init__()
    if row.id > len(state.discard_history) or state.discard_history[row.id-1] != row:
        raise ValueError('Discard base copy differs from its committed original occurrence')
    validate_allocation(state,registry,row.card);validate_base_recipe(registry,row)
    if not registry.card(row.card_id).hand_playable:
        raise ValueError('Discard base copy requires a playable hand card')


def commit(r,event,capture):
    """Publish once after actual HAND -> GRAVEYARD, before listeners capture."""
    if type(capture) is not tuple or len(capture)!=7:raise ValueError('Discard publication needs its complete original capture')
    card,entry_id,source,reveal,components,jade_size,memory=capture
    validate_state(r.state,r.registry)
    row=DiscardRecord(r.state.next_discard_id,event.player_id,r.state.turn,r.state.action_number,
        event.sequence,card,entry_id,source,reveal,components,jade_size)
    _validate_event(row,event);entity=r.state.entities.get(row.entity_id)
    if (event.sequence!=len(r.game._events)+1 or entity is None or
            (entity.owner,entity.controller,entity.card_id,entity.kind,entity.zone,entity.zone_epoch)!=
            (card.owner,card.controller,card.card_id,card.kind,Zone.GRAVEYARD,card.zone_epoch+1)):
        raise ValueError('Discard publication lost its actual original physical movement')
    r.state.discard_history.append(row);r.state.next_discard_id+=1
    validate_state(r.state,r.registry)
    if memory is not None:
        from .deathrattle_memory import remember_discard
        remember_discard(r,memory,row)


def validate_boundary(game):
    state=game._state;validate_state(state,game.registry)
    from .hero_health_history import effective_events
    # Rewind restores the original State ledger while retaining diagnostic
    # events. Only committed timeline events can witness current occurrences.
    if tuple(e.sequence for e in effective_events(game._events) if e.kind=='card_discarded')!=tuple(row.event_sequence for row in state.discard_history):
        raise ValueError('Discard history lost its complete committed event inventory')
    for row in state.discard_history:
        if row.event_sequence>len(game._events):raise ValueError('Discard history names a future original event')
        _validate_event(row,game._events[row.event_sequence-1])


def rows_from_dict(value):
    from .serialization import _row,_list,_integer
    _integer(value['next_discard_id'],'next discard ID',1);rows=[]
    for item in _list(value['discard_history'],'discard history'):
        row=_row(item,DiscardRecord);row['card']=allocation_from_dict(row['card']);row['source']=allocation_from_dict(row['source'])
        row['components']=tuple(_list(row['components'],'discard original components'))
        rows.append(DiscardRecord(**row))
    value['discard_history']=rows


def validate_definition(card):
    if card.on_discard is None:return
    if type(card.on_discard) is not str or not card.on_discard.strip():
        raise ValueError('Native own-discard body requires a nonempty behavior ID')
    if not card.hand_playable or card.starship_for:
        raise ValueError('Native own-discard body requires a physical non-composite hand card')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows=tuple(a for a in abilities if a.kind=='on_discard')
    if not rows:return
    card=registry.card(card_id);validate_definition(card)
    if (card.on_discard is None or card.kind!=kind or components or len(rows)!=1 or
            type(rows[0]) is not AbilityInstance):
        raise ValueError('Own-discard carrier lost its unique native body')
    rows[0].__post_init__()
    if rows[0].behavior_id!=card.on_discard:
        raise ValueError('Own-discard body differs from its native card declaration')


def validate_context(context, registry):
    from .registry import RuleContext
    if type(context) is not RuleContext:raise ValueError('Own-discard validation requires a typed context')
    own=(type(context.trigger) is AbilityInstance and context.trigger.kind=='on_discard')
    if context.discard is None:
        if own:raise ValueError('Own-discard body lost its successful original fact')
        return
    if type(context.discard) is not DiscardRecord or not own:
        raise ValueError('Own-discard context requires its typed fact and native trigger')
    row=context.discard;row.__post_init__();_validate_event(row,context.event)
    _int(context.source_id,'own-discard source',1);_int(context.player_id,'own-discard player',1)
    if (context.source_id!=row.entity_id or context.player_id!=row.player_id or context.target_id is not None or
            row.id>len(context.state.discard_history) or context.state.discard_history[row.id-1]!=row or
            context.state.discard_history[-1]!=row or context.state.next_discard_id!=row.id+1 or
            (context.state.turn,context.state.action_number)!=(row.turn,row.action) or
            type(context.rewind_attempt) is not int or context.rewind_attempt!=0 or
            any(getattr(context,name) is not None for name in
                ('death','choice','player_effect','window','play','cast','draw','power','battlecry','combo','deathrattle','power_payload','end_turn','physical'))):
        raise ValueError('Own-discard context disagrees with its independent accepted body')
    source=context.state.entities.get(row.entity_id)
    if (source is None or (source.owner,source.controller,source.card_id,source.kind,source.zone,source.zone_epoch)!=
            (row.card.owner,row.player_id,row.card_id,row.kind,Zone.GRAVEYARD,row.card.zone_epoch+1)):
        raise ValueError('Own-discard acceptance lost its original after-discard carrier')
    validate_carrier(registry,source.card_id,source.kind,source.abilities,source.components)
    if context.trigger not in source.abilities or context.trigger.behavior_id!=registry.card(row.card_id).on_discard:
        raise ValueError('Own-discard acceptance borrowed another native declaration')


def validate_call(call, registry):
    validate_context(call.context,registry)
    if call.context.discard is not None and call.behavior_id!=call.context.trigger.behavior_id:
        raise ValueError('Own-discard call substituted its accepted native body')


def capture_body(r,event):
    """One successful original occurrence, no additional discard/cast executor."""
    row=r.state.discard_history[-1];_validate_event(row,event)
    source=r.state.entities[row.entity_id]
    if r.registry.card(source.card_id).stored_deathrattle:
        from .stored_deathrattles import capture_group
        return capture_group(r,event)
    validate_carrier(r.registry,source.card_id,source.kind,source.abilities,source.components)
    from .lifecycle import active_abilities
    bodies=active_abilities(source,'on_discard')
    if not bodies:return ()
    return (r.call(bodies[0].behavior_id,row.entity_id,row.player_id,event=event,
                  trigger=bodies[0],discard=row),)


def material_value(row):
    if type(row) is not DiscardRecord:
        raise ValueError('Discard material requires a typed successful original record')
    row.__post_init__()
    if row.kind != CardType.MINION:
        raise ValueError('Retained discard material requires an original minion')


def validate_material(state, registry, row):
    material_value(row)
    if row.id > len(state.discard_history) or state.discard_history[row.id-1] != row:
        raise ValueError('Discard material differs from its original committed occurrence')
    validate_allocation(state, registry, row.card)
    definition = registry.card(row.card_id)
    if not definition.hand_playable or definition.starship_for:
        raise ValueError('Retained discard material requires an ordinary hand card')


def material_entity(r, row):
    validate_material(r.state, r.registry, row)
    entity = r.state.entities[row.entity_id]
    if (entity.owner,entity.controller,entity.card_id,entity.kind,entity.zone,entity.zone_epoch) != (
            row.card.owner,row.player_id,row.card_id,row.kind,Zone.GRAVEYARD,row.card.zone_epoch+1):
        r.emit('zone_target_skipped', target_id=row.entity_id, reason='captured_discard_departed')
        return None
    if entity.components:
        raise ValueError('Retained composite discard material is not supported')
    return entity


def return_material(r, effect):
    effect.__post_init__()
    entity = material_entity(r, effect.discard)
    if entity is None:return
    player = r.player(effect.discard.player_id)
    # This old hand lease belongs to the old acquisition, not the new return.
    # Other earned local attachments keep their original native lifecycle.
    entity.hand_lifetime = None
    if len(player.hand) >= hand_capacity(player, r.rules):
        # A terminal failed delivery must also invalidate the old material.
        original=SourceAllocationFact.capture(r.state,entity)
        r.move(entity, Zone.GRAVEYARD, hand_entry_reason=None)
        r.refresh_auras()
        from .zones import emit_burn
        emit_burn(r,entity,profile='graveyard_delivery_overflow',original=original,reason='return_hand_full')
        return
    r.move(entity, Zone.HAND, hand_entry_reason='return', hand_entry_source_id=effect.source_id)
    r.refresh_auras()
    r.emit('card_returned', target_id=entity.id, player_id=player.id)


def validate_frame_materials(state, registry, frame):
    from dataclasses import fields, is_dataclass
    from .effects import ReturnToHand
    from .hand_upgrades import BuffStoredCard
    from .model import GameState
    from .registry import RuleContext
    from .copy_materials import CopyEntryMaterial,validate_scope as validate_copy
    seen = set()
    def visit(value, scope):
        if value is None or type(value) is GameState or (id(value),id(scope)) in seen:return
        seen.add((id(value),id(scope)))
        if type(value) is RuleContext:scope=value.state
        row = value.discard if type(value) is ReturnToHand else value.card if type(value) is BuffStoredCard else None
        if row is not None and (type(value) is ReturnToHand or type(row) is DiscardRecord):
            validate_material(scope,registry,row)
        if type(value)is CopyEntryMaterial and value.profile in ('discard_copy','discard_summon_copy'):
            validate_copy(scope,registry,value,hand_copy=value.profile=='discard_copy')
            if value.profile=='discard_copy':validate_material(scope,registry,value.discard)
        if is_dataclass(value) and not isinstance(value,type):
            for field in fields(value):visit(getattr(value,field.name),scope)
        elif isinstance(value,(tuple,list)):
            for item in value:visit(item,scope)
    visit(frame,state)
