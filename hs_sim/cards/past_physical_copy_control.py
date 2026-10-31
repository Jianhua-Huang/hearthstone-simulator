"""Five real original-subject, copy, silence and control-return consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.cross_zone import TransformMinionIntoCopy
from hs_sim.engine.model import CardDefinition,CardType,Keyword,NativeDeathrattleSpec,SummonStats,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.selected_minion_memory import RememberBattlecryMinion,ReturnRememberedMinion,SilenceCapturedMinion
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion,death_record
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-physical-copy-control-v1.json'
BATCH_HASH='471c4a3e1b1825584d5ebbe9e019f3ec52e1a086f12915cf00034c5273ee426d'
KAAHRJ,CELESTIA,NAMELESS,NAJAK,PLAGUEMAW=ROOTS=('DRG_308','BOT_555','DMF_116','AV_331','BAR_540')
DEPENDENCIES=EXISTING=()
EVIDENCE=('MIS_701',)
PREFIX='cards.past_physical_copy_control.'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION'or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Physical copy/control requires its complete original minion face')
    fields={}
    if cid in(KAAHRJ,NAJAK,NAMELESS):
        fields.update(battlecry=PREFIX+cid,targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
            kinds=(CardType.MINION,),relation='any'if cid==NAMELESS else'enemy'))
    if cid in(KAAHRJ,NAJAK):fields.update(deathrattle=PREFIX+cid+'.death',
        native_deathrattle=NativeDeathrattleSpec('selected_copy'if cid==KAAHRJ else'control_return'))
    if cid==CELESTIA:fields.update(keywords=(Keyword.STEALTH,),triggers=(TriggerSpec('card_played',PREFIX+cid),))
    if cid==PLAGUEMAW:fields['triggers']=(TriggerSpec('minion_died',PREFIX+cid),)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            any(d[k]for k in('dependencies','existing_dependencies','complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=12):
        raise TargetValidationError('Physical copy/control changed complete source roles or claimed full support')
    for row in d['cards']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original physical copy/control row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed complete past source')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            row['record']!=rows[row['record']['id']]for row in d['cards']):raise TargetValidationError('Cropped original past source')
    return d


def register_past_physical_copy_control(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Physical copy/control changed or replaced another original face')
        registry._validate_card(card);prepared.append(card)
    def selected(c):
        if c.target_id is None:return ()
        if c.battlecry is None:raise ValueError('Native selected minion requires its actual original Battlecry')
        target=c.state.entities[c.target_id]
        if target.controller==c.player_id or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return ()
        return(RememberBattlecryMinion(MinionReference.capture(c.source),MinionReference.capture(target),c.battlecry.id),)
    def kaahrj_death(c):
        subjects=memory(c,'selected_copy').selected_subjects;cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(x.copy,),cause)for x in subjects)
    def najak_death(c):
        subjects=memory(c,'control_return').selected_subjects
        return tuple(ReturnRememberedMinion(c.deathrattle.id,i)for i in range(len(subjects)))
    def celestia(c):
        if c.event is None or c.event.kind!='card_played':raise ValueError('Celestia requires its actual completed opponent play')
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):raise ValueError('Celestia lost original physical play')
        if row.player_id==c.player_id or row.kind!=CardType.MINION or row.countered or row.minion_entry is None or not living_source(c):return ()
        target=resolve_board_presence(c.state,row.minion_entry.reference)
        if target is None or not target.active or target.health<=0 or target.doomed:return ()
        return(TransformMinionIntoCopy(MinionReference.capture(c.source),MinionReference.capture(target),c.source_id),)
    def nameless(c):
        if c.target_id is None or not living_source(c):return ()
        target=c.state.entities[c.target_id]
        if target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return ()
        ref=MinionReference.capture(target)
        return(TransformMinionIntoCopy(MinionReference.capture(c.source),ref,c.source_id,stats=SummonStats(4,4)),
            SilenceCapturedMinion(ref,c.source_id))
    def plaguemaw(c):
        if not living_source(c):return ()
        identity=dict(c.event.data)['death_id'];death=death_record(c.state,identity)
        if death.controller!=c.player_id or Keyword.TAUNT not in death.keywords:return ()
        return(ResurrectMinion(c.player_id,death.id,position=death.position,source_id=c.source_id,
            cause=SummonCause.capture(c),remove_keywords=(Keyword.TAUNT,)),)
    for bid,body in((KAAHRJ,selected),(NAJAK,selected),(KAAHRJ+'.death',kaahrj_death),(NAJAK+'.death',najak_death),
            (CELESTIA,celestia),(NAMELESS,nameless),(PLAGUEMAW,plaguemaw)):
        registry.register_behavior(PREFIX+bid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
