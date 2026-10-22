"""Actual Spellcaster split; the condition stays with its authored prefix."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source

CARD='CATA_483'
CONDITION='cards.assemble_conditional.own_spell_damage_turn'
BODY='cards.assemble_conditional.self_copy'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-conditional-spell-damage-fragments-v1.json'
BATCH_HASH='98ec79dfbb02a9dd4ecb6c8200f79f491703e2935ab3070aed597eab56e63a9a'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,)or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped'))or
            canonical_digest(rows[0]['record'])!=rows[0]['record_sha256']):
        raise TargetValidationError('Conditional assembly requires the complete original Spellcaster')
    return data


def register_assemble_conditional_spell_damage_fragments(registry):
    data=load_batch();row=data['existing_dependencies'][0];original=registry.card(CARD);decl=data['reviewed_template']
    if(canonical_digest(asdict(original))!=row['definition_sha256']or
            original.battlecry!=decl['original_battlecry_id'] or original.spell_damage!=1 or
            row['record']['text'].count('&')!=1 or row['record']['text_en'].count('&')!=1):
        raise TargetValidationError('Conditional assembly changed its complete original Spellcaster')
    registry.register_trigger_condition(CONDITION,lambda c:
        spell_damage_dealt(c.state,registry,c.player_id,turn=c.state.turn)>0)
    def copy_self(c):
        if c.deathrattle is not None:
            raise ResolutionError('Natural/active Deathrattle self-copy policy remains explicitly unimplemented')
        if not living_source(c):return ()
        return (CopyMinion(capture_board_presence(c.state,c.source_id),c.player_id,cause=SummonCause.capture(c)),)
    registry.register_behavior(BODY,copy_self)
    registry.register_assemble_template(AssembleTemplate(CARD,
        AssemblePrefix('battlecry',spell_damage=1,condition_id=CONDITION),
        AssembleSuffix(BODY,tuple(decl['allowed_timings']),pending_timings=tuple(decl['pending_timings'])),
        original_battlecry_id=original.battlecry))
