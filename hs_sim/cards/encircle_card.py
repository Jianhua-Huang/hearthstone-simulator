"""Encircle composes five fixed entries and one attributed opponent pool entry."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, TOKEN = 'BE_265', 'BE_873t'
BODY = 'cards.encircle.summon'
POOL = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), min_cost=1, max_cost=1, collectible=True)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/encircle-v1.json'
BATCH_HASH = '713d9e9a1afe0c79d528a7a7cb35ccf2f7b6095f35c01bfcf43ea6a70efa18aa'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (TOKEN,) or
            any(data[k] for k in ('dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['existing_dependencies'])):
        raise TargetValidationError('Encircle lost its complete original root or existing Shredclaw')
    return data


def register_encircle_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']; token = data['existing_dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('RARITY')) != ('SPELL', 6, 14, 4):
        raise TargetValidationError('Encircle requires its original six-cost Demon Hunter Epic spell')
    expected = CardDefinition(TOKEN, token['name'], CardType.MINION, cost=2, attack=3, health=1,
        keywords=(Keyword.RUSH,), metadata=metadata_from_record(token))
    if registry.card(TOKEN) != expected:
        raise TargetValidationError('Encircle must reuse the unchanged original Shredclaw definition')
    def body(c):
        cause = SummonCause.capture(c)
        fixed = tuple(SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), cause) for _ in range(5))
        return (*fixed, SummonFromPool(3-c.player_id, POOL, QUERY, source_id=c.source_id, cause=cause))
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=6, on_play=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
