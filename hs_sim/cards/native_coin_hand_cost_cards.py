"""Blackpaw's Whip declares its fixed Coin family and ordinary draw Deathrattle."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import Draw
from hs_sim.engine.model import CardDefinition, CardType, CoinHandCountCostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_503'
BODY = 'cards.blackpaws_whip.draw'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-coin-hand-cost-v1.json'
BATCH_HASH = '9021dcd480822e2d35792d11a82e7bb20fb34c709bdaa2208f3f023918e4e2a4'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD):
        raise TargetValidationError('Blackpaw weapon requires its complete reviewed source')
    for key in ('cards', 'existing_dependencies', 'coin_family_records', 'coin_nonhand_evidence'):
        if any(canonical_digest(x['record']) != x['record_sha256'] for x in data[key]):
            raise TargetValidationError('Coin family lost an original full source row')
    family = data['coin_family_records']
    if (len(family) != 68 or any(x['record']['type'] != 'SPELL' or
            x['record']['tags'].get('COIN_CARD') != 1 for x in family) or
            data['coin_spell_ids'] != sorted(x['record']['id'] for x in family) or
            [x['record']['id'] for x in data['coin_nonhand_evidence']] != ['GAME_005e']):
        raise TargetValidationError('Coin hand family differs from the fixed complete spell classification')
    return data


def register_native_coin_hand_cost_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Coin price requires the original complete dependency: ' + cid)
    raw = data['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (Draw(c.player_id, 1, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.WEAPON, cost=raw['cost'],
        attack=raw['attack'], durability=raw['health'], deathrattle=BODY,
        hand_count_cost=CoinHandCountCostSpec(tuple(data['coin_spell_ids'])), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
