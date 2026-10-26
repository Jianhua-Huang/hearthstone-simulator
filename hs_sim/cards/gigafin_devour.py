"""Gigafin marks real enemy destruction, returns base minions, and binds its Maw."""
import json
from pathlib import Path

from hs_sim.engine.consumed_cards import ConsumptionProfile
from hs_sim.engine.devoured_minions import DevourEnemyMinions, DigestDevouredMinions, ReturnDevouredMinion
from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/gigafin-devoured-minions-v1.json'
BATCH_HASH = 'fb6fdd5b36f612c3e42a39c272a97cc80a5c41ce47af15876b0dcd193b939b08'
CARD, MAW = 'TSC_962', 'TSC_962t'
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (CARD, MAW)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(v['record']['id'] for v in data['cards']) != (CARD,) or
            tuple(v['record']['id'] for v in data['dependencies']) != (MAW,) or
            tuple(v['record']['id'] for v in data['evidence_only']) != ('TSC_962e', 'TSC_962e2') or
            data['existing_dependencies'] or data['skipped'] or data['consumption_kind'] != 'board_minions' or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Gigafin requires its complete original body, Maw and two enchantments')
    if any(canonical_digest(v['record']) != v['record_sha256'] for v in
            data['cards']+data['dependencies']+data['evidence_only']):
        raise TargetValidationError('Gigafin lost a complete original raw row')
    if canonical_digest(json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))) != data['reference_canonical_sha256']:
        raise TargetValidationError('Gigafin lost its independent complete past reference')
    return data


def register_gigafin_devour(registry):
    data = load_batch(); raw = data['cards'][0]['record']; maw = data['dependencies'][0]['record']
    if any(cid in registry.cards for cid in (CARD, MAW)) or CARD in registry.consumption_profiles:
        raise TargetValidationError('Gigafin cannot replace an existing body or consumption declaration')
    if ((raw['cost'], raw['attack'], raw['health']) != (8, 7, 4) or
            (maw['cost'], maw['attack'], maw['health']) != (6, 4, 7)):
        raise TargetValidationError('Gigafin requires its original 7/4 body and 4/7 Maw')
    def consume(c):
        if c.battlecry is None: raise UnsupportedDefinitionError('Gigafin requires its actual accepted Battlecry')
        return (DevourEnemyMinions(CARD, c.battlecry.id),)
    def release(c):
        if c.deathrattle is None: raise UnsupportedDefinitionError('Gigafin requires its actual accepted Deathrattle')
        if c.deathrattle.ability.consumed_card_id is None: return ()
        return (ReturnDevouredMinion(c.deathrattle.id, SummonCause.capture(c)),)
    def digest(c):
        if c.deathrattle is None: raise UnsupportedDefinitionError('Gigafin Maw requires its actual accepted Deathrattle')
        if c.deathrattle.ability.devour_parent is None: return ()
        return (DigestDevouredMinions(c.deathrattle.id),)
    definitions = (
        CardDefinition(CARD, raw['name'], CardType.MINION, cost=8, attack=7, health=4,
            metadata=metadata_from_record(raw), keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec(MAW, 'right'),), battlecry=data['producer_behavior_id'],
            deathrattle=data['deathrattle_behavior_id']),
        CardDefinition(MAW, maw['name'], CardType.MINION, cost=6, attack=4, health=7,
            metadata=metadata_from_record(maw), keywords=(Keyword.TAUNT,), deathrattle=data['maw_behavior_id']),
    )
    for card in definitions:
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id) != PoolCard.from_definition(card):
            raise TargetValidationError('Gigafin cannot replace independent printed metadata')
    for name, body in ((data['producer_behavior_id'], consume), (data['deathrattle_behavior_id'], release),
            (data['maw_behavior_id'], digest)): registry.register_behavior(name, body)
    for card in definitions:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_consumption_profile(ConsumptionProfile(CARD, data['consumption_kind']))
