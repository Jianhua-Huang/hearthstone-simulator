"""Original draw/damage facts, native spell prices and a persistent Treant family."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.damage_history import hero_power_damage
from hs_sim.engine.draw_casts import drawn_cards
from hs_sim.engine.effects import Damage,DamageBatch,Destroy,DestroyBatch
from hs_sim.engine.model import (CardDefinition,CardType,CostAuraSpec,CostSpec,DamageKind,
    Keyword,PlayerAuraSpec,PlayerEffectSpec,TargetMode,TargetSpec,Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-history-spell-cost-treants-v1.json'
BATCH_HASH='81d3891816728279ca80cc8d2796b0322ee956b1b5156a03d84c89a24106273f'
KELIDAN,MORDRESH,KALECGOS,KAELTHAS,GORU=ROOTS=('BT_196','BAR_547','DAL_609','BT_255','DRG_319')
DEPENDENCIES=()
EXISTING=('DRG_311t',)
EVIDENCE=('MIS_701',)
PREFIX='cards.past_history_spell_cost_treants.'
TARGET_RULE=PREFIX+'original_draw_target'
PROGRAM=PREFIX+'persistent_Treants'
SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')


def drawn_this_turn(c):
    entry_id=c.source.hand_entry_id
    if c.play is not None and c.play.source_id==c.source_id:entry_id=c.play.hand_entry_id
    if entry_id is None:return False
    return any(row.entity_id==c.source_id and row.hand_entry_id==entry_id for row in
        drawn_cards(c.state,c.player_id,outcome='hand',turn=c.state.turn,completed=True))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('History/cost/Treant consumers require their full original minion faces')
    fields={}
    if cid!=KAELTHAS:fields['battlecry']=PREFIX+cid
    if cid==KELIDAN:fields.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
        kinds=(CardType.MINION,)),target_rule=TARGET_RULE)
    if cid==KALECGOS:fields['cost_auras']=(CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.SPELL,)),first_per_turn=True),)
    if cid==KAELTHAS:fields['cost_auras']=(CostAuraSpec(CostSpec(set_to=1,card_types=(CardType.SPELL,)),every_nth_per_turn=3),)
    if cid==GORU:fields['keywords']=(Keyword.TAUNT,)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def program(treant_ids):
    return PlayerEffectSpec(PROGRAM,GORU,auras=(PlayerAuraSpec(1,1,tuple(treant_ids),'controlled_minion_cards'),))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=12 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage',
                'formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('History/cost/Treant consumers changed their original roles or full source')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original history/cost/Treant row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed complete past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            row['record']!=rows[row['record']['id']]for row in d['cards']):raise TargetValidationError('Cropped original past source')
    family=d['treant_family'];p=ROOT/family['source_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=family['source_sha256']:raise TargetValidationError('Changed complete Treant reference')
    source=json.loads(p.read_text(encoding='utf8'))
    if(source['treant_member_ids']!=family['card_ids']or len(family['card_ids'])!=29 or
            tuple(x['record']['id']for x in family['records'])!=tuple(family['card_ids'])or
            any(canonical_digest(x['record'])!=x['record_sha256']or x['record']['tags'].get('2831')!=1 for x in family['records'])or
            canonical_digest(asdict(program(family['card_ids'])))!=d['goru_program_sha256']):
        raise TargetValidationError('Treant aura lost its complete original named predicate or ordinary player program')
    return d


def register_past_history_spell_cost_treants(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('History/cost/Treant consumers replaced the existing named Treant')
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('History/cost/Treant consumer changed or replaced another original face')
        registry._validate_card(card);prepared.append(card)
    registry.register_target_rule(TARGET_RULE,lambda c:not drawn_this_turn(c))
    def kelidan(c):
        if drawn_this_turn(c):
            return(DestroyBatch(tuple(i for p in(c.player_id,3-c.player_id)for i in minions(c,registry,p)
                if i!=c.source_id),c.source_id),)
        return(Destroy(c.target_id,c.source_id),)if c.target_id is not None else ()
    def mordresh(c):
        if hero_power_damage(c.state,registry,c.player_id)<10:return ()
        return(DamageBatch(tuple(Damage(i,10,c.source_id,DamageKind.MINION_ABILITY)
            for i in characters(c,registry,3-c.player_id))),)
    for cid,body in((KELIDAN,kelidan),(MORDRESH,mordresh),
            (KALECGOS,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',SPELLS,source_id=c.source_id),)),
            (GORU,lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))):
        registry.register_behavior(PREFIX+cid,body)
    registry.register_player_effect(program(d['treant_family']['card_ids']))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
