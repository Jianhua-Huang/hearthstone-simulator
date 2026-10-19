"""Acolyte of Infinity owns one remembered local cost attachment per Battlecry."""
import json
from pathlib import Path

from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.linked_hand_costs import (SetRandomHandCostForDeathrattle, RestoreRememberedCost,
    INFINITE_COST_VALUE, INFINITE_COST_POLICY)
from hs_sim.engine.model import CardDefinition, CardType, NativeDeathrattleSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'END_018'
PREFIX = 'cards.acolyte_of_infinity.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/infinite-cost-v1.json'
BATCH_HASH = '4498223814fd430207731563047856cc909eebfa06c80c54b83e3bec78e61a08'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('END_018e', 'END_018e2') or
            (data['policy']['numeric_policy'], data['policy']['infinite_cost_value']) !=
                (INFINITE_COST_POLICY, INFINITE_COST_VALUE) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('Acolyte lost its complete native source')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Acolyte original source pin changed')
    return data


def register_infinite_cost_card(registry):
    raw = load_batch()['cards'][0]['record']
    def battlecry(c):
        if c.battlecry is None:
            raise ValueError('Cost linkage requires its actual native Battlecry')
        source = c.source
        ref = MinionReference.capture(source) if source.kind == CardType.MINION and source.zone == Zone.BOARD else None
        ids = tuple(a.id for a in active_abilities(source, 'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind == 'cost_link') if ref else ()
        return (SetRandomHandCostForDeathrattle(c.player_id, c.battlecry.id, ref, ids),)
    def deathrattle(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'cost_link':
            raise UnsupportedDefinitionError('Cost restoration requires its actual original native memory')
        return tuple(RestoreRememberedCost(c.deathrattle.id, link) for link in memory.cost_links)
    registry.register_behavior(PREFIX+'set', battlecry)
    registry.register_behavior(PREFIX+'restore', deathrattle)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=PREFIX+'set', deathrattle=PREFIX+'restore',
        native_deathrattle=NativeDeathrattleSpec('cost_link'), metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
