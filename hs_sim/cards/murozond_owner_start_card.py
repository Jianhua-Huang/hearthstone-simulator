"""Murozond's delayed self grant composes finite triggers and guarded stat sets."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.infinite_damage import INFINITE_HEALTH_VALUE
from hs_sim.engine.limited_triggers import GrantLimitedTrigger
from hs_sim.engine.model import CardDefinition, CardType, LimitedTriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference, SetCapturedMinionStats
from hs_sim.engine.timed_keywords import owner_deadline
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_024'
PREFIX = 'cards.murozond_owner_start.'
INFINITE_ATTACK_VALUE = INFINITE_HEALTH_VALUE
NUMERIC_POLICY = 'int32-max-set-attack-v1'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/murozond-owner-start-v1.json'
BATCH_HASH = '9348f861820665201544707edda7d7da900f8744cabfd9d946c4415b89cfbf25'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,)
            or tuple(x['record']['id'] for x in data['evidence_only']) != ('TIME_024e',)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))
            or (data['policy']['numeric_policy'], data['policy']['infinite_attack_value']) !=
                (NUMERIC_POLICY, INFINITE_ATTACK_VALUE)):
        raise TargetValidationError('Murozond lost its complete original source or explicit numeric policy')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Murozond requires unchanged complete source rows')
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 9, 8, 8):
        raise TargetValidationError('Murozond changed its printed original body')
    return data


def register_murozond_owner_start_card(registry):
    def battlecry(c):
        if c.battlecry is None:
            raise ResolutionError('Murozond requires its actual Battlecry')
        body = c.source
        if (body.zone != Zone.BOARD or body.kind != CardType.MINION or body.controller != c.player_id
                or not body.active or body.doomed or body.health <= 0):
            return ()
        ref = MinionReference.capture(body)
        spec = LimitedTriggerSpec('turn_started', PREFIX + 'set_attack',
            condition_id=PREFIX + 'caster.' + str(c.player_id))
        return (GrantLimitedTrigger(body.id, spec, c.source_id, recipient=ref,
            deadline=owner_deadline(c.state, c.player_id)),)

    def due(c):
        ability = c.trigger
        if (ability is None or ability.kind != 'limited_trigger' or ability.source_id is None
                or ability.limited_trigger.event != 'turn_started'
                or ability.limited_trigger.behavior_id != PREFIX + 'set_attack'
                or ability.limited_trigger.condition_id != PREFIX + 'caster.' + str(c.event.player_id)):
            raise ResolutionError('Murozond lost its original consumed next-start attachment')
        return (SetCapturedMinionStats(MinionReference.capture(c.source), attack=INFINITE_ATTACK_VALUE,
            source_id=ability.source_id),)

    registry.register_behavior(PREFIX + 'battlecry', battlecry)
    registry.register_behavior(PREFIX + 'set_attack', due)
    for player in (1, 2):
        registry.register_trigger_condition(PREFIX + 'caster.' + str(player),
            lambda c, player=player: c.event.player_id == player)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=9, attack=8, health=8,
        battlecry=PREFIX + 'battlecry', metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
