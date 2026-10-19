"""Sample a complete named reward domain, then use ordinary hand/deck delivery."""
from dataclasses import asdict,dataclass
import json,random

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import AddToHand,Effect,_integer
from .model import CardType,Zone
from .pools import GenerationContext

ACCEPTED='fixed_reward_split_accepted'


@dataclass(frozen=True)
class SplitFixedRewards(Effect):
    pool_id:str
    pool_context:GenerationContext
    source:SourceAllocationFact
    hand_count:int

    @property
    def source_id(self):return self.source.entity_id

    def __post_init__(self):
        from .model import _name
        _name(self.pool_id,'fixed reward pool');_integer(self.hand_count,'hand reward count',0)
        if type(self.pool_context)is not GenerationContext or type(self.source)is not SourceAllocationFact:
            raise ValueError('Fixed rewards require their original domain and source')
        self.pool_context.__post_init__();self.source.__post_init__()
        if(self.source.zone,self.source.kind)!=(Zone.BOARD,CardType.MINION):raise ValueError('Fixed reward split requires its original minion source')


def members(registry,request):
    request.__post_init__();pool=registry.pool(request.pool_id,request.pool_context)
    cards=tuple(x.card_id for x in pool.members)
    if not pool.complete or pool.excluded_card_ids or any(x.weight!=1 for x in pool.members)or request.hand_count>len(cards):
        raise ValueError('Fixed reward split requires its full uniform finite domain')
    for cid in cards:
        if not registry.card(cid).hand_playable:raise ValueError('Fixed reward domain contains an unknown hand reward')
    return cards


def sample(rng,cards,count):
    remaining=list(cards);selected=[]
    for _ in range(count):selected.append(remaining.pop(rng.randrange(len(remaining))if len(remaining)>1 else 0))
    return tuple(selected),tuple(remaining)


def split(r,request):
    cards=members(r.registry,request);validate_allocation(r.state,r.registry,request.source)
    before=r.game._rng.getstate();selected,remainder=sample(r.game._rng,cards,request.hand_count);after=r.game._rng.getstate()
    from .serialization import end_turn_rng_to_json
    r.emit(ACCEPTED,source_id=request.source_id,player_id=request.source.controller,
        request=json.dumps(asdict(request),sort_keys=True,separators=(',',':')),candidates=cards,
        selected=selected,remainder=remainder,rng_before=json.dumps(end_turn_rng_to_json(before)),
        rng_after=json.dumps(end_turn_rng_to_json(after)),_capture=False)
    from .deck_shuffles import ShuffleDeckCards
    from .zones import AddToDeck
    pid=request.source.controller
    return(*tuple(AddToHand(pid,cid,request.source_id)for cid in selected),
        ShuffleDeckCards(pid,pid,tuple(AddToDeck(pid,cid,source_id=request.source_id)for cid in remainder),request.source_id))


def request_from_dict(raw):
    from .serialization import _row
    row=_row(raw,SplitFixedRewards);row['source']=allocation_from_dict(row['source'])
    row['pool_context']=GenerationContext(**_row(row['pool_context'],GenerationContext))
    return SplitFixedRewards(**row)


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .serialization import end_turn_rng_from_json
    for event in effective_events(game._events):
        if event.kind!=ACCEPTED:continue
        data=dict(event.data);request=request_from_dict(json.loads(data['request']))
        validate_allocation(game._state,game.registry,request.source);cards=members(game.registry,request)
        if (event.source_id,event.player_id)!=(request.source_id,request.source.controller)or tuple(data['candidates'])!=cards:
            raise ValueError('Fixed reward split lost its complete original domain')
        local=random.Random();local.setstate(end_turn_rng_from_json(json.loads(data['rng_before'])))
        selected,remainder=sample(local,cards,request.hand_count)
        if (tuple(data['selected']),tuple(data['remainder']),end_turn_rng_from_json(json.loads(data['rng_after'])))!=(selected,remainder,local.getstate()):
            raise ValueError('Fixed reward split changed its original random partition')


def register(mechanics):mechanics.register(SplitFixedRewards,split)
