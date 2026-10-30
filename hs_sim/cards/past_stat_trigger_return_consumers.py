"""Actual health/combat triggers, original stat groups and physical weapon growth."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import Damage,DamageBatch,ModifyWeapon,RandomDamage
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (AttackPolicySpec,CardDefinition,CardType,CostSpec,DamageKind,
    EquippedWeaponReference,Keyword,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.effects import ChoiceOption
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference,SetCapturedMinionStats
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.costs import local_cost
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-stat-trigger-return-consumers-v1.json'
BATCH_HASH='d91ec1ccf11faf7642f322e0e00079bd320c58455f56776f560ad152fd59ca30'
GUNSPIRE,GUFF,ROKARA,CROWLEY,BOOGEY,GLASS,BOLVAR,BAROV,TARIM,KELESETH,GRUMBLE,ASHVANE=ROOTS=(
    'GIL_152','BAR_720','BAR_847','GIL_547','OG_300','GIL_817','ICC_858','SCH_526','UNG_015','ICC_851','LOOT_358','TSC_943')
DEPENDENCIES=EXISTING=()
PREFIX='cards.past_stat_trigger_return.'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Stat/trigger consumer lost its complete original minion face')
    fields={};events={GUNSPIRE:'health_resolved',GUFF:'spell_cast_finished',ROKARA:'attack_finished',
        CROWLEY:'attack_finished',BOOGEY:'attack_finished',GLASS:'health_resolved',BOLVAR:'shield_lost'}
    if cid in events:fields['triggers']=(TriggerSpec(events[cid],PREFIX+cid),)
    else:fields['battlecry']=PREFIX+cid
    if cid==BAROV:fields['deathrattle']=PREFIX+'barov_death'
    if cid==GUNSPIRE:fields['attack_policies']=(AttackPolicySpec('cannot_attack'),)
    keys=tuple(k for tag,k in(('RUSH',Keyword.RUSH),('DIVINE_SHIELD',Keyword.DIVINE_SHIELD),('TAUNT',Keyword.TAUNT))if raw['tags'].get(tag)==1)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=keys,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            any(d[k]for k in('dependencies','existing_dependencies'))or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=26 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Stat/trigger consumers lost full source roles or made a completeness claim')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','evidence_only')for x in d[key]):
        raise TargetValidationError('Stat/trigger consumers changed a complete original raw row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Stat/trigger consumers changed the complete past reference')
    reference=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in reference['candidate_records']}
    if(len(reference['candidate_ids'])!=732 or d['original_candidate_ids']!=reference['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Stat/trigger consumers cropped the original complete past source')
    return d


def register_past_stat_trigger_return_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Stat/trigger consumers cannot replace an existing original face')
        registry._validate_card(card);prepared.append(card)
    def gunspire(c):
        result=health_result(c.event)
        if result is None or result.target_id!=c.source_id or result.damage_dealt<=0:return()
        ids=characters(c,registry,3-c.player_id)
        return(RandomDamage(ids,3,c.source_id,DamageKind.MINION_ABILITY),)if ids else()
    def guff(c):
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if((row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id)or not row.completed):
            raise TargetValidationError('Guff lost its original completed CAST')
        if(row.player_id!=c.player_id or not row.payload_started or row.failure is not None or row.interrupted or
                registry.card(row.card_id).spell_school!=SpellSchool.NATURE or not living_source(c)):return()
        options=tuple(ChoiceOption(str(i),registry.card(c.state.entities[i].card_id).name,
            (BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),2,2,c.source_id),))
            for i in minions(c,registry,c.player_id)if i!=c.source_id)
        return(ChooseRandomEffects(c.player_id,c.source_id,options),)if options else()
    def original_attacker(c):
        row=completed_attack(c)
        if row is None or row.source_kind!=CardType.MINION:return None,None
        entity=c.state.entities.get(row.declaration.source_id)
        if(entity is None or(entity.card_id,entity.zone_epoch,entity.entered_order)!=(row.combat.source_card_id,
                row.combat.source_zone_epoch,row.combat.source_entered_order)or entity.zone!=Zone.BOARD or
                not entity.active or entity.health<=0 or entity.doomed):return row,None
        return row,entity
    def rokara(c):
        row,entity=original_attacker(c)
        if entity is None or entity.controller!=c.player_id or row.declaration.player_id!=c.player_id or not living_source(c):return()
        return(BuffCapturedMinion(MinionReference.capture(entity),1,1,c.source_id),)
    def kill_growth(c):
        row,entity=original_attacker(c)
        if entity is None or entity.id!=c.source_id or not living_source(c):return()
        target=c.state.entities[row.delivery.target_id]
        # Attack completion may precede the ordinary death checkpoint. The
        # original fatal transition is already frozen on the target then.
        causes=((target.death_cause,)if target.death_cause is not None else())+tuple(
            death.cause for death in c.state.death_history if death.entity_id==row.delivery.target_id)
        for cause in causes:
            result=cause.health_result
            if(cause.kind in('damage','poison')and result is not None and result.target_kind==CardType.MINION.value and
                    (cause.source_id,cause.source_card_id,cause.source_zone_epoch,cause.source_entered_order)==
                    (c.source_id,row.combat.source_card_id,row.combat.source_zone_epoch,row.combat.source_entered_order)and
                    result.damage_kind==DamageKind.COMBAT.value and result.original_target_id==row.delivery.target_id and
                    result.source_entered_order==row.combat.source_entered_order and
                    row.combat.event_cursor<result.batch_id<=row.terminal.event_cursor):
                return(BuffCapturedMinion(MinionReference.capture(entity),2,2,c.source_id),)
        return()
    def glass(c):
        result=health_result(c.event)
        if result is None or result.healed<=0 or not living_source(c):return()
        if result.source_controller is None:raise UnsupportedDefinitionError('Glass Knight requires actual healing source attribution')
        return(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.DIVINE_SHIELD,c.source_id),)if result.source_controller==c.player_id else()
    def bolvar(c):
        target=c.state.entities[c.event.target_id]
        return(BuffCapturedMinion(MinionReference.capture(c.source),2,0,c.source_id),)if(
            target.kind==CardType.MINION and target.controller==c.player_id and living_source(c))else()
    def group(c):return tuple(MinionReference.capture(c.state.entities[i])for p in(1,2)
        for i in minions(c,registry,p)if i!=c.source_id)
    def keleseth(c):
        ids=tuple(c.state.players[c.player_id].deck)
        if any(local_cost(c.state.entities[i])[0]==2 for i in ids):return()
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),1,1,c.source_id)
            for i in ids if c.state.entities[i].kind==CardType.MINION)
    def grumble(c):
        return tuple(ReturnCapturedMinion(MinionReference.capture(c.state.entities[i]),c.source_id,cost=CostSpec(set_to=1))
            for i in minions(c,registry,c.player_id)if i!=c.source_id)
    def ashvane(c):
        player=c.state.players[c.player_id];refs=tuple(CardReference.capture(c.state.entities[i])for i in(*player.hand,*player.deck)
            if c.state.entities[i].kind==CardType.WEAPON);weapon=equipped_weapon(c.state,player)
        return(*(ModifyWeapon(ref.entity_id,1,1,c.source_id,stored_card=ref)for ref in refs),
            *((ModifyWeapon(EquippedWeaponReference.capture(weapon),1,1,c.source_id),)if weapon is not None else()))
    bodies={GUNSPIRE:gunspire,GUFF:guff,ROKARA:rokara,CROWLEY:kill_growth,BOOGEY:kill_growth,GLASS:glass,BOLVAR:bolvar,
        BAROV:lambda c:tuple(SetCapturedMinionStats(ref,health=1,source_id=c.source_id)for ref in group(c)),
        'barov_death':lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.MINION_ABILITY)
            for p in(1,2)for i in minions(c,registry,p))),),
        TARIM:lambda c:tuple(SetCapturedMinionStats(ref,3,3,c.source_id)for ref in group(c)),
        KELESETH:keleseth,GRUMBLE:grumble,ASHVANE:ashvane}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
