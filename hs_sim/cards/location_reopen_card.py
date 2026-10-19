"""Welcome Home uses ordinary location refresh, ability grants and pool summons."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import GrantDeathrattle
from hs_sim.engine.locations import RefreshLocation
from hs_sim.engine.model import CardDefinition, CardType, TargetSpec, Zone
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'TIME_EVENT_997'
BODY = 'cards.location_reopen.play'
DEATH = 'cards.location_reopen.death'
QUERY = PoolQuery(kinds=(CardType.MINION,), min_cost=3, max_cost=3, collectible=True)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/location-reopen-v1.json'
BATCH_HASH = '3cc36cf2218f2770f2e60bb18c476cacce438bf696bdd42d793f0b18e25e3b33'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (ROOT+'e',) or
            data['dependencies'] or data['existing_dependencies'] or
            any(canonical_digest(x['record']) != x['record_sha256']
                for section in ('cards', 'evidence_only') for x in data[section])):
        raise TargetValidationError('Welcome Home requires its complete source and enchantment evidence')
    return data


def register_location_reopen_card(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'SPELL' or raw['cost'] != 3 or 'SPELL_SCHOOL' in raw['tags']:
        raise TargetValidationError('Welcome Home changed its printed three-mana spell')
    registry.register_behavior(BODY, lambda c: (RefreshLocation(c.target_id, c.source_id),
        GrantDeathrattle(c.target_id, DEATH, c.source_id)))
    registry.register_behavior(DEATH, lambda c: (GenerateFromPool(c.player_id, 'constructed.cards', QUERY,
        source_id=c.source_id, destination='board', cause=SummonCause.capture(c)),))
    card = CardDefinition(ROOT, raw['name'], CardType.SPELL, cost=3, on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.LOCATION,)),
        metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
