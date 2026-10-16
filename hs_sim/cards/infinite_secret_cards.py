"""Flames of Infinity with explicit health policy and ordinary end-turn ordering."""
import json
from pathlib import Path
from hs_sim.engine.infinite_damage import (INFINITE_HEALTH_POLICY, INFINITE_HEALTH_VALUE,
                                          RandomInfiniteDamageMinion)
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .core_secret_cards import enemy_minions
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/infinite-secret-effects-v1.json'
BATCH_HASH = '9ce59bc9ec3e04f257f93424823b11bbd02ca94d14c3d2ed08a75b2bcebe29b5'
BODY = 'cards.infinite_secret.flames'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Infinite secret differs from its reviewed full source pin')
    return data


def highest(c, registry):
    candidates = enemy_minions(c, registry)
    if not candidates: return ()
    health = max(c.state.entities[eid].health for eid in candidates)
    return tuple(MinionReference.capture(c.state.entities[eid]) for eid in candidates
                 if c.state.entities[eid].health == health)


def register_infinite_secret_cards(registry):
    registry.register_secret_condition(BODY, lambda c: c.event is not None and c.event.kind == 'turn_ended'
        and c.event.player_id != c.player_id and bool(highest(c, registry)))
    registry.register_behavior(BODY, lambda c: (RandomInfiniteDamageMinion(highest(c, registry), c.source_id),))
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if (raw['id'] != 'END_024' or canonical_digest(raw) != row['record_sha256'] or
                raw['cost'] != recipe['cost'] or raw['tags'].get('SECRET') != 1 or
                (recipe['numeric_policy'], recipe['infinite_value']) != (INFINITE_HEALTH_POLICY, INFINITE_HEALTH_VALUE)):
            raise TargetValidationError('Unreviewed infinite secret or numeric policy')
        card = CardDefinition(raw['id'], raw['name'], CardType.SPELL, cost=raw['cost'],
            keywords=(Keyword.SECRET,), spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']],
            secret=SecretSpec('END_024', ('turn_ended',), BODY, BODY), metadata=metadata_from_record(raw))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
