"""Drest'agath's physical tutor; full native fallback still needs real Yogg."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import (GenerateFromPool,GenerationPolicy,PoolCard,PoolDefinition,
    PoolMember,PoolQuery)
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='BE_703'
GODS=('BE_009','BE_013','BE_017','BE_784')
POOL='cards.drestagath.native-old-gods'
BODY='cards.drestagath.draw-or-generate'
QUERY=PoolQuery(kinds=(CardType.MINION,),keywords_all=(Keyword.OLD_GOD,))
POLICY=GenerationPolicy(allowed_special=(Keyword.OLD_GOD,))
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/drestagath-v1.json'
BATCH_HASH='bd5444aa634fc41c07b98b5fdfb982fbfef358efdd4987db7157774b901c6292'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=GODS[1:]or
            tuple(x['record']['id']for x in data['evidence_only'])!=GODS[:1]or
            data['dependencies']or data['skipped']or data['official_faces_verified']!=2 or
            tuple(data['pool_source_domain']['ids'])!=GODS or data['pending_executable_dependencies']!=['BE_009']):
        raise TargetValidationError('Drestagath requires its complete four-Old-God inventory and explicit missing Yogg dependency')
    for row in data['cards']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Drestagath complete original source changed')
    return data


def register_drestagath_card(registry):
    data=load_batch();raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('DEATHRATTLE'))!=('MINION',4,6,4,1):
        raise TargetValidationError('Drestagath lost its original four-cost 6/4 Deathrattle')
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']:
            raise TargetValidationError('Drestagath requires the unchanged complete existing Old God: '+cid)
    # Independent metadata, never an executable blank Yogg substitute.
    pending=data['evidence_only'][0]['record']
    if any(x['record']['tags'].get('OLD_GOD')!=1 for x in data['existing_dependencies']+data['evidence_only']):
        raise TargetValidationError('Drestagath inventory lost a printed native Old God')
    inventory=PoolCard(pending['id'],CardType.MINION,pending['cost'],metadata_from_record(pending),
        keywords=(Keyword.OLD_GOD,),battlecry=True,deathrattle=False,choose_one=False,attack=pending['attack'])
    if inventory.card_id not in registry.pool_cards:registry.register_pool_card(inventory)
    elif registry.pool_card(inventory.card_id)!=inventory:
        raise TargetValidationError('Pending Old God independent inventory changed')
    registry.register_pool(PoolDefinition(POOL,'drestagath-cn37-fixed-old-gods-v1',
        'local-2026-09-23','experimental',tuple(PoolMember(x)for x in GODS)))
    def body(c):
        fallback=GenerateFromPool(c.player_id,POOL,QUERY,source_id=c.source_id,policy=POLICY)
        return (DrawMatching(c.player_id,QUERY,'skip',source_id=c.source_id,on_empty=(fallback,)),)
    registry.register_behavior(BODY,body)
    definition=CardDefinition(CARD,raw['name'],CardType.MINION,cost=4,attack=6,health=4,
        deathrattle=BODY,metadata=metadata_from_record(raw))
    registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
