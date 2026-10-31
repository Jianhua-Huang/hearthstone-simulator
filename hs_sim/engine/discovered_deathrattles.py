"""One genuine pool discovery grants its printed Deathrattle to the original body."""
from dataclasses import dataclass,fields,replace
from .effects import AddToHand,Effect,GrantDeathrattle,_integer
from .model import CardType,ChoicePurpose,ChoiceResult,DeathrattleMemory,RememberedDiscovery
from .pools import DiscoverFromPool,PoolQuery
from .sacrifice import MinionReference,live_minion,reference_value

QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,deathrattle=True)


@dataclass(frozen=True)
class DiscoveredDeathrattleTarget:
    battlecry_id:int
    reference:MinionReference|None

    def __post_init__(self):
        _integer(self.battlecry_id,'original discovered-Deathrattle Battlecry',1)
        if self.reference is not None:reference_value(self.reference)


def validate_spec(spec):
    if type(spec)is not DiscoverFromPool or type(spec.memory_target)is not DiscoveredDeathrattleTarget:
        raise ValueError('Printed Deathrattle discovery requires its typed original recipient')
    spec.memory_target.__post_init__()
    plain=DiscoverFromPool(spec.player_id,spec.pool_id,QUERY,source_id=spec.source_id,prompt=spec.prompt)
    if (spec.destination!='memory'or spec.source_id is None or
            any(getattr(spec,f.name)!=getattr(plain,f.name)for f in fields(spec)if f.name not in('destination','memory_target'))):
        raise ValueError('Printed Deathrattle discovery requires one plain complete minion discovery')


def validate_target(state,registry,spec,*,active=True):
    validate_spec(spec)
    from .battlecries import battlecry_record
    row=battlecry_record(state,spec.memory_target.battlecry_id)
    if ((row.source_id,row.player_id)!=(spec.source_id,spec.player_id)or not row.payload_started or row.failure is not None or
            registry.card(row.payload.card_id).kind!=CardType.MINION or
            active and(row.completed or row.interrupted)):
        raise ValueError('Discovered Deathrattle lost its original active Battlecry')
    ref=spec.memory_target.reference
    if ref is not None:
        entity=state.entities.get(ref.entity_id)
        if (ref.entity_id!=row.source_id or entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order):
            raise ValueError('Discovered Deathrattle borrowed an unknown or future original recipient')
    return row


def validate_link(state,registry,link):
    if type(link)is not RememberedDiscovery:raise ValueError('Discovered Deathrattle requires its original typed selection')
    link.__post_init__()
    from .battlecries import battlecry_record
    row=battlecry_record(state,link.battlecry_id)
    if link.discovery_id>len(state.card_discovery_history):raise ValueError('Unknown original Deathrattle discovery')
    discovery=state.card_discovery_history[link.discovery_id-1];result=discovery.result
    card=registry.card(link.card_id)
    if (discovery.id!=link.discovery_id or discovery.is_control or result.choice.purpose!=ChoicePurpose.POOL_DISCOVERY or
            (result.choice.source_id,result.choice.player_id)!=(row.source_id,row.player_id)or
            len(result.selected)!=1 or result.selected[0].card_id!=link.card_id or
            not row.payload_started or row.failure is not None or card.kind!=CardType.MINION or card.deathrattle is None):
        raise ValueError('Discovered Deathrattle differs from its original complete selected face')
    return row,discovery,card


def validate_ability(state,registry,ability):
    link=ability.deathrattle_discovered_from
    if link is None:return
    ability.__post_init__();row,_,card=validate_link(state,registry,link)
    if (ability.deathrattle_card_id!=card.id or ability.behavior_id!=card.deathrattle or
            ability.deathrattle_copied_from is None and ability.deathrattle_inherited_from is None and
            ability.deathrattle_grant_card_id!=row.payload.card_id or
            (None if ability.deathrattle_memory is None else ability.deathrattle_memory.spec)!=card.native_deathrattle):
        raise ValueError('Discovered Deathrattle changed its printed selected payload')


