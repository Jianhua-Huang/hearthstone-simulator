"""Native original-card disappearance and one physical return, never generation.

Broxigar uses the original opening and actual Deathrattle interpreter. Custody
is derived from effective game events, so Rewind restores its original claim.
The complete private receipts are also committed to the snapshot hash.
"""
from dataclasses import asdict,dataclass
import json

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import Effect,_integer,_player,_source
from .errors import ResolutionError
from .model import CardType,OpeningHook,Zone
from .hero_health_history import effective_events

ROOT='TIME_020'
FINAL='TIME_020t5t'
DISAPPEARED='native_card_disappeared'
CLAIMED='vanished_card_return_claimed'
RETURNED='vanished_card_returned'
KINDS=frozenset((DISAPPEARED,CLAIMED,RETURNED))
POLICY='broxigar-single-original-v1'


def plain(value):return json.loads(json.dumps(value,sort_keys=True,separators=(',',':')))
def payload(value):return json.dumps(plain(value),sort_keys=True,separators=(',',':'))
def proof(event):return json.loads(dict(event.data)['proof'])


@dataclass(frozen=True)
class VanishedCardProfile:
    source_card_id:str
    opening_behavior:str
    return_behavior:str
    policy:str=POLICY

    def __post_init__(self):
        if self.source_card_id!=ROOT or self.policy!=POLICY:raise ValueError('Unreviewed original-card return profile')
        if any(type(v)is not str or not v for v in(self.opening_behavior,self.return_behavior)):
            raise ValueError('Original-card return requires both actual behavior identities')


def validate_profile(registry,profile):
    if type(profile)is not VanishedCardProfile:raise ValueError('Expected typed disappearance profile')
    profile.__post_init__();root=registry.card(profile.source_card_id);final=registry.card(FINAL)
    if (root.kind!=CardType.MINION or root.opening_hooks!=(OpeningHook('before_deal',profile.opening_behavior),) or
            final.kind!=CardType.MINION or final.deathrattle!=profile.return_behavior):
        raise ValueError('Disappearance lost its real opening and final Demon Deathrattle')


@dataclass(frozen=True)
class DisappearOriginalCard(Effect):
    source_id:int
    player_id:int
    profile_id:str


@dataclass(frozen=True)
class ReappearOriginalCard(Effect):
    player_id:int
    source_id:int
    profile_id:str
    deathrattle_id:int


def active_origins(events):
    rows={}
    for event in effective_events(events):
        if event.kind==DISAPPEARED:rows[event.sequence]=event
        elif event.kind==CLAIMED:rows.pop(proof(event)['origin_event'],None)
    return tuple(rows.values())


def matches(entity,fact):
    return entity is not None and (entity.id,entity.card_id,entity.kind,entity.owner,entity.controller,
        entity.zone,entity.zone_epoch,entity.entered_order)==(fact.entity_id,fact.card_id,fact.kind,fact.owner,
        fact.controller,fact.zone,fact.zone_epoch,fact.entered_order)


def disappear(r,effect):
    from .opening_deck_copies import is_hook_source
    from .nondeath_removal import RemoveFromGame,remove_from_game
    from .zones import CardReference
    _source(effect.source_id);_player(effect.player_id)
    profile=r.registry._vanished_card_profiles.get(effect.profile_id)
    if profile is None or not is_hook_source(r.state,effect.source_id,effect.player_id,profile.source_card_id):
        raise ResolutionError('Disappearance requires its actual original opening source')
    entity=r.state.entities[effect.source_id]
    if (entity.card_id,entity.controller,entity.zone)!=(profile.source_card_id,effect.player_id,Zone.DECK):
        raise ResolutionError('Disappearance source left its actual starting deck')
    before=SourceAllocationFact.capture(r.state,entity)
    remove_from_game(r,RemoveFromGame((CardReference.capture(entity),),entity.id,reveal=True))
    after=SourceAllocationFact.capture(r.state,entity)
    r.emit(DISAPPEARED,source_id=entity.id,player_id=effect.player_id,
        proof=payload(dict(before=asdict(before),after=asdict(after),profile_id=effect.profile_id,policy=POLICY)),_capture=False)


