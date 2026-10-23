"""Sir Finley uses a complete source-pinned basic-skill discovery family."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.hero_power_discovery import DiscoverHeroPower, HeroPowerDiscoveryProfile
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'LOE_076'
LEAVES = DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
POWERS = ('HERO_11bp', 'HERO_10bp', 'HERO_06bp', 'HERO_05bp', 'HERO_08bp', 'HERO_04bp',
          'HERO_09bp', 'HERO_03bp', 'HERO_02bp', 'HERO_07bp', 'HERO_01bp')
BODY = 'cards.past_basic_hero_power_discovery.discover'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-basic-hero-power-discovery-v1.json'
BATCH_HASH = 'c23058c7c7bcfeb4016ac953dd8a11ae3e7ca68625b9f74ff78de2172b948dd6'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(data['profile_power_ids']) != POWERS or
            tuple(x['record']['id'] for x in data['dependencies']) != LEAVES or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != POWERS or
            any(data[k] for k in ('cards', 'evidence_only', 'choice_only', 'skipped',
                                 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Finley requires its complete original source and eleven basic skills')
    return data


def register_past_basic_hero_power_discovery_card(registry):
    data = load_batch()
    for cid in POWERS:
        if canonical_digest(asdict(registry.card(cid))) != data['existing_power_definition_pins'][cid]:
            raise TargetValidationError('Finley must reuse the unchanged complete basic skill: '+cid)
    raw = data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 1, 1, 3, 1):
        raise TargetValidationError('Finley lost its original one-mana battlecry face')
    registry.register_behavior(BODY, lambda c: (DiscoverHeroPower(c.player_id, c.source_id, CARD),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=1, attack=1, health=3,
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hero_power_discovery_profile(HeroPowerDiscoveryProfile(CARD, POWERS))
