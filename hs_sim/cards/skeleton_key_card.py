"""The Skeleton Key delegates refresh controls, damage and delivery to the engine."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'JAIL_319'
CONTROL = 'JAIL_319t'
BODY = 'cards.skeleton_key.play'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/skeleton-key-v1.json'
BATCH_HASH = '679016f9f4089dc82cb2fbe3003a29cf3760293399e8467dd78fd2e799850064'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (CONTROL,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (ROOT+'e',) or
            data['existing_dependencies'] or
            data['numeric_normalizations'] != {CONTROL: {'cost': 0}} or
            any(canonical_digest(x['record']) != x['record_sha256']
                for section in ('cards', 'dependencies', 'evidence_only') for x in data[section])):
        raise TargetValidationError('Skeleton Key requires its complete card, control and raw evidence')
    return data


def register_skeleton_key_card(registry):
    data = load_batch()
    raw = data['cards'][0]['record']
    control = data['dependencies'][0]['record']
    if (raw['type'] != 'SPELL' or raw['cost'] != 1 or raw['tags'].get('SPELL_SCHOOL') != 1 or
            control['type'] != 'SPELL' or control['cost'] is not None or 'COST' in control['tags'] or
            control['tags'].get('HIDE_STATS') != 1):
        raise TargetValidationError('Skeleton Key changed its original spell or hidden control face')
    registry.register_behavior(BODY, lambda c: (DiscoverFromPool(c.player_id, 'constructed.cards',
        PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current'),
        source_id=c.source_id, refresh_card_id=CONTROL),))
    registry.register_card(CardDefinition(CONTROL, control['name'], CardType.SPELL, cost=0,
        choice_only=True,
        metadata=replace(metadata_from_record(control), deck_identity=CONTROL)))
    card = CardDefinition(ROOT, raw['name'], CardType.SPELL, cost=1, spell_school=SpellSchool.ARCANE,
        on_play=BODY, metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
