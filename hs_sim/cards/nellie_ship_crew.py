"""Nellie's three actual Pirate selections belong to the original Ship."""
import json
from pathlib import Path

from hs_sim.engine.colossal_crew import ColossalCrewProfile, PROFILE, discover
from hs_sim.engine.effects import AddToHand
from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, CostSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/nellie-ship-crew-v1.json'
BATCH_HASH = 'd85f899c344555988248e2b9ed6ab24ba95b010205e722725a9f09fd353ab8c2'
CARD, SHIP = 'TSC_660', 'TSC_660t'
PROFILE_ID = 'native-nellie-original-ship-crew-v1'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (CARD, SHIP)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != (CARD,) or
            tuple(r['record']['id'] for r in data['dependencies']) != (SHIP,) or
            tuple(r['record']['id'] for r in data['evidence_only']) != ('TSC_660e', 'TSC_660e2') or
            data['existing_dependencies'] or data['skipped'] or data['profile_id'] != PROFILE_ID or
            data['discoveries'] != 3 or data['crew_cost'] != 1 or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Nellie requires its complete original body, Ship and two enchantments')
    if any(canonical_digest(r['record']) != r['record_sha256'] for r in
            data['cards']+data['dependencies']+data['evidence_only']):
        raise TargetValidationError('Nellie lost a complete original source row')
    if canonical_digest(json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))) != data['reference_canonical_sha256']:
        raise TargetValidationError('Nellie lost the independent full past reference')
    return data


def register_nellie_ship_crew(registry):
    data = load_batch(); raw = data['cards'][0]['record']; child = data['dependencies'][0]['record']
    if any(cid in registry.cards for cid in (CARD, SHIP)) or PROFILE_ID in registry.colossal_crew_profiles:
        raise TargetValidationError('Nellie cannot replace an existing native body or crew declaration')
    if ((raw['cost'], raw['attack'], raw['health']) != (7, 5, 5) or
            (child['cost'], child['attack'], child['health']) != (5, 2, 6)):
        raise TargetValidationError('Nellie requires its original seven-mana body and 2/6 Ship')
    def choose(c): return discover(c, registry, PROFILE_ID)
    def deliver(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec != PROFILE:
            raise UnsupportedDefinitionError('Nellie Ship requires its actual accepted native crew')
        return tuple(AddToHand(c.player_id, link.card_id, c.source_id, cost=CostSpec(set_to=1))
            for link in memory.discoveries)
    definitions = (
        CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=5, health=5,
            metadata=metadata_from_record(raw), keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec(SHIP, 'right'),), battlecry=data['producer_behavior_id']),
        CardDefinition(SHIP, child['name'], CardType.MINION, cost=5, attack=2, health=6,
            metadata=metadata_from_record(child), keywords=(Keyword.TAUNT,),
            deathrattle=data['deathrattle_behavior_id'], native_deathrattle=PROFILE),
    )
    for card in definitions:
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id) != PoolCard.from_definition(card):
            raise TargetValidationError('Nellie cannot replace independent printed metadata')
    registry.register_behavior(data['producer_behavior_id'], choose)
    registry.register_behavior(data['deathrattle_behavior_id'], deliver)
    for card in definitions:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_colossal_crew_profile(ColossalCrewProfile(PROFILE_ID, CARD, SHIP,
        data['producer_behavior_id'], data['deathrattle_behavior_id']))
