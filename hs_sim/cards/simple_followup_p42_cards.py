"""Successful Fire-cast Get and actual own-turn hero-damage retaliation."""
import json
from pathlib import Path
from hs_sim.engine.effects import RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,HealthFlow,SpellSchool,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p42-v1.json'
BATCH_HASH='8af8e5e4cdce3d2695fadfc9523a1f2bd8705cbf1d59bc9e2f6bb318af6af530'
HERALD='FIR_913';DESTROYER='FIR_955';ROOTS=(HERALD,DESTROYER);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p42.'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('elemental',))

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P42 complete reviewed recipe set changed')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P42 original row')
    return data

def register_simple_followup_p42_cards(registry):
    def herald(c):
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):raise ResolutionError('Inferno Herald lost original completed spell linkage')
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:raise ResolutionError('Inferno Herald requires actual successful spell completion')
        if cast.player_id!=c.player_id or not living_source(c)or registry.card(cast.card_id).spell_school!=SpellSchool.FIRE:return()
        return(GenerateFromPool(c.player_id,POOL_ID,QUERY,source_id=c.source_id,cost=CostSpec(delta=-3,card_types=(CardType.MINION,))),)
    def destroyer(c):
        result=c.health_result
        if result is None:raise ResolutionError('Emberroot Destroyer requires its original settled health result')
        if(not living_source(c)or result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0 or
           result.active_player!=c.player_id or result.target_kind!=CardType.HERO.value or
           result.target_controller!=c.player_id or result.target_id!=c.state.players[c.player_id].hero_id):return()
        return(RandomDamage(minions(c,registry,3-c.player_id),3,c.source_id,DamageKind.MINION_ABILITY),)
    registry.register_behavior(PREFIX+HERALD,herald);registry.register_behavior(PREFIX+DESTROYER,destroyer)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION'or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):raise TargetValidationError('P42 requires complete collectible minion faces')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),triggers=(TriggerSpec('spell_cast_finished'if cid==HERALD else'health_resolved',PREFIX+cid),))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
