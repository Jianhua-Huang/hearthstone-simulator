"""The actual Caverns reprint identity reached by the extended Assemble list."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, ORIGINAL = 'WON_317', 'OG_330'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-huckster-reprint-v1.json'
BATCH_HASH = 'ed3a5adc11c6d9f49f001f7005d0d9cfc925ace95a3f45252a62131cf2f2abce'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = value['cards']+value['existing_dependencies']
    if (canonical_digest(value) != BATCH_HASH or
            [row['record']['id'] for row in rows] != [CARD, ORIGINAL] or
            any(value[k] for k in ('dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Huckster reprint lost its complete reviewed source')
    dbf = {row['record']['id']: row['record']['dbf_id'] for row in rows}
    if (len(value['official_faces']) != 4 or
            any(dbf[ORIGINAL if f['card_id']==CARD else CARD] not in f['face']['copyOfCardId']
                for f in value['official_faces'])):
        raise TargetValidationError('Huckster reprint lost its mutual original primary identity')
    return value


def register_assemble_huckster_reprint(registry):
    value = load_batch(); raw = value['cards'][0]['record']
    original = registry.card(ORIGINAL); fragment = registry.assemble_templates[ORIGINAL]
    metadata = replace(metadata_from_record(raw), deck_identity=value['deck_identity'])
    if (canonical_digest(asdict(original)) != value['reviewed_original_definition_sha256'] or
            canonical_digest(asdict(fragment)) != value['reviewed_original_fragment_sha256'] or
            raw['type'] != 'MINION' or metadata != original.metadata or
            any(getattr(original,k) != raw[k] for k in ('cost', 'attack', 'health'))):
        raise TargetValidationError('Huckster reprint changed its original native face or fragment')
    card = replace(original, id=CARD, name=raw['name'], metadata=metadata)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_assemble_template(replace(fragment, card_id=CARD))
