"""Actual stat, physical-zone, choice and destruction-continuation Battlecries."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import TakeCapturedMinion,TransformStoredCard
from hs_sim.engine.effects import (ChoiceOption,Damage,DestroyBatch,GainArmor,InvokeBehavior,RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import (BuffCapturedMinion,DestroyCapturedMinion,GrantCapturedKeyword,MinionReference)
from hs_sim.engine.zones import CardReference,CopyLowestCostMinion,HAND_TYPES,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/targeted-battlecry-effects-v1.json'
BATCH_HASH='02b67c53565b32d4dee30464a451412681bdf03fc04a05a796a0506158cb82b2'
PREFIX='cards.targeted_battlecry.'
SCRIPTS={'CATA_161':'nightmare','CATA_200':'eye','CORE_EX1_198':'natalie','CORE_ULD_165':'rift',
    'CORE_ULD_178':'siamat','EDR_518':'garden','FIR_960':'nurturer','JAIL_118':'vama',
    'TIME_429':'augur','TIME_435':'eternus','TLC_233':'incubator','TLC_606':'armorer'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Targeted Battlecries differ from reviewed full source pin')
    return data


def register_targeted_battlecry_cards(registry):
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'health_bound','v1'),
        lambda c:c.target['health']<=c.source['health'])

    def nightmare(c):
        if c.target_id is None:return ()
        target=c.state.entities[c.target_id];amount=c.source.attack
        return ((BuffStoredCard(CardReference.capture(target),attack=amount,source_id=c.source_id),)
            if target.zone==Zone.HAND else (BuffCapturedMinion(MinionReference.capture(target),attack=amount,source_id=c.source_id),))

    def destroy_health(c,damage=False):
        if c.target_id is None:return ()
        target=c.state.entities[c.target_id];amount=max(0,target.health)
        if damage:
            follow=(Damage(c.state.players[c.player_id].hero_id,amount,c.source_id,DamageKind.MINION_ABILITY),)
        else:
            follow=(BuffCapturedMinion(MinionReference.capture(c.source),health=amount,source_id=c.source_id),) if c.source.zone==Zone.BOARD else ()
        return (DestroyCapturedMinion(MinionReference.capture(target),c.source_id,follow),)

    def siamat(c):
        if c.source.zone!=Zone.BOARD:return ()
        source=MinionReference.capture(c.source)
        return (RequestChoice(c.player_id,tuple(ChoiceOption(key.value,key.value,
            (GrantCapturedKeyword(source,key,c.source_id),)) for key in
            (Keyword.RUSH,Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.WINDFURY)),
            c.source_id,prompt='选择两项效果',min_count=2,max_count=2),)

    def garden(c):
        follow=() if c.target_id is None else (ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(delta=-1),c.source_id),)
        return (Imbue(c.player_id,c.source_id),)+follow

    def vama(c):
        targets=[]
        for pid in (1,2):
            for eid in minions(c,registry,pid):
                meta=registry.card(c.state.entities[eid].card_id).metadata
                if meta is None:raise UnsupportedDefinitionError('Current minion classes are unknown: '+c.state.entities[eid].card_id)
                if CardClass.PALADIN not in meta.classes:targets.append(eid)
        return (DestroyBatch(tuple(targets),c.source_id),)

    def augur(c):
        result=[]
        for eid in c.state.players[c.player_id].hand:
            entity=c.state.entities[eid]
            if entity.kind!=CardType.MINION:continue
            higher=max(entity.attack,entity.health)
            result.append(BuffStoredCard(CardReference.capture(entity),higher-entity.attack,higher-entity.health,c.source_id))
        return tuple(result)

    def incubator(c):
        return tuple(effect for eid in minions(c,registry,c.player_id) if eid!=c.source_id and c.state.entities[eid].attack<=2
            for ref in (MinionReference.capture(c.state.entities[eid]),)
            for effect in (BuffCapturedMinion(ref,1,1,c.source_id),GrantCapturedKeyword(ref,Keyword.TAUNT,c.source_id)))


    def eternus(c):
        if c.target_id is None:return ()
        if (c.play is not None and c.play.source_id==c.source_id and c.play.target_id==c.target_id and
                c.play.body_targets is None and c.battlecry is not None and c.battlecry.origin=='hand'
                and c.battlecry.native_target is None):
            return (TakeCapturedMinion(None,c.player_id,c.source_id,c.play.id),)
        target=c.state.entities.get(c.target_id)
        if target is None or target.zone!=Zone.BOARD or target.kind!=CardType.MINION or not target.active or target.health<=0 or target.doomed:
            return ()
        return (TakeCapturedMinion(MinionReference.capture(target),c.player_id,c.source_id),)

    def armor_result(c):
        result=c.health_result
        return (InvokeHealthResult(PREFIX+'armor_after',c.event),) if result.target_id==result.original_target_id else ()

    def armor_after(c):
        result=c.health_result
        died=any(d.entity_id==result.original_target_id and d.cause is not None and
            d.cause.kind in ('damage','poison') and d.cause.result==result.payload() for d in c.state.death_history)
        return (GainArmor(c.player_id,5),) if died else ()

    bodies={
        'nightmare':nightmare,
        'eye':lambda c:(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),'GAME_005',c.source_id),) if c.target_id is not None else (),
        'natalie':lambda c:destroy_health(c),'rift':lambda c:destroy_health(c,True),'siamat':siamat,'garden':garden,
        'nurturer':lambda c:(CopyLowestCostMinion(c.player_id,('beast',),c.source_id),),
        'vama':vama,'augur':augur,
        'eternus':eternus,
        'incubator':incubator,
        'armorer':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.MINION_ABILITY,PREFIX+'armor_result'),) if c.target_id is not None else (),
        'armor_result':armor_result,'armor_after':armor_after,
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch();dep=data['existing_dependencies'][0];coin=registry.card('GAME_005')
    if canonical_digest(dep['record'])!=dep['record_sha256'] or coin.kind!=CardType.SPELL or coin.cost!=0 or coin.on_play is None:
        raise TargetValidationError('Existing Coin lost its complete executable spell face')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id']
        if (canonical_digest(raw)!=row['record_sha256'] or raw['type']!='MINION' or SCRIPTS.get(cid)!=recipe['script']
                or (raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=
                   (recipe['cost'],recipe['attack'],recipe['health'],recipe['collectible'])):
            raise TargetValidationError('Targeted Battlecry lost its complete reviewed face')
        kwargs={};target=recipe['target']
        if target is not None:
            hand=target in ('hand_card','hand_minion');mixed=target=='friendly_hand_or_board_minion'
            kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.HAND,) if hand else (Zone.HAND,Zone.BOARD) if mixed else (Zone.BOARD,),
                kinds=HAND_TYPES if target=='hand_card' else (CardType.MINION,),
                relation='friendly' if hand or mixed else 'enemy' if target=='enemy_minion' else 'any')
            if cid=='TIME_435':kwargs['target_rule']=PREFIX+'health_bound'
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            battlecry=PREFIX+recipe['script'],keywords=tuple(Keyword(k) for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
