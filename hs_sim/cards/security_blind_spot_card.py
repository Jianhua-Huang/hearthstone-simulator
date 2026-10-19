"""Low Security Wing uses ordinary pool delivery and a later-other-play hand gate."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardClass, CardDefinition, CardType
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_987'
BODY = 'cards.security_blind_spot.generate'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='specified',
    classes=(CardClass.SHAMAN,), include_neutral=False)
GRANT = CreatedMinionGrant(special='other_play_lock')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/security-blind-spot-v1.json'
BATCH_HASH = 'be0c6be7221cc5fb68d119eb579b7d124926781700e4da52f3ab3db8080aebba'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Low Security Wing requires its complete original source and primary faces')
    row, = d['cards']; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'],raw['cost'],raw['health'],raw['collectible'],raw['tags']['CLASS'],raw['tags']['RARITY']) !=
            ('LOCATION',1,3,True,8,4)):
        raise TargetValidationError('Original one-cost three-durability Shaman Location changed')
    return d


def register_security_blind_spot_card(registry):
    registry.register_behavior(BODY,lambda c:(GenerateFromPool(c.player_id,POOL_ID,QUERY,
        source_id=c.source_id,minion_grant=GRANT),))
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD,raw['name'],CardType.LOCATION,cost=1,durability=3,on_use=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
