"""Magmaw declares its finite Colossal sequence and ordinary limb Deathrattle."""
import json
from pathlib import Path

from hs_sim.engine.model import AppendageSpec,CardDefinition,CardType,Keyword
from hs_sim.engine.colossal_reserves import ColossalReserveProfile
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='CATA_550'
LIMBS=(CARD+'t',)+tuple(CARD+'t'+str(i)for i in range(2,7))
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/magmaw-v1.json'
BATCH_HASH='be4e0bb893781b384ca1a5f90e2625750bac627afa7add315e6ff8aa6cda23e7'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=data['cards']+data['existing_dependencies']+data['evidence_only']
    if (canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,*LIMBS,CARD+'e1')or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)or data['dependencies']or data['skipped']):
        raise TargetValidationError('Magmaw requires the full original body, six limb faces and evidence')
    raw=data['cards'][0]['record']
    if (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'))!=(7,2,12,99):
        raise TargetValidationError('Magmaw changed its original finite99appendages')
    return data


def register_magmaw_card(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record'];old=registry.card(raw['id'])
        if (old.kind,old.cost,old.attack,old.health,old.metadata)!=(CardType.MINION,raw['cost'],raw['attack'],raw['health'],metadata_from_record(raw))or old.deathrattle is None:
            raise TargetValidationError('Finite Colossal lost its actual existing limb dependency')
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        fields=dict(keywords=(Keyword.COLOSSAL,),colossal=tuple(AppendageSpec(LIMBS[i%len(LIMBS)])for i in range(99)))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_colossal_reserve_profile(ColossalReserveProfile(CARD))
