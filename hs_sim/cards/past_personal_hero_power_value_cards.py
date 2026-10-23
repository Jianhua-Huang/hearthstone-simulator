"""Free Spirit and Daring Fire-Eater use finite player-owned skill programs."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.hero_power_values import ARMOR, NEXT_DAMAGE, HeroPowerValueProfile
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SPIRIT, FIRE_EATER = 'ETC_382', 'TRL_390'
LEAVES = DEPENDENCIES = (SPIRIT, FIRE_EATER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_personal_power.'
ARMOR_SPEC, DAMAGE_SPEC = PREFIX+'armor', PREFIX+'next_damage'
PROGRAMS = {SPIRIT: dict(kind=ARMOR, amount=1), FIRE_EATER: dict(kind=NEXT_DAMAGE, amount=2)}
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-personal-hero-power-values-v1.json'
BATCH_HASH = 'f3ae6ac9692e58b59d5de2b6c90f0f8c483fb112063d00a1da5bcc288be106cf'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(x['record']['id'] for x in data['dependencies']) != LEAVES or data['programs'] != PROGRAMS or
            any(data[k] for k in ('cards', 'evidence_only', 'choice_only', 'skipped',
                                 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Personal skill programs lost their complete original sources')
    return data


def register_past_personal_hero_power_value_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_power_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Personal skill programs must reuse the unchanged basic skill: '+cid)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; program = PROGRAMS[cid]
        expected = (1, 1, 2) if cid == SPIRIT else (1, 1, 1)
        if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', *expected, 1):
            raise TargetValidationError('Personal skill consumer changed its printed battlecry face')
        spec_id = ARMOR_SPEC if cid == SPIRIT else DAMAGE_SPEC
        body = PREFIX+cid
        registry.register_behavior(body, lambda c, effect_id=spec_id: (
            AddPlayerEffect(c.player_id, effect_id, c.source_id),))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=1, health=raw['health'],
            battlecry=body, deathrattle=body if cid == SPIRIT else None, metadata=metadata_from_record(raw))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
        registry.register_player_effect(PlayerEffectSpec(spec_id, cid, program['kind']))
        registry.register_hero_power_value_profile(HeroPowerValueProfile(spec_id, program['amount']))
