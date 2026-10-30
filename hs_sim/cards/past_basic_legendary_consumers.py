"""Real ordinary legendary consumers, including two finite public primitives."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddToHand,Damage,DamageBatch,DestroyBatch,Draw,TriggerDeathrattles
from hs_sim.engine.health_swaps import SwapCapturedMinionHealth
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,KeywordAuraSpec,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.secret_repeats import NativeSecretRepeatProfile
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-basic-legendary-consumers-v1.json'
BATCH_HASH='80a89ef8a772eb7f5699c1c5be1ec68650f9c27d27725c59d6a386e51d3e1d9a'
SOGGOTH,OCTOSARI,KATHRENA,MOSH,ANOMALUS,MUKLA,HUHURAN,VOLJIN,RHYSSA,SHAW=ROOTS=(
    'OG_340','ULD_177','LOOT_511','UNG_933','OG_120','OG_122','OG_309','GVG_014','DAL_573','GIL_650')
DEPENDENCIES=()
BANANA='EX1_014t'
PREFIX='cards.past_basic_legendary.'


def make_definition(raw):
    cid=raw['id'];fields={}
    if(cid not in ROOTS or raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('RARITY')!=5 or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Basic legendary requires its complete actual minion face')
    if cid==SOGGOTH:fields['keywords']=(Keyword.TAUNT,Keyword.ELUSIVE)
    elif cid==SHAW:fields['keyword_auras']=(KeywordAuraSpec(Keyword.RUSH,'friendly_minions',include_self=False),)
    elif cid!=RHYSSA:
        if cid in(OCTOSARI,KATHRENA,ANOMALUS):fields['deathrattle']=PREFIX+cid
        if cid not in(OCTOSARI,ANOMALUS):fields['battlecry']=PREFIX+cid
        if cid in(HUHURAN,VOLJIN):
            fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),
                relation='friendly'if cid==HUHURAN else'any')
            if cid==HUHURAN:fields['target_rule']=PREFIX+'friendly_deathrattle'
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-basic-legendary-consumers-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or
            [x['record']['id']for x in data['existing_dependencies']]!=[BANANA,'TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701']or
            len(data['official_observations'])!=24 or
            any(data[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Basic legendary batch lost complete identities, roles or source boundaries')
    for group in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Basic legendary changed a complete pinned raw row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Basic legendary changed a retained complete reference')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    rows={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Basic legendary cropped the complete original past domain')
    mukla=next(x['record']for x in data['cards']if x['record']['id']==MUKLA)
    if mukla['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=data['existing_dependencies'][0]['record']['dbf_id']:
        raise TargetValidationError('Mukla lost his actual complete client Banana association')
    return data


def register_past_basic_legendary_consumers(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Basic legendary changed a complete actual existing dependency')
    for row in data['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Basic legendary cannot replace or alter an existing physical face')
        registry._validate_card(card);prepared.append(card)
    def octosari(c):return(Draw(c.player_id,8,c.source_id),)
    def kathrena(c):
        position=deathrattle_position(c)if c.deathrattle is not None else None
        return(SummonFromZone(c.player_id,count=1,query=PoolQuery(tribes_any=('beast',)),
            source_id=c.source_id,cause=SummonCause.capture(c),position=position),)
    def mosh(c):
        victims=tuple(i for p in(1,2)for i in minions(c,registry,p)
            if c.state.entities[i].health<c.state.entities[i].max_health)
        return(DestroyBatch(victims,c.source_id),)
    def anomalus(c):
        return(DamageBatch(tuple(Damage(i,8,c.source_id,DamageKind.MINION_ABILITY)
            for p in(1,2)for i in minions(c,registry,p))),)
    def mukla(c):return tuple(AddToHand(c.player_id,BANANA,c.source_id)for _ in range(2))
    def huhuran(c):return()if c.target_id is None else(TriggerDeathrattles(c.target_id,c.source_id),)
    def voljin(c):
        target=c.state.entities.get(c.target_id)
        if not living_source(c)or target is None or target.zone!=Zone.BOARD or target.kind!=CardType.MINION:return()
        return(SwapCapturedMinionHealth(MinionReference.capture(c.source),MinionReference.capture(target),c.source_id),)
    for cid,body in((OCTOSARI,octosari),(KATHRENA,kathrena),(MOSH,mosh),(ANOMALUS,anomalus),
            (MUKLA,mukla),(HUHURAN,huhuran),(VOLJIN,voljin)):
        registry.register_behavior(PREFIX+cid,body)
    def dr_target(c):
        return False if c.target is None else c.target['has_deathrattle']
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'friendly_deathrattle',
        'current-active-friendly-deathrattle-v1'),dr_target)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    profile=NativeSecretRepeatProfile(RHYSSA)
    if asdict(profile)!=data['native_secret_repeat_profile']:raise TargetValidationError('Rhyssa lost her exact native declaration')
    registry.register_native_secret_repeat_profile(profile)
