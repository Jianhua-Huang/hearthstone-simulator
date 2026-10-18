"""Complete native death, health and actual-event declarations under historical IDs."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p88-v1.json'
BATCH_HASH='ec6dbea53639d2f35fc30800a5d849887665d2066c9ba493e8a5103232d3cb0e'
LIGHTSHOWER,MIXTRESS,VENDOR,PORCUPINE,CRYPT,FORGE,SAPPER,RATTLER,SERVANT,ACOLYTE,DEATH_ACOLYTE,BATTLEFIEND,VAPOR=(
 'BAR_310','CFM_120','DMF_067','BT_201','RLK_657','SW_068','ULD_280','WC_701','YOD_026','EX1_007','RLK_121','BT_351','WC_042')
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=DEPENDENCIES=ROOTS=(LIGHTSHOWER,MIXTRESS,VENDOR,PORCUPINE,CRYPT,FORGE,SAPPER,RATTLER,SERVANT,ACOLYTE,DEATH_ACOLYTE,BATTLEFIEND,VAPOR)

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=ROOTS:raise TargetValidationError('P88 complete assigned scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P88 complete original source changed')
 return d

def register_simple_followup_p88_cards(registry):
 d=load_batch()
 for cid,pin in d['existing_dependency_definition_pins'].items():
  if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']:raise TargetValidationError('P88 requires unchanged complete source '+cid)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];original=registry.card(d['reviewed_declaration_aliases'][cid])
  definition=replace(original,id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw))
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
