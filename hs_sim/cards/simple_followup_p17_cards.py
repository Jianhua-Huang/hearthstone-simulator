"""Three exact Dream dependencies; the complete random parent is separate."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import ReturnToHand
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p17-v1.json'
BATCH_HASH='d6d7c5e90fba3ecbb8eff9fbf23fa619f8950587882721fecf767a62ff1cd15d'
SISTER='DREAM_01';DRAKE='DREAM_03';DREAM='DREAM_04';DEPENDENCIES=(SISTER,DRAKE,DREAM);ROOTS=()
PARENT='EDR_001';PREFIX='cards.simple_followup_p17.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P17 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or tuple(x['record']['id']for x in data['evidence_only'])!=(PARENT,)or
       data['cards']or data['existing_dependencies']or data['skipped']):raise TargetValidationError('Unreviewed P17 dependency or reserved parent set')
    for row in data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P17 original row')
    return data

def register_simple_followup_p17_cards(registry):
    data=load_batch()
    registry.register_behavior(PREFIX+'owner_return',lambda c:(ReturnToHand(c.target_id,to_owner=True),))
    for row in data['dependencies']:
        raw=row['record'];cid=raw['id'];metadata=replace(metadata_from_record(raw),deck_identity=cid);kwargs={}
        if metadata.collectible is not False or metadata.classes!=(CardClass.DREAM,):raise TargetValidationError('P17 must retain its exact noncollectible Dream class')
        if raw['cost']is not None:kwargs['cost']=raw['cost']
        elif 'COST'in raw['tags']:raise TargetValidationError('Absent printed Dream cost cannot carry a COST tag')
        if cid==DREAM:
            if raw['type']!='SPELL'or raw['tags'].get('SPELL_SCHOOL')!=4:raise TargetValidationError('Dream must retain its printed Nature spell face')
            kwargs.update(spell_school=SpellSchool.NATURE,on_play=PREFIX+'owner_return',
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        else:
            if raw['type']!='MINION':raise TargetValidationError('Dream bodies require their complete minion definitions')
            kwargs.update(attack=raw['attack'],health=raw['health'])
            if cid==SISTER:
                if raw['tags'].get('ELUSIVE')!=1:raise TargetValidationError('Laughing Sister lost its native Elusive declaration')
                kwargs['keywords']=(Keyword.ELUSIVE,)
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),metadata=metadata,**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
