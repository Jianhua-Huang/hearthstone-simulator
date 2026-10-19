"""Completed quest hand rewards wait for capacity; ordinary generation does not.

The original completion/recipe is retained, the shared creator handles actual
acquisition. FIFO delivery and its exact reaction window remain CN-pending.
"""
from dataclasses import asdict,dataclass,replace
import json

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import AddToHand,ChoiceOption,Effect,RequestChoice,_integer
from .hand_capacity import hand_capacity
from .model import CardType,Event,Zone

ACCEPTED='quest_hand_reward_accepted'
DELIVERED='quest_hand_reward_delivered'


@dataclass(frozen=True)
class GiveQuestHandReward(Effect):
    instruction:AddToHand
    source:SourceAllocationFact
    instance_id:int
    stage:int
    completion:Event
    ordinal:int=0

    @property
    def source_id(self):return self.instruction.source_id

    def __post_init__(self):
        if type(self.instruction)is not AddToHand or type(self.source)is not SourceAllocationFact or type(self.completion)is not Event:
            raise ValueError('Quest reward requires its original creation, allocation and completion')
        self.instruction.__post_init__();self.source.__post_init__()
        _integer(self.instance_id,'original quest reward instance',1);_integer(self.stage,'original quest stage',0)
        _integer(self.ordinal,'original quest hand reward ordinal',0)
        if (self.source.zone!=Zone.QUEST or self.source.kind!=CardType.SPELL or
                (self.completion.kind,self.completion.source_id,self.completion.player_id)!=(
                    'quest_stage_completed',self.source.entity_id,self.source.controller)or
                self.instruction.player_id!=self.source.controller or
                self.instruction.source_id not in (None,self.source.entity_id)):
            raise ValueError('Quest reward substituted its original owner/source')


@dataclass(frozen=True)
class RefillQuestHandRewards(Effect):pass


@dataclass(frozen=True)
class QuestHandReward:
    id:int
    request:GiveQuestHandReward
    turn:int
    action:int
    phase:str='pending'
    delivery:SourceAllocationFact|None=None

    def __post_init__(self):
        _integer(self.id,'quest hand reward ID',1);_integer(self.turn,'quest reward turn',1)
        _integer(self.action,'quest reward action',0)
        if type(self.request)is not GiveQuestHandReward:raise ValueError('Typed original quest reward required')
        self.request.__post_init__()
        if self.action<self.request.completion.action or self.phase not in ('pending','delivered'):
            raise ValueError('Quest reward changed its accepted phase or clock')
        if (self.delivery is not None)!=(self.phase=='delivered'):raise ValueError('Quest reward lost its actual hand delivery')
        if self.delivery is not None:
            self.delivery.__post_init__();q=self.request.instruction
            if (self.delivery.card_id,self.delivery.owner,self.delivery.controller,self.delivery.zone)!=(q.card_id,q.player_id,q.player_id,Zone.HAND):
                raise ValueError('Quest reward delivery differs from the accepted recipe')


def wrap_reward(r,call,work):
    """Only a genuine declared quest reward planner grants deferred delivery."""
    c=call.context
    if c.event is None or c.event.kind!='quest_stage_completed':return work
    source=c.source;definition=r.registry.card(source.card_id);spec=definition.quest
    if spec is None or source.zone!=Zone.QUEST:return work
    progress=source.quest_progress
    if (progress is None or not progress.completing or
            spec.stages[progress.stage].reward_behavior!=call.behavior_id or
            c.event.source_id!=source.id or c.event.player_id!=c.player_id):return work
    fact=SourceAllocationFact.capture(c.state,source);ordinal=0
    def wrap(effect):
        nonlocal ordinal
        if type(effect)is AddToHand:
            result=GiveQuestHandReward(effect,fact,progress.id,progress.stage,c.event,ordinal);ordinal+=1
            return result
        if type(effect)is RequestChoice:
            return replace(effect,options=tuple(replace(o,effects=tuple(wrap(x)for x in o.effects))for o in effect.options))
        return effect
    return [wrap(x)for x in work]


def _key(request):return(request.completion.sequence,request.ordinal)
def _json(row):return json.dumps(asdict(row),sort_keys=True,separators=(',',':'))


