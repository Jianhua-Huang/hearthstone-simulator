"""Original damage, draw, hand-position and attack facts compose public effects."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.effects import Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import DestroyCapturedMinion,DoubleCapturedMinionStats,MinionReference
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-event-draws-v1.json'
BATCH_HASH='ab0e05a57bd097b655274a2affe5774b8f082be23f1a1740566af6ece99c51f6'
ROOTS=('AT_063','BRM_031','BOT_103','CFM_808','GVG_049')
DEPENDENCIES=()
ACIDMAW,CHROMAGGUS,LUNA,GENZO,GAHZRILLA=ROOTS
PREFIX='cards.past_legendary_events.'
EVENTS={ACIDMAW:'damage_dealt',CHROMAGGUS:'card_drawn',LUNA:'card_played',
    GENZO:'attack_declared',GAHZRILLA:'damage_dealt'}


def make_definition(raw):
    cid=raw['id']
    if(cid not in ROOTS or raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('RARITY')!=5 or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Past event consumers require their complete original Legendary faces')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        triggers=(TriggerSpec(EVENTS[cid],PREFIX+cid),),metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-event-draws-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=14 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past event consumers lost complete original source roles')
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Past event consumer changed a complete original row')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Past event consumers changed the complete original reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Past event consumers cropped full membership or changed original faces')
    return d


def register_past_legendary_event_draws(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Past event consumer cannot replace or alter an existing definition')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Past event consumer changed complete existing metadata')
        prepared.append(card)
    def acidmaw(c):
        e=c.state.entities.get(c.event.target_id)
        return(DestroyCapturedMinion(MinionReference.capture(e),c.source_id),)if(
            c.event.amount>0 and living_source(c)and e is not None and e.kind==CardType.MINION and
            e.zone==Zone.BOARD and e.controller!=c.player_id)else()
    def chromaggus(c):
        row=draw_record(c.state,dict(c.event.data)['draw_id'])
        if(row.entity_id,row.player_id)!=(c.event.target_id,c.event.player_id)or row.outcome not in('hand','cast'):
            raise ResolutionError('Chromaggus lost its original physical draw')
        if row.player_id!=c.player_id or not living_source(c):return()
        e=c.state.entities[row.entity_id]
        if e.controller!=row.player_id or e.card_id!=row.card_id and row.transformation is None:
            raise ResolutionError('Chromaggus lost its accepted original drawn face')
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,e),c.player_id,
            mode='current'if row.outcome=='hand'else'base',source_id=c.source_id),)
    def luna(c):
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Luna lost its original completed physical play')
        return(Draw(c.player_id,1,c.source_id),)if(row.player_id==c.player_id and row.source_id!=c.source_id and
            row.hand_index==row.hand_size-1 and living_source(c))else()
    def genzo(c):
        window=dict(c.event.data)['window_id']
        rows=[r for r in c.state.character_attack_history if r.declaration.id==window]
        if len(rows)!=1:raise ResolutionError('Genzo lost its unique original attack declaration')
        row=rows[0];w=row.declaration
        if(w.source_id,w.target_id,w.player_id,row.declaration_event_cursor+1)!=(
                c.event.source_id,c.event.target_id,c.event.player_id,c.event.sequence):
            raise ResolutionError('Genzo borrowed another original attack declaration')
        if w.source_id!=c.source_id or w.player_id!=c.player_id or not living_source(c):return()
        return tuple(Draw(p,max(0,3-len(c.state.players[p].hand)),c.source_id)for p in(c.player_id,3-c.player_id))
    def gahzrilla(c):
        return(DoubleCapturedMinionStats(MinionReference.capture(c.source),attack=True,source_id=c.source_id),)if(
            c.event.target_id==c.source_id and c.event.amount>0 and living_source(c))else()
    for cid,body in((ACIDMAW,acidmaw),(CHROMAGGUS,chromaggus),(LUNA,luna),(GENZO,genzo),(GAHZRILLA,gahzrilla)):
        registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
