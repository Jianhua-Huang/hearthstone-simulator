"""Taunt death producers keep native placement, budget and shared Soul state."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.mana_worth_summons import SummonManaWorth, query
from hs_sim.engine.model import Keyword
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .simple_followup_p68_cards import PREFIX, SOUL

SOURCES = ('BE_900', 'JAIL_733')
MECH_BODY = 'cards.assemble_taunt_death.mechs'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-taunt-death-producers-v1.json'
BATCH_HASH = 'cf30216e95e2f73178e541da484e026012aa6b3bc60bb9da7e419eade03b7657'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES+(SOUL,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            data['native_budget'] != dict(pool_id='constructed.cards', amount=4,
                tribe='mech', initial_query=json.loads(json.dumps(asdict(query(4,'mech'))))) or
            canonical_digest(data['soul_progress']) != data['soul_progress_sha256']):
        raise TargetValidationError('Taunt death assembly lost complete originals or native producer recipes')
    return data


def register_assemble_taunt_death_producers(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Taunt death assembly changed a complete actual source or Soul')
    if canonical_digest(asdict(registry.player_effect(PREFIX+'soul_progress'))) != data['soul_progress_sha256']:
        raise TargetValidationError('Taunt death assembly changed original shared Soul progress')
    registry.register_behavior(MECH_BODY, lambda c: (SummonManaWorth(c.player_id,
        'constructed.cards', 4, SummonCause.capture(c), tribe='mech'),))
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('deathrattle', tuple(Keyword(k) for k in row['keywords'])),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']),
                deathrattle_behavior_id=row['deathrattle_body_id'])))
