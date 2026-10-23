"""Native seven-Lackey recipes and the named Reliquary Prime follow-up."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import TransformMinionFromPool
from hs_sim.engine.effects import Buff, Damage, GrantKeyword, Overload
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, Keyword,
    KeywordAuraSpec, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromCandidates, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .recruit_cards import shuffle

SLURPER,RELIQUARY,PRIME='DAL_433','BT_197','BT_197t'
FACELESS,KOBOLD,WITCHY,GOBLIN,ETHEREAL,TITANIC,DRACONIC=(
    'DAL_613','DAL_614','DAL_615','DAL_739','DAL_741','ULD_616','DRG_052')
LACKEYS=(FACELESS,KOBOLD,WITCHY,GOBLIN,ETHEREAL,TITANIC,DRACONIC)
PARENTS=(SLURPER,RELIQUARY)
DEPENDENCIES=(*PARENTS,*LACKEYS,PRIME)
COLLECTIBLE_ROOTS=()
POOL_ID='constructed.cards'
PREFIX='cards.past_lackey_prime.'
OPPONENT_TURN=KeywordAuraSpec(Keyword.ELUSIVE,'self',condition='controller_opponent_turn')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-lackey-prime-v1.json'
BATCH_HASH='ad92749840a6ae488dbedc4fd188108ad15aa356e3be26b8d6acd9a8ce681f81'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(data['collectible_leaf_ids'])!=PARENTS or
            tuple(r['record']['id']for r in data['dependencies'])!=DEPENDENCIES or
            tuple(data['lackey_ids'])!=LACKEYS or data['prime_id']!=PRIME or
            data['provider_child_id']!='SCH_199t19' or
            any(data[k]for k in('cards','existing_dependencies','choice_only','skipped',
                                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(r['record'])!=r['record_sha256']
                for r in data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Native Lackey/Prime complete sources changed')
    raw={r['record']['id']:r['record']for r in data['dependencies']+data['evidence_only']}
    for face in data['official_observations']:
        if face['card_id']==SLURPER and face['face'].get('childIds')!=[
                raw[c]['dbf_id']for c in (*LACKEYS,data['provider_child_id'])]:
            raise TargetValidationError('Lackey source lost its full children, including a separate provider')
        if face['card_id']==RELIQUARY and face['face'].get('childIds')!=[raw[PRIME]['dbf_id']]:
            raise TargetValidationError('Reliquary named Prime identity changed')
    return data


def register_past_lackey_prime_cards(registry):
    def witchy(c):
        if c.target_id is None:return ()
        target=c.state.entities[c.target_id]
        if target.zone!=Zone.BOARD or target.kind!=CardType.MINION:return ()
        return (TransformMinionFromPool(MinionReference.capture(target),POOL_ID,1,
            cost_basis='printed',source_id=c.source_id),)

    scripts={
        SLURPER:lambda c:(GenerateFromCandidates(c.player_id,LACKEYS,c.source_id),),
        FACELESS:lambda c:(GenerateFromPool(c.player_id,POOL_ID,
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2),
            source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),),
        KOBOLD:lambda c:()if c.target_id is None else(Damage(c.target_id,2,c.source_id,DamageKind.MINION_ABILITY),),
        WITCHY:witchy,
        GOBLIN:lambda c:()if c.target_id is None else(Buff(c.target_id,attack=1,source_id=c.source_id),
            GrantKeyword(c.target_id,Keyword.RUSH,c.source_id)),
        TITANIC:lambda c:()if c.target_id is None else(Buff(c.target_id,health=2,source_id=c.source_id),
            GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id)),
        ETHEREAL:lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),source_id=c.source_id),),
        DRACONIC:lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
            PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',),
                class_mode='current'),source_id=c.source_id),),
        RELIQUARY:lambda c:shuffle(c,PRIME,1),
    }
    for cid,body in scripts.items():registry.register_behavior(PREFIX+cid,body)
    registry.register_behavior(PREFIX+'overload',lambda c:(Overload(c.player_id,1),))
    for row in load_batch()['dependencies']:
        raw=row['record'];cid=raw['id'];fields={}
        if raw['type']!='MINION' or raw['collectible']!=(cid in PARENTS):
            raise TargetValidationError('Native Lackey/Prime source type changed')
        if cid in LACKEYS:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('MARK_OF_EVIL'),
                    raw['tags'].get('BATTLECRY'))!=(1,1,1,1,1):
                raise TargetValidationError('Lackey requires its full original subtype and Battlecry')
            fields['battlecry']=PREFIX+cid
            if cid==KOBOLD:fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE)
            elif cid in(WITCHY,GOBLIN,TITANIC):
                fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),relation='friendly')
        elif cid==SLURPER:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('OVERLOAD'),
                    raw['tags'].get('CARDRACE'))!=(1,2,1,1,14):
                raise TargetValidationError('Sludge Slurper requires its native Murloc and Overload')
            fields.update(battlecry=PREFIX+cid,on_play=PREFIX+'overload')
        elif cid==RELIQUARY:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('LIFESTEAL'),
                    raw['tags'].get('DEATHRATTLE'))!=(1,1,3,1,1):
                raise TargetValidationError('Reliquary lost its native Lifesteal Deathrattle')
            fields.update(keywords=(Keyword.LIFESTEAL,),deathrattle=PREFIX+cid)
        else:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TAUNT'),
                    raw['tags'].get('LIFESTEAL'),raw['tags'].get('ELUSIVE'))!=(7,6,8,1,1,1):
                raise TargetValidationError('Prime lost its native conditional Elusive face')
            fields.update(keywords=(Keyword.TAUNT,Keyword.LIFESTEAL),keyword_auras=(OPPONENT_TURN,))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
            health=raw['health'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
