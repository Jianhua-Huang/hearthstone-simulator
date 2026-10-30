"""Actual live spell-cost observers and own-turn historical recast consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,EndTurnSpec,SpellSchool,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.spell_history import RecastFromHistory,SpellHistoryQuery
from hs_sim.engine.spell_source_costs import SpellSourceCostObserverProfile,validate_record
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-cast-cost-history-v1.json'
BATCH_HASH='ccdb62c152eabb3d6ddea119834467f3df4fd017832301affe8d14b8f2a2d467'
TAMSIN,GAZLOWE,VARGOTH=ROOTS=('BAR_918','GVG_117','DAL_558')
DEPENDENCIES=EXISTING=()
EVIDENCE=('BAR_918e','MIS_701')
PREFIX='cards.past_cast_cost_history.'
MECHS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('mech',))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Past CAST consumer lost its complete original minion face')
    trigger=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec())if cid==VARGOTH else TriggerSpec('spell_cast_finished',PREFIX+cid))
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        triggers=(trigger,),metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            d['dependencies']or d['existing_dependencies']or tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            len(d['official_observations'])!=8 or any(d[k]for k in('complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past CAST consumers changed complete source roles or claimed a partial pool complete')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','evidence_only')for x in d[key]):
        raise TargetValidationError('Past CAST consumers changed an original complete raw row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Past CAST consumers changed the full original past reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or any(x['record']!=rows[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Past CAST consumers cropped the complete original source')
    return d


def register_past_cast_cost_history(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Past CAST consumer cannot replace another original face')
        registry._validate_card(card);prepared.append(card)
    def observed(c):
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Past cost observer borrowed another completed CAST')
        if(row.player_id!=c.player_id or not living_source(c)or not row.completed or not row.payload_started or
                row.failure is not None or row.interrupted):return()
        if c.source.card_id==TAMSIN and registry.card(row.card_id).spell_school!=SpellSchool.SHADOW:return()
        validate_record(c.state,registry,row)
        if row.source_cost is None:raise ResolutionError('Past cost observer lost its original accepted spell quote')
        if c.source.card_id==TAMSIN:
            return(CopyCard(None,c.player_id,mode='base',source_id=c.source_id,cost=CostSpec(set_to=0),cast_id=row.id),)if row.source_cost.amount>=1 else()
        return(GenerateFromPool(c.player_id,'constructed.cards',MECHS,source_id=c.source_id),)if row.source_cost.amount==1 else()
    def history(c):
        if c.event.player_id!=c.player_id or not living_source(c):return()
        return(RecastFromHistory(c.player_id,SpellHistoryQuery(min_turn=c.state.turn,max_turn=c.state.turn),
            count=1,selection='random',source_id=c.source_id),)
    for cid,body in((TAMSIN,observed),(GAZLOWE,observed),(VARGOTH,history)):registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_source_cost_observer(SpellSourceCostObserverProfile(TAMSIN,SpellSchool.SHADOW))
    registry.register_spell_source_cost_observer(SpellSourceCostObserverProfile(GAZLOWE,None))
