"""One ordinary bonus per original delivery, after the whole summon group."""
from dataclasses import dataclass
from random import Random
from .bonus_effects import BONUS_EFFECTS,bonus_candidates
from .model import Keyword,validate_end_turn_rng
from .sacrifice import GrantCapturedKeyword,MinionReference,live_minion,reference_value

@dataclass(frozen=True)
class GroupBonusFact:
    beneficiary:MinionReference
    candidates:tuple[Keyword,...]
    selected:Keyword|None
    outcome:str
    rng_before:tuple
    rng_after:tuple

    def __post_init__(self):
        reference_value(self.beneficiary)
        if self.selected is not None and type(self.selected)is not Keyword:raise ValueError('Selected group bonus requires its typed keyword')
        if type(self.candidates)is not tuple or len(set(self.candidates))!=len(self.candidates)or any(type(k)is not Keyword or k not in BONUS_EFFECTS for k in self.candidates):
            raise ValueError('Group bonus needs its original ordered keyword candidates')
        if self.outcome not in('selected','stale','empty')or(self.outcome=='selected')!=bool(self.candidates):
            raise ValueError('Group bonus changed its original result policy')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        selected=local.choice(self.candidates)if self.candidates else None
        if self.selected!=selected or local.getstate()!=self.rng_after:
            raise ValueError('Group bonus differs from its original candidates and random state')

def beneficiaries(state,root,children=None):
    children={c.id:c for c in state.card_summon_history}if children is None else children
    result=[]
    for child_id in root.entry_root_ids:
        for delivery in children[child_id].deliveries:
            if delivery.outcome=='delivered':
                f=delivery.entity
                result.append(MinionReference(f.entity_id,f.controller,f.card_id,f.zone_epoch,f.entered_order))
    return tuple(result)

def validate(root,state,*,closed=False,children=None):
    facts=root.bonus_receipts
    if type(facts)is not tuple or any(type(f)is not GroupBonusFact for f in facts):raise ValueError('Group bonus needs its complete typed accepted prefix')
    for fact in facts:fact.__post_init__()
    if not root.request.bonus_effects:
        if facts:raise ValueError('Unrewarded group borrowed bonus receipts')
        return
    if facts and len(root.entry_root_ids)!=len(root.selection.occurrences):raise ValueError('Group bonus preceded the complete original summon group')
    if not closed:
        refs=beneficiaries(state,root,children)
        if tuple(f.beneficiary for f in facts)!=refs[:len(facts)]or len(facts)>len(refs):raise ValueError('Group bonus changed its original physical beneficiaries or order')
        if root.status=='completed'and len(facts)!=len(refs):raise ValueError('Completed group omitted an actual original bonus beneficiary')
        children={c.id:c for c in state.card_summon_history}if children is None else children
        if facts and any(children[cid].status=='active'for cid in root.entry_root_ids):raise ValueError('Group rewarded before all child summons finished')

def reward_next(r,root):
    from .ordered_group_batches import FinishOrderedGroup,emit,update
    refs=beneficiaries(r.state,root);index=len(root.bonus_receipts)
    if index>=len(refs):return None
    ref=refs[index];entity=live_minion(r.state,ref)
    candidates=()if entity is None else bonus_candidates(r.state,entity)
    before=r.game._rng.getstate();selected=r.game._rng.choice(candidates)if candidates else None
    fact=GroupBonusFact(ref,candidates,selected,'stale'if entity is None else'selected'if candidates else'empty',before,r.game._rng.getstate())
    root=update(r.state,root,bonus_receipts=(*root.bonus_receipts,fact))
    emit(r,'ordered_group_rewarded',root)
    grant=()if selected is None else(GrantCapturedKeyword(ref,selected,root.request.group.cause.source.entity_id),)
    return(*grant,FinishOrderedGroup(root.id))

def from_dict(value):
    from .serialization import _list,_row,end_turn_rng_from_json
    row=_row(value,GroupBonusFact)
    row['beneficiary']=MinionReference(**_row(row['beneficiary'],MinionReference))
    row['candidates']=tuple(Keyword(k)for k in _list(row['candidates'],'Original bonus candidates'))
    row['selected']=None if row['selected']is None else Keyword(row['selected'])
    for name in('rng_before','rng_after'):row[name]=end_turn_rng_from_json(row[name])
    return GroupBonusFact(**row)
