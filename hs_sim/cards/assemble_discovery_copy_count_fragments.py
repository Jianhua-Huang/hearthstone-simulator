"""Reviewed discovery/copy/count bodies retain their actual original contexts."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.dark_gifts import DARK_GIFTS,DARK_GIFT_VERSION
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('BE_150','BE_204','BE_734','CORE_BOT_256','EDR_102','END_013',
    'FIR_924','FIR_960','JAIL_123','TIME_605','TIME_872','TLC_461')
FAMILY='cthun.empire'
SKILLS=tuple('BE_013t'+str(n)for n in range(1,5))
FANATIC='BE_013t5'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-discovery-copy-count-fragments-v1.json'
BATCH_HASH='9be752b94c2ad5ae5a6de749dd2649d2ea1e37df89e2f38f9b56630d0d445ad2'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+SKILLS+(FANATIC,) or
            tuple(d['card_id']for d in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Discovery-copy assembly requires twelve complete sources and five existing Cthun dependencies')
    evidence=data['inherited_cthun_audit'];path=BATCH_PATH.parents[2]/evidence['path']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=evidence['sha256'] or
            evidence['all_primary_faces_verified']is not False or evidence['cn_calibrated']is not False):
        raise TargetValidationError('Discovery-copy assembly must retain original Cthun evidence and unresolved CN conflicts')
    if(data['dark_gift_version']!=DARK_GIFT_VERSION or
            data['dark_gift_recipes_sha256']!=canonical_digest([asdict(g)for g in DARK_GIFTS])):
        raise TargetValidationError('Discovery-copy assembly changed the complete original Dark Gift recipes')
    return data


def register_assemble_discovery_copy_count_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Discovery-copy assembly changed a complete original source or dependency')
    if canonical_digest(asdict(registry.ability_family_profiles[FAMILY]))!=canonical_digest(data['ability_family_pin']):
        raise TargetValidationError('Discovery-copy assembly changed the complete original skill family')
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),spell_damage=decl['spell_damage']),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']),pending_timings=tuple(decl['pending_timings']))))
