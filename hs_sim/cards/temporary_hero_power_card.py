"""Story of Sulfuras retains the original physical power across two real uses."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior, RandomDamage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.temporary_hero_powers import SwapTemporaryHeroPower, TemporaryHeroPowerProfile
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

CARD = 'TLC_632'
POWERS = ('TLC_632t', 'TLC_632t2')
PREFIX = 'cards.temporary_hero_power.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/temporary-hero-power-v1.json'
BATCH_HASH = 'f8cbf12de15fe768f5bf11916bbadcc0d8db9f6859113bc7ae40803d6b94c18c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != POWERS):
        raise TargetValidationError('Unreviewed complete Story of Sulfuras source')
    for row in data['cards'] + data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original temporary hero power face')
    return data


def register_temporary_hero_power_card(registry):
    registry.register_behavior(PREFIX+'swap', lambda c: (SwapTemporaryHeroPower(c.player_id, CARD, c.source_id),))
    registry.register_behavior(PREFIX+'damage', lambda c: (InvokeBehavior(PREFIX+'damage_now', c.source_id, c.player_id),))
    registry.register_behavior(PREFIX+'damage_now', lambda c: (
        RandomDamage(characters(c, registry, 3-c.player_id), 8, c.source_id, DamageKind.HERO_POWER),))
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; root = raw['id'] == CARD
        card = CardDefinition(raw['id'], raw['name'], CardType.SPELL if root else CardType.HERO_POWER,
            cost=raw['cost'], metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            on_play=PREFIX+'swap' if root else None, on_use=None if root else PREFIX+'damage',
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_temporary_hero_power_profile(TemporaryHeroPowerProfile(CARD, POWERS))
