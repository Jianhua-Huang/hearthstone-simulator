"""Bulwark of Azzinoth's actual Standard weapon-pool dependency."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.weapon_damage_replacement import RULE
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CORE_BT_781'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/weapon-damage-replacement-v1.json'
BATCH_HASH = '0d8aaa4d38411b773e4d9e59b6a357be57500847818c0388ef26df411fce0877'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('BT_781',)):
        raise TargetValidationError('Bulwark requires its complete native Core face and original identity evidence')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Bulwark complete original record changed')
    return data


def register_weapon_damage_replacement_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']
    original = data['evidence_only'][0]['record']
    if raw['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID') != original['dbf_id']:
        raise TargetValidationError('Bulwark lost its actual original copy identity')
    card = CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=raw['cost'],attack=raw['attack'],
        durability=raw['health'],health_rules=(RULE,),
        metadata=replace(metadata_from_record(raw),deck_identity=original['id']))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
