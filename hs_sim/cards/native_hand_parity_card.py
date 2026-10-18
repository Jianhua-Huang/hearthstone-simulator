"""Genn's one-way native hand face and bounded starting-power battlecry."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior, ModifyCost, ReplaceHeroPower
from hs_sim.engine.hand_parity import HandParityTransformProfile
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, HeroPowerReference
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .upgraded_hero_power_cards import UPGRADES

CARD, WORGEN = 'CATA_615', 'CATA_615t'
PREFIX = 'cards.native_hand_parity.'
FEE = CostSpec(set_to=1, card_types=(CardType.HERO_POWER,))
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-hand-parity-v1.json'
BATCH_HASH = '39dd7de0ed06a4ca5c6d1f8919ff73161b8ee48a384b2d8d41e0051eed971b04'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (WORGEN,)):
        raise TargetValidationError('Unreviewed complete native Genn source')
    for row in data['cards'] + data['dependencies'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Genn dependency')
    return data


def register_native_hand_parity_card(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Genn changed an original basic or upgraded power dependency')
    def upgrade(c):
        player = c.state.players[c.player_id]
        starting = player.starting_hero_power_card_id
        base = starting if starting in UPGRADES else next((k for k,v in UPGRADES.items() if v == starting), None)
        power = c.state.entities.get(player.hero_power_id)
        if base is None or power is None:
            return ()
        upgraded = UPGRADES[base]
        if power.card_id == base:
            return (ReplaceHeroPower(c.player_id, upgraded, power=HeroPowerReference.capture(power),
                cost=FEE, source_id=c.source_id),)
        if power.card_id == upgraded:
            return (ModifyCost(power.id, FEE, c.source_id),)
        # The original starting type no longer occupies the primary slot.
        return ()
    registry.register_behavior(PREFIX+'upgrade', upgrade)
    registry.register_behavior(PREFIX+'battlecry', lambda c: (InvokeBehavior(PREFIX+'upgrade', c.source_id, c.player_id),))
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'],
            metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            battlecry=PREFIX+'battlecry' if raw['id'] == WORGEN else None)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hand_parity_profile(HandParityTransformProfile(CARD, WORGEN))
