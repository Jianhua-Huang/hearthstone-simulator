"""An explicitly evidenced zero-cost material; retired Core is evidence only."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'ICC_023'
RETIRED_CORE = 'CORE_ICC_023'
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-zero-penguin-v1.json'
BATCH_HASH = '5ae6c600f73f91bf0da2d47d25b475cb4d7c86980910f232db3738f784b65d6b'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards'] + data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != (CARD,) or
            tuple(row['record']['id'] for row in rows) != (CARD, RETIRED_CORE) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows) or
            data['evidence_only'][0]['record']['card_set_id'] != 1810 or
            data['numeric_normalizations'] != {CARD: {'cost': 0}} or
            len(data['official_observations']) != 2 or
            {face['locale'] for face in data['official_observations']} != {'zh_CN', 'en_US'} or
            any(face['card_id'] != CARD or face['face']['manaCost'] != 0 for face in data['official_observations']) or
            data['retired_core_evidence_only'] is not True or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('dependencies', 'existing_dependencies', 'skipped', 'display_normalizations'))):
        raise TargetValidationError('Penguin requires complete original evidence and explicit primary zero cost')
    return data


def register_zombeast_zero_penguin(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', None, 1, 1) or 'COST' in raw['tags']:
        raise TargetValidationError('Only the reviewed absent Penguin COST can use this primary zero declaration')
    if CARD in registry.cards or CARD in registry.pool_cards or CARD in registry.crafted_minion_parts:
        raise TargetValidationError('Penguin requires its exact new original identity')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=0, attack=1, health=1,
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_crafted_minion_part(CARD)
