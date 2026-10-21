"""Raviz declares two independent native continuous board-edge contributions."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword, KeywordAuraSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_230'
LEFT = KeywordAuraSpec(Keyword.RUSH, 'friendly_leftmost_minion', include_self=True)
RIGHT = KeywordAuraSpec(Keyword.IMMUNE_WHILE_ATTACKING, 'friendly_rightmost_minion', include_self=True)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/positional-keyword-auras-v1.json'
BATCH_HASH = '7a4e7c7a0c7a9209c9388e03471df1b25f8d17a406baa899a00c06881eff67bb'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped'))):
        raise TargetValidationError('Positional auras lost their complete original Raviz face')
    return data


def register_positional_keyword_aura_card(registry):
    row = load_batch()['cards'][0]; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
             raw['tags'].get('CARDRACE'), raw['tags'].get('AURA')) != ('MINION', 4, 4, 4, 14, 20, 1)):
        raise TargetValidationError('Raviz requires its actual four-cost 4/4 Beast aura source')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=4, health=4,
        keyword_auras=(LEFT, RIGHT), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
