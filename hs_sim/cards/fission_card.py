"""Divergence delegates the actual hand split to the shared stored-card flow."""
import json
from pathlib import Path

from hs_sim.engine.hand_minion_split import SplitRandomHandMinion
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_030'
BODY = 'cards.divergence.split'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/fission-v1.json'
BATCH_HASH = '6bdd39a63e6e51601fda279349a2c6839f3a457f597932d67a3e590e3b252d86'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TIME_030e1', 'TIME_030e2') or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('Divergence lost its complete original split source')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Divergence source pin changed')
    return data


def register_fission_card(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (SplitRandomHandMinion(c.player_id, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
        spell_school=SpellSchool.SHADOW, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
