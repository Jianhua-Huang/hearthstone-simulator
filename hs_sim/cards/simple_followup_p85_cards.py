"""Independent historical faces reusing reviewed complete current declarations."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p85-v1.json'
BATCH_HASH='f6fb732baed7540d933ec1259e78bf780f46bf19a7a252b80002370c82779cdb'
ANSHE,BRUTE,FINJA,TIGER,EARTH,GRIZZLY,CURATOR,BOOMKIN,CLEANER,THRESHER=(
 'BAR_313','BT_510','CFM_344','EX1_028','EX1_250','GIL_623','KAR_061','ONY_018','REV_946','SCH_605')
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=DEPENDENCIES=ROOTS=(ANSHE,BRUTE,FINJA,TIGER,EARTH,GRIZZLY,CURATOR,BOOMKIN,CLEANER,THRESHER)

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=ROOTS:
  raise TargetValidationError('P85 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):
  raise TargetValidationError('P85 complete original record changed')
 return d

def register_simple_followup_p85_cards(registry):
 d=load_batch()
 for cid,pin in d['existing_dependency_definition_pins'].items():
  if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']:
   raise TargetValidationError('P85 requires unchanged complete source '+cid)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];original=registry.card(d['reviewed_declaration_aliases'][cid])
  definition=replace(original,id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw))
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
