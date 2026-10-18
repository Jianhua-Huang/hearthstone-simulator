"""Healing Rain delegates actual units to the common split/health interpreter."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import RandomSplitHealing
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

HEALING_RAIN = 'CORE_LOOT_373'
BODY = 'cards.native_split_healing.rain'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-split-healing-v1.json'
BATCH_HASH = '6ba33c252862db04c2e142cbf39c4e07cce1e14e8fd04a0933fa0b26fcee4449'
POLICY = 'original-spell-immune-base-healing-units-live-health-rules-v1'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['policy'] != POLICY or
            tuple(x['record']['id'] for x in d['cards']) != (HEALING_RAIN,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Healing Rain requires its complete original source and unit policy')
    row, = d['cards']
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Healing Rain complete original source row changed')
    return d


def register_native_split_healing_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'),raw['tags'].get('349')) != ('SPELL',3,8,4,1):
        raise TargetValidationError('Healing Rain requires its printed three-mana Shaman Nature spell')
    registry.register_behavior(BODY,lambda c:(RandomSplitHealing(c.player_id,c.cast.id,c.source_id,12),))
    card = CardDefinition(HEALING_RAIN,raw['name'],CardType.SPELL,cost=3,metadata=metadata_from_record(raw),
        spell_school=SpellSchool.NATURE,on_play=BODY)
    registry.register_card(card)
    if HEALING_RAIN not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
