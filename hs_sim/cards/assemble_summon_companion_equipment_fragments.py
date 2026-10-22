"""Native death-slot bodies stay native; other timings compose ordinary summons."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.engine.pools import GenerateFromPool,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .simple_followup_p30_cards import QUERIES as Q30
from .simple_followup_p34_cards import QUERIES as Q34
from .simple_followup_p45_cards import QUERIES as Q45
from .simple_followup_p89_cards import QUERIES as Q89

SOURCES=('CATA_723','CORE_GVG_114','CORE_REV_308','DINO_431','JAIL_878','TIME_052','TLC_479','MEND_301','CORE_EX1_383')
DEPENDENCIES=('TLC_446t2','TLC_446t3','TLC_446t4','NEW1_034','NEW1_033','NEW1_032','EX1_383t')
PREFIX='cards.assemble_summon.nondeath.'
PROFILES={'CATA_723':('generate','constructed.cards',Q30['CATA_723'],2),
    'CORE_GVG_114':('summon','constructed.cards',Q30['CORE_GVG_114'],1),
    'DINO_431':('summon','constructed.cards',Q34['DINO_431'],1),
    'JAIL_878':('summon','constructed.cards',Q45['JAIL_878'],1),
    'TIME_052':('generate','constructed.past.cards',Q89['TIME_052'],1)}
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-summon-companion-equipment-fragments-v1.json'
BATCH_HASH='f6bcdc5ecc2c678f2c43af8f27b3c01b9bb888bd8f51cf81ae9e227166c0cf52'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+DEPENDENCIES or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Summon assembly requires nine complete sources and seven fixed dependencies')
    return data


def nondeath_body(c,profile):
    mode,pool,query,count=profile;cause=SummonCause.capture(c)
    if mode=='generate':
        return (GenerateFromPool(c.player_id,pool,query,count=count,source_id=c.source_id,destination='board',cause=cause),)
    return (SummonFromPool(c.player_id,pool,query,source_id=c.source_id,cause=cause),)


def register_assemble_summon_companion_equipment_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Summon assembly changed a complete original source or fixed dependency')
    for decl in data['reviewed_templates']:
        cid=decl['card_id']
        if cid in PROFILES:
            mode,pool,query,count=PROFILES[cid]
            actual=dict(mode=mode,pool_id=pool,query=asdict(query),count=count)
            if canonical_digest(actual)!=canonical_digest(decl['nondeath_profile'])or decl['behavior_id']!=PREFIX+cid:
                raise TargetValidationError('Summon assembly changed its reviewed nondeath producer parameters')
            registry.register_behavior(decl['behavior_id'],lambda c,profile=PROFILES[cid]:nondeath_body(c,profile))
        registry.register_assemble_template(AssembleTemplate(cid,
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords'])),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']),
                deathrattle_behavior_id=decl['deathrattle_behavior_id'])))
