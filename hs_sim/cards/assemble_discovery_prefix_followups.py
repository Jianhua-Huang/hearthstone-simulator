"""Native discovery prefixes finish delivery before their independent rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import DiscoverFromPool, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .simple_followup_p36_cards import QUERIES as NATIVE_QUERIES, REAVER
from .simple_followup_p63_cards import WHELP, PROMISE

SOURCES = (WHELP, REAVER)
PREFIX = 'cards.assemble_discovery_prefix.'
QUERIES = {WHELP: PoolQuery(collectible=True, class_mode='current', min_cost=5, max_cost=5),
    REAVER: NATIVE_QUERIES[REAVER]}
POOL_ID = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-discovery-prefix-followups-v1.json'
BATCH_HASH = '3bcec937acc78df9124ab6a1920ccbbce34ea2295898548edadda0a0587ae9c0'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Discovery prefixes require both complete reviewed native sources')
    return data


def register_assemble_discovery_prefix_followups(registry):
    data = load_batch()
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        original = registry.card(row['record']['id'])
        if (canonical_digest(asdict(original)) != row['definition_sha256'] or
                original.battlecry != declaration['original_battlecry_id']):
            raise TargetValidationError('Discovery prefix changed its complete original native card')
    for cid, query in QUERIES.items():
        if (canonical_digest(asdict(query)) != data['queries_sha256'][cid] or
                canonical_digest(asdict(query)) != canonical_digest(data['queries'][cid])):
            raise TargetValidationError('Discovery prefix changed its complete original query')
    if (canonical_digest(asdict(registry.player_effect(PROMISE))) !=
            data['next_turn_player_effect_sha256'] or
            canonical_digest(data['next_turn_player_effect']) != data['next_turn_player_effect_sha256']):
        raise TargetValidationError('Discovery reward changed the original next-owner-turn promise')
    for behavior_id in data['required_original_behaviors']:
        registry.behavior(behavior_id)

    for cid, key in ((WHELP, 'whelp_discover'), (REAVER, 'reaver_discover')):
        registry.register_behavior(PREFIX + key, lambda c, query=QUERIES[cid]:
            (DiscoverFromPool(c.player_id, POOL_ID, query, source_id=c.source_id),))
    registry.register_behavior(PREFIX + 'next_mana', lambda c:
        (AddPlayerEffect(c.player_id, PROMISE, c.source_id),))
    for declaration in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix(declaration['timing'], before_behavior_id=declaration['before_behavior_id']),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings'])),
            original_battlecry_id=declaration['original_battlecry_id']))
