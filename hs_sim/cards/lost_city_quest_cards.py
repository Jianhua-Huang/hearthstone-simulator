"""Actual Lost City quest, all nine UnGoro rewards and the two missing bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import AddToHand
from hs_sim.engine.fixed_reward_splits import SplitFixedRewards
from hs_sim.engine.minion_base_programs import MinionBaseStatsProfile
from hs_sim.engine.model import CardDefinition,CardType,Keyword,PlayerEffectSpec,QuestSpec,QuestStageSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT,REWARD,WARP,CORE='TLC_602','TLC_602t','UNG_028t','UNG_067t1'
PREFIX='cards.lost_city.'
BASE_PROGRAM=PREFIX+'minion_bases'
WARP_USED=PREFIX+'time_warp_used'
POOL=PREFIX+'original_rewards'
CONTEXT=GenerationContext('lost-city-source-rewards-cn37','experimental')
REWARDS=('UNG_116t','UNG_920t1',WARP,'UNG_954t1','UNG_940t8',CORE,'UNG_942t','UNG_829t1','UNG_934t1')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/lost-city-quest-v1.json'
BATCH_HASH='9f7f525519e1d62972ca3d1f2c13bfd6b57e6886cd839a0a0e2a30e4634dfc75'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(ROOT,)or
            tuple(x['record']['id']for x in d['dependencies'])!=(REWARD,WARP,CORE)or
            tuple(d['reward_ids'])!=REWARDS or len(d['reward_origins'])!=9 or d['skipped']):
        raise TargetValidationError('Lost City requires its complete original quest and reward domain')
    records=[x for k in('cards','dependencies','existing_dependencies','evidence_only','reward_origins')for x in d[k]]
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in records):raise TargetValidationError('Lost City complete source record changed')
    by_id={x['record']['id']:x['record']for x in records}
    domain={by_id[cid]['dbf_id']for cid in REWARDS}
    if domain!={x['record']['tags']['QUEST_REWARD_DATABASE_ID']for x in d['reward_origins']}:
        raise TargetValidationError('Lost City truncated the original nine quest rewards')
    q=by_id[ROOT];reward=by_id[REWARD]
    if (q['cost'],q['tags'].get('QUEST_PROGRESS_TOTAL'),q['tags'].get('QUEST_REWARD_DATABASE_ID'),
            reward['cost'],reward['attack'],reward['health'])!=(1,10,reward['dbf_id'],5,8,8):
        raise TargetValidationError('Lost City changed its actual ten-turn quest or 5-mana reward')
    return d


def register_lost_city_quest_cards(registry):
    d=load_batch()
    for cid,pin in d['existing_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid)))!=pin:raise TargetValidationError('Existing full UnGoro reward dependency changed')
    def progress(c):
        if c.event is None or c.event.kind!='turn_started':return ()
        q=c.source.quest_progress
        return(AdvanceQuest(c.source_id,q.id,q.stage,key=f"actual_turn:{dict(c.event.data)['turn']}"),)
    def warp(c):
        if any(x.spec_id==WARP_USED for x in c.state.players[c.player_id].player_effects):return ()
        return(AddPlayerEffect(c.player_id,WARP_USED,c.source_id),QueueTurns((c.player_id,),c.source_id))
    bodies={'progress':progress,'reward':lambda c:(AddToHand(c.player_id,REWARD,c.source_id),),
        'split':lambda c:(SplitFixedRewards(POOL,CONTEXT,SourceAllocationFact.capture(c.state,c.source),2),),
        'warp':warp,'core':lambda c:(AddPlayerEffect(c.player_id,BASE_PROGRAM,c.source_id),)}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for item in d['cards']+d['dependencies']:
        raw=item['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kw={}
        if cid==ROOT:kw.update(keywords=(Keyword.QUEST,),quest=QuestSpec('quest',(
            QuestStageSpec(ROOT,10,('turn_started',),PREFIX+'progress',PREFIX+'reward'),)))
        elif cid==REWARD:kw.update(attack=raw['attack'],health=raw['health'],battlecry=PREFIX+'split')
        else:kw['on_play']=PREFIX+('warp'if cid==WARP else 'core')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kw)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(WARP_USED,WARP))
    registry.register_player_effect(PlayerEffectSpec(BASE_PROGRAM,CORE))
    registry.register_minion_base_stats_profile(MinionBaseStatsProfile(BASE_PROGRAM,CORE,5,5))
    registry.register_pool(PoolDefinition(POOL,'original-nine-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid)for cid in REWARDS),complete=True))
