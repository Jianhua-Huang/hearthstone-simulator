"""Sigil of Cinder expires through the existing player clock and split executor."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import DELAYED_SPELL_PROFILE, RandomSplitDamage
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'FIR_902'
PROGRAM = 'cards.cinder_sigil'
EXPIRE = PROGRAM+'.expire'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/cinder-sigil-card-v1.json'
BATCH_HASH = 'b2b364a53648e4369d7b8210eb55e18e2f9686924114a16df94101044ba7e5eb'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD]
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))
            or canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Sigil of Cinder lost its complete reviewed source')
    return data


def register_cinder_sigil_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('349'), raw['tags'].get('SIGIL'),
            raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, 1, 1, 7):
        raise TargetValidationError('Sigil of Cinder lost its real immune Fel spell face')

    def expire(c):
        instance = c.player_effect
        if (instance is None or instance.spec_id != PROGRAM or instance.source_id != c.source_id
                or c.event is None or c.event.kind != 'player_effect_expired'
                or (c.event.source_id, c.event.player_id) != (c.source_id, c.player_id)):
            raise TargetValidationError('Cinder requires its original actual Sigil expiry')
        return (RandomSplitDamage(c.player_id, None, c.source_id, 6,
            profile=DELAYED_SPELL_PROFILE, spell_bonus_multiplier=0, player_effect=instance),)

    registry.register_behavior(EXPIRE, expire)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, CARD, kind='sigil', duration=1,
        tick_event='turn_started', on_expire=EXPIRE, capture_health_source=True))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        spell_school=SpellSchool.FEL, ongoing_effect_id=PROGRAM, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
