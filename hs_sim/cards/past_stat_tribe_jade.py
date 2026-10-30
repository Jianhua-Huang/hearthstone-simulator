"""Five actual stat/tribe consumers; ordinary writers own every mutation."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope, minion_references
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, EndTurnSpec, Keyword, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference, SetCapturedMinionStats
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-stat-tribe-jade-v1.json'
BATCH_HASH = '6d7f268b776728e2eeb923eca825b82a9ee50e3bf45132260ee20a67df30ce95'
VERANUS, FRIZZ, AYA, THERAZANE, EYSOR = ROOTS = ('DRG_095','DRG_257','CFM_902','DEEP_036','DMF_709')
DEPENDENCIES = ()
EXISTING = ('CFM_712_t01','CFM_712_t04','CFM_712_t07','CFM_712_t20')
EVIDENCE = ('MIS_701',)
PREFIX = 'cards.past_stat_tribe_jade.'
DRAGONS = MinionScope((Zone.DECK,), PoolQuery(tribes_any=('dragon',)), tribe_basis='current')
ELEMENTALS = MinionScope((Zone.HAND,Zone.DECK), PoolQuery(tribes_any=('elemental',)), tribe_basis='current')
TOTEMS = MinionScope(query=PoolQuery(tribes_any=('totem',)), exclude_source=True, tribe_basis='current')


def make_definition(raw):
    cid = raw['id']; attack = raw['attack']
    if cid==EYSOR and attack is None and 'ATK' not in raw['tags']:
        attack=0  # Both complete pinned primary faces explicitly supply this zero.
    if cid not in ROOTS or raw['type']!='MINION' or any(type(v) is not int for v in (raw['cost'],attack,raw['health'])):
        raise TargetValidationError('Stat/tribe consumer requires its complete original minion face')
    fields = dict(metadata=metadata_from_record(raw))
    if cid in (VERANUS,FRIZZ,AYA):fields['battlecry']=PREFIX+cid
    if cid in (AYA,THERAZANE):fields['deathrattle']=PREFIX+cid
    if cid==THERAZANE:fields['keywords']=(Keyword.TAUNT,)
    if cid==EYSOR:fields['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec()),)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=attack,health=raw['health'],**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=ROOTS or
            d['dependencies'] or tuple(x['record']['id'] for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id'] for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=12 or
            any(d[k] for k in ('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Stat/tribe consumers changed their complete source roles or claimed full support')
    for key in ('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256'] for x in d[key]):
            raise TargetValidationError('Stat/tribe consumer changed a complete original row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Stat/tribe consumer changed its original full past source')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record'] for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids'] or any(
            x['record']!=rows[x['record']['id']] for x in d['cards']):
        raise TargetValidationError('Stat/tribe consumer cropped its complete past source')
    zero=d['zero_attack_evidence'];raw=next(x['record'] for x in d['cards'] if x['record']['id']==EYSOR)
    if (zero['record']!=raw or len(zero['primary_faces'])!=2 or any(
            x['face']['id']!=raw['dbf_id'] or type(x['face'].get('attack')) is not int or x['face']['attack']!=0
            for x in zero['primary_faces'])):
        raise TargetValidationError('Eysor requires both full explicit zero-attack primary faces')
    return d


def register_past_stat_tribe_jade(registry):
    d=load_batch()
    if CLASSIC not in registry.jade_families or canonical_digest(asdict(registry.jade_families[CLASSIC]))!=d['jade_family_sha256']:
        raise TargetValidationError('Aya requires the existing complete four-template Jade family')
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Aya cannot replace or trim an existing Jade artwork dependency')
    prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Stat/tribe consumer cannot replace another complete original face')
        registry._validate_card(card);prepared.append(card)

    def veranus(c):
        enemies=MinionScope((Zone.BOARD,))
        return tuple(SetCapturedMinionStats(ref,health=1,source_id=c.source_id)
            for ref in minion_references(c.state,registry,3-c.player_id,enemies,c.source_id))
    def frizz(c):
        return tuple(ModifyStoredCost(ref,CostSpec(delta=-2),c.source_id)
            for ref in minion_references(c.state,registry,c.player_id,DRAGONS,c.source_id))
    def aya(c):
        position=deathrattle_position(c) if c.deathrattle is not None else None
        return (SummonJadeGolem(c.player_id,c.source_id,CLASSIC,position=position,cause=SummonCause.capture(c)),)
    def therazane(c):
        refs=minion_references(c.state,registry,c.player_id,ELEMENTALS,c.source_id)
        return tuple(BuffStoredCard(ref,c.state.entities[ref.entity_id].attack,
            c.state.entities[ref.entity_id].max_health,c.source_id) for ref in refs)
    def eysor(c):
        if c.event is None or c.event.player_id!=c.player_id:return ()
        return (BuffMinionsInZones(c.player_id,1,1,TOTEMS,c.source_id),)
    for cid,body in ((VERANUS,veranus),(FRIZZ,frizz),(AYA,aya),(THERAZANE,therazane),(EYSOR,eysor)):
        registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
