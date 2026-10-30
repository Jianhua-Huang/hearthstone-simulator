"""Live clock declarations carried by ordinary, copyable native abilities.

Host-time events are never trigger-captured. Their inert printed declaration
therefore identifies the passive rule without introducing another lifecycle.
Historical receipts prove complete bounded material, not external provenance.
"""
from dataclasses import asdict,dataclass
import json

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .lifecycle import active_abilities
from .model import CardType,TriggerSpec,Zone

CARD='EX1_560'
POLICY='battlefield-turn-time-v1'
EVENT='turn_time_advanced'


@dataclass(frozen=True)
class BattlefieldTurnClockProfile:
    source_card_id:str
    behavior_id:str
    limit_ms:int=15000
    policy:str=POLICY

    def __post_init__(self):
        if(self.source_card_id!=CARD or type(self.behavior_id)is not str or not self.behavior_id.strip()or
                type(self.limit_ms)is not int or self.limit_ms!=15000 or self.policy!=POLICY):
            raise ValueError('Unreviewed live battlefield turn clock')


def validate_profile(registry,profile):
    if type(profile)is not BattlefieldTurnClockProfile:raise ValueError('Expected a typed battlefield clock')
    profile.__post_init__();card=registry.card(profile.source_card_id)
    if(card.kind!=CardType.MINION or card.choice_only or
            card.triggers!=(TriggerSpec(EVENT,profile.behavior_id),)):
        raise ValueError('Battlefield clock lost its complete passive native declaration')
    registry.behavior(profile.behavior_id)


def sources(game):
    profiles={p.behavior_id:p for p in game.registry._turn_clock_profiles.values()
        if type(p)is BattlefieldTurnClockProfile}
    if not profiles:return()
    rows=[];state=game._state
    for pid in(1,2):
        for eid in state.players[pid].board:
            entity=state.entities[eid]
            if(entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD or not entity.active or
                    entity.health<=0 or entity.doomed or game.registry.card(entity.card_id).interactable is not None):continue
            for ability in active_abilities(entity,'trigger'):
                profile=profiles.get(ability.behavior_id)
                if profile is None or ability.event!=EVENT:continue
                rows.append(dict(profile_id=profile.source_card_id,allocation=asdict(SourceAllocationFact.capture(state,entity)),
                    ability=asdict(ability),next_attachment_id=state.next_attachment_id))
    return tuple(sorted(rows,key=lambda row:(row['allocation']['entered_order'],row['allocation']['entity_id'],row['ability']['id'])))


def encode_sources(rows):return json.dumps(rows,sort_keys=True,separators=(',',':'))


def start_boundary(turn):
    # Scenario has the engine's genuine conceptual first interval, without
    # pretending that a constructed opening/turn_started notification occurred.
    if turn.origin=='scenario':return turn.start_event,turn.start_action
    if turn.origin=='actual'and turn.publication_event is not None:
        return turn.publication_event,turn.publication_action
    return None


def validate_sources(game,raw):
    from .serialization import _ability_from_dict
    if type(raw)is not str:raise ValueError('Clock source receipt requires complete JSON material')
    rows=json.loads(raw)
    if type(rows)is not list or not rows:raise ValueError('Battlefield time charge requires nonempty original sources')
    keys=[];seen=set()
    for row in rows:
        if type(row)is not dict or set(row)!={'profile_id','allocation','ability','next_attachment_id'}:
            raise ValueError('Clock source receipt lost complete original fields')
        profile=game.registry._turn_clock_profiles.get(row['profile_id'])
        validate_profile(game.registry,profile)
        allocation=allocation_from_dict(row['allocation']);validate_allocation(game._state,game.registry,allocation,closed=True)
        ability=_ability_from_dict(row['ability']);bound=row['next_attachment_id']
        if(allocation.kind!=CardType.MINION or allocation.zone!=Zone.BOARD or allocation.entered_order<=0 or
                type(bound)is not int or not ability.id<bound<=game._state.next_attachment_id or
                ability.kind!='trigger'or ability.event!=EVENT or ability.behavior_id!=profile.behavior_id or ability.consumed or
                ability.source_id is None or ability.source_id>=allocation.next_entity_id):
            raise ValueError('Clock source changed its allocated native ability or original board carrier')
        identity=(allocation.entity_id,ability.id)
        if identity in seen:raise ValueError('Clock source receipt repeats one physical ability')
        seen.add(identity);keys.append((allocation.entered_order,allocation.entity_id,ability.id))
    if keys!=sorted(keys):raise ValueError('Clock source receipt changed original source order')
    return rows
