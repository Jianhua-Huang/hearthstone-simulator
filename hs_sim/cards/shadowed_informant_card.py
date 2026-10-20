"""Shadowed Informant's native rotating Battlecry class and ordinary discovery."""
import json
from pathlib import Path

from hs_sim.engine.model import CardClass, CardDefinition, CardType, HandProgressSpec
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.rotating_discovery_classes import (RotateDiscoveryClass,
    RotatingDiscoveryClassProfile, source)
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_614'
BODY = 'cards.shadowed_informant.discover'
TICK = 'cards.shadowed_informant.rotate'
OWN = 'cards.shadowed_informant.owner_start'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/shadowed-informant-v1.json'
BATCH_HASH = '6954b951b12a64dba6f75c77e06942575996badbaca34b44502084717878bc62'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or [r['record']['id'] for r in data['cards']] != [CARD] or
            any(data[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Shadowed Informant requires its complete original source')
    raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS')) != ('MINION',2,2,2,12):
        raise TargetValidationError('Shadowed Informant changed its printed neutral body')
    return data


def register_shadowed_informant_card(registry):
    def rotate(c):
        native=source(c.source)
        if native is None:
            raise ValueError('Shadowed Informant lost its native discovery parameter')
        return (RotateDiscoveryClass(CardReference.capture(c.source),native.id,c.event),)

    def discover(c):
        if c.battlecry is None or c.battlecry.payload.discovery_class is None:
            raise ValueError('Shadowed Informant requires its original accepted Battlecry class')
        value=CardClass(c.battlecry.payload.discovery_class)
        return (DiscoverFromPool(c.player_id,'constructed.cards',
            PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(value,),include_neutral=False),
            source_id=c.source_id),)

    registry.register_trigger_condition(OWN,lambda c:c.event.player_id==c.player_id)
    registry.register_behavior(TICK,rotate)
    registry.register_behavior(BODY,discover)
    raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=2,attack=2,health=2,battlecry=BODY,
        hand_progress=HandProgressSpec('event',1,on_complete=TICK,repeat=True,event='turn_started',condition_id=OWN),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_rotating_discovery_class_profile(RotatingDiscoveryClassProfile(CARD))
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
