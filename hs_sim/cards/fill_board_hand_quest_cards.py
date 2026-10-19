"""Two actual capacity quests share guarded state acceptance and old rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (QUEST_FULL_BOARD_TURNS, QUEST_FULL_THEN_EMPTY_HAND,
    CardDefinition, CardType, Keyword, QuestSpec, QuestStageSpec, Zone)
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BOARD = 'TLC_239'
HAND = 'END_017'
ROOTS = (BOARD, HAND)
REWARDS = ('TLC_239t', 'END_017t')
PREFIX = 'cards.fill_area_quests.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/fill-board-hand-quests-v1.json'
BATCH_HASH = '478311d81ef7144c05116d89a02ba8e30350ef3f74650b31b89312ab2f96b341'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != ROOTS or data['dependencies'] or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != REWARDS or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TLC_239e',)):
        raise TargetValidationError('Area quests require their exact complete roots and rewards')
    for section in ('cards', 'existing_dependencies', 'evidence_only'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original area quest row')
    return data


def register_fill_board_hand_quest_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Area quest changed its existing complete named reward')

    def progress(c):
        q = c.source.quest_progress
        if q is None or c.source.zone != Zone.QUEST or c.event is None:
            raise ResolutionError('Area progress requires its original accepted quest snapshot')
        if c.source.card_id == BOARD:
            key = 'owner_turn:'+str(current_owner_turn(c.state).id)
        elif c.source.card_id == HAND:
            if q.value not in (0, 1): return ()
            key = 'full' if q.value == 0 else 'empty'
        else:
            raise ResolutionError('Unknown native area quest')
        return (AdvanceQuest(c.source_id, q.id, q.stage, key=key),)

    registry.register_behavior(PREFIX+'progress', progress)
    for row, reward in zip(data['cards'], REWARDS):
        raw = row['record']; cid = raw['id']; goal = 3 if cid == BOARD else 2
        if (raw['type'], raw['cost'], raw['tags'].get('QUEST'), raw['tags'].get('QUEST_PROGRESS_TOTAL')) != ('SPELL', 1, 1, goal):
            raise TargetValidationError('Area quest changed its actual native goal')
        reward_body = PREFIX+cid+'.reward'
        registry.register_behavior(reward_body, lambda c, reward=reward: (AddToHand(c.player_id, reward, c.source_id),))
        state_event = QUEST_FULL_BOARD_TURNS if cid == BOARD else QUEST_FULL_THEN_EMPTY_HAND
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], keywords=(Keyword.QUEST,),
            quest=QuestSpec('quest', (QuestStageSpec(cid, goal, (state_event,), PREFIX+'progress', reward_body),)),
            metadata=metadata_from_record(raw))
        registry.register_card(card)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
