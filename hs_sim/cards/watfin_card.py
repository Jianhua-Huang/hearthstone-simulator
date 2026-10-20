"""Actual Watfin; altered offers and physical lifecycle belong to the engine."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.suspicious_discoveries import DiscoverSuspiciousMinion, SuspiciousDiscoveryProfile
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_EVENT_100'
TOKEN = 'JAIL_EVENT_100t'
BEHAVIOR = 'cards.watfin.discover'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/watfin-suspicious-v1.json'
BATCH_HASH = 'a136099c100e295df710262b2671a64219204c8d554fdbd9adf67417f3fafa58'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = (*data['cards'], *data['dependencies'], *data['evidence_only'])
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            tuple(r['record']['id'] for r in data['dependencies']) != (TOKEN,) or
            tuple(r['record']['id'] for r in data['evidence_only']) != ('JAIL_EVENT_100e',) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows) or
            canonical_digest(data['name_catalog']) != data['name_catalog_sha256']):
        raise TargetValidationError('Watfin requires the complete reviewed original source and name domain')
    return data


def register_watfin_card(registry):
    data = load_batch()
    def discover(c):
        source = c.state.entities[c.source_id]
        return (DiscoverSuspiciousMinion(c.player_id, SourceAllocationFact.capture(c.state, source),
            BoardPresenceReference.capture(c.state, source.id) if source.kind == CardType.MINION and source.zone == Zone.BOARD else None,
            CARD),)
    registry.register_behavior(BEHAVIOR, discover)
    for item in (*data['cards'], *data['dependencies']):
        raw = item['record']; meta = metadata_from_record(raw)
        if canonical_digest(asdict(meta)) != canonical_digest(item['metadata']):
            raise TargetValidationError('Watfin metadata changed')
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=meta,
            manual_playable=raw['id'] == CARD,
            battlecry=BEHAVIOR if raw['id'] == CARD else None)
        registry.register_card(card)
        if raw['id'] == CARD:
            pool = PoolCard.from_definition(card)
            if CARD in registry.pool_cards:
                if registry.pool_cards[CARD] != pool: raise TargetValidationError('Watfin changed an existing pool declaration')
            else: registry.register_pool_card(pool)
    registry.register_suspicious_discovery_profile(SuspiciousDiscoveryProfile(CARD,
        tuple(tuple(row) for row in data['name_catalog']), tuple(data['tribes'])))