def grant_fields(r,link,effect):
    row,_,card=validate_link(r.state,r.registry,link)
    memory=None if card.native_deathrattle is None else DeathrattleMemory(card.native_deathrattle)
    if (effect.behavior_id,effect.deathrattle_memory,effect.source_id)!=(card.deathrattle,None,row.source_id):
        raise ValueError('Discovered Deathrattle grant changed its fresh printed material')
    return dict(deathrattle_card_id=card.id,deathrattle_discovered_from=link,deathrattle_memory=memory)


@dataclass(frozen=True)
class GainDiscoveredDeathrattle(Effect):
    target:DiscoveredDeathrattleTarget
    result:ChoiceResult

    def __post_init__(self):
        if type(self.target)is not DiscoveredDeathrattleTarget or type(self.result)is not ChoiceResult:
            raise ValueError('Discovered Deathrattle requires its original typed target and genuine choice')
        self.target.__post_init__();self.result.__post_init__()


def gain(r,request):
    request.__post_init__()
    from .card_discoveries import require_original_result
    original=require_original_result(r.state,request.result)
    if len(original.result.selected)!=1:raise ValueError('Printed Deathrattle grant requires exactly one selected card')
    link=RememberedDiscovery(request.target.battlecry_id,original.id,original.result.selected[0].card_id)
    row,_,card=validate_link(r.state,r.registry,link)
    ref=request.target.reference
    if ref is None:return ()
    if ref.entity_id!=row.source_id:raise ValueError('Discovered Deathrattle grant borrowed another original body')
    entity=live_minion(r.state,ref)
    if entity is None:r.stale(request,ref.entity_id);return ()
    from .resolver import _grant_to
    _grant_to(r,GrantDeathrattle(entity.id,card.deathrattle,row.source_id),entity,
        grant_card_id=row.payload.card_id,discovered_deathrattle=link)
    return ()


def apply_selection(r,effect):
    spec=effect.batch.spec;validate_target(r.state,r.registry,spec)
    from .card_discoveries import require_original_result
    require_original_result(r.state,effect.choice_result)
    from .discovery_delivery import MaterializeDiscoveredCard
    recipe=AddToHand(spec.player_id,effect.selection.card_id,spec.source_id)
    # Gain before ordinary acquisition notifications, including a full-hand burn.
    return(GainDiscoveredDeathrattle(spec.memory_target,effect.choice_result),
        MaterializeDiscoveredCard(effect.choice_result,recipe))


def validate_boundary(game):
    state=game._state
    abilities=[a for e in state.entities.values()for a in e.abilities]
    abilities.extend(a for d in state.death_history for a in d.abilities)
    abilities.extend(row.capture.ability for row in state.deathrattle_history)
    links={a.deathrattle_discovered_from for a in abilities if a.deathrattle_discovered_from is not None}
    if not links:return
    from .discovery import ResolvePoolDiscovery,validate_selection
    from .discovery_offers import offer_for_result
    for ability in abilities:
        if ability.deathrattle_discovered_from is not None:validate_ability(state,game.registry,ability)
    for link in links:
        _,original,_=validate_link(state,game.registry,link)
        offer=offer_for_result(game,original.result)
        option=next(o for o in offer.options if o.id==original.result.selected_ids[0])
        if len(option.effects)!=1 or type(option.effects[0])is not ResolvePoolDiscovery:
            raise ValueError('Discovered Deathrattle lost its original complete pool offer')
        effect=option.effects[0];spec=effect.batch.spec
        validate_target(state,game.registry,spec,active=False)
        if spec.memory_target.battlecry_id!=link.battlecry_id or effect.selection.card_id!=link.card_id:
            raise ValueError('Discovered Deathrattle borrowed another original offered selection')
        validate_selection(game.registry,game._generation_context,replace(effect,choice_result=original.result))


def register(mechanics):
    mechanics.register_payload_type(DiscoveredDeathrattleTarget)
    mechanics.register(GainDiscoveredDeathrattle,gain)
