"""Three ordinary discoveries with native payment and delayed hand-cost effects."""
import json
from pathlib import Path
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p36-v1.json'
BATCH_HASH='af328f6a5c554caf3704992055e515f843b94d3db7c77792f70fad65c924e4ca'
RELIC='TLC_334';SCAVENGER='TLC_461';REAVER='FIR_952';ROOTS=(RELIC,SCAVENGER,REAVER);DEPENDENCIES=();EXISTING_DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p36.'
QUERIES={RELIC:PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=8),
 REAVER:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FEL,),class_mode='current')}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P36 complete reviewed source pin changed')
    if tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('Unreviewed P36 recipe set')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P36 original row')
    return data

def register_simple_followup_p36_cards(registry):
    data=load_batch()
    def relic(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[RELIC],source_id=c.source_id,cost=CostSpec(set_to=1)),)
    def scavenger(c):
        amount=c.state.players[c.player_id].mana
        return(DiscoverFromPool(c.player_id,POOL_ID,PoolQuery(collectible=True,min_cost=amount,max_cost=amount,class_mode='current'),source_id=c.source_id),)
    def reaver(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[REAVER],source_id=c.source_id),InvokeBehavior(PREFIX+'discount',c.source_id,c.player_id,play_id=None if c.play is None else c.play.id))
    def discount(c):return tuple(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-1),c.source_id)
        for i in c.state.players[c.player_id].hand for e in(c.state.entities[i],)
        if e.kind==CardType.SPELL and registry.card(e.card_id).spell_school==SpellSchool.FEL)
    for name,body in((RELIC,relic),(SCAVENGER,scavenger),(REAVER,reaver),('discount',discount)):registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int or raw['tags'].get('SPELL_SCHOOL')is not None:raise TargetValidationError('P36 requires complete reviewed unschooled faces')
        if cid==RELIC:kwargs['on_play']=PREFIX+cid
        elif kind==CardType.MINION:
            if any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P36 explicit minion stats required')
            kwargs.update(attack=raw['attack'],health=raw['health'],battlecry=PREFIX+cid)
        else:raise TargetValidationError('Unreviewed P36 type')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
