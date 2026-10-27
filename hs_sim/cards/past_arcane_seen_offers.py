"""Pocket Dimension reuses original discovery menus and ordinary delivery."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-seen-offers-v1.json'
BATCH_HASH = '9b2e337696b3c57dc1a6d955889c19b671770c011aed652321ab3abfc0231d13'
CARD = 'GDB_133'
LEAVES = DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_seen_offers.'
QUERY = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(x['record']['id']for x in data['dependencies']) != LEAVES or
            len(data['official_observations']) != 2 or CARD not in reference['candidate_ids'] or
            any(data[k]for k in ('cards','existing_dependencies','evidence_only','skipped','numeric_normalizations',
                'display_normalizations','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record']) != x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Pocket Dimension changed its complete original source or finite policy')
    return data


def register_past_arcane_seen_offers(registry):
    raw = load_batch()['dependencies'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL')) != ('SPELL',4,4,1):
        raise TargetValidationError('Pocket Dimension requires its original Arcane Mage face')
    if CARD in registry.cards:
        raise TargetValidationError('Pocket Dimension cannot overwrite its original identity')
    card = CardDefinition(CARD,raw['name'],CardType.SPELL,cost=4,spell_school=SpellSchool.ARCANE,
        on_play=PREFIX+CARD,metadata=metadata_from_record(raw))
    registry._validate_card(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD) != PoolCard.from_definition(card):
        raise TargetValidationError('Pocket Dimension differs from its original printed metadata')
    registry.register_behavior(PREFIX+CARD,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',QUERY,
        source_id=c.source_id,repeat_until_seen=True),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
