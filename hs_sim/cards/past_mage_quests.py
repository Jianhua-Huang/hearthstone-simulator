"""Four original Mage quests, using public payment, turn and reward machinery."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddToHand,ReplaceHeroPower
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,QuestSpec,QuestStageSpec
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.play_history import play_record,starting_deck_identity
from hs_sim.engine.player_spell_mana_costs import row_for
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.quests import AdvanceQuest,ResetQuestProgress
from hs_sim.engine.resources import mana_consumption_result
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .entry_native_cards import submitted_tribes
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-mage-quests-v1.json'
BATCH_HASH='4c543695ec06e175f4dda781b85816a8481657cd4844923dda86e19987365dd0'
POLICY='cn37-local-past-mage-quests-v1'
DRACONIC,ALLIES,TEMPLE,WAYGATE=LEAVES=('DRG_323','DRG_324','ULD_433','UNG_028')
DRAGON,SCROLL=TOKENS=('DRG_323t','ULD_433p')
WARP='UNG_028t'
DEPENDENCIES=LEAVES+TOKENS
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_mage_quests.'
POOL='constructed.cards'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    records=d['dependencies']+d['existing_dependencies']
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(d['new_token_ids'])!=TOKENS or
            tuple(row['record']['id']for row in d['dependencies'])!=DEPENDENCIES or
            tuple(row['record']['id']for row in d['existing_dependencies'])!=(WARP,) or
            len(d['official_observations'])!=14 or any(d[k]for k in ('cards','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in records)):
        raise TargetValidationError('Past Mage quests require all seven complete original records')
    path=ROOT/d['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Past Mage quests lost their full original reference scope')
    return d


def _advance(c,key):
    q=c.source.quest_progress
    return AdvanceQuest(c.source_id,q.id,q.stage,key=key)


def draconic_progress(c):
    event=c.event
    if event.player_id!=c.player_id:return ()
    if event.kind=='card_committed':
        record=play_record(c.state,dict(event.data)['play_id'])
        if (record.source_id,record.player_id)!=(event.source_id,event.player_id):
            raise ResolutionError('Learn Draconic lost its original committed payment')
        amount=row_for(record).mana_for(c.player_id);identity=f'play:{record.id}'
    elif event.kind=='mana_consumed':
        record=mana_consumption_result(event)
        if not 0<record.id<=len(c.state.mana_consumption_history) or c.state.mana_consumption_history[record.id-1]!=record:
            raise ResolutionError('Learn Draconic lost its original direct expenditure')
        amount=record.mana_for(c.player_id);identity=f'consume:{record.id}'
    else:raise ResolutionError('Learn Draconic requires an actual spell expenditure event')
    return tuple(_advance(c,f'{identity}:unit:{i}')for i in range(min(amount,8)))


def allies_progress(c):
    event=c.event
    if event.player_id!=c.player_id:return ()
    turn=current_owner_turn(c.state)
    if turn.player_id!=c.player_id:raise ResolutionError('Elemental Allies lost its genuine owner turn')
    key=f'owner_turn:{turn.id}'
    if event.kind=='turn_ended':
        q=c.source.quest_progress
        return (ResetQuestProgress(c.source_id,q.id,q.stage),)if q.value and key not in q.keys else ()
    if event.kind!='card_played':raise ResolutionError('Elemental Allies requires a completed original play')
    record=play_record(c.state,dict(event.data)['play_id'])
    if (record.source_id,record.player_id)!=(event.source_id,event.player_id) or not record.completed:
        raise ResolutionError('Elemental Allies lost its completed original play')
    return (_advance(c,key),)if record.kind==CardType.MINION and submitted_tribes(record).matches_any(('elemental',))else ()


def spell_progress(c):
    if c.event.kind!='spell_cast_started':raise ResolutionError('Mage cast quests require an original spell cast')
    record=cast_record(c.state,dict(c.event.data)['cast_id'])
    if (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
        raise ResolutionError('Mage quest lost its original spell cast')
    if record.player_id!=c.player_id or record.failure not in (None,'countered'):return ()
    if c.source.card_id==WAYGATE:
        originals,_=starting_deck_identity(c.state)
        if record.source_id in originals[c.player_id-1] and not c.state.entities[record.source_id].face_replaced:return ()
    return (_advance(c,f'cast:{record.id}'),)


def register_past_mage_quests(registry):
    d=load_batch()
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_cards[cid]))!=row['pool_metadata_sha256']):
            raise TargetValidationError('Past Mage quests changed the complete existing Time Warp dependency')
    bodies={
        'draconic_progress':draconic_progress,'allies_progress':allies_progress,'spell_progress':spell_progress,
        'draconic_reward':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DRAGON),),SummonCause.capture(c)),),
        'allies_reward':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*3),),
        'temple_reward':lambda c:(ReplaceHeroPower(c.player_id,SCROLL,source_id=c.source_id),),
        'waygate_reward':lambda c:(AddToHand(c.player_id,WARP,c.source_id),),
        'scroll':lambda c:(GenerateFromPool(c.player_id,POOL,
            PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',
                classes=(CardClass.MAGE,),include_neutral=False),source_id=c.source_id,cost=CostSpec(delta=-2)),),
    }
    plans={
        DRACONIC:('sidequest',8,('card_committed','mana_consumed'),'draconic_progress','draconic_reward'),
        ALLIES:('sidequest',2,('card_played','turn_ended'),'allies_progress','allies_reward'),
        TEMPLE:('quest',10,('spell_cast_started',),'spell_progress','temple_reward'),
        WAYGATE:('quest',8,('spell_cast_started',),'spell_progress','waygate_reward'),
    }
    prepared=[]
    for row in d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kw={}
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Past Mage quest face already registered')
        if cid in plans:
            qkind,goal,events,progress,reward=plans[cid]
            kw.update(keywords=(Keyword.SIDEQUEST if qkind=='sidequest'else Keyword.QUEST,),
                quest=QuestSpec(qkind,(QuestStageSpec(cid,goal,events,PREFIX+progress,PREFIX+reward),)))
        elif cid==DRAGON:kw.update(attack=raw['attack'],health=raw['health'])
        elif cid==SCROLL:kw['on_use']=PREFIX+'scroll'
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kw)
        registry._validate_card(card);prepared.append(card)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
