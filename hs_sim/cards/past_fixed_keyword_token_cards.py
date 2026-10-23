"""Complete card-defined Sparkbot and Adventurer lists use ordinary generators."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,Keyword,TriggerSpec
from hs_sim.engine.pools import GenerateFromCandidates,PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

DRONE,STONE='TTN_860','WC_028'
PARENTS=(DRONE,STONE)
SPARKS=('TTN_719t','TTN_719t7','TTN_719t4','TTN_719t6','TTN_719t2','TTN_719t5','TTN_719t1','TTN_719t3')
ADVENTURERS=('WC_034t','WC_034t2','WC_034t3','WC_034t4','WC_034t5','WC_034t6','WC_034t7','WC_034t8')
DEPENDENCIES=(*PARENTS,*SPARKS,*ADVENTURERS)
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_fixed_keyword_tokens.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-fixed-keyword-tokens-v1.json'
BATCH_HASH='8bb27069fa80d594263aeba413f3b8a8184977228ef10c79c31be2a91d015dbf'
SPARK_BONUSES=('DIVINE_SHIELD','LIFESTEAL','POISONOUS','REBORN','RUSH','ELUSIVE','TAUNT','WINDFURY')
ADVENTURER_BONUSES=('POISONOUS','TAUNT','DIVINE_SHIELD','WINDFURY','SPELLPOWER','STEALTH','LIFESTEAL','RUSH')
KEYWORDS={name:Keyword[name] for name in set(SPARK_BONUSES+ADVENTURER_BONUSES)-{'SPELLPOWER'}}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in data['dependencies'])!=DEPENDENCIES or
            tuple(data['collectible_leaf_ids'])!=PARENTS or
            any(data[k]for k in('cards','existing_dependencies','choice_only','skipped','display_normalizations')) or
            data['numeric_normalizations']!={STONE:{'attack':0}} or
            data['child_pools']!={DRONE:list(SPARKS),STONE:list(ADVENTURERS)} or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Fixed keyword token sources lost complete native inventories')
    dbf={r['record']['id']:r['record']['dbf_id']for r in data['dependencies']}
    for face in data['official_observations']:
        if face['face'].get('childIds')!=[dbf[cid]for cid in data['child_pools'][face['card_id']]]:
            raise TargetValidationError('Fixed token pool differs from its complete primary parent children')
    evidence={r['record']['id']:r['record']for r in data['evidence_only']}
    if len(evidence)!=8 or set(evidence)!=set(data['magnetic_pairs'].values()):
        raise TargetValidationError('Every Sparkbot needs its original paired magnetic attachment evidence')
    for row in data['dependencies'][2:10]:
        raw=row['record'];effect=evidence[data['magnetic_pairs'][raw['id']]]
        if (effect['type']!='ENCHANTMENT' or effect['tags'].get('MAGNETIC')!=1 or
                effect['tags'].get('853')!=raw['dbf_id'] or raw['tags'].get('2787')!=effect['dbf_id']):
            raise TargetValidationError('Sparkbot magnetic identity pair changed')
    return data


def register_past_fixed_keyword_token_cards(registry):
    registry.register_behavior(PREFIX+DRONE,lambda c:(GenerateFromCandidates(c.player_id,SPARKS,c.source_id),))
    registry.register_behavior(PREFIX+STONE,lambda c:(GenerateFromCandidates(c.player_id,ADVENTURERS,c.source_id),))
    data=load_batch();bonuses=dict(zip(SPARKS,SPARK_BONUSES))|dict(zip(ADVENTURERS,ADVENTURER_BONUSES))
    for row in data['dependencies']:
        raw=row['record'];cid=raw['id'];fields={}
        if raw['type']!='MINION' or raw['collectible']!=(cid in PARENTS):
            raise TargetValidationError('Fixed keyword token kind or collectible identity changed')
        if cid==DRONE:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'),raw['tags'].get('CARDRACE'))!=(1,1,2,1,17):
                raise TargetValidationError('Drone Deconstructor lost its native Mech Battlecry')
            fields['battlecry']=PREFIX+DRONE
        elif cid==STONE:
            if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TRIGGER_VISUAL'))!=(1,None,2,1) or 'ATK'in raw['tags']:
                raise TargetValidationError('Meeting Stone requires its explicit reviewed printed zero')
            fields['triggers']=(TriggerSpec('turn_ended',PREFIX+STONE,EndTurnSpec()),)
        else:
            spark=cid in SPARKS;expected=(1,1,1)if spark else(2,2,2)
            if (raw['cost'],raw['attack'],raw['health'])!=expected or raw['tags'].get(bonuses[cid])!=1:
                raise TargetValidationError('Fixed token lost its complete body or original bonus')
            if spark and(raw['tags'].get('CARDRACE')!=17 or raw['tags'].get('MAGNETIC')!=1):
                raise TargetValidationError('Sparkbot requires its native Magnetic Mech face')
            fields['keywords']=((Keyword.MAGNETIC,)if spark else())+(()if bonuses[cid]=='SPELLPOWER'else(KEYWORDS[bonuses[cid]],))
            if spark:fields['magnetic_tribes']=('mech',)
            if bonuses[cid]=='SPELLPOWER':fields['spell_damage']=1
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack']or 0,
            health=raw['health'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
