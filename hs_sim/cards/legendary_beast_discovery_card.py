"""Beast Speaker Taka consumes one ordinary pool selection, without a hand copy."""
import json
from pathlib import Path

from hs_sim.engine.discovery_memory import DeathrattleDiscoveryTarget, PROFILE, QUERY
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pools import DiscoverFromPool, PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'DINO_430'
PREFIX = 'cards.legendary_beast_memory.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/legendary-beast-discovery-v1.json'
BATCH_HASH = '1ace42d77ba882b98ad4b5634235e0508b87e6d62b220729175994920d144562'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('DINO_430e',) or
            data['dependencies'] or data['existing_dependencies'] or data['skipped']):
        raise TargetValidationError('Taka requires its complete original body and enchantment evidence')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Taka source row')
    return data


def register_legendary_beast_discovery_card(registry):
    def discover(c):
        if c.battlecry is None:
            raise UnsupportedDefinitionError('Taka discovery requires its original Battlecry')
        ref = MinionReference.capture(c.source) if c.source.kind == CardType.MINION and c.source.zone == Zone.BOARD else None
        abilities = () if ref is None else tuple(a.id for a in active_abilities(c.source, 'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec == PROFILE)
        return (DiscoverFromPool(c.player_id, 'constructed.cards', QUERY, source_id=c.source_id,
            destination='memory', memory_target=DeathrattleDiscoveryTarget(c.battlecry.id, ref, abilities)),)
    def summon(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec != PROFILE:
            raise UnsupportedDefinitionError('Taka summon requires its actual native Deathrattle memory')
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(link.card_id),), cause)
            for link in memory.discoveries)
    registry.register_behavior(PREFIX+'discover', discover)
    registry.register_behavior(PREFIX+'summon', summon)
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 7, 2, 2) or
            raw['tags'].get('BATTLECRY') != 1 or raw['tags'].get('DEATHRATTLE') != 1):
        raise TargetValidationError('Taka changed its complete original body')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=2, health=2,
        battlecry=PREFIX+'discover', deathrattle=PREFIX+'summon', native_deathrattle=PROFILE,
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
