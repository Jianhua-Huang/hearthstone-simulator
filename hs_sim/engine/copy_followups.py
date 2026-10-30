"""Original successful board-copy continuations over existing summon deliveries."""
from dataclasses import asdict,dataclass,replace
import json
from .effects import Effect,_behavior,_integer
from .copy_materials import CopyEntryMaterial
from .errors import ResolutionError
from .sacrifice import MinionReference,live_minion,reference_value


@dataclass(frozen=True)
class ContinueCopiedMinion(Effect):
    root_id:int
    index:int
    beneficiary:MinionReference
    behavior_id:str
    def __post_init__(self):
        _integer(self.root_id,'original copy root',1);_integer(self.index,'copy delivery',0)
        reference_value(self.beneficiary);_behavior(self.behavior_id)


def decode(value):
    from .serialization import _row
    row=dict(_row(json.loads(value),ContinueCopiedMinion))
    row['beneficiary']=MinionReference(**_row(row['beneficiary'],MinionReference))
    return ContinueCopiedMinion(**row)


def followup_record(state,registry,effect):
    from .summon_quantities import record
    effect.__post_init__();registry.behavior(effect.behavior_id);root=record(state,effect.root_id)
    material=None if root.selected is None else root.request.materials[root.selected]
    if type(material)is not CopyEntryMaterial or material.on_summon!=effect.behavior_id:
        raise ValueError('Copy followup differs from its original selected material')
    if effect.index>=len(root.deliveries):raise ValueError('Copy followup precedes actual delivery')
    delivery=root.deliveries[effect.index];fact=delivery.entity;ref=effect.beneficiary
    if delivery.outcome!='delivered' or (ref.entity_id,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order)!=(
            fact.entity_id,fact.controller,fact.card_id,fact.zone_epoch,fact.entered_order):
        raise ValueError('Copy followup borrowed another body or lifetime')
    return root,delivery


def continue_copied_minion(r,effect):
    from .summon_quantities import update
    root,delivery=followup_record(r.state,r.registry,effect)
    if root.status!='active' or delivery.followup_started:raise ResolutionError('Copy followup already accepted or closed')
    rows=list(root.deliveries);rows[effect.index]=replace(delivery,followup_started=True)
    update(r.state,root,deliveries=tuple(rows))
    event=r.emit('copy_followup_started',source_id=root.request.cause.source.entity_id,
        target_id=delivery.entity.entity_id,player_id=root.request.player_id,
        followup=json.dumps(asdict(effect),ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)
    if live_minion(r.state,effect.beneficiary)is None:
        r.stale(effect,effect.beneficiary.entity_id);return ()
    return(r.call(effect.behavior_id,root.request.cause.source.entity_id,
        root.request.player_id,target_id=delivery.entity.entity_id,event=event),)


def original_copy_material(context):
    """Original selected copy recipe, including its physical source zone."""
    event=context.event
    if event is None or event.kind!='copy_followup_started':raise ValueError('Expected actual copy continuation')
    effect=decode(dict(event.data)['followup'])
    # Registry lookup is already part of accepting this BehaviorCall; do not use
    # context.source's possibly changed card face to reconstruct the origin.
    roots=[x for x in context.state.card_summon_history if x.id==effect.root_id]
    if len(roots)!=1:raise ValueError('Copy context lost original root')
    root=roots[0]
    if root.selected is None or effect.index>=len(root.deliveries):raise ValueError('Copy context precedes its actual selected delivery')
    material=root.request.materials[root.selected];delivery=root.deliveries[effect.index]
    fact=delivery.entity;ref=effect.beneficiary
    if delivery.outcome!='delivered' or (ref.entity_id,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order)!=(
            fact.entity_id,fact.controller,fact.card_id,fact.zone_epoch,fact.entered_order):
        raise ValueError('Copy context borrowed another original beneficiary')
    if(type(material)is not CopyEntryMaterial or material.on_summon!=effect.behavior_id or not delivery.followup_started or
        (context.source_id,context.player_id,context.target_id)!=(root.request.cause.source.entity_id,root.request.player_id,delivery.entity.entity_id)or
        (event.source_id,event.player_id,event.target_id)!=(context.source_id,context.player_id,context.target_id)):
        raise ValueError('Copy context differs from original physical continuation')
    return material


def original_copy_reference(context):
    """Frozen copied source, independent of subsequent summons or source changes."""
    material=original_copy_material(context)
    a=material.origin
    return MinionReference(a.entity_id,a.controller,a.card_id,a.zone_epoch,a.entered_order)


def validate_followup_events(game):
    roots=game._state.card_summon_history;seen=set()
    for event in game._events:
        if event.kind!='copy_followup_started':continue
        effect=decode(dict(event.data)['followup']);root,delivery=followup_record(game._state,game.registry,effect);key=(root.id,effect.index)
        if key in seen or not delivery.followup_started or (event.source_id,event.player_id,event.target_id)!=(
                root.request.cause.source.entity_id,root.request.player_id,delivery.entity.entity_id):
            raise ValueError('Duplicated or foreign original copy followup receipt')
        seen.add(key)
    expected={(x.id,d.index)for x in roots if x.selected is not None and type(x.request.materials[x.selected])is CopyEntryMaterial
        for d in x.deliveries if d.followup_started}
    if seen!=expected:raise ValueError('Copy followup receipts disagree with original deliveries')


def register(mechanics):mechanics.register(ContinueCopiedMinion,continue_copied_minion)