def activation_signature(row):
    c=row.capture
    return dict(id=c.id,carrier_id=c.carrier_id,player_id=c.player_id,card_id=c.card_id,
        behavior_id=c.ability.behavior_id,ability_id=c.ability.id,origin=c.origin,death_id=c.death_id,
        trigger_source_id=c.trigger_source_id,turn=c.turn,action=c.action,repeat_index=c.repeat_index,
        trigger_index=c.trigger_index,execution_order=row.execution_order,source_attack=row.source_attack)


def reappear(r,effect):
    from .zones import SetAsideCardReference,MoveCard,move_physical_card
    _player(effect.player_id);_source(effect.source_id);_integer(effect.deathrattle_id,'return Deathrattle',1)
    profile=r.registry._vanished_card_profiles.get(effect.profile_id)
    if profile is None or effect.deathrattle_id>len(r.state.deathrattle_history):
        raise ResolutionError('Reappearance requires its registered actual Deathrattle')
    row=r.state.deathrattle_history[effect.deathrattle_id-1];capture=row.capture
    if (capture.carrier_id!=effect.source_id or capture.ability.behavior_id!=profile.return_behavior or
            effect.player_id!=3-capture.player_id or row.execution_order is None or row.completed or row.interrupted):
        raise ResolutionError('Reappearance borrowed an unrelated or inactive Deathrattle')
    candidates=active_origins(r.game._events)
    for candidate in candidates:
        fact=allocation_from_dict(proof(candidate)['after'])
        if not matches(r.state.entities.get(fact.entity_id),fact):
            raise ResolutionError('Unclaimed original disappeared card left its physical custody')
    if not candidates:return ()
    if len(candidates)!=1:
        raise ResolutionError('Multiple original Broxigar identities require verified mirror source selection')
    original=candidates[0];fact=allocation_from_dict(proof(original)['after'])
    actual=SourceAllocationFact.capture(r.state,r.state.entities[fact.entity_id])
    claim=r.emit(CLAIMED,source_id=effect.source_id,target_id=fact.entity_id,player_id=effect.player_id,
        proof=payload(dict(profile_id=effect.profile_id,policy=POLICY,origin_event=original.sequence,
            candidates=tuple(e.sequence for e in candidates),original=asdict(actual),activation=activation_signature(row))),_capture=False)
    # Delegate the same physical movement/hand entry/overflow operation. Its
    # observers are queued until this handler returns, so receipt capture is
    # before any observer can move the successfully delivered card again.
    entity=move_physical_card(r,MoveCard(SetAsideCardReference(fact.entity_id,fact.controller,
        fact.card_id,fact.zone_epoch),effect.player_id,Zone.HAND,source_id=effect.source_id))
    if entity is None:raise ResolutionError('Accepted original return failed its physical movement')
    r.emit(RETURNED,source_id=effect.source_id,target_id=entity.id,player_id=effect.player_id,
        proof=payload(dict(claim_event=claim.sequence,after=asdict(SourceAllocationFact.capture(r.state,entity)))),_capture=False)


def snapshot_value(game):
    from .serialization import event_to_dict
    rows=[event_to_dict(e)for e in game._events if e.kind in KINDS]
    return dict(policy=POLICY,events=rows)if rows else None


