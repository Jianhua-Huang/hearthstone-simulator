"""Actual frozen original draws and semantic shuffle-entry current copies."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial,CopyEntryMaterial
from hs_sim.engine.deck_shuffles import INSERT_EVENTS
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-draw-shuffle-copy-v1.json'
BATCH_HASH='b0f95a2e5da3974ce40c4920626864c61815d9b63d52029b59f86cc600ef8964'
BETRUG,TAK=ROOTS=('DAL_607','DAL_719')
DEPENDENCIES=EXISTING=()
EVIDENCE=('DAL_607e','MIS_701')
PREFIX='cards.past_draw_shuffle_copy.'
GRANT=CreatedMinionGrant(keywords=(Keyword.RUSH,),identity=PREFIX+'expire',special='turn_end_destroy')


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Past draw/shuffle consumer lost its complete original minion face')
    events=('card_drawn',)if cid==BETRUG else tuple(sorted(INSERT_EVENTS))
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        triggers=tuple(TriggerSpec(event,PREFIX+cid)for event in events),metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            d['existing_dependencies']or tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            len(d['official_observations'])!=6 or canonical_digest(d['actual_copy_entry_grant'])!=canonical_digest(asdict(GRANT))or any(d[k]for k in('complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past draw/shuffle consumers changed complete roles or claimed partial completion')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','evidence_only')for x in d[key]):
        raise TargetValidationError('Past draw/shuffle consumers changed an original complete row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Past draw/shuffle consumers changed the full past reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or any(x['record']!=rows[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Past draw/shuffle consumers cropped the complete original source')
    return d


def register_past_draw_shuffle_copy(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Past draw/shuffle consumer cannot replace another original face')
        registry._validate_card(card);prepared.append(card)
    def drawn(c):
        row=draw_record(c.state,dict(c.event.data)['draw_id'])
        if(row.entity_id,row.player_id)!=(c.event.target_id,c.event.player_id):
            raise ResolutionError('Betrug lost its original physical draw')
        if row.player_id!=c.player_id or not living_source(c)or row.outcome!='hand' or registry.card(row.card_id).kind!=CardType.MINION:return()
        entity=c.state.entities[row.entity_id]
        if(entity.controller,entity.zone)!=(c.player_id,Zone.HAND)or entity.card_id!=row.card_id and row.transformation is None:
            raise ResolutionError('Betrug original draw context lost its accepted hand face')
        material=CopyEntryMaterial.capture(c.state,entity,'stored_copy','current',registry=registry,player_id=c.player_id,
            minion_grant=GRANT,grant_source_id=c.source_id)
        material=replace(material,draw_id=row.id,draw_event=c.event.sequence)
        return(SummonByCard(c.player_id,(material,),SummonCause.capture(c)),)
    def expire(c):
        return(DestroyCapturedMinion(MinionReference.capture(c.source),c.source_id),)if living_source(c)else()
    def shuffled(c):
        if c.event.player_id!=c.player_id or not living_source(c):return()
        marker=dict(c.event.data).get('deck_insertion')
        if type(marker)is not tuple or len(marker)!=6:raise ResolutionError('Tak lost its original insertion policy')
        mode,rid,actor,count,profile,issuer=marker
        if mode!='random':return()
        if type(rid)is not int or not 1<=rid<=len(c.state.deck_shuffle_history):
            raise ResolutionError('Tak lost its original semantic shuffle record')
        row=c.state.deck_shuffle_history[rid-1]
        if(row.player_id,row.actor_id,row.declared_count,row.profile,None if row.source is None else row.source.entity_id)!=(
                c.event.player_id,actor,count,profile,issuer):raise ResolutionError('Tak shuffle borrowed another original issuer or batch')
        if actor is None:raise UnsupportedDefinitionError('Tak requires the actual issuer of this original own-deck shuffle')
        if actor!=c.player_id:return()
        entity=c.state.entities[c.event.target_id]
        if(entity.zone,entity.controller)!=(Zone.DECK,c.player_id):raise ResolutionError('Tak original insertion context lost its physical deck card')
        material=CapturedCardCopyMaterial.capture(c.state,entity)
        return(CopyCard(material,c.player_id,mode='current',source_id=c.source_id),)
    for cid,body in((BETRUG,drawn),(TAK,shuffled),('expire',expire)):registry.register_behavior(PREFIX+cid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
