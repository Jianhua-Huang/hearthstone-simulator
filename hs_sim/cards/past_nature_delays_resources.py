"""Real hidden deadlines, original forged draw, stat theft and mana conversion."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChangeManaCrystals, Draw, GainArmor, GainTemporaryMana
from hs_sim.engine.health_theft import StealMinionStats
from hs_sim.engine.model import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    HandActionSpec, HandProgressSpec, PlayerEffectSpec, TargetSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import (ConvertManaCrystalsToMinions, SummonByCard,
    SummonCause, SummonEntryMaterial)
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOTS=('ETC_387','RLK_655','TTN_930','TTN_951','UNG_111','VAC_508')
DEPENDENCIES=('ETC_387b','ETC_387c','ETC_387bt','ETC_387ct','TTN_930t','TTN_951t','UNG_111t1')
CHOICES=('ETC_387b','ETC_387c')
TOKENS=('ETC_387bt','ETC_387ct','UNG_111t1')
PREFIX='cards.past_nature_delays_resources.'
ANCIENTS=PREFIX+'ancient_deadline'
GIANTS=PREFIX+'giant_deadline'
TRAIL=PREFIX+'trail_deadline'
POLICY='cn37-local-past-nature-delays-resources-v1'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-nature-delays-resources-v1.json'
BATCH_HASH='ad8d64d7e88415ed147050b962cfa89a0e8efe4b244f7b84cfa4333bf0a1c376'
CHOOSE_ONE=PoolQuery(choose_one=True)


def make_definition(raw):
    cid=raw['id'];fields={}
    if cid in TOKENS:
        if cid=='UNG_111t1':fields['deathrattle']=PREFIX+'mana_refund'
        return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],
            attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**fields)
    if cid in CHOICES:fields['choice_only']=True
    else:fields['on_play']=PREFIX+cid
    if cid=='ETC_387':
        fields.update(on_play='engine.choose_one',choose_one=ChooseOneSpec(tuple(
            ChooseBranch(branch,label,PREFIX+branch)for branch,label in(
                ('ETC_387b','两回合后召唤三个5/5古树'),('ETC_387c','四回合后召唤三个8/8巨人'))),
            ChooseBranch('ETC_387:combined','两者兼得',PREFIX+'rhythm_both')))
    if cid=='RLK_655':fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid=='TTN_930':fields['hand_progress']=HandProgressSpec('event',3,'TTN_930t',
        event='turn_ended',condition_id=PREFIX+'owner_end')
    if cid=='TTN_951':fields['hand_actions']=(HandActionSpec('forge','forge',2,'TTN_951t'),)
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
        spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            d['existing_dependencies'] or len(d['evidence_only'])!=14 or
            len(d['official_observations'])!=32 or len(d['unconfirmed_primary_faces'])!=4 or
            len(d['complete_druid_Nature_inventory'])!=85 or d['original_missing_native_ids']!=list(ROOTS) or
            any(d[k]for k in('new_standard_roots','membership_uses_executable_coverage',
                'source_scope_bound','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Nature delayed/resource consumers require their full fixed source')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Nature delayed/resource consumers lost a complete original row')
    return d


def register_past_nature_delays_resources(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        cid=row['record']['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Nature delayed/resource consumer cannot overwrite '+cid)
        card=make_definition(row['record'])
        if canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Nature delayed/resource consumer changed its full reviewed face')
        prepared.append(card)

    def fixed(c,token,count=3):
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(token),),cause)for _ in range(count))

    def wither(c):
        target=c.state.entities.get(c.target_id)
        if (target is None or target.zone!=Zone.BOARD or target.kind!=CardType.MINION or
                not target.active or target.health<=0 or target.doomed):return()
        donor=MinionReference.capture(target)
        return tuple(StealMinionStats(MinionReference.capture(c.state.entities[i]),donor,c.source_id)
            for i in minions(c,registry,c.player_id)if has_any_tribe(registry,c.state.entities[i],('undead',)))

    bodies={
        'ETC_387b':lambda c:(AddPlayerEffect(c.player_id,ANCIENTS,c.source_id),),
        'ETC_387c':lambda c:(AddPlayerEffect(c.player_id,GIANTS,c.source_id),),
        'rhythm_both':lambda c:(AddPlayerEffect(c.player_id,ANCIENTS,c.source_id),AddPlayerEffect(c.player_id,GIANTS,c.source_id)),
        'ancients':lambda c:fixed(c,'ETC_387bt'),
        'giants':lambda c:fixed(c,'ETC_387ct'),
        'RLK_655':wither,
        'TTN_930':lambda c:(Draw(c.player_id,1,c.source_id),GainArmor(c.player_id,5)),
        'TTN_930t':lambda c:(Draw(c.player_id,2,c.source_id),GainArmor(c.player_id,10)),
        'TTN_951':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(CHOOSE_ONE),)),),
        'TTN_951t':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(CHOOSE_ONE),),
            DrawGroupReward('combine_original_choose_one')),),
        'UNG_111':lambda c:(ConvertManaCrystalsToMinions(c.player_id,'UNG_111t1',SummonCause.capture(c)),),
        'mana_refund':lambda c:(ChangeManaCrystals(c.player_id,1),),
        'VAC_508':lambda c:(AddPlayerEffect(c.player_id,TRAIL,c.source_id),),
        'trail_reward':lambda c:(GainTemporaryMana(c.player_id,2),),
    }
    registry.register_trigger_condition(PREFIX+'owner_end',lambda c:c.event is not None and c.event.player_id==c.player_id)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:registry.register_pool_card(PoolCard.from_definition(card))
    for key,duration,body in((ANCIENTS,2,'ancients'),(GIANTS,4,'giants')):
        registry.register_player_effect(PlayerEffectSpec(key,'ETC_387',kind='secret_objective',
            duration=duration,tick_event='turn_started',on_expire=PREFIX+body))
    registry.register_player_effect(PlayerEffectSpec(TRAIL,'VAC_508',kind='sigil',duration=1,
        tick_event='turn_started',on_expire=PREFIX+'trail_reward'))
