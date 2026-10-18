"""Kong Zo's single spell discovery and two actual destination choices."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import DiscoverFromPool,PoolCard
from hs_sim.engine.discovery_destinations import MODE,QUERY,OPTIONS
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_517';BEHAVIOR='cards.kong_zo.battlecry'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discovered-spell-destination-v1.json'
BATCH_HASH='64d1573085b2dc5593a843ac691f55833e2d05a18b68a4ac852c11e2973aff2f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in data['dependencies'])!=OPTIONS or data['evidence_only']):
        raise TargetValidationError('Kong Zo requires its complete original spell and two option faces')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Kong Zo original source changed')
    return data


def register_discovered_spell_destination_card(registry):
    def battlecry(c):
        if c.battlecry is None:raise ValueError('Kong Zo requires actual Battlecry execution')
        return (DiscoverFromPool(c.player_id,'constructed.cards',QUERY,source_id=c.source_id,destination=MODE),)
    registry.register_behavior(BEHAVIOR,battlecry)
    d=load_batch();raw=d['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',3,3,4):raise TargetValidationError('Unexpected Kong Zo native shape')
    c=CardDefinition(CARD,raw['name'],CardType.MINION,cost=3,attack=3,health=4,battlecry=BEHAVIOR,
        metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(c)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(c))
    for row in d['dependencies']:
        raw=row['record']
        if (raw['type'],raw['cost'],raw['collectible'])!=('SPELL',3,False):raise TargetValidationError('Unexpected Kong Zo choice-only face')
        registry.register_card(CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=3,choice_only=True,metadata=metadata_from_record(raw)))
