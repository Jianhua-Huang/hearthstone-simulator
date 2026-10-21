"""Stone Gauntlet delegates actual health conversion to the shared mutators."""
import json
from pathlib import Path

from hs_sim.engine.health_loss import ConvertHeroHealthToArmor
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .metadata import metadata_from_record

CARD = 'BE_558'
BODY = 'cards.health_armor_conversion.stone_gauntlet'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/health-armor-conversion-v1.json'
BATCH_HASH = 'cdd00d759d435795a929daf084c84a57c9431d4f358f79907fcdc2886eafd522'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Stone Gauntlet lost its complete reviewed original face')
    return data


def register_health_armor_conversion_card(registry):
    def body(c):
        attack = completed_attack(c)
        if (attack is None or attack.source_kind != CardType.HERO or
                attack.declaration.player_id != c.player_id or attack.combat.weapon_id != c.source_id):
            return ()
        return (ConvertHeroHealthToArmor(c.player_id, 5, c.source_id),)
    registry.register_behavior(BODY, body)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS')) != ('WEAPON', 1, 2, 2, 10):
        raise TargetValidationError('Stone Gauntlet requires its original 1-cost 2/2 Warrior weapon')
    card = CardDefinition(CARD, raw['name'], CardType.WEAPON, cost=1, attack=2, durability=2,
        triggers=(TriggerSpec('attack_finished', BODY),), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
