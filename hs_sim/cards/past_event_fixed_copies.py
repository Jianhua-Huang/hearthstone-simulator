"""Six actual printed backward copies and current in-play copy consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import TransformMinionIntoCopy
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,SummonStats,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import death_record
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-event-fixed-copies-v1.json'
BATCH_HASH='d6c4217861a6b6f1421321f8d06ae135ded4642c6c9dbeea02acee1c66b510b9'
SPLINTER,ZOLA,TALDARAM,MOORABI,SONYA,IXLID=ROOTS=('GIL_658','LOOT_516','ICC_852','ICC_289','LOOT_165','LOOT_329')
DEPENDENCIES=()
EXISTING=()
CORRECTIONS=('DRG_402','GVG_005','SCH_352','BAR_549','LOOT_218','ICC_091')
EVIDENCE=('MIS_701',)
PREFIX='cards.past_event_fixed_copies.'


def no_threes(c):
    # Same original local-deck Cost reader as the already reviewed Prince Keleseth.
    return not any(local_cost(c.state.entities[i])[0]==3 for i in c.state.players[c.player_id].deck)


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Event/fixed copy requires its complete original minion face')
    fields={}
    if cid in(SPLINTER,ZOLA,TALDARAM):
        fields.update(battlecry=PREFIX+cid,targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
            kinds=(CardType.MINION,),relation='any'if cid==TALDARAM else'friendly'))
        if cid==TALDARAM:fields['target_rule']=PREFIX+'no_threes'
    else:fields['triggers']=(TriggerSpec({MOORABI:'frozen',SONYA:'minion_died',IXLID:'card_played'}[cid],PREFIX+cid),)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            d['dependencies']or d['existing_dependencies']or
            tuple(x['record']['id']for x in d['existing_effect_corrections'])!=CORRECTIONS or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=26 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Event/fixed copy changed complete roles or claimed full support')
    for row in d['cards']+d['existing_effect_corrections']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original event/fixed copy row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped full past reference')
    return d


def target(c):
    entity=c.state.entities.get(c.target_id)
    return entity if entity is not None and entity.zone==Zone.BOARD and entity.kind==CardType.MINION and entity.active and entity.health>0 and not entity.doomed else None


def register_past_event_fixed_copies(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']:
            raise TargetValidationError('Event/fixed copy changed or replaced an existing face')
        registry._validate_card(card);prepared.append(card)
    def hand(c,fixed=False):
        original=target(c)
        if original is None:return()
        return(CopyCard(MinionReference.capture(original),c.player_id,mode='base',source_id=c.source_id,
            stats=SummonStats(10,10)if fixed else None,cost=CostSpec(set_to=10)if fixed else None),)
    def taldaram(c):
        original=target(c)
        if original is None or not no_threes(c)or not living_source(c):return()
        return(TransformMinionIntoCopy(MinionReference.capture(c.source),MinionReference.capture(original),c.source_id,stats=SummonStats(3,3)),)
    def moorabi(c):
        if c.event is None or c.event.kind!='frozen':raise ValueError('Moorabi requires an actual newly frozen event')
        original=c.state.entities.get(c.event.target_id)
        if(original is None or original.id==c.source_id or original.zone!=Zone.BOARD or original.kind!=CardType.MINION or
                not original.frozen or not living_source(c)):return()
        # The actual accepted freeze face is stable even if an earlier reaction later removes it.
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,original),c.player_id,mode='base',source_id=c.source_id),)
    def sonya(c):
        if c.event is None or c.event.kind!='minion_died':raise ValueError('Sonya requires an actual original minion death')
        dead=death_record(c.state,dict(c.event.data)['death_id'])
        if dead.controller!=c.player_id or dead.zone!=Zone.BOARD or dead.entity_id==c.source_id or not living_source(c):return()
        return(CopyCard(dead,c.player_id,mode='base',source_id=c.source_id,stats=SummonStats(1,1),cost=CostSpec(set_to=1)),)
    def ixlid(c):
        if c.event is None or c.event.kind!='card_played':raise ValueError('Ixlid requires an actual completed own minion play')
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):raise ValueError('Ixlid lost original completed physical play')
        if(row.player_id!=c.player_id or row.source_id==c.source_id or row.kind!=CardType.MINION or row.countered or
                row.minion_entry is None or not living_source(c)):return()
        original=resolve_board_presence(c.state,row.minion_entry.reference)
        if original is None or not original.active or original.health<=0 or original.doomed:return()
        return(CopyMinion(row.minion_entry.reference,c.player_id,cause=SummonCause.capture(c)),)
    registry.register_target_rule(PREFIX+'no_threes',no_threes)
    for cid,body in((SPLINTER,lambda c:hand(c,True)),(ZOLA,hand),(TALDARAM,taldaram),(MOORABI,moorabi),(SONYA,sonya),(IXLID,ixlid)):
        registry.register_behavior(PREFIX+cid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
