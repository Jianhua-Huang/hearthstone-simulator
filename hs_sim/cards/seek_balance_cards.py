"""Reach Equilibrium's two actual quests and independently usable reward halves."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.hand_combinations import HandCombinationProfile
from hs_sim.engine.model import (CardDefinition, CardType, Keyword, QuestSpec,
    QuestStageSpec, SpellSchool)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT, HOLY, SHADOW, LEFT, RIGHT, FULL = ('TLC_817','TLC_817t','TLC_817t2',
    'TLC_817t3','TLC_817t4','TLC_817t5')
PREFIX = 'cards.seek_balance.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/seek-balance-v1.json'
BATCH_HASH = '5115b7b5e425c5f6d42bd40c753105a3a042cc285291c73d0d73081c98b4bf04'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['cards']) != (ROOT,) or
            tuple(r['record']['id'] for r in data['dependencies']) != (HOLY,SHADOW,LEFT,RIGHT) or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != (FULL,) or data['evidence_only']):
        raise TargetValidationError('Reach Equilibrium requires its complete original family')
    for key in ('cards','dependencies','existing_dependencies'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original Reach Equilibrium face')
    return data


def register_seek_balance_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(FULL))) != data['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Reach Equilibrium changed its existing complete combined reward')
    rows = {row['record']['id']:row['record'] for key in ('cards','dependencies') for row in data[key]}
    stages = []
    for cid, school, reward in ((HOLY,SpellSchool.HOLY,LEFT),(SHADOW,SpellSchool.SHADOW,RIGHT)):
        def progress(c, school=school):
            if c.event is None or c.event.player_id != c.player_id:
                return ()
            cast_id = dict(c.event.data)['cast_id']
            record = c.state.cast_history[cast_id-1]
            if not record.completed or record.failure is not None or registry.card(record.card_id).spell_school != school:
                return ()
            q = c.source.quest_progress
            return (AdvanceQuest(c.source_id,q.id,q.stage,key='cast:'+str(cast_id)),)
        progress_id, reward_id = PREFIX+cid+'.progress', PREFIX+cid+'.reward'
        registry.register_behavior(progress_id,progress)
        registry.register_behavior(reward_id,lambda c,reward=reward:(AddToHand(c.player_id,reward,c.source_id),))
        raw = rows[cid]
        if (raw['type'],raw['cost'],raw['tags'].get('QUEST_PROGRESS_TOTAL')) != ('SPELL',1,4):
            raise TargetValidationError('Reach Equilibrium changed a native four-spell objective')
        stage = QuestStageSpec(cid,4,('spell_cast_finished',),progress_id,reward_id)
        stages.append(stage)
        registry.register_card(CardDefinition(cid,raw['name'],CardType.SPELL,cost=1,keywords=(Keyword.QUEST,),
            quest=QuestSpec('quest',(stage,)),metadata=metadata_from_record(raw)))
    root = rows[ROOT]
    if (root['type'],root['cost'],root['tags'].get('QUEST')) != ('SPELL',1,1):
        raise TargetValidationError('Reach Equilibrium changed its real quest source')
    registry.register_card(CardDefinition(ROOT,root['name'],CardType.SPELL,cost=1,keywords=(Keyword.QUEST,),
        quest=QuestSpec('paired_quest',tuple(stages)),metadata=metadata_from_record(root)))
    full = registry.card(FULL)
    for cid, keyword, fields in ((LEFT,Keyword.TAUNT,dict(battlecry=full.battlecry)),
            (RIGHT,Keyword.REBORN,dict(deathrattle=full.deathrattle))):
        raw = rows[cid]
        if (raw['type'],raw['cost'],raw['attack'],raw['health']) != ('MINION',5,4,4):
            raise TargetValidationError('Reach Equilibrium changed an actual reward half')
        registry.register_card(CardDefinition(cid,raw['name'],CardType.MINION,cost=5,attack=4,health=4,
            keywords=(keyword,),metadata=metadata_from_record(raw),**fields))
    registry.register_hand_combination(HandCombinationProfile(FULL,LEFT,RIGHT))
    for cid in rows:
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))