def validate_request(state,registry,request):
    request.__post_init__();validate_allocation(state,registry,request.source)
    spec=registry.card(request.source.card_id).quest
    if spec is None or request.stage>=len(spec.stages)or request.instance_id>=state.next_attachment_id:
        raise ValueError('Quest reward lost its original declared stage or instance')
    actual=spec.stages[request.stage];data=dict(request.completion.data)
    if (data.get('stage'),data.get('stage_card_id'),data.get('goal'),data.get('progress'),data.get('completing'))!=(
            request.stage+1,actual.card_id,actual.goal,actual.goal,True):
        raise ValueError('Quest reward changed its actual completed stage')


def accept(r,request):
    validate_request(r.state,r.registry,request)
    from .hero_health_history import effective_events
    if request.completion not in effective_events(r.game._events):raise ValueError('Quest reward borrowed an unknown completion event')
    if any(_key(x.request)==_key(request)for x in r.state.quest_hand_rewards):raise ValueError('Quest reward was accepted twice')
    from .opening import validate_hand_card
    validate_hand_card(r,request.instruction)
    # No current real fixed reward supplies a temporary creation deadline.
    # Reject an unsupported delayed deadline rather than apply it on a later turn.
    if request.instruction.expires_turn is not None and not has_space(r.state,r.rules,request.instruction.player_id):
        raise ValueError('Deferred temporary quest creation requires a reviewed expiry profile')
    row=QuestHandReward(len(r.state.quest_hand_rewards)+1,request,r.state.turn,r.state.action_number)
    r.state.quest_hand_rewards.append(row)
    r.emit(ACCEPTED,source_id=request.source.entity_id,player_id=request.instruction.player_id,row=_json(row),_capture=False)
    if has_space(r.state,r.rules,request.instruction.player_id):return deliver(r,row)
    return ()


def has_space(state,rules,pid):return len(state.players[pid].hand)<hand_capacity(state.players[pid],rules)


def ready(state,rules,player_id=None):
    return state.status=='playing'and any(row.phase=='pending'and
        (player_id is None or row.request.instruction.player_id==player_id)and
        has_space(state,rules,row.request.instruction.player_id)for row in state.quest_hand_rewards)


def deliver(r,row):
    q=row.request.instruction
    if row.phase!='pending'or not has_space(r.state,r.rules,q.player_id):raise ValueError('Quest reward requires its pending obligation and actual slot')
    from .opening import create_hand_card,announce_hand_card
    entity=create_hand_card(r,q,defer_publication=True)
    if entity.zone!=Zone.HAND:raise ValueError('Quest reward bypassed its reserved hand capacity')
    completed=replace(row,phase='delivered',delivery=SourceAllocationFact.capture(r.state,entity))
    r.state.quest_hand_rewards[row.id-1]=completed
    r.emit(DELIVERED,source_id=row.request.source.entity_id,target_id=entity.id,player_id=q.player_id,row=_json(completed),_capture=False)
    announce_hand_card(r,q,entity)
    return ()


def refill(r,work):
    row=next((x for x in r.state.quest_hand_rewards if x.phase=='pending'and
        has_space(r.state,r.rules,x.request.instruction.player_id)),None)
    return deliver(r,row)if row is not None else ()


def schedule(r,queue,continuation,triggers):
    if ready(r.state,r.rules)and not any(type(x)is RefillQuestHandRewards for x in(*queue,*continuation,*triggers)):
        triggers.append(RefillQuestHandRewards())


def _hand_from_dict(value):
    from .serialization import _row,_cost_spec_from_dict
    from .card_creation import CardSpellRepeatGrant,CreatedMinionStats,minion_grant_from_dict
    from .model import ChooseBranchSelection,SummonStats
    row=_row(value,AddToHand);row['revealed_to']=tuple(row['revealed_to'])
    row['cost']=None if row['cost']is None else _cost_spec_from_dict(row['cost'])
    row['spell_repeat']=None if row['spell_repeat']is None else CardSpellRepeatGrant(**_row(row['spell_repeat'],CardSpellRepeatGrant))
    if row['choose_branch']is not None:
        c=_row(row['choose_branch'],ChooseBranchSelection);c['origins']=tuple(c['origins']);row['choose_branch']=ChooseBranchSelection(**c)
    row['minion_grant']=None if row['minion_grant']is None else minion_grant_from_dict(row['minion_grant'])
    if row['minion_stats']is not None:
        s=_row(row['minion_stats'],CreatedMinionStats)
        s['set_to']=None if s['set_to']is None else SummonStats(**_row(s['set_to'],SummonStats))
        row['minion_stats']=CreatedMinionStats(**s)
    return AddToHand(**row)


