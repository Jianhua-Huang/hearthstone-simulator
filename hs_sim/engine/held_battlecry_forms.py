"""Native held Battlecry selection keeps the original physical card and stats."""
from dataclasses import dataclass, replace
import json
from random import Random

from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, TargetMode, Zone

PUBLICATION='held_battlecry_form_selected'
ACQUISITIONS=frozenset(('card_created','card_added_to_hand','card_moved_to_hand',
    'card_drawn','card_returned','stored_card_transformed'))


@dataclass(frozen=True)
class HeldBattlecryFormsProfile:
    card_id: str
    forms: tuple[str,...]

    def __post_init__(self):
        if (type(self.card_id)is not str or not self.card_id or type(self.forms)is not tuple or
                not self.forms or any(type(x)is not str or not x for x in self.forms) or
                len(set(self.forms))!=len(self.forms) or self.card_id in self.forms):
            raise ValueError('Held Battlecry requires its original root and unique ordered real forms')


def validate_profile(registry, profile):
    if type(profile)is not HeldBattlecryFormsProfile:raise ValueError('Typed held Battlecry profile required')
    profile.__post_init__();root=registry.card(profile.card_id)
    if (root.kind!=CardType.MINION or root.battlecry is not None or root.targeting is None or
            root.targeting.mode!=TargetMode.IF_AVAILABLE or registry.player_target_rule(root.target_rule)is None):
        raise ValueError('Held Battlecry root requires its native player target rule')
    for cid in profile.forms:
        card=registry.card(cid)
        if (card.kind!=CardType.MINION or card.battlecry is None or
                (card.cost,card.attack,card.health)!=(root.cost,root.attack,root.health) or
                card.requires_target or card.targeting is not None and card.targeting.mode!=TargetMode.IF_AVAILABLE):
            raise ValueError('Held Battlecry form must retain the original body and a reviewed ordinary Battlecry')
        if card.targeting is not None and card.target_rule not in ('any_entity','any_character') and registry.player_target_rule(card.target_rule)is None:
            raise ValueError('Held Battlecry target needs its reviewed public predicate')


def source(entity, profile):
    rows=[a for a in entity.abilities if a.kind=='battlecry' and a.origin=='printed' and
        a.battlecry_card_id in profile.forms]
    if len(rows)>1:raise ValueError('A native held Battlecry has only one original selection slot')
    return rows[0]if rows else None


def public_form(registry, entity):
    profile=registry.held_battlecry_forms_profiles.get(entity.card_id)
    native=None if profile is None else source(entity,profile)
    return None if native is None or native.consumed else native.battlecry_card_id


def target_allowed(registry, context):
    profile=registry.held_battlecry_forms_profiles.get(context.source.get('card_id'))
    selected=context.source.get('battlecry_form')
    if profile is None or selected is None:return False
    if selected not in profile.forms:raise ValueError('Public Battlecry form is outside its original family')
    card=registry.card(selected);spec=card.targeting;target=context.target
    if spec is None or target is None:return False
    if (target.get('zone')not in tuple(z.value for z in spec.zones) or
            target.get('kind')not in tuple(k.value for k in spec.kinds) or
            spec.exclude_source and target['ref']==context.source['ref']):return False
    owner=target.get('controller')
    if spec.relation=='friendly'and owner!=context.player_id or spec.relation=='enemy'and owner==context.player_id:return False
    if card.target_rule in ('any_entity','any_character'):return True
    return registry.target_rule(card.target_rule)(context)


def _events(game):
    from .hero_health_history import effective_events
    return tuple(effective_events(game._events))


def synchronize(r, event=None):
    profiles=r.registry.held_battlecry_forms_profiles
    if not profiles or getattr(r,'_selecting_held_battlecry',False):return
    if r.state.opening is not None and r.state.opening.stage!='complete':return
    if event is not None and event.kind not in ACQUISITIONS and event.kind!='turn_started':return
    carriers=[(p,r.state.entities[eid])for p in r.state.players.values()for eid in tuple(p.hand)
        if r.state.entities[eid].card_id in profiles and not r.state.entities[eid].silenced]
    if not carriers:return
    previous={}
    for row in _events(r.game):
        if row.kind==PUBLICATION:
            d=dict(row.data);previous[(row.source_id,d['hand_entry_id'],d['zone_epoch'])]=d
    from .serialization import end_turn_rng_to_json
    r._selecting_held_battlecry=True
    try:
        for player,entity in carriers:
                eid=entity.id;profile=profiles[entity.card_id]
                key=(eid,entity.hand_entry_id,entity.zone_epoch);last=previous.get(key)
                owner_start=event is not None and event.kind=='turn_started'and event.player_id==player.id
                if last is not None and (not owner_start or last['turn_event']==event.sequence):continue
                native=source(entity,profile);old=None if native is None else native.battlecry_card_id
                before=r.game._rng.getstate()
                mode='owner_start_random'if last is not None else'inherited'if native is not None else'initial_random'
                inherited_source=None
                if mode=='inherited':
                    inherited_source=native.source_id
                    if inherited_source==eid and not any(k[0]==eid for k in previous):
                        inherited_source=entity.origin_entity_id
                selected=old if mode=='inherited'else r.game._rng.choice(profile.forms)
                after=r.game._rng.getstate();body=r.registry.card(selected)
                if native is None:
                    native=AbilityInstance(attachment_id(r.state),'battlecry',source_id=eid,origin='printed',
                        behavior_id=body.battlecry,battlecry_card_id=selected)
                    entity.abilities.append(native)
                else:
                    updated=replace(native,source_id=eid,behavior_id=body.battlecry,battlecry_card_id=selected)
                    entity.abilities[entity.abilities.index(native)]=updated;native=updated
                refresh_entity(entity)
                r.emit(PUBLICATION,source_id=eid,target_id=eid,player_id=player.id,
                    root=profile.card_id,ability_id=native.id,hand_entry_id=entity.hand_entry_id,
                    zone_epoch=entity.zone_epoch,mode=mode,turn_event=event.sequence if owner_start and last is not None else 0,
                    inherited_source_id=inherited_source,
                    previous=old,candidates=profile.forms,selected=selected,
                    rng_before=json.dumps(end_turn_rng_to_json(before),separators=(',',':')),
                    rng_after=json.dumps(end_turn_rng_to_json(after),separators=(',',':')))
    finally:r._selecting_held_battlecry=False


