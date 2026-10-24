"""Reviewed native Beast donors; curated offer membership is separate."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PARTS = ('BE_193', 'CORE_BT_201', 'CORE_EX1_028', 'CORE_GIL_558', 'CS2_125',
    'CS2_127', 'CS2_169', 'GIL_562', 'ICC_905', 'LEG_CS3_037', 'LOOT_258',
    'NX2_050', 'TIME_053', 'UNG_810')
CORE_PORCUPINE = 'CORE_BT_201'
BASE_PORCUPINE = 'BT_201'
COLLECTIBLE_ROOTS = ()
DECK_IDENTITIES = {'CORE_BT_201': 'BT_201', 'CORE_EX1_028': 'EX1_028',
    'CORE_GIL_558': 'GIL_558'}
KEYWORD_TAGS = ('TAUNT', 'STEALTH', 'WINDFURY', 'POISONOUS', 'LIFESTEAL', 'RUSH')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-native-keyword-parts-v1.json'
BATCH_HASH = '51b543cbe87a20f67d424c30d59133e4f63d6a61c82eac39feb9236a609a8491'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    profiles = {cid: 'core-porcupine-alias' if cid == CORE_PORCUPINE else
        'plain-printed-keywords' for cid in PARTS}
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(row['record']['id'] for row in rows) != (*PARTS, BASE_PORCUPINE) or
            data['declaration_profiles'] != profiles or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False or any(data[key] for key in ('cards', 'dependencies',
                'evidence_only', 'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Native Zombeast donors lost their full original source or reviewed scope')
    return data


def register_zombeast_native_keyword_parts(registry):
    data = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Native Zombeast donors require one original registration')
    if BASE_PORCUPINE not in registry.crafted_minion_parts:
        raise TargetValidationError('Core Porcupine requires the existing reviewed native donor')
    base_raw = data['existing_dependencies'][-1]['record']
    base = registry.card(BASE_PORCUPINE)
    if (base.cost, base.attack, base.health, base.metadata) != (base_raw['cost'],
            base_raw['attack'], base_raw['health'], metadata_from_record(base_raw)):
        raise TargetValidationError('Core Porcupine changed its existing native reference')
    # Validate every declaration before installing any capability. Plain parts
    # cannot acquire unreviewed extra text through a later definition change.
    for row in data['existing_dependencies'][:-1]:
        raw = row['record']
        card = registry.card(raw['id'])
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or
                type(raw['cost']) is not int or not 0 <= raw['cost'] <= 5):
            raise TargetValidationError('Native Zombeast donor requires its complete low-cost minion face')
        metadata = metadata_from_record(raw)
        if raw['id'] in DECK_IDENTITIES:
            metadata = replace(metadata, deck_identity=DECK_IDENTITIES[raw['id']])
        if raw['id'] == CORE_PORCUPINE:
            expected = replace(base, id=card.id, name=raw['name'], metadata=metadata)
        else:
            keywords = tuple(Keyword[tag] for tag in KEYWORD_TAGS if raw['tags'].get(tag) == 1)
            expected = CardDefinition(card.id, raw['name'], CardType.MINION, cost=raw['cost'],
                attack=raw['attack'], health=raw['health'], keywords=keywords, metadata=metadata)
        if card != expected or (card.cost, card.attack, card.health) != (
                raw['cost'], raw['attack'], raw['health']):
            raise TargetValidationError('Unreviewed native Zombeast donor declaration: ' + card.id)
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
