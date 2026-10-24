"""Plain cross-set materials; exact aliases are not a curated pool policy."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DEFINITIONS = ('CS2_119', 'CS2_120', 'CS2_172', 'DMF_190', 'DRG_065', 'EX1_017', 'EX1_170', 'GIL_143', 'GVG_071', 'OG_325', 'OG_326', 'UNG_808', 'UNG_814')
EXISTING = ('EX1_028', 'GIL_558')
PARTS = DEFINITIONS + EXISTING
# These are reachable-content candidates, not newly legal Standard roots.
COLLECTIBLE_ROOTS = ()
KEYWORD_TAGS = ('TAUNT', 'STEALTH', 'WINDFURY', 'CHARGE', 'POISONOUS',
    'DIVINE_SHIELD', 'RUSH', 'LIFESTEAL', 'REBORN')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-plain-legacy-parts-v1.json'
BATCH_HASH = '97b20ac749d949ca915eff6f979b8abcb865ed18f47d2a6a9fecb945ab38870d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards'] + data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['definition_ids']) != DEFINITIONS or
            tuple(data['existing_donor_ids']) != EXISTING or tuple(data['native_part_ids']) != PARTS or
            tuple(row['record']['id'] for row in rows) != PARTS or
            set(data['native_keywords']) != set(PARTS) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows) or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Plain material batch lost its full reviewed source')
    return data


def register_zombeast_plain_legacy_parts(registry):
    data = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Plain materials require one original native approval')
    definitions = []
    # Validate the entire new/existing batch before any catalog mutation.
    for row in data['cards'] + data['existing_dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or
                type(raw['cost']) is not int or not 0 <= raw['cost'] <= 5):
            raise TargetValidationError('Plain material requires its original low-cost minion face')
        keywords = tuple(Keyword[k] for k in KEYWORD_TAGS if raw['tags'].get(k) == 1)
        if tuple(data['native_keywords'][cid]) != tuple(k.value for k in keywords):
            raise TargetValidationError('Plain material changed its exact printed keyword declaration')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], keywords=keywords,
            metadata=metadata_from_record(raw))
        registry._validate_card(card)
        if cid in DEFINITIONS:
            if cid in registry.cards or cid in registry.pool_cards:
                raise TargetValidationError('New plain material collides with an existing exact identity')
            definitions.append(card)
        elif registry.card(cid) != card or registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Existing plain material gained an unreviewed extra declaration')
    for card in definitions:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
