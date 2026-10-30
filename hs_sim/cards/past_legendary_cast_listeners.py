"""Past Legendary listeners use original cast/play facts and public effect tails."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import (AddToHand,Damage,GainTemporaryMana,GrantSpellDamage,
    RandomDamage,RefreshHeroPower)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE,RandomSplitDamage
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-cast-listeners-v1.json'
BATCH_HASH='aafc1ac23c1487e42b9f32cc724fa5367d850fe8f81ba926daa4ee36c636cddc'
ROOTS=('AT_129','AT_131','CFM_807','EX1_100','EX1_614','GVG_028','GVG_118','ONY_007','SCH_400','TSC_073')
DEPENDENCIES=('EX1_614t','GVG_028t','GVG_068')
PREFIX='cards.past_legendary_cast.'
CHO_BODY='cards.trigger_source.cho'
COIN='GVG_028t'
START=('AT_129','AT_131','EX1_100','GVG_028','GVG_118','GVG_068')


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower());collectible=cid not in('EX1_614t',COIN)
    if (cid not in(*ROOTS,*DEPENDENCIES)or raw['collectible']is not collectible or
            kind!=(CardType.SPELL if cid==COIN else CardType.MINION)or cid in ROOTS and raw['tags'].get('RARITY')!=5):
        raise TargetValidationError('Cast listeners require complete original roots and actual child roles')
    cost=0 if cid==COIN else raw['cost']
    if type(cost)is not int or cid==COIN and raw['cost']is not None:
        raise TargetValidationError('Cast listener cost requires its complete typed source or exact reviewed Coin zero')
    fields={}
    if cid==COIN:fields['on_play']=PREFIX+COIN
    else:
        if cid=='EX1_100'and raw['attack']is not None:
            raise TargetValidationError('Cho zero must retain its original absent Attack and reviewed primary zero')
        attack=0 if cid=='EX1_100'else raw['attack']
        if type(attack)is not int or type(raw['health'])is not int:
            raise TargetValidationError('Cast minion requires its full stats or exact reviewed Cho zero')
        fields.update(attack=attack,health=raw['health'])
        if cid!='EX1_614t':fields['triggers']=(TriggerSpec('spell_cast_started'if cid in START else'card_played',
            CHO_BODY if cid=='EX1_100'else PREFIX+cid),)
    return CardDefinition(cid,raw['name'],kind,cost=cost,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-cast-listeners-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=['CORE_EX1_100','TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=28 or
            d['numeric_normalizations']!={'EX1_100':{'attack':0},COIN:{'cost':0}}or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Cast listeners lost full original roles or declared a partial source complete')
    rows={x['record']['id']:x['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]}
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Cast listeners changed a complete original source row')
    if any(rows[parent]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=rows[child]['dbf_id']
            for parent,child in(('EX1_614','EX1_614t'),('GVG_028',COIN),('GVG_118','GVG_068'))):
        raise TargetValidationError('Cast listeners changed an actual named parent-child identity')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Cast listeners changed the complete original past reference')
    ref=json.loads(p.read_text(encoding='utf8'));records={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(x['record']!=records[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Cast listeners cropped original full membership or changed root rows')
    return d


def register_past_legendary_cast_listeners(registry):
    d=load_batch();old=d['existing_dependencies'][0];prepared=[]
    if (canonical_digest(asdict(registry.card('CORE_EX1_100')))!=old['definition_sha256']or
            canonical_digest(asdict(registry.pool_card('CORE_EX1_100')))!=old['pool_card_sha256']or
            registry.card('CORE_EX1_100').triggers[0].behavior_id!=CHO_BODY):
        raise TargetValidationError('Original Cho requires the unchanged complete accepted Core consumer')
    registry.behavior(CHO_BODY)
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Cast listeners cannot replace or change complete definitions')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Cast listeners changed complete old metadata')
        prepared.append(card)
    def started(c):
        if c.event is None or c.event.kind!='spell_cast_started':raise ResolutionError('Listener requires original CAST start')
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(row.source_id,row.player_id,row.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):
            raise ResolutionError('Listener borrowed another original CAST')
        return row if row.origin=='hand'and living_source(c)else None
    def played(c):
        if c.event is None or c.event.kind!='card_played':raise ResolutionError('Listener requires original completed physical play')
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Listener borrowed another completed physical play')
        return row if row.player_id==c.player_id and row.source_id!=c.source_id and living_source(c)else None
    def personal(c):
        row=played(c)
        return row if row is not None and row.kind==CardType.SPELL and not row.countered else None
    def targeted(c):
        row=started(c)
        return(row is not None and row.player_id==c.player_id and row.target_id==c.source_id and
            row.target_origin is not None and(row.target_origin.entity_id,row.target_origin.zone_epoch)==(c.source_id,c.source.zone_epoch))
    def eydis(c):
        if not targeted(c):return()
        ids=characters(c,registry,3-c.player_id)
        return(RandomDamage(ids,3,c.source_id,DamageKind.MINION_ABILITY),)if ids else()
    def gallywix(c):
        row=started(c)
        if row is None or row.player_id==c.player_id or row.card_id==COIN:return()
        source=c.state.entities[row.source_id]
        if(source.card_id,source.kind)!=(row.card_id,CardType.SPELL):raise ResolutionError('Gallywix lost the original spell material')
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,source),c.player_id,mode='base',source_id=c.source_id),
            AddToHand(row.player_id,COIN,c.source_id,revealed_to=(c.player_id,)))
    def troggzor(c):
        row=started(c)
        return(SummonByCard(c.player_id,(SummonEntryMaterial('GVG_068'),),SummonCause.capture(c)),)if row is not None and row.player_id!=c.player_id else()
    def burly(c):
        row=started(c)
        return(BuffCapturedMinion(MinionReference.capture(c.source),2,0,c.source_id),)if row is not None and row.player_id!=c.player_id else()
    def xavius(c):
        return(SummonByCard(c.player_id,(SummonEntryMaterial('EX1_614t'),),SummonCause.capture(c)),)if played(c)is not None else()
    def beardo(c):
        return(RefreshHeroPower(c.player_id),)if personal(c)is not None and c.state.players[c.player_id].hero_power_id is not None else()
    def haleh(c):
        return(RandomSplitDamage(c.player_id,None,c.source_id,4,profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY),)if personal(c)is not None else()
    def nazjan(c):
        row=personal(c)
        return(Damage(c.state.players[3-c.player_id].hero_id,row.cost,c.source_id,DamageKind.MINION_ABILITY),)if row is not None else()
    bodies={'AT_129':lambda c:(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.DIVINE_SHIELD,c.source_id),)if targeted(c)else(),
        'AT_131':eydis,'CFM_807':beardo,'EX1_614':xavius,'GVG_028':gallywix,'GVG_118':troggzor,'GVG_068':burly,
        'ONY_007':haleh,'SCH_400':lambda c:(GrantSpellDamage(c.source_id,1,c.source_id),)if personal(c)is not None else(),
        'TSC_073':nazjan,COIN:lambda c:(GainTemporaryMana(c.player_id,1),)}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
