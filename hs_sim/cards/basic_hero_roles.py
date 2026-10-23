"""Default role definitions and complete basic Totem family; no formal pool claim."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Damage,Heal,HealBatch
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,EndTurnSpec,HealingKind,Keyword,TargetSpec,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record,reviewed_definition_digest
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/basic-hero-roles-v1.json'
BATCH_HASH='16215dc8a4dcb6d6d2f5455696fbf894565af4e10661920354d859651d3901ed'
PREFIX='cards.basic_roles.'
TOTEMS=('CS2_050','CS2_051','CS2_052','NEW1_009')
BINDINGS=('HERO_02','HERO_05','HERO_09','HERO_11')


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Basic roles lost their complete reviewed source pin')
    return value


def representative_initial_bindings():
    data=load_batch();rows=data['binding_updates'];powers={x['power_record']['id']:x['power_record']for x in data['canonical_roles']}
    if tuple(x['hero_record']['id']for x in rows)!=BINDINGS:raise TargetValidationError('Unreviewed starting hero binding set')
    for row in rows:
        raw=row['hero_record'];power=powers[row['power_id']]
        if (canonical_digest(raw)!=row['hero_record_sha256']or canonical_digest(power)!=row['power_record_sha256']or
                raw['tags']['HERO_POWER']!=power['dbf_id']or raw['tags']['CLASS']!=power['tags']['CLASS']):
            raise TargetValidationError('Starting hero binding differs from its original class/reference')
    return tuple((x['hero_record']['id'],x['power_id'])for x in rows)


def register_basic_hero_roles(registry):
    data=load_batch()
    if tuple(data['basic_totem_ids'])!=TOTEMS:raise TargetValidationError('Basic Totem family must remain complete and ordered')
    for row in data['binding_updates']:
        if reviewed_definition_digest(registry.card(row['hero_record']['id']))!=row['after_definition_sha256']:
            raise TargetValidationError('Starting role changed fields outside its reviewed initial power binding')
    for row in data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']or reviewed_definition_digest(registry.card(row['record']['id']))!=row['definition_sha256']:
            raise TargetValidationError('Existing Life Tap/Ghoul dependency differs from its full reviewed behavior')
    def available(c):
        own=c.observation['players'][c.player_id-1]
        present={x['card_id']for x in own['board']if x.get('kind')==CardType.MINION.value}
        return any(cid not in present for cid in TOTEMS)
    registry.register_use_rule(PREFIX+'totem_available',available,visibility='player')
    def totem(c):
        present={c.state.entities[i].card_id for i in c.state.players[c.player_id].board if c.state.entities[i].kind==CardType.MINION}
        entries=tuple(SummonEntryMaterial(cid)for cid in TOTEMS if cid not in present)
        return(SummonByCard(c.player_id,entries,SummonCause.capture(c),selection='random'),)if entries else ()
    bodies=dict(totemic_call=totem,
        steady_shot=lambda c:(Damage(c.state.players[3-c.player_id].hero_id if c.target_id is None else c.target_id,
            2,c.source_id,DamageKind.HERO_POWER),),
        lesser_heal=lambda c:(Heal(c.target_id,2,c.source_id,HealingKind.HERO_POWER),)if c.target_id is not None else (),
        demon_claws=lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=1,source_id=c.source_id,expires_turn=c.state.turn),),
        ghoul_charge=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial('HERO_11bpt'),),SummonCause.capture(c)),),
        healing_totem=lambda c:(HealBatch(tuple(Heal(eid,1,c.source_id,HealingKind.EFFECT)for eid in minions(c,registry,c.player_id))),))
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Basic role source row differs from its review')
        kind=CardType[raw['type']];kwargs={}
        if script=='starting_hero':kwargs['initial_hero_power']=recipe['initial_power']
        elif kind==CardType.HERO_POWER:
            if script not in bodies:raise TargetValidationError('Unknown default Hero Power body')
            kwargs['on_use']=PREFIX+script
            if script in ('totemic_call','ghoul_charge'):kwargs['requires_board_space']=True
            if script=='totemic_call':kwargs['use_rule']=PREFIX+'totem_available'
            if script=='lesser_heal':kwargs['targeting']=TargetSpec()
        elif script=='taunt_totem':kwargs['keywords']=(Keyword.TAUNT,)
        elif script=='spell_damage_totem':kwargs['spell_damage']=recipe['amount']
        elif script=='healing_totem':kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+script,EndTurnSpec()),)
        elif script!='plain_totem':raise TargetValidationError('Unknown full basic Totem face')
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=replace(metadata_from_record(raw),deck_identity=raw['id']),**kwargs)
        registry.register_card(card)
        if kind==CardType.MINION:registry.register_pool_card(PoolCard.from_definition(card))
    for cid in TOTEMS:
        if registry.card(cid).kind!=CardType.MINION:raise TargetValidationError('Missing executable member in the basic Totem family')
