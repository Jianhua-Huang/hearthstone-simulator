"""Current-tribe captured buffs; two complete roots await public capabilities."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,TargetSpec,Zone
from hs_sim.engine.physical_draw_groups import shares_tribes
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.tribes import tribe_state
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p12-v1.json'
BATCH_HASH='7f350eab3dbef9d55cac8e20f269552975ca60a347d13a7caec09e220b8bf415'
ENTROPY='TIME_026';TREES='TLC_230';FLEET='TLC_441';SHRED='TIME_025t';TREANT='TLC_230t'
ROOTS=(FLEET,);SKIPPED=(ENTROPY,TREES);PREFIX='cards.simple_followup_p12.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P12 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or
       tuple(x['record']['id']for x in data['skipped'])!=SKIPPED or
       tuple(x['record']['id']for x in data['evidence_only'])!=(SHRED,TREANT)or
       data['dependencies']or data['existing_dependencies']):raise TargetValidationError('Unreviewed P12 source/dependency set')
    for row in data['cards']+data['skipped']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P12 original row')
    return data

def register_simple_followup_p12_cards(registry):
    data=load_batch()
    def fleet(c):
        target=c.state.entities.get(c.target_id)
        if(target is None or target.id not in minions(c,registry,c.player_id)):return ()
        original=tribe_state(registry,target)
        if original is None:raise UnsupportedDefinitionError('Fleet original current target tribe is unknown')
        selected=[target]
        if original.members:
            for eid in minions(c,registry,c.player_id):
                if eid==target.id:continue
                entity=c.state.entities[eid];other=tribe_state(registry,entity)
                if other is None:raise UnsupportedDefinitionError('Fleet current candidate tribe is unknown')
                if other.members and shares_tribes(original,other):selected.append(entity)
        return tuple(BuffCapturedMinion(MinionReference.capture(e),1,2,c.source_id)for e in selected)
    registry.register_behavior(PREFIX+'fleet',fleet)
    raw=data['cards'][0]['record']
    if raw['collectible']is not True or 'SPELL_SCHOOL'in raw['tags']:raise TargetValidationError('Fleet printed metadata changed')
    card=CardDefinition(FLEET,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+'fleet',
        targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'),
        metadata=replace(metadata_from_record(raw),deck_identity=FLEET))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
