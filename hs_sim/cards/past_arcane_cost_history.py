"""The Galactic Projection Orb composes cost-grouped history and target preference."""
import json
from pathlib import Path

from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_history import RecastFromHistory, SpellHistoryQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-cost-history-v1.json'
BATCH_HASH = '60f92a011d9c9d326f9ce4cd48babc43eb955d84c375fdc9a95294339020df78'
CARD = 'TOY_378'
LEAVES = DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_cost_history.'
QUERY = SpellHistoryQuery(cards=PoolQuery(exclude_card_ids=(CARD,)))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(x['record']['id']for x in data['dependencies']) != LEAVES or
            len(data['official_observations']) != 2 or CARD not in reference['candidate_ids'] or
            any(data[k]for k in ('cards','existing_dependencies','evidence_only','skipped','numeric_normalizations',
                'display_normalizations','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record']) != x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Orb changed its complete original source or finite history policy')
    return data


def register_past_arcane_cost_history(registry):
    raw = load_batch()['dependencies'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL')) != ('SPELL',10,4,1):
        raise TargetValidationError('Orb requires its exact original ten-cost Arcane Mage face')
    if CARD in registry.cards:raise TargetValidationError('Orb cannot overwrite its original identity')
    card = CardDefinition(CARD,raw['name'],CardType.SPELL,cost=10,spell_school=SpellSchool.ARCANE,
        on_play=PREFIX+CARD,metadata=metadata_from_record(raw))
    registry._validate_card(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD) != PoolCard.from_definition(card):
        raise TargetValidationError('Orb differs from its original printed metadata')
    registry.register_behavior(PREFIX+CARD,lambda c:(RecastFromHistory(c.player_id,QUERY,distinct='cost',
        selection='cost_ascending',source_id=c.source_id,target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
