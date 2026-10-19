"""Faceless Enigma reuses contextual offers and actual generated spell casts."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pool_offers import ChooseFromPools, PoolOfferGroup
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_860'
BODY = 'cards.faceless_enigma.offer'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.SPELL,),collectible=True,keywords_all=(Keyword.SECRET,))
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/secret-pair-v1.json'
BATCH_HASH = '6b8ee568b321df031973d033a433090399494bdf9691b07b47ccb6c73cdc2611'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            any(data[k] for k in ('dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Faceless Enigma requires its complete reviewed original sources')
    for row in (*data['cards'],*data['existing_dependencies']):
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Secret pair original source pin changed')
    raw = data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags']['CLASS'],
            raw['tags']['RARITY'],raw['tags']['BATTLECRY'])!=('MINION',2,2,2,True,4,4,1):
        raise TargetValidationError('Original two-cost Mage Epic Battlecry body changed')
    if any(x['record']['type']!='SPELL' or x['record']['tags'].get('SECRET')!=1
            for x in data['existing_dependencies']):
        raise TargetValidationError('Reviewed Secret dependency is not an original Secret spell')
    return data


def register_secret_pair_card(registry):
    registry.register_behavior(BODY,lambda c:(ChooseFromPools(c.player_id,
        (PoolOfferGroup(POOL_ID,QUERY,2),),source_id=c.source_id,delivery='secret_pair',
        prompt='选择为自己施放的奥秘；另一个为对手施放'),))
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=2,attack=2,health=2,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
