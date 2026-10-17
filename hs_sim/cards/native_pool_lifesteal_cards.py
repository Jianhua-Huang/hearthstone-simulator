"""One real Osk face declares both granted keywords in the original pool entry."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-pool-lifesteal-v1.json'
BATCH_HASH = '4f029c1c56d2d7a044edd372a98e1acf0727fbcfcc462595edadd9e408f8bcc8'
FORM = 'TLC_452t20'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=6, max_cost=6)
KEYWORDS = (Keyword.TAUNT, Keyword.LIFESTEAL)
BODY = 'cards.native_pool_lifesteal.summon'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (FORM,)
            or tuple(x['record']['id'] for x in data['evidence_only']) != ('TLC_452',)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Native Taunt/Lifesteal source changed')
    return data


def register_native_pool_lifesteal_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'], raw['tags'].get('BATTLECRY')) != ('MINION', 6, 6, 6, False, 1):
        raise TargetValidationError('Native Osk face requires its exact printed body')
    registry.register_behavior(BODY, lambda c: (SummonFromPool(c.player_id, POOL_ID, QUERY,
        source_id=c.source_id, cause=SummonCause.capture(c), entry_keywords=KEYWORDS),))
    card = CardDefinition(FORM, raw['name'], CardType.MINION, cost=6, attack=6, health=6,
        metadata=metadata_from_record(raw), battlecry=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
