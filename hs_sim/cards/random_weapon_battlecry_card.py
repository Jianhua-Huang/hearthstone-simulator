"""Stadium Announcer delegates both equipment results and native Rewind."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword,RewindSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_weapon_equipment import EquipRandomWeapons
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TIME_034'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/random-weapon-battlecry-v1.json'
BATCH_HASH='7824d1891cd249428f58c2b7f3bd6c1a5d881fc708c407000f86fa772514ecf2'
BEHAVIOR='cards.stadium_announcer.battlecry'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or data['dependencies']or data['evidence_only']:
        raise TargetValidationError('Stadium Announcer complete source pin changed')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Stadium Announcer original record changed')
    return data


def register_random_weapon_battlecry_card(registry):
    def battlecry(c):
        if c.battlecry is None:raise ValueError('Stadium Announcer requires actual Battlecry execution')
        return (EquipRandomWeapons(c.player_id,c.source_id),)
    registry.register_behavior(BEHAVIOR,battlecry)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('REWIND'))!=('MINION',4,3,3,1):
        raise TargetValidationError('Unexpected Stadium Announcer native shape')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.REWIND,),rewind=RewindSpec(),battlecry=BEHAVIOR,
        metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
