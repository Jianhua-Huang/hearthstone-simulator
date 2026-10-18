"""Glaivebound Adept uses original hero attack facts through a pure player rule."""
import json
from pathlib import Path
from hs_sim.engine.effects import Damage
from hs_sim.engine.hero_attack_history import hero_attack_count
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HeroAttackQuery, TargetMode, TargetSpec
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BT_495'
BODY = 'cards.native_hero_attack_targets.adept'
RULE = BODY + '_target'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-hero-attack-targets-v1.json'
BATCH_HASH = 'd151b2623f2b12b94ab7be28535c3f1647771ec732dbf218f43fdee46d748fda'


def load_batch():
    data = json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Glaivebound Adept requires its complete reviewed original source')
    return data


def register_native_hero_attack_target_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != (
            'MINION', 5, 6, 4, 1):
        raise TargetValidationError('Glaivebound Adept printed face changed')

    def condition(c):
        return c.observation['players'][c.player_id - 1]['hero_attacked_this_turn']

    def adept(c):
        if c.target_id is None or not hero_attack_count(c.state, c.player_id, HeroAttackQuery(window='owner_turn')):
            return ()
        return (Damage(c.target_id, 4, c.source_id, DamageKind.MINION_ABILITY),)

    registry.register_player_target_rule(PlayerTargetRuleSpec(RULE, 'v1'), condition)
    registry.register_behavior(BODY, adept)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=5, attack=6, health=4,
        battlecry=BODY, targeting=TargetSpec(TargetMode.IF_AVAILABLE), target_rule=RULE,
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
