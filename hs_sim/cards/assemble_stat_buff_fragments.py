"""Ten reviewed stat halves retain native queries, timing stages and references."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import CardType,Keyword
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('BE_207','DINO_421','EDR_230','END_021','TIME_037','TIME_051','TIME_720','TIME_871','TLC_233','JAIL_513')
DOVE='TIME_037'
BEFORE='cards.assemble_stat_buff.draw_minion'
DOVE_BODY='cards.parallel_trial_p01.dove_hand'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-stat-buff-fragments-v1.json'
BATCH_HASH='af6d4accc7e6537ba53e70ab226ace4c59cd02c5e45ec91b61834527247d7993'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES or
            tuple(d['card_id']for d in data['reviewed_templates'])!=SOURCES or
            data['numeric_normalizations']!={'BE_207':{'attack':0}} or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Stat assembly requires ten complete reviewed original sources')
    return data


def register_assemble_stat_buff_fragments(registry):
    data=load_batch();query=PoolQuery(kinds=(CardType.MINION,))
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Stat assembly changed a complete original source')
    if canonical_digest(asdict(query))!=canonical_digest(data['dove_draw_query']):
        raise TargetValidationError('Stat assembly changed the complete original Dove draw query')
    registry.register_behavior(BEFORE,lambda c:(DrawMatching(c.player_id,query,'skip',source_id=c.source_id),))
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),
                spell_damage=decl['spell_damage'],before_behavior_id=decl['before_behavior_id']),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings'])),
            original_battlecry_id=decl['original_battlecry_id']))
