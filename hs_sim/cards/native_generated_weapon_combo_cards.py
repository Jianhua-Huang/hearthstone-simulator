"""Neferset Weaponsmith binds its actual Battlecry weapon to its Combo."""
import json
from pathlib import Path

from hs_sim.engine.battlecry_weapon_outputs import GenerateBattlecryWeapon, combo_weapon
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_516'
PREFIX = 'cards.neferset_weaponsmith.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-generated-weapon-combo-v1.json'
BATCH_HASH = 'c9d738a35d735bb6869f5d46b801417298659ca010a746dd014157add0a93502'
QUERY = PoolQuery(kinds=(CardType.WEAPON,), collectible=True, class_mode='other', include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Weaponsmith requires its complete reviewed source pin')
    return data


def register_native_generated_weapon_combo_cards(registry):
    raw = load_batch()['cards'][0]['record']
    def battlecry(c):
        if c.battlecry is None:
            raise ValueError('Weaponsmith requires its actual Battlecry execution')
        return (GenerateBattlecryWeapon(c.battlecry.id, GenerateFromPool(c.player_id, 'constructed.cards',
            QUERY, source_id=c.source_id)),)
    def combo(c):
        card = combo_weapon(c, registry)
        return () if card is None else (BuffStoredCard(card, attack=2, source_id=c.source_id),)
    registry.register_behavior(PREFIX + 'battlecry', battlecry)
    registry.register_behavior(PREFIX + 'combo', combo)
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.COMBO,),
        battlecry=PREFIX + 'battlecry', combo=PREFIX + 'combo', metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
