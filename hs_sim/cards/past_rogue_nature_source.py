"""Complete Rogue past Nature view using real weapon and physical draw effects."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import AddToHand,Buff,Damage,Draw,GrantKeyword,GrantTrigger,ModifyWeapon
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,EquippedWeaponReference,
    HandProgressSpec,Keyword,SpellSchool,TargetSpec,Zone)
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup,DrawGroupSlot,DrawGroupReward
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError,canonical_digest
from . import past_priest_nature_source as priest
from .metadata import metadata_from_record
from .simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-rogue-nature-source-v1.json'
BATCH_HASH='b8244b1b6e9ecb5d8d9b408737fd57fc9ba8cf8a3fd43bfa133eadf6cf5a6951'
POLICY='cn37-local-rogue-past-nature-v1'
ROOTS=('BAR_318','BAR_321','CS2_074','ICC_221','UNG_057','UNG_060','UNG_823','UNG_856','YOP_015')
DEPENDENCIES=('UNG_057t1','YOP_015t')
EVIDENCE=('BAR_318e','BAR_321e','CS2_074e','ICC_221e','UNG_823e','YOP_015e')
WEAPON_REQUIRED=('BAR_318','BAR_321','CS2_074','ICC_221','UNG_823')
PREFIX='cards.past_rogue_nature_source.'


def make_definition(raw):
    cid=raw['id'];fields={}
    if (cid not in ROOTS+DEPENDENCIES or raw['type']!='SPELL' or
            raw['tags'].get('SPELL_SCHOOL')!=4 or raw['collectible'] is not (cid in ROOTS)):
        raise TargetValidationError('Rogue Nature requires its real original spell faces')
    if cid in WEAPON_REQUIRED:fields['requires_weapon']=True
    if cid=='UNG_057t1':fields['targeting']=TargetSpec()
    if cid in ('YOP_015','YOP_015t'):
        fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid=='YOP_015':fields.update(keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id='YOP_015t'))
    if cid=='YOP_015t':fields['keywords']=(Keyword.CORRUPTED,)
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf8'));prior=priest.load_batch()
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or
            tuple(v['record']['id']for v in d['dependencies'])!=DEPENDENCIES or
            tuple(v['record']['id']for v in d['evidence_only'])!=EVIDENCE or
            [v['record']['id']for v in d['existing_dependencies']]!=[WO]or
            len(d['official_observations'])!=24 or d['source_card_id']!=WO or d['pool_id']!=NATURE_PAST_POOL or
            d['original_member_ids']!=prior['merged_member_ids']or
            d['merged_member_ids']!=prior['merged_member_ids']+list(ROOTS)or
            d['actual_rogue_ids']!=list(ROOTS)or
            [v['card_id']for v in d['native_pins']]!=d['merged_member_ids']or
            canonical_digest(d['query'])!=canonical_digest(asdict(QUERIES[WO]))or
            any(d[k]for k in ('new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Rogue Nature lost a complete original source or real face role')
    if (d['original_source_document']!=priest.BATCH_PATH.relative_to(ROOT).as_posix()or
            hashlib.sha256(priest.BATCH_PATH.read_bytes()).hexdigest()!=d['original_source_sha256']):
        raise TargetValidationError('Rogue Nature changed the complete original 174-row union reference')
    for key in ('cards','dependencies','existing_dependencies','evidence_only'):
        for v in d[key]:
            if canonical_digest(v['record'])!=v['record_sha256']:
                raise TargetValidationError('Rogue Nature lost a complete original raw face')
    derived=[v['record']['id']for v in prior['full_union_records']if
        CardClass.ROGUE in metadata_from_record(v['record']).classes or
        CardClass.NEUTRAL in metadata_from_record(v['record']).classes]
    if derived!=list(ROOTS):raise TargetValidationError('Rogue Nature differs from the full original reference query')
    return d


def register_past_rogue_nature_cards(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Rogue Nature cannot replace or lose a real original definition')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Rogue Nature changed an existing complete metadata row')
        prepared.append(card)
    def weapon(c,cid):
        w=equipped_weapon(c.state,c.state.players[c.player_id])
        if w is None:return()
        ref=EquippedWeaponReference.capture(w)
        if cid=='BAR_318':return(GrantTrigger(w.id,'attack_finished',PREFIX+'silverleaf_draw',c.source_id),)
        if cid=='BAR_321':return(ModifyWeapon(ref,attack=1,source_id=c.source_id),GrantKeyword(w.id,Keyword.IMMUNE_WHILE_ATTACKING,c.source_id))
        if cid=='CS2_074':return(ModifyWeapon(ref,attack=2,source_id=c.source_id),)
        if cid=='ICC_221':return(GrantKeyword(w.id,Keyword.LIFESTEAL,c.source_id,expires_turn=c.state.turn),)
        return(GrantKeyword(w.id,Keyword.POISONOUS,c.source_id),)
    def silverleaf(c):
        attack=completed_attack(c)
        if (attack is None or attack.source_kind!=CardType.HERO or attack.declaration.player_id!=c.player_id or
                attack.combat is None or attack.combat.weapon_id!=c.source_id):return()
        return(Draw(c.player_id,source_id=c.source_id),)
    def hallucination(c):
        other=c.state.players[3-c.player_id].hero_class
        if type(other)is not CardClass or other in (CardClass.NEUTRAL,CardClass.DREAM):
            raise UnsupportedDefinitionError('Hallucination requires the actual known opponent class')
        return(DiscoverFromPool(c.player_id,'constructed.cards',PoolQuery(class_mode='specified',classes=(other,),include_neutral=False,collectible=True),source_id=c.source_id),)
    def nitro(c,corrupted=False):
        result=(Buff(c.target_id,attack=2,source_id=c.source_id),)
        w=equipped_weapon(c.state,c.state.players[c.player_id])
        return result+(ModifyWeapon(EquippedWeaponReference.capture(w),attack=2,source_id=c.source_id),)if corrupted and w is not None else result
    bodies={cid:(lambda c,cid=cid:weapon(c,cid))for cid in WEAPON_REQUIRED}
    bodies.update({'silverleaf_draw':silverleaf,
        'UNG_057':lambda c:(AddToHand(c.player_id,'UNG_057t1',c.source_id),)*2,
        'UNG_057t1':lambda c:(Damage(c.target_id,2,c.source_id),),
        'UNG_060':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),),DrawGroupReward('copy_self')),),
        'UNG_856':hallucination,'YOP_015':lambda c:nitro(c),'YOP_015t':lambda c:nitro(c,True)})
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))


def checked_native(registry,d):
    for row in d['native_pins']:
        cid=row['card_id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Rogue Nature changed complete native member '+cid)
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Rogue Nature changed its existing real source')


def local_pool(registry,context):
    d=load_batch();checked_native(registry,d);old=priest.local_pool(registry,context)
    return replace(old,version=POLICY+':'+old.version,members=tuple(PoolMember(cid)for cid in d['merged_member_ids']))


def register_scope(registry,context):
    d=load_batch();expected=local_pool(registry,context);pool=registry.pool(NATURE_PAST_POOL,context)
    if pool!=replace(expected,version=context.target_id+':'+expected.version):
        raise TargetValidationError('Rogue Nature cannot crop, borrow or reweight a full original source')
    registry.register_generation_scope(GenerationScope(POLICY+':'+WO+':rogue:'+context.target_id,
        pool.id,context.target_id,context.mode,WO,CardClass.ROGUE,QUERIES[WO],pool_digest(pool)))
    actual=resolve_candidates(registry,context,pool.id,QUERIES[WO],current_class=CardClass.ROGUE,
        source_card_id=WO,exclude_source_by_rule=True)
    if [v.card_id for v in actual]!=d['actual_rogue_ids']or[v.weight for v in actual]!=[1]*9:
        raise TargetValidationError('Rogue Nature actual candidates lost the complete original class view')
