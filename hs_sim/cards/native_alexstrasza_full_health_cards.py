"""A real Battlecry installs an independent, once-only full-health reward."""
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.hero_health_history import validate_transition
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect, PlayerEffectDamage
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_307'
PREFIX = 'cards.alexstrasza_full_health.'
PENDING = PREFIX + 'pending'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-alexstrasza-full-health-v1.json'
BATCH_HASH = 'f0474884e1bfc675a9a21fc43e30967e42c5c45f42452ba8e24004dc51cd4d30'
HEALTH_EVENTS = ('health_resolved', 'health_lost', 'health_loss_floor_resolved',
    'max_health_gained', 'max_health_lost', 'health_spent', 'stats_changed',
    'enchantment_removed', 'attachments_expired', 'hero_replaced', 'hero_recovered', 'hero_health_set')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH or tuple(row['record']['id'] for row in data['cards']) != (CARD,):
        raise TargetValidationError('Alexstrasza requires its complete reviewed source pin')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Alexstrasza complete original source changed')
    return data


def reward(player_id, instance, target_id):
    return ConsumePlayerEffect(player_id, instance,
        (PlayerEffectDamage(player_id, instance, target_id, 15),))


def reached_full(c):
    value = dict(c.event.data).get('hero_health_transition')
    if value is None:
        return ()
    player, _, _, before, old_max, _, _, after, new_max = validate_transition(value)
    if player != c.player_id or before >= old_max or after <= 0 or after != new_max:
        return ()
    if c.player_effect is None:
        raise ValueError('Full-health reward lost its original player instance')
    return (reward(c.player_id, c.player_effect, c.state.players[3-c.player_id].hero_id),)


def check_full(c):
    hero = c.state.entities[c.state.players[c.player_id].hero_id]
    if hero.health <= 0 or hero.health != hero.max_health:
        return ()
    return tuple(reward(c.player_id, instance, c.state.players[3-c.player_id].hero_id)
        for instance in c.state.players[c.player_id].player_effects if instance.spec_id == PENDING)


def battlecry(c):
    # Capture before the health assignment can publish reactions that retire,
    # transform or take the physical minion. Precise CN arming order is M6.
    return (AddPlayerEffect(c.player_id, PENDING, c.source_id, capture_health_source=True),
        SetHeroHealth(c.state.players[c.player_id].hero_id, 15, c.source_id),
        InvokeBehavior(PREFIX+'check', c.source_id, c.player_id))


def register_native_alexstrasza_full_health_cards(registry):
    data = load_batch()
    registry.register_behavior(PREFIX+'battlecry', battlecry)
    registry.register_behavior(PREFIX+'reached', reached_full)
    registry.register_behavior(PREFIX+'check', check_full)
    registry.register_player_effect(PlayerEffectSpec(PENDING, CARD,
        triggers=tuple(TriggerSpec(event, PREFIX+'reached') for event in HEALTH_EVENTS)))
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 7, 8, 8):
        raise TargetValidationError('Unreviewed Alexstrasza definition')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=PREFIX+'battlecry',
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
