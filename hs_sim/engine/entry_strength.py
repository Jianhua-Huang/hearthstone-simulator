"""Accepted deferred entry strength for ordinary plain and base-copy recipes.

History facts belong to the selected child, not its unchanged producer request.
This is an internal quantity-template policy pending CN calibration.
"""
from dataclasses import dataclass
from .effects import _integer,_player
from .model import CardClass,HeraldRecord

def material_profile(registry,material):
    from .summon_quantities import SummonEntryMaterial
    from .copy_materials import CopyEntryMaterial
    from .replay_entry_material import PhysicalReplayEntryMaterial
    if not registry.card(material.card_id).herald_scaling:return None
    if type(material)is SummonEntryMaterial:return 'plain_herald'
    if type(material)is PhysicalReplayEntryMaterial:return 'whole_card_printed_primary_herald'
    if type(material)is CopyEntryMaterial and material.mode=='base':return material.profile+'_base_herald'
    return None

@dataclass(frozen=True)
class AcceptedEntryStrength:
    profile:str
    material_index:int
    card_id:str
    player_id:int
    turn:int
    action:int
    next_entity_id:int
    next_attachment_id:int
    history:tuple[HeraldRecord,...]
    count:int
    def __post_init__(self):
        if self.profile not in('plain_herald','board_copy_base_herald','stored_copy_base_herald','whole_card_printed_primary_herald'):raise ValueError('Unknown deferred entry-strength profile')
        if type(self.card_id)is not str or not self.card_id:raise ValueError('Selected entry-strength face required')
        _player(self.player_id)
        for n in('material_index','action','count'):_integer(getattr(self,n),'entry strength '+n,0)
        for n in('turn','next_entity_id','next_attachment_id'):_integer(getattr(self,n),'entry strength '+n,1)
        if type(self.history)is not tuple or any(type(x)is not HeraldRecord for x in self.history):raise ValueError('Complete typed original entry-strength history required')
        from .herald import herald_rank
        counts={1:0,2:0};prior=(0,0);soldiers=set()
        for i,row in enumerate(self.history,1):
            row.__post_init__()
            if row.id!=i or row.count_before!=counts[row.player_id]or row.rank!=herald_rank(row.count_before):raise ValueError('Entry strength lost its complete ordered counter basis')
            if(row.turn,row.action)<prior or row.turn>self.turn or row.action>self.action:raise ValueError('Future/reordered entry-strength counter facts')
            if any(n is not None and n>=self.next_entity_id for n in(row.source_id,row.soldier_id)):raise ValueError('Future entry-strength source/body identity')
            if row.soldier_id is not None:
                if row.soldier_id in soldiers:raise ValueError('Repeated entry-strength soldier identity')
                soldiers.add(row.soldier_id)
            counts[row.player_id]+=1;prior=(row.turn,row.action)
        if self.count!=counts[self.player_id]:raise ValueError('Entry strength count differs from its full original history')

def capture(state,registry,request,selected):
    if selected is None:return None
    material=request.materials[selected];profile=material_profile(registry,material)
    if profile is None:return None
    history=tuple(state.herald_history)
    return AcceptedEntryStrength(profile,selected,material.card_id,request.player_id,state.turn,state.action_number,
        state.next_entity_id,state.next_attachment_id,history,sum(x.player_id==request.player_id for x in history))

def validate(state,registry,root,*,closed=False):
    selected=root.selected;fact=root.entry_strength
    expected=None if selected is None else material_profile(registry,root.request.materials[selected])
    if (expected is not None)!=(fact is not None):raise ValueError('Selected summon lost/borrowed its original entry-strength facts')
    if fact is None:return
    if type(fact)is not AcceptedEntryStrength:raise ValueError('Typed accepted entry strength required')
    fact.__post_init__();plan=root.plan
    if(fact.profile,fact.material_index,fact.card_id,fact.player_id)!=(expected,selected,root.request.materials[selected].card_id,root.request.player_id):raise ValueError('Entry strength borrowed another selected material or recipient')
    if(fact.turn,fact.action,fact.next_attachment_id)!=(plan.turn,plan.action,plan.next_attachment_id)or fact.next_entity_id>state.next_entity_id:raise ValueError('Entry strength is not from original quantity acceptance')
    if not closed and tuple(state.herald_history[:len(fact.history)])!=fact.history:raise ValueError('Entry strength differs from its actual original counter history')
    from .herald import soldier_card
    for row in fact.history:
        if row.soldier_card_id!=soldier_card(registry,row.hero_class):raise ValueError('Entry strength counter changed its original registered soldier')
        registry.card(row.soldier_card_id)

def from_dict(value):
    if value is None:return None
    from .serialization import _row
    row=_row(value,AcceptedEntryStrength);history=[]
    for item in row['history']:
        record=_row(item,HeraldRecord);record['hero_class']=CardClass(record['hero_class']);history.append(HeraldRecord(**record))
    row['history']=tuple(history);return AcceptedEntryStrength(**row)
