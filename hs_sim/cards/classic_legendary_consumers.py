"""Original Classic faces consume existing target, draw, death and cost rules."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier,ChoiceOption,Destroy,Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,HandActionSpec,Keyword,PlayerEffectSpec,
    TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.player_effects import AddPlayerEffect,ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/classic-legendary-consumers-v1.json'
BATCH_HASH='1268f7714086743d98e9d76125c61d4a69b6143810d7d0538561d58b6f74921f'
BLACK_KNIGHT,NAT,HARRISON,ALEXSTRASZA,BEAST,MILLHOUSE=ROOTS=(
    'EX1_002','EX1_557','EX1_558','EX1_561','EX1_577','NEW1_029')
FINKLE,=DEPENDENCIES=('EX1_finkle',)
PREFIX='cards.classic_legendary.'
PROGRAM=PREFIX+'millhouse_pending'
NORMALIZATIONS={NAT:{'attack':0}}


def make_definition(raw):
    cid=raw['id'];fields={}
    if(cid not in(*ROOTS,*DEPENDENCIES)or raw['type']!='MINION'or type(raw['cost'])is not int or
            type(raw['health'])is not int):
        raise TargetValidationError('Classic consumers require complete original minion faces')
    attack=raw['attack']
    if cid==NAT:
        if attack is not None or 'ATK'in raw['tags']:
            raise TargetValidationError('Nat normalization only accepts its original absent attack field')
        attack=0
    if type(attack)is not int:raise TargetValidationError('Classic consumer lacks verified printed attack')
    if cid in ROOTS:
        if not raw['collectible']or raw['tags'].get('RARITY')!=5:
            raise TargetValidationError('Classic consumer lost its original collectible Legendary identity')
        if cid==BLACK_KNIGHT:
            if(raw['tags'].get('TRADEABLE'),raw['tags'].get('DECK_ACTION_COST'))!=(1,1):
                raise TargetValidationError('Black Knight lost its actual Tradeable declaration')
            fields.update(battlecry=PREFIX+'black_knight',hand_actions=(HandActionSpec('trade','trade',1),),
                targeting=TargetSpec(mode=TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
                    kinds=(CardType.MINION,),relation='enemy'),target_rule=PREFIX+'taunt')
        elif cid==NAT:fields['triggers']=(TriggerSpec('turn_started',PREFIX+'nat'),)
        elif cid==BEAST:fields['deathrattle']=PREFIX+'beast'
        else:fields['battlecry']=PREFIX+{HARRISON:'harrison',ALEXSTRASZA:'alexstrasza',MILLHOUSE:'millhouse'}[cid]
        if cid==ALEXSTRASZA:fields['targeting']=TargetSpec(zones=(Zone.HERO,),kinds=(CardType.HERO,))
    elif raw['collectible']or raw['text']or raw['text_en']:
        raise TargetValidationError('Pip Quickwit requires its complete original vanilla face')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=attack,health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-classic-legendary-consumers-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701','EX1_560']or
            d['numeric_normalizations']!=NORMALIZATIONS or len(d['official_observations'])!=20 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Classic consumers lost complete source identities, roles or policy')
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Classic consumers changed a complete original source row')
    records={x['record']['id']:x['record']for key in('cards','dependencies')for x in d[key]}
    if records[BEAST]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=records[FINKLE]['dbf_id']:
        raise TargetValidationError('The Beast lost its actual named original child')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Classic consumers changed a complete retained source')
    if d['retained_documents']['full_reference']!={'path':d['full_reference_document'],'sha256':d['full_reference_sha256']}:
        raise TargetValidationError('Classic consumers lost their exact complete reference binding')
    ref=json.loads((ROOT/d['full_reference_document']).read_text(encoding='utf8'))
    full={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=full[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Classic consumers cropped the complete original past domain')
    return d


def register_classic_legendary_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Classic consumer cannot replace or alter an existing face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Classic consumer changed complete existing metadata')
        prepared.append(card)
    def black_knight(c):return(Destroy(c.target_id,c.source_id),)if c.target_id is not None else()
    def nat(c):
        if c.event.player_id!=c.player_id or not living_source(c):return()
        return(ChooseRandomEffects(c.player_id,c.source_id,(
            ChoiceOption('draw','Draw one',(Draw(c.player_id,1,c.source_id),)),ChoiceOption('miss','No extra draw'))),)
    def harrison(c):
        weapon_id=c.state.players[3-c.player_id].weapon_id
        if weapon_id is None:return()
        weapon=c.state.entities[weapon_id]
        if weapon.zone!=Zone.WEAPON or not weapon.active or weapon.doomed or weapon.durability<=0:return()
        return(Destroy(weapon_id,c.source_id),Draw(c.player_id,weapon.durability,c.source_id))
    def alexstrasza(c):return(SetHeroHealth(c.target_id,15,c.source_id),)
    def beast(c):
        return(SummonByCard(3-c.player_id,(SummonEntryMaterial(FINKLE),),SummonCause.capture(c)),)
    def millhouse(c):return(AddPlayerEffect(3-c.player_id,PROGRAM,c.source_id),)
    def millhouse_start(c):
        if c.event.player_id!=c.player_id:return()
        if c.player_effect is None or c.player_effect.spec_id!=PROGRAM:
            raise ResolutionError('Millhouse lost its exact original opponent player instance')
        # Bind to the actual beneficiary start, including extra or skipped turns.
        # The normal modifier handles every later spell and expires at that turn end.
        return(ConsumePlayerEffect(c.player_id,c.player_effect,(
            AddCostModifier(c.player_id,CostSpec(set_to=0,card_types=(CardType.SPELL,)),
                source_id=c.source_id,expires_turn=c.state.turn),)),)
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'taunt',keywords_all=(Keyword.TAUNT,)))
    for name,body in(('black_knight',black_knight),('nat',nat),('harrison',harrison),
            ('alexstrasza',alexstrasza),('beast',beast),('millhouse',millhouse),('millhouse_start',millhouse_start)):
        registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,MILLHOUSE,
        triggers=(TriggerSpec('turn_started',PREFIX+'millhouse_start'),)))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
