"""The original Frozen Mammoth and its reviewed native composition donor."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.school_freeze import SchoolFreezeProfile, after_cast
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'AV_128'
BODY = 'cards.frozen_mammoth.after_fire'
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/frozen-mammoth-v1.json'
BATCH_HASH = '5510b8615f7a3b9bdeee833a9fe008a0b6fa883ee78af936fb5b6cd90927d991'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256'] or
            len(data['official_observations']) != 2 or
            {x['locale'] for x in data['official_observations']} != {'en_US', 'zh_CN'} or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Frozen Mammoth lost its complete original evidence')
    reference = json.loads(BATCH_PATH.with_name('zombeast-local-reference-v1.json').read_text(encoding='utf-8'))
    if (canonical_digest(reference) != data['reference_canonical_sha256'] or
            CARD not in reference['second_reference_ids']):
        raise TargetValidationError('Frozen Mammoth lost its independently retained secondary identity')
    return data


def register_frozen_mammoth_card(registry):
    raw = load_batch()['cards'][0]['record']; meta = metadata_from_record(raw)
    if ((raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health']) !=
            ('MINION', True, 4, 6, 7) or meta.tribes != ('beast',) or
            CARD in registry.cards or CARD in registry.pool_cards):
        raise TargetValidationError('Unreviewed complete native Frozen Mammoth face')
    registry.register_behavior(BODY, lambda c: after_cast(c, registry, BODY))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=6, health=7,
        metadata=meta, triggers=(TriggerSpec('spell_cast_finished', BODY),))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_school_freeze_profile(SchoolFreezeProfile(CARD, BODY))
    registry.register_crafted_minion_part(CARD)
