"""Pterrordax Egg grants theft only to its original named summon continuation."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.health_theft import StealHealthFromOtherMinions
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, TOKEN = 'TLC_831', 'TLC_831t'
PREFIX = 'cards.pterrordax_egg.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-pterrordax-egg-v1.json'
BATCH_HASH = 'f31136b91a47f539f2798cfdcb100424f19eedb25cb917df1397c8c1e26e7cfa'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD] or
            [x['record']['id'] for x in data['existing_dependencies']] != [TOKEN] or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'] + data['existing_dependencies'])):
        raise TargetValidationError('Pterrordax Egg requires its full original source and token')
    return data


def register_native_pterrordax_egg_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Pterrordax Egg changed the existing complete blank token')
    raw = data['cards'][0]['record']
    def steal(c):
        beneficiary = original_named_reference(c)
        return (StealHealthFromOtherMinions(c.player_id, beneficiary, 1, beneficiary.entity_id),)
    registry.register_behavior(PREFIX + 'steal', steal)
    registry.register_behavior(PREFIX + 'death', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(TOKEN, on_summon=PREFIX + 'steal'),), SummonCause.capture(c)),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=0,
        health=raw['health'], metadata=metadata_from_record(raw), deathrattle=PREFIX + 'death')
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