def validate_game(game):
    profiles=game.registry.held_battlecry_forms_profiles
    if not profiles:return
    state=game._state;events=_events(game);by_id={e.sequence:e for e in events};last={};starts=set();latest_source={}
    from .serialization import end_turn_rng_from_json
    keys={'root','ability_id','hand_entry_id','zone_epoch','mode','turn_event','inherited_source_id','previous','candidates','selected','rng_before','rng_after'}
    for event in events:
        if event.kind!=PUBLICATION:continue
        d=dict(event.data)
        if set(d)!=keys or d['root']not in profiles:raise ValueError('Held Battlecry lost its complete original selection receipt')
        profile=profiles[d['root']]
        if (type(event.source_id)is not int or event.target_id!=event.source_id or event.player_id not in (1,2) or
                any(type(d[k])is not int or d[k]<minimum for k,minimum in
                    (('ability_id',1),('hand_entry_id',1),('zone_epoch',0),('turn_event',0))) or
                d['ability_id']>=state.next_attachment_id or d['hand_entry_id']>len(state.hand_entries) or
                d['selected']not in profile.forms or tuple(d['candidates'])!=profile.forms):
            raise ValueError('Held Battlecry changed its original physical allocation or complete candidate family')
        entry=state.hand_entries[d['hand_entry_id']-1]
        if (entry.entity_id!=event.source_id or entry.player_id!=event.player_id or entry.card_id!=profile.card_id or
                entry.zone_epoch>d['zone_epoch']):raise ValueError('Held Battlecry borrowed another original hand arrival')
        key=(event.source_id,d['hand_entry_id'],d['zone_epoch']);prior=last.get(key)
        if d['mode']=='owner_start_random':
            start=by_id.get(d['turn_event']);identity=(event.source_id,d['hand_entry_id'],d['zone_epoch'],d['turn_event'])
            if (prior is None or start is None or start.kind!='turn_started' or start.player_id!=event.player_id or
                    start.sequence>=event.sequence or identity in starts or
                    (prior['ability_id'],prior['selected'])!=(d['ability_id'],d['previous'])):
                raise ValueError('Held Battlecry lost its genuine unique owner-start and previous native selection')
            starts.add(identity)
        elif d['mode']in ('initial_random','inherited'):
            if prior is not None or d['turn_event']!=0 or d['mode']=='initial_random'and d['previous']is not None or d['mode']=='inherited'and d['previous']!=d['selected']:
                raise ValueError('Held Battlecry changed its original initial selection')
        else:raise ValueError('Unknown native held Battlecry selection mode')
        if d['mode']=='inherited':
            parent=d['inherited_source_id'];original=latest_source.get(parent)if type(parent)is int else None
            if original is None or (original['root'],original['selected'])!=(d['root'],d['selected']):
                raise ValueError('Inherited Battlecry lost its original source selection')
        elif d['inherited_source_id']is not None:raise ValueError('Random Battlecry cannot borrow an inherited selection')
        rng=Random();rng.setstate(end_turn_rng_from_json(json.loads(d['rng_before'])))
        selected=d['previous']if d['mode']=='inherited'else rng.choice(profile.forms)
        if selected!=d['selected']or rng.getstate()!=end_turn_rng_from_json(json.loads(d['rng_after'])):
            raise ValueError('Held Battlecry changed its local random selection proof')
        last[key]=d
        latest_source[event.source_id]=d
    suspended=state.opening is not None and state.opening.stage!='complete'
    for entity in state.entities.values():
        profile=profiles.get(entity.card_id)
        if profile is None:continue
        native=source(entity,profile)
        if native is not None and (native.behavior_id!=game.registry.card(native.battlecry_card_id).battlecry or native.consumed):
            raise ValueError('Held Battlecry changed its native original body')
        if entity.zone==Zone.HAND and not entity.silenced and not suspended:
            d=last.get((entity.id,entity.hand_entry_id,entity.zone_epoch))
            if native is None or d is None or (native.id,native.battlecry_card_id,native.source_id)!=(d['ability_id'],d['selected'],entity.id):
                raise ValueError('Held Battlecry lost its complete current selection and original receipt')
