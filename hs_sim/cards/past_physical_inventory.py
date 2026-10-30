"""Four actual past deck/hand consumers over existing physical entry pipelines."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.copy_followups import original_copy_material
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import GrantKeyword,TriggerDeathrattles
from hs_sim.engine.model import CardDefinition,CardType,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-physical-inventory-v1.json'
BATCH_HASH='e367d17add0ce56cf6546fff3b5118bbfaa99824593dc79ef636c0d966c830ab'
BLACKTHORN,BOOM,OBLIVITRON,GOYA=ROOTS=('BAR_329','DAL_070','DAL_376','CFM_672')
DEPENDENCIES=EXISTING=()
EVIDENCE=('DAL_070e','MIS_701')
PREFIX='cards.past_physical_inventory.'
DEATHRATTLES=PoolQuery(kinds=(CardType.MINION,),max_cost=5,deathrattle=True)
MECHS=PoolQuery(kinds=(CardType.MINION,),tribes_any=('mech',))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in ('cost','attack','health')):
        raise TargetValidationError('Physical consumer requires its full original minion face')
    fields={'deathrattle' if cid==OBLIVITRON else 'battlecry':PREFIX+cid}
    if cid==GOYA:fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            d['dependencies'] or d['existing_dependencies'] or tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            len(d['official_observations'])!=10 or any(d[k]for k in ('complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Physical consumers changed full source roles or claimed complete coverage')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in ('cards','evidence_only')for x in d[key]):
        raise TargetValidationError('Physical consumer changed a full original row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Physical consumers changed the full past reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids'] or any(x['record']!=rows[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Physical consumers cropped the full past source')
    return d


def register_past_physical_inventory(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Physical consumer cannot replace another full original face')
        registry._validate_card(card);prepared.append(card)
    registry.register_behavior(PREFIX+BLACKTHORN,lambda c:(SummonFromZone(c.player_id,count=3,query=DEATHRATTLES,
        source_id=c.source_id,cause=SummonCause.capture(c)),))
    def boom(c):
        materials=tuple(CopyEntryMaterial.capture(c.state,c.state.entities[i],'stored_copy','current',
            registry=registry,player_id=c.player_id,on_summon=PREFIX+'rush')for i in c.state.players[c.player_id].deck
            if c.state.entities[i].kind==CardType.MINION)
        return (SummonByCard(c.player_id,materials,SummonCause.capture(c),selection='random'),)if materials else ()
    def rush(c):
        original_copy_material(c)
        return (GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),)
    registry.register_behavior(PREFIX+BOOM,boom);registry.register_behavior(PREFIX+'rush',rush)
    registry.register_behavior(PREFIX+OBLIVITRON,lambda c:(SummonFromZone(c.player_id,zone=Zone.HAND,query=MECHS,
        position=deathrattle_position(c),source_id=c.source_id,cause=SummonCause.capture(c),on_summon=PREFIX+'deathrattle'),))
    registry.register_behavior(PREFIX+'deathrattle',lambda c:(TriggerDeathrattles(c.target_id,c.source_id),))
    def goya(c):
        if c.target_id is None:return ()
        card_id=c.state.entities[c.target_id].card_id;cause=SummonCause.capture(c)
        cards=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck
            if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].card_id==card_id)
        return tuple(SummonStoredCard(card,c.player_id,cause=cause)for card in cards)
    registry.register_behavior(PREFIX+GOYA,goya)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
