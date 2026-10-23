"""Named Dreadseeds and an actual Deathrattle corpse-paid Footman branch."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.effects import SpendResource
from hs_sim.engine.model import EndTurnSpec, Keyword, Resource
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .corpse_trigger_choice_cards import FOOTMAN
from .native_dreadseed_cards import SEEDS, EVIDENCE_ONLY, TURNS, BATCH_HASH as NATIVE_HASH
from .native_followup_cards import deathrattle_position

SOURCES = ('EDR_841', 'RLK_061')
DEATH_BODY = 'cards.assemble_native_summon_costs.necromancer_death'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-native-summon-costs-v1.json'
BATCH_HASH = '7d7934f0fde57f07b9ac0fdc63853310c435868fd82b5f0da57df433f8d41b84'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != SOURCES+SEEDS+(FOOTMAN,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != EVIDENCE_ONLY or
            any(data[k] for k in ('cards', 'dependencies', 'choice_only', 'skipped')) or
            tuple(data['native_seed_ids']) != SEEDS or data['native_seed_turns'] != TURNS or
            data['native_dreadseed_batch_hash'] != NATIVE_HASH or
            tuple(x['card_id'] for x in data['reviewed_templates']) != SOURCES or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['existing_dependencies']+data['evidence_only']) or
            any(canonical_digest(x['definition']) != x['definition_sha256'] for x in data['existing_dependencies'])):
        raise TargetValidationError('Native summon assembly lost its complete originals or named seed inventory')
    return data


def register_assemble_native_summon_costs(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Native summon assembly changed a complete source or actual token')
    def necromancer_death(c):
        if c.deathrattle is None:
            raise UnsupportedDefinitionError('Corpse-paid death body requires its actual accepted Deathrattle')
        summon = SummonByCard(c.player_id, (SummonEntryMaterial(FOOTMAN),),
            SummonCause.capture(c), position=deathrattle_position(c))
        return (SpendResource(c.player_id, Resource.CORPSES, 1, on_success=(summon,),
            requires_board_space=True),)
    registry.register_behavior(DEATH_BODY, necromancer_death)
    for row in data['reviewed_templates']:
        end = EndTurnSpec(**row['end_turn']) if row['end_turn'] is not None else None
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'], tuple(Keyword(k) for k in row['keywords']), end),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']),
                deathrattle_behavior_id=row['deathrattle_body_id']),
            original_end_turn_id=row['original_end_turn_id']))
