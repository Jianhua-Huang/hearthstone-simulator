"""Gelbin's Triumph selects from the active format's complete Aura inventory."""
import json
from pathlib import Path

from hs_sim.engine.aura_duration import GenerateAuraWithExtraTurn
from hs_sim.engine.model import CardClass, CardDefinition, CardType
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_621'
BODY = 'cards.gelbin_triumph.generate'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/generated-aura-duration-v1.json'
BATCH_HASH = '4ceeda69358407911d50b7bd82e27b5dc672ef6d7f73254a1d5c83f0d849b321'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,):
        raise TargetValidationError('Gelbin Triumph requires its complete reviewed Aura source')
    all_rows = data['cards'] + data['existing_dependencies'] + data['evidence_only']
    for row in all_rows:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Aura evidence')
    if data['aura_ids'] != sorted(row['record']['id'] for row in all_rows
                                if row['record']['tags'].get('PALADIN_AURA') == 1):
        raise TargetValidationError('Aura domain differs from its complete explicit raw tags')
    return data


def register_generated_aura_duration_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']
    query = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified',
        classes=(CardClass.PALADIN,), include_neutral=False, card_ids=tuple(data['aura_ids']))
    registry.register_behavior(BODY, lambda c: (GenerateAuraWithExtraTurn(
        GenerateFromPool(c.player_id, 'constructed.cards', query, source_id=c.source_id)),))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
