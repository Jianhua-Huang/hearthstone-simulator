"""Dwarven Sharpshooter declares a live permission; targeting stays public."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.hero_power_targets import HeroPowerMinionTargetProfile
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'DRG_253'
LEAVES = DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
POWERS = ('HERO_05bp', 'HERO_05bp2')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-hero-power-targets-v1.json'
BATCH_HASH = 'd35504743aa3645078eba105c156b61dba28e259deab6a987ad7adc816f3119c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(x['record']['id'] for x in data['dependencies']) != LEAVES or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != POWERS or
            tuple(data['profile_power_ids']) != POWERS or
            any(data[k] for k in ('cards', 'evidence_only', 'choice_only', 'skipped',
                                 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Skill target source lost its complete original records')
    return data


def register_past_hero_power_target_card(registry):
    data = load_batch()
    for cid in POWERS:
        if canonical_digest(asdict(registry.card(cid))) != data['existing_power_definition_pins'][cid]:
            raise TargetValidationError('Native target permission changed its original skill: '+cid)
    raw = data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 1, 1, 3):
        raise TargetValidationError('Sharpshooter lost its full native one-mana face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=1, attack=1, health=3,
        metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hero_power_target_profile(HeroPowerMinionTargetProfile(CARD, POWERS))
