"""Known social-only Deathrattle retains its complete native combat identity."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p16-v1.json'
BATCH_HASH='888a45bc790793a5a23fbaf89be87cabae8325462e5a96b40cee3577c82d6d5b'
GUARD='JAIL_703';ROOTS=(GUARD,);DEPENDENCIES=();SKIPPED_DEPENDENCIES=('DREAM_01','DREAM_03','DREAM_04')
PARENT='EDR_001';PREFIX='cards.simple_followup_p16.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P16 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['skipped_dependencies'])!=SKIPPED_DEPENDENCIES or
       tuple(x['record']['id']for x in data['evidence_only'])!=(PARENT,)or data['dependencies']or data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed P16 roots or pending dependencies')
    for row in data['cards']+data['skipped_dependencies']+data['evidence_only']+data['noncombat_text_review']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P16 original row')
    return data

def register_simple_followup_p16_cards(registry):
    data=load_batch()
    def noncombat_sorry_permission(c):
        # Social emote permission is explicitly outside the requested combat
        # scope. Keep real native activation/provenance, without client state.
        if c.deathrattle is None:raise ResolutionError('Sorry permission requires its native Deathrattle invocation')
        return ()
    registry.register_behavior(PREFIX+'noncombat_sorry_permission',noncombat_sorry_permission)
    raw=data['cards'][0]['record']
    if raw['type']!='MINION'or raw['collectible']is not True or raw['tags'].get('DEATHRATTLE')!=1:
        raise TargetValidationError('Guard lost its printed native Deathrattle face')
    card=CardDefinition(GUARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        deathrattle=PREFIX+'noncombat_sorry_permission',metadata=replace(metadata_from_record(raw),deck_identity=GUARD))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
