"""Illidari Studies separates its ordinary discovery from the next-card price."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import CardAbilityCondition, CardDefinition, CardType, CostSpec, Keyword
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/printed-outcast-study-v1.json'
BATCH_HASH = '4cd2e4a398479573273c8f28368baa287bbb46f5e478f574127121daee25d222'
STUDIES, LEGACY = 'CORE_YOP_001', 'YOP_001'
PREFIX = 'cards.printed_outcast_study.'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(collectible=True, class_mode='current', keywords_all=(Keyword.OUTCAST,))
PRINTED_OUTCAST = CardAbilityCondition('outcast', basis='printed')
NEXT_COST = CostSpec(delta=-1, ability=PRINTED_OUTCAST)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (STUDIES,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (LEGACY,) or
            any(data[k] for k in ('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Illidari Studies requires its complete reviewed source and legacy identity')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Illidari Studies original source row is incomplete')
    return data


def register_printed_outcast_study_cards(registry):
    data = load_batch();raw = data['cards'][0]['record'];legacy = data['evidence_only'][0]['record']
    if (raw['tags'].get('858') != legacy['dbf_id'] or legacy['id'] != LEGACY or
            (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('DISCOVER')) != ('SPELL',1,14,1) or
            (legacy['type'],legacy['cost'],legacy['tags'].get('CLASS')) != ('SPELL',1,14)):
        raise TargetValidationError('Studies lost its exact current face or explicit raw858 legacy edition')
    registry.register_behavior(PREFIX+'study', lambda c: (
        DiscoverFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id),
        AddCostModifier(c.player_id, NEXT_COST, uses_remaining=1, source_id=c.source_id),))
    card = CardDefinition(STUDIES, raw['name'], CardType.SPELL, cost=1,
        metadata=replace(metadata_from_record(raw), deck_identity=LEGACY), on_play=PREFIX+'study')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
