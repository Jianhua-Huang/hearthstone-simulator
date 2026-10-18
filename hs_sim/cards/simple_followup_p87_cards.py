"""Complete accepted native declarations under their original historical faces."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p87-v1.json'
BATCH_HASH='213177f831f84f0da6905551741f3eb1bd1fb39fc8ed78d58afa12858a9a7437'
FIRE,INFERNAL,KINGS,BLADE,ARCHER,DOCTOR,IMP,PROTECTOR,SUNFURY,SEER,COMPANION,TOLVIR,PHOENIX=(
 'CS2_042','CS2_064','CS2_088','CS2_181','CS2_189','EX1_011','EX1_319','EX1_362','EX1_058','EX1_103','ULD_191','ULD_271','UNG_084')
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=DEPENDENCIES=ROOTS=(FIRE,INFERNAL,KINGS,BLADE,ARCHER,DOCTOR,IMP,PROTECTOR,SUNFURY,SEER,COMPANION,TOLVIR,PHOENIX)

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=ROOTS:raise TargetValidationError('P87 complete assigned scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P87 complete original source changed')
 return d

def register_simple_followup_p87_cards(registry):
 d=load_batch()
 for cid,pin in d['existing_dependency_definition_pins'].items():
  if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']:raise TargetValidationError('P87 requires unchanged complete source '+cid)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];original=registry.card(d['reviewed_declaration_aliases'][cid])
  definition=replace(original,id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw))
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