def validate_boundary(game):
    from .opening_deck_copies import hook_pairs
    from .nondeath_removal import removal_result
    from .zones import destruction_result
    records=[e for e in game._events if e.kind in KINDS]
    profiles=game.registry._vanished_card_profiles
    if not records:
        if game._state.opening is not None and ROOT in profiles:
            profile=profiles[ROOT]
            for event in game._events:
                if event.kind=='opening_effect' and dict(event.data).get('behavior_id')==profile.opening_behavior:
                    entity=game._state.entities.get(event.source_id)
                    if not(opening_pending(game,entity)):
                        raise ValueError('Original opening lost its disappearance receipt')
        return
    if ROOT not in profiles:raise ValueError('Saved disappeared cards have no native profile')
    profile=profiles[ROOT];profile.__post_init__()
    opening=game._state.opening
    if opening is None:raise ValueError('Disappearance cannot invent a Scenario opening')
    origins={};claims={};returned={};seen_entities=set()
    for event in records:
        _player(event.player_id);_source(event.source_id)
        if event.amount!=0 or set(dict(event.data))!={'proof'}:raise ValueError('Malformed original-card custody receipt')
        raw=proof(event)
        if type(raw)is not dict:raise ValueError('Original-card proof must be a complete mapping')
        if event.kind==DISAPPEARED:
            if set(raw)!={'before','after','profile_id','policy'} or(raw['profile_id'],raw['policy'])!=(ROOT,POLICY):
                raise ValueError('Malformed original disappearance')
            before,after=allocation_from_dict(raw['before']),allocation_from_dict(raw['after'])
            validate_allocation(game._state,game.registry,before,closed=True);validate_allocation(game._state,game.registry,after,closed=True)
            if (event.source_id in seen_entities or event.target_id is not None or
                    (before.entity_id,before.card_id,before.kind,before.controller,before.zone)!=(event.source_id,ROOT,CardType.MINION,event.player_id,Zone.DECK) or
                    (before.entity_id,ROOT)not in hook_pairs(game._state,event.player_id) or
                    plain(asdict(after))!=dict(plain(asdict(before)),zone=Zone.SETASIDE.value,zone_epoch=before.zone_epoch+1)):
                raise ValueError('Disappearance changed its original physical source')
            hook=[e for e in game._events[:event.sequence-1]if e.kind=='opening_effect'and e.source_id==event.source_id
                  and dict(e.data).get('behavior_id')==profile.opening_behavior and dict(e.data).get('stage')=='dealing']
            removed=[e for e in game._events[(hook[-1].sequence if hook else 0):event.sequence-1]
                     if e.kind=='cards_removed_from_game'and e.source_id==event.source_id]
            if len(hook)!=1 or hook[0].player_id!=event.player_id or len(removed)!=1 or tuple(removal_result(removed[0])[0])!=(
                    (before.entity_id,event.player_id,Zone.DECK.value,ROOT),):
                raise ValueError('Disappearance lost its genuine opening removal')
            seen_entities.add(event.source_id);origins[event.sequence]=event
        elif event.kind==CLAIMED:
            if set(raw)!={'profile_id','policy','origin_event','candidates','original','activation'} or(raw['profile_id'],raw['policy'])!=(ROOT,POLICY):
                raise ValueError('Malformed original return acceptance')
            _integer(raw['origin_event'],'original disappearance event',1)
            if type(raw['candidates'])is not list or any(type(v)is not int or v<1 for v in raw['candidates']):
                raise ValueError('Return candidates require their exact original event identities')
            candidates=active_origins(game._events[:event.sequence-1])
            if (len(candidates)!=1 or raw['candidates']!=[e.sequence for e in candidates] or
                    raw['origin_event']!=candidates[0].sequence or raw['origin_event']not in origins):
                raise ValueError('Return changed the complete original custody pool or selected original')
            original=allocation_from_dict(proof(candidates[0])['after']);signature=raw['activation']
            actual=allocation_from_dict(raw['original']);validate_allocation(game._state,game.registry,actual,closed=True)
            identity=('entity_id','card_id','kind','owner','controller','zone','zone_epoch','entered_order')
            if any(getattr(actual,k)!=getattr(original,k)for k in identity):
                raise ValueError('Return acceptance changed the actual original stored allocation')
            if (type(signature)is not dict or set(signature)!=set(activation_signature_shape()) or
                    signature['carrier_id']!=event.source_id or signature['player_id']!=3-event.player_id or
                    signature['behavior_id']!=profile.return_behavior or event.target_id!=original.entity_id):
                raise ValueError('Original return changed its actual Deathrattle or beneficiary')
            for key in('id','carrier_id','ability_id','turn','repeat_index','trigger_index','execution_order'):
                _integer(signature[key],'return activation '+key,1)
            _integer(signature['action'],'return action',0);_integer(signature['source_attack'],'return source Attack',0)
            _player(signature['player_id']);_source(signature['death_id']);_source(signature['trigger_source_id'])
            if signature['origin']not in('death','effect','stored','history')or game.registry.card(signature['card_id']).kind not in(
                    CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO):
                raise ValueError('Return invented an unknown native Deathrattle carrier')
            claims[event.sequence]=event
        else:
            if 'claim_event'not in raw:raise ValueError('Return delivery lost its original claim')
            _integer(raw['claim_event'],'original return claim event',1)
            if set(raw)!={'claim_event','after'} or raw['claim_event']not in claims or raw['claim_event']in returned:
                raise ValueError('Return delivery lost or duplicated its original claim')
            claim=claims[raw['claim_event']];original=allocation_from_dict(proof(origins[proof(claim)['origin_event']])['after'])
            after=allocation_from_dict(raw['after']);validate_allocation(game._state,game.registry,after,closed=True)
            if ((event.source_id,event.player_id,event.target_id)!=(claim.source_id,claim.player_id,claim.target_id) or
                    (after.entity_id,after.owner,after.controller,after.card_id,after.kind,after.zone_epoch,after.entered_order)!=(
                    original.entity_id,original.owner,claim.player_id,ROOT,CardType.MINION,original.zone_epoch+1,original.entered_order) or
                    after.zone not in(Zone.HAND,Zone.GRAVEYARD)):
                raise ValueError('Return replaced its physical identity, recipient, residence or outcome')
            deliveries=[e for e in game._events[claim.sequence:event.sequence-1]if
                e.kind in('card_moved_to_hand','card_burned')and(e.source_id,e.target_id,e.player_id)==(claim.source_id,claim.target_id,claim.player_id)]
            if len(deliveries)!=1 or (after.zone==Zone.HAND)!=(deliveries[0].kind=='card_moved_to_hand'):
                raise ValueError('Original return has no unique real hand movement or burn')
            if after.zone==Zone.GRAVEYARD:
                burn=destruction_result(deliveries[0])
                if burn is None or burn.profile!='setaside_overflow' or burn.card!=allocation_from_dict(proof(claim)['original']):
                    raise ValueError('Original return burn changed its actual stored source')
            returned[raw['claim_event']]=event
    if set(claims)!=set(returned):raise ValueError('Accepted return lost its atomic physical delivery receipt')
    for event in game._events:
        if event.kind=='opening_effect'and dict(event.data).get('behavior_id')==profile.opening_behavior:
            if event.source_id not in seen_entities and not opening_pending(game,game._state.entities.get(event.source_id)):
                raise ValueError('Original opening lost one complete physical disappearance')
    effective=effective_events(game._events)
    for event in effective:
        if event.kind!=CLAIMED:continue
        signature=proof(event)['activation'];rid=signature['id']
        if rid>len(game._state.deathrattle_history) or plain(activation_signature(game._state.deathrattle_history[rid-1]))!=signature:
            raise ValueError('Original return rewrote its complete effective Deathrattle identity')
    for event in active_origins(game._events):
        fact=allocation_from_dict(proof(event)['after'])
        if not matches(game._state.entities.get(fact.entity_id),fact):
            raise ValueError('Unclaimed disappeared card lost its original set-aside residence')


def activation_signature_shape():
    return ('id','carrier_id','player_id','card_id','behavior_id','ability_id','origin','death_id',
            'trigger_source_id','turn','action','repeat_index','trigger_index','execution_order','source_attack')


def opening_pending(game,entity):
    return (game._state.opening is not None and game._state.opening.stage=='dealing'and game._frame is not None
            and entity is not None and entity.card_id==ROOT and entity.zone==Zone.DECK)


def register(mechanics):
    mechanics.register(DisappearOriginalCard,disappear)
    mechanics.register(ReappearOriginalCard,reappear)
