"""Printed dead-face Undead extreme and per-body resurrection Reborn."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p15-v1.json'
BATCH_HASH='dfda428971fdefa3f16be999912e8bd126827fab975ccb132c8be27a25540880'
MANIFEST='TIME_616';RESUSCITATE='TLC_818';ROOTS=(MANIFEST,RESUSCITATE);PREFIX='cards.simple_followup_p15.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P15 complete reviewed source pin changed')
    if tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')):
        raise TargetValidationError('Unreviewed P15 root/dependency set')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P15 source row')
    return data

def register_simple_followup_p15_cards(registry):
    data=load_batch()
    def manifest(c):
        return(Resurrect(c.player_id,query=DeathQuery(cards=PoolQuery(tribes_any=('undead',)),cost_extreme='highest',cost_basis='printed'),
            source_id=c.source_id,cause=SummonCause.capture(c)),)
    def resuscitate(c):
        cause=SummonCause.capture(c)
        return tuple(Resurrect(c.player_id,query=DeathQuery(cards=PoolQuery(min_cost=n,max_cost=n),cost_basis='printed'),
            source_id=c.source_id,cause=cause,on_summon=PREFIX+'reborn')for n in(1,2,3))
    def reborn(c):
        if c.death is None or c.target_id is None:raise ResolutionError('Resuscitate requires its original successful resurrection body')
        return(GrantCapturedKeyword(MinionReference.capture(c.state.entities[c.target_id]),Keyword.REBORN,c.source_id),)
    for name,body in(('manifest',manifest),('resuscitate',resuscitate),('reborn',reborn)):
        registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='SPELL'or raw['collectible']is not True or raw['tags'].get('SPELL_SCHOOL')!=6:
            raise TargetValidationError('P15 requires its complete printed Shadow spell face')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),on_play=PREFIX+('manifest'if cid==MANIFEST else'resuscitate'))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