def rows_from_dict(value):
    from .serialization import _row,_list,event_from_dict
    rows=[]
    for raw in _list(value['quest_hand_rewards'],'quest hand reward history'):
        row=_row(raw,QuestHandReward);q=_row(row['request'],GiveQuestHandReward)
        q['instruction']=_hand_from_dict(q['instruction']);q['source']=allocation_from_dict(q['source'])
        event=dict(q['completion']);data=event['data']
        if (type(data)not in(tuple,list)or any(type(x)not in(tuple,list)or len(x)!=2 or type(x[0])is not str for x in data)or
                len({x[0]for x in data})!=len(data)):
            raise ValueError('Stored quest completion requires its original unique event facts')
        event['data']=dict(data)
        q['completion']=event_from_dict(event);row['request']=GiveQuestHandReward(**q)
        row['delivery']=None if row['delivery']is None else allocation_from_dict(row['delivery'])
        rows.append(QuestHandReward(**row))
    value['quest_hand_rewards']=rows


def validate_shape(state,registry):
    if type(state.quest_hand_rewards)is not list:raise ValueError('Quest rewards require their complete original list')
    keys=set();deliveries=set()
    for i,row in enumerate(state.quest_hand_rewards,1):
        if type(row)is not QuestHandReward:raise ValueError('Typed quest hand reward required')
        row.__post_init__();validate_request(state,registry,row.request)
        key=_key(row.request)
        if row.id!=i or key in keys or row.turn>state.turn or row.action>state.action_number:
            raise ValueError('Quest reward lost its original ordering or clock')
        keys.add(key)
        if not registry.card(row.request.instruction.card_id).hand_playable:raise ValueError('Unknown playable quest hand reward')
        if row.delivery is not None:
            validate_allocation(state,registry,row.delivery)
            if row.delivery.entity_id in deliveries:raise ValueError('Quest rewards borrowed one actual hand delivery')
            deliveries.add(row.delivery.entity_id)


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .summon_quantities import walk_work
    validate_shape(game._state,game.registry);events=effective_events(game._events)
    ids={row.id for row in game._state.quest_hand_rewards}
    for e in events:
        if e.kind in(ACCEPTED,DELIVERED)and json.loads(dict(e.data).get('row','{}')).get('id')not in ids:
            raise ValueError('Quest reward lost its recorded original obligation')
    for row in game._state.quest_hand_rewards:
        if row.request.completion not in events:raise ValueError('Quest reward lost its actual completion')
        original=replace(row,phase='pending',delivery=None)
        accepted=[e for e in events if e.kind==ACCEPTED and dict(e.data).get('row')==_json(original)]
        if len(accepted)!=1 or accepted[0].sequence<=row.request.completion.sequence:
            raise ValueError('Quest reward lost its complete acceptance')
        if row.phase=='delivered':
            done=[e for e in events if e.kind==DELIVERED and dict(e.data).get('row')==_json(row)]
            if len(done)!=1 or done[0].sequence<=accepted[0].sequence:raise ValueError('Quest reward lost its actual delivery receipt')
    frame=game._frame;queue=(*frame.prefix,*frame.continuation)if frame else()
    controls=tuple(x for x in queue if type(x)is RefillQuestHandRewards)
    if len(controls)>1:raise ValueError('Duplicate quest refill markers')
    for w in queue:
        if type(w)is GiveQuestHandReward:
            validate_request(game._state,game.registry,w)
            if w.completion not in events:raise ValueError('Queued quest hand reward lost its actual completion')
    if frame:
        # Public reward instructions can occur in genuine reward choice options;
        # only the internal refill marker is forbidden in user-selectable work.
        for x in walk_work(frame.options):
            if type(x)is RefillQuestHandRewards:raise ValueError('Choice cannot invent a quest refill')
            if type(x)is GiveQuestHandReward:
                validate_request(game._state,game.registry,x)
                if x.completion not in events:raise ValueError('Reward choice borrowed another completion')
        old=tuple(x for x in frame.paid_hand_choice_boundary.work if type(x)in(GiveQuestHandReward,RefillQuestHandRewards))
        current=tuple(x for x in queue if type(x)in(GiveQuestHandReward,RefillQuestHandRewards))
        if old!=current:raise ValueError('Quest hand reward changed its original choice work')
    if ready(game._state,game.ruleset)and not controls:raise ValueError('Available quest reward lost its refill marker')


def register(mechanics):
    mechanics.register(GiveQuestHandReward,accept)
    mechanics.register(RefillQuestHandRewards,refill)
