"""Actual shared play/death subjects and a separate original prefix Deathrattle."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_on_play import AssembleOnPlayDeathSource
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.kindred import current_source
from hs_sim.engine.model import BoardPresenceReference, CardType, Keyword, Zone
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('BE_264', 'END_015', 'TLC_226')
COPY = 'cards.assemble_dual_minion_play.copy_source'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-dual-minion-play-followups-v1.json'
BATCH_HASH = '13a4fcb084d5fd24e26013684dcd7b70962a1b17cc117022e807f7a9d14f6dbd'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies']) or
            any(canonical_digest(q) != data['generation_query_sha256'][cid]
                for cid, q in data['generation_queries'].items())):
        raise TargetValidationError('Actual play/death assembly lost three full originals and complete queries')
    return data


def register_assemble_dual_minion_play_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Actual play/death assembly changed a complete original source')
    for cid, profile in data['original_kindred_profiles'].items():
        if asdict(registry.kindred_profiles[cid]) != profile:
            raise TargetValidationError('Actual play/death assembly changed the complete native Kindred profile')

    def copy_source(c):
        source = current_source(c) if c.kindred is not None else c.source
        if (source is None or source.kind != CardType.MINION or source.zone != Zone.BOARD or
                not source.active or source.health <= 0 or source.doomed):
            return ()
        return (CopyMinion(BoardPresenceReference.capture(c.state, source.id), c.player_id,
            cause=SummonCause.capture(c)),)

    registry.register_behavior(COPY, copy_source)
    for row in data['reviewed_templates']:
        profile = AssembleOnPlayDeathSource(**{key: row[key] for key in (
            'card_id', 'original_behavior_id', 'condition_id', 'kind', 'original_deathrattle_id',
            'body_behavior_id', 'original_kindred_active_id', 'prefix_deathrattle_id')})
        registry.register_assemble_on_play_death_source(profile)
        timing = 'on_play_prefix_deathrattle' if profile.prefix_deathrattle_id else 'on_play_deathrattle'
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(timing, tuple(Keyword(key) for key in row['keywords']), condition_id=row['condition_id']),
            AssembleSuffix(row['body_behavior_id'], tuple(row['allowed_timings']),
                pending_timings=tuple(row['pending_timings']))))
