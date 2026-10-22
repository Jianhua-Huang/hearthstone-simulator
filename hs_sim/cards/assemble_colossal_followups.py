"""Two real Colossal prefixes retain every original native appendage."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_colossal import AssembleColossalSource
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import AppendageSpec, BoardPresenceReference, CardType, EndTurnSpec, HealthFlow, Keyword, Zone
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.targets import TargetValidationError, canonical_digest
from . import simple_followup_p50_cards as native_limbs

BLOOD, VULCANOS = SOURCES = ('CATA_300', 'CATA_488')
LIMBS = ('CATA_300t1', 'CATA_300t2', 'CATA_300t3', 'CATA_488t', 'CATA_488t2')
PREFIX = 'cards.assemble_colossal.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-colossal-followups-v1.json'
BATCH_HASH = '0a34643d28c4d48fba89001a584d96f5c2b43bd5b5c37824a3c4fbedc514c5f1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + LIMBS or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            canonical_digest(data['plume_query']) != data['plume_query_sha256']):
        raise TargetValidationError('Colossal assembly requires two full sources and all five original appendages')
    return data


def register_assemble_colossal_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Colossal assembly changed a complete original source or appendage')
    if (native_limbs.POOL_ID != data['plume_pool_id'] or
            canonical_digest(asdict(native_limbs.FIRE_QUERY)) != data['plume_query_sha256']):
        raise TargetValidationError('Colossal assembly changed the original complete Plume query')
    for entry in data['reviewed_templates']:
        registry.behavior(entry['original_behavior_id'])

    def own_heal(c):
        if c.event is None or c.event.kind != 'health_resolved' or c.health_result is None:
            raise ResolutionError('Blackblood assembly requires its original settled health result')
        result = c.health_result
        return result.flow == HealthFlow.HEALING.value and result.healed > 0 and result.source_controller == c.player_id

    def attack_enemy(c):
        if c.source.kind != CardType.MINION or c.source.zone != Zone.BOARD:
            return ()
        return (AttackRandomEnemyMinion(BoardPresenceReference.capture(c.state, c.source_id), c.player_id, c.source_id),)

    registry.register_trigger_condition(PREFIX + 'own_heal', own_heal)
    registry.register_behavior(PREFIX + 'attack_enemy', attack_enemy)
    for entry in data['reviewed_templates']:
        cid = entry['card_id']
        registry.register_assemble_colossal_source(AssembleColossalSource(cid,
            tuple(AppendageSpec(**spec) for spec in entry['colossal'])))
        if entry['timing'] == 'health_resolved':
            registry.register_assemble_reaction_source(AssembleReactionSource(cid, 'health_resolved',
                entry['original_behavior_id'], entry['condition_id']))
        registry.register_assemble_template(AssembleTemplate(cid,
            AssemblePrefix(entry['timing'], tuple(Keyword(key) for key in entry['keywords']),
                end_turn=EndTurnSpec(**entry['end_turn']) if entry['end_turn'] else None,
                condition_id=entry['condition_id']),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
