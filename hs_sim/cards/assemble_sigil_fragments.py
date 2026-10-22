"""Reviewed Sigil text projections; original one-shot spells remain intact."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleProjection, AssembleSuffix
from hs_sim.engine.model import CardType
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .native_followup_cards import deathrattle_position

SOURCES = ('BE_873', 'CATA_528')
TOKENS = ('BE_873t', 'CATA_528t')
TIMINGS = ('battlecry', 'deathrattle', 'end_turn', 'start_turn')
PREFIX = 'cards.assemble_sigil.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-sigil-fragments-v1.json'
BATCH_HASH = 'e6e202531c2410c6ab53a9ae9366229ecc42833f35d3883d6d418b70d1057d4e'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in rows) != SOURCES+TOKENS or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows)):
        raise TargetValidationError('Assembled Sigils require complete original spells and exact physical tokens')
    return data


def register_assemble_sigil_fragments(registry):
    data = load_batch(); rows = {r['record']['id']: r for r in data['existing_dependencies']}
    for cid, row in rows.items():
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Assembled Sigil changed its complete native dependency: '+cid)
    for cid, token, count in zip(SOURCES, TOKENS, (3, 1)):
        row = rows[cid]; raw = row['record']
        if (raw['type'] != 'SPELL' or raw['attack'] is not None or raw['health'] is not None or
                raw['tags'].get('SIGIL') != 1 or raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1):
            raise TargetValidationError('Sigil projection requires its literal whole non-minion source')
        def summon(c, token=token, count=count):
            cause = SummonCause.capture(c)
            return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(token),), cause,
                position=deathrattle_position(c) if c.deathrattle is not None else None) for _ in range(count))
        registry.register_behavior(PREFIX+cid, summon)
        registry.register_assemble_projection(AssembleProjection(cid, CardType.SPELL,
            row['definition_sha256'], row['record_sha256'], AssemblePrefix('start_turn'),
            AssembleSuffix(PREFIX+cid, TIMINGS)))
