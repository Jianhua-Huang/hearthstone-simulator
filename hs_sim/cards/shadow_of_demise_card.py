"""The empty Shadow is unplayable; its held native source copies accepted spells."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CORE_RLK_567'
IDENTITY = 'RLK_567'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/shadow-of-demise-v1.json'
BATCH_HASH = '6a16986fbaa8e682dc1c03dde139b188ae0b1af3d82a15cb5cd8f104342c5168'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (IDENTITY, 'RLK_567e', 'RLK_567e2') or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            data['printed_zero_cost'] != 0 or data['deck_identity'] != IDENTITY):
        raise TargetValidationError('Shadow requires its complete original source and explicit zero-cost review')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Shadow source pin changed')
    return data


def register_shadow_of_demise_card(registry):
    data = load_batch()
    raw = data['cards'][0]['record']
    if (raw['type'] != 'SPELL' or raw['cost'] is not None or 'COST' in raw['tags'] or
            raw['tags']['LITERALLY_UNPLAYABLE'] != 1 or raw['tags']['CLASS'] != 7 or
            raw['tags']['SPELL_SCHOOL'] != 6 or raw['tags']['858'] != data['evidence_only'][0]['record']['dbf_id']):
        raise TargetValidationError('Original unformed Shadow lost its real face or Core identity')
    # All text is the native held source. Its literal unformed face has no cast body.
    registry.register_behavior('cards.shadow_of_demise.empty', lambda c: ())
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=0, manual_playable=False,
        on_play='cards.shadow_of_demise.empty', spell_school=SpellSchool.SHADOW,
        metadata=replace(metadata_from_record(raw), deck_identity=IDENTITY))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_mirror(CARD)
