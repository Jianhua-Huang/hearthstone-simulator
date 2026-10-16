"""Real death rewards, damage-sized summons and original physical draw buffs."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.draw_beneficiaries import DrawMatchingWithFollowup
from hs_sim.engine.effects import ChoiceOption,Damage,GainArmor,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record,reviewed_definition_digest
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/health-draw-beneficiaries-v1.json'
BATCH_HASH='2a6f4146d3f23c68f71671fdc1a7f7e133a7d3a05a784dfcbaeb8e56f121724e'
PREFIX='cards.health_beneficiary.'
SCRIPTS={'EDR_262':'bond','END_014':'spark','TIME_212':'rod','TLC_221':'swarm','TLC_231':'story','JAIL_866':'recipe','EDR_850pe':'wolf'}
WOLF='EDR_850pe';EMBER='TLC_249'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Health/draw beneficiaries lost their complete reviewed pin')
    return data


def original_death(c):
    result=c.health_result
    return result.target_id==result.original_target_id and any(d.entity_id==result.original_target_id and d.cause is not None
        and d.cause.kind in('damage','poison')and d.cause.result==result.payload()for d in c.state.death_history)


def drawn_card(c):
    if c.draw is None or(c.draw.player_id,c.draw.source_id,c.draw.entity_id,c.draw.outcome)!=(c.player_id,c.source_id,c.target_id,'hand')or not c.draw.completed:
        raise TargetValidationError('Draw reward requires its completed original physical hand draw')
    return c.state.entities[c.target_id]


def register_health_beneficiary_cards(registry):
    def invoke(c,name):return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id)
    def after_health(c,name):return (InvokeHealthResult(PREFIX+name,c.event),)
    def summon(c,cid):return SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
    def bond_after(c):return (summon(c,WOLF),)if original_death(c)else ()
    def spark_after(c):
        if not original_death(c):return ()
        refs=tuple(MinionReference.capture(c.state.entities[eid])for eid in minions(c,registry,c.player_id))
        if not refs:return ()
        options=tuple(ChoiceOption(json.dumps(asdict(ref),sort_keys=True,separators=(',',':')),
            'Random friendly minion',entity_id=ref.entity_id)for ref in refs)
        return (RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,sample_size=1,on_select=PREFIX+'spark_selected'),)
    def spark_selected(c):
        result=c.choice
        if result is None or result.selected_ids or len(result.choice.options)!=1:
            raise TargetValidationError('Spark lost its one automatically sampled original beneficiary')
        option=result.choice.options[0]
        ref=MinionReference(**json.loads(option.id));ref.__post_init__()
        if(ref.player_id,ref.entity_id)!=(c.player_id,option.entity_id):
            raise TargetValidationError('Spark beneficiary differs from original sampled reference')
        return (BuffCapturedMinion(ref,3,3,c.source_id),)
    def swarm_after(c):return tuple(summon(c,EMBER)for _ in range(c.health_result.damage_dealt))
    def story_reward(c):
        e=drawn_card(c)
        return (BuffStoredCard(CardReference.capture(e),health=5,source_id=c.source_id),GainArmor(c.player_id,5))if e.attack>=5 else ()
    def recipe_reward(c):
        e=drawn_card(c)
        return (BuffStoredCard(CardReference.capture(e),3,3,c.source_id),)if c.state.players[c.player_id].max_mana>=10 else ()
    bodies=dict(bond=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'bond_result'),),
        bond_result=lambda c:after_health(c,'bond_after'),bond_after=bond_after,
        spark=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'spark_result'),),
        spark_result=lambda c:after_health(c,'spark_after'),spark_after=spark_after,spark_selected=spark_selected,
        rod=lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),invoke(c,'rod_after')),
        rod_after=lambda c:(RandomDamage(minions(c,registry,3-c.player_id),4,c.source_id,DamageKind.SPELL),),
        swarm=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'swarm_result'),),
        swarm_result=lambda c:after_health(c,'swarm_after'),swarm_after=swarm_after,
        story=lambda c:(DrawMatchingWithFollowup(c.player_id,PoolQuery(kinds=(CardType.MINION,)),c.source_id,PREFIX+'story_reward'),),
        story_reward=story_reward,
        recipe=lambda c:(DrawMatchingWithFollowup(c.player_id,PoolQuery(kinds=(CardType.MINION,)),c.source_id,PREFIX+'recipe_reward',2),),
        recipe_reward=recipe_reward)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']or reviewed_definition_digest(registry.card(row['record']['id']))!=row['definition_sha256']:
            raise TargetValidationError('Existing Sizzling Cinder lost its complete native definition')
    raws={row['record']['id']:row['record']for row in data['cards']}
    for link in data['gallery_links']:
        dep=raws[WOLF]if link['root_id']=='EDR_262'else data['existing_dependencies'][0]['record']
        if link['gallery_record']['id']!=raws[link['root_id']]['dbf_id']or dep['dbf_id']not in link['gallery_record']['child_ids']:
            raise TargetValidationError('Named summon dependency differs from its complete CN gallery link')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];kwargs={};kind=CardType(raw['type'].lower())
        if canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=recipe['script']or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Health/draw recipe lost its complete reviewed native face')
        if kind==CardType.SPELL:
            target=recipe['target']
            if target is not None:
                is_minion=target in('minion','friendly_minion')
                kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,)if is_minion else(Zone.HERO,Zone.BOARD),
                    kinds=(CardType.MINION,)if is_minion else(CardType.HERO,CardType.MINION),
                    relation='friendly'if target=='friendly_minion'else'enemy'if target=='enemy'else'any')
            kwargs.update(on_play=PREFIX+recipe['script'],spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        elif kind==CardType.MINION and raw['id']==WOLF:kwargs['keywords']=(Keyword.RUSH,)
        else:raise TargetValidationError('Unknown health/draw card kind')
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
