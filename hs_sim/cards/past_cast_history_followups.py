"""Original spell starts, complete Concoctions and captured spell-history consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.reference_inputs import reference_path
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword,SpellSchool,TriggerSpec,Zone
from hs_sim.engine.pools import GenerateFromCandidates,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.spell_history import RecastFromHistory,SpellHistoryQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .past_real_concoctions_cards import SINGLES

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-cast-history-followups-v1.json'
BATCH_HASH='4f7553a34daa9f5e7b770747ffbbad9f27470e5c27df71ac3e9339df84f73d63'
LYRA,PUTRICIDE,ASVEDON,JACE,LYNESSA=ROOTS=('UNG_963','RLK_572','RLK_608','SW_044','LOOT_216')
ORIGINAL_TEN=ROOTS+('RLK_803','GIL_598','DRG_090','SCH_224','REV_373')
DEPENDENCIES=()
EVIDENCE=('MIS_701',)
PREFIX='cards.past_cast_history_followups.'
POOL='constructed.cards'
PRIEST=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.PRIEST,),include_neutral=False)
FEL=SpellHistoryQuery(cards=PoolQuery(spell_schools=(SpellSchool.FEL,)),origins=('hand',),outcomes='completed')
FRIENDLY=SpellHistoryQuery(origins=('hand',),outcomes='completed',target_policy='friendly_minion')


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION':raise TargetValidationError('Cast-history roots require their original physical minion faces')
    extra={}
    if cid in(ASVEDON,JACE,LYNESSA):extra['battlecry']=PREFIX+cid
    if cid==ASVEDON:extra['keywords']=(Keyword.TAUNT,)
    if cid in(LYRA,PUTRICIDE):extra['triggers']=(TriggerSpec('spell_cast_started'if cid==LYRA else'minion_died',PREFIX+cid),)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**extra)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            len(d['existing_dependencies'])!=20 or tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            tuple(d['original_ten_source_roots'])!=ORIGINAL_TEN or tuple(d['required_next_source_roots'])!=ORIGINAL_TEN[5:]or
            len(d['official_observations'])!=52 or tuple(d['complete_base_Concoction_ids'])!=SINGLES or
            d['base_Concoction_weights']!=[1]*5 or any(d[k]for k in('complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Cast-history consumers lost original complete roles or required next roots')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Changed complete original cast-history row')
    for value in d['retained_documents'].values():
        p=(reference_path(value['path'], root=ROOT)).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=value['sha256']:
            raise TargetValidationError('Cast-history source lost its complete original reference')
    past=json.loads((reference_path(d['retained_documents']['past']['path'], root=ROOT)).read_text(encoding='utf8'))
    rows={x['record']['id']:x['record']for x in past['candidate_records']}
    if past['candidate_ids']!=d['original_candidate_ids']or len(d['original_candidate_ids'])!=732 or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped complete original past source')
    return d


def register_past_cast_history_followups(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Cast-history root cannot replace an original face')
        registry._validate_card(card);prepared.append(card)
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or not row['pool_card_present']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Cast-history source changed an existing actual Concoction')
    def alive(c):return(c.source.kind==CardType.MINION and c.source.zone==Zone.BOARD and c.source.active and
        c.source.health>0 and not c.source.doomed)
    def lyra(c):
        if c.event is None or c.event.kind!='spell_cast_started':raise TargetValidationError('Lyra requires the actual original CAST start')
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):
            raise TargetValidationError('Lyra borrowed another spell-start fact')
        return(GenerateFromPool(c.player_id,POOL,PRIEST,source_id=c.source_id),)if alive(c)and cast.player_id==c.player_id and cast.origin=='hand'else()
    def putricide(c):return(GenerateFromCandidates(c.player_id,SINGLES,c.source_id),)if alive(c)else()
    def lynessa(c):
        if not alive(c):return()
        return(RecastFromHistory(c.player_id,FRIENDLY,selection='random',source_id=c.source_id,target_id=c.source_id,
            targeting='explicit',target_residence=capture_board_presence(c.state,c.source_id)),)
    bodies={LYRA:lyra,PUTRICIDE:putricide,
        ASVEDON:lambda c:(RecastFromHistory(c.player_id,SpellHistoryQuery(side='enemy',origins=('hand',),outcomes='completed'),
            count=1,selection='newest',source_id=c.source_id),),
        JACE:lambda c:(RecastFromHistory(c.player_id,FEL,selection='random',source_id=c.source_id,
            target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),),LYNESSA:lynessa}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
