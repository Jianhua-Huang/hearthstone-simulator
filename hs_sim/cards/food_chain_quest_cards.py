"""The Food Chain checks after Battlecry; Shokk shares ordinary discoveries."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.minion_type_history import submitted_minion_types
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Keyword, QuestSpec, QuestStageSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT, REWARD = 'TLC_830', 'TLC_830t'
PREFIX = 'cards.food_chain.'
POOL_ID = 'constructed.cards'
ATTACKS = (1,3,5,7)
DISCOVER_ATTACKS = (8,6,4)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/food-chain-quest-v1.json'
BATCH_HASH = 'd235947b618f2f2e28dedf52c0bf1b54ed3ece3d4cf8980f0ee204b1b95d962c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['cards']) != (ROOT,) or
            tuple(r['record']['id'] for r in data['dependencies']) != (REWARD,) or
            data['existing_dependencies'] or data['evidence_only']):
        raise TargetValidationError('Food Chain requires its complete original quest and Shokk')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Food Chain source row')
    return data


def register_food_chain_quest_cards(registry):
    def progress(c):
        if c.event is None or c.event.kind != 'card_played' or c.event.player_id != c.player_id:
            return ()
        row = play_record(c.state,dict(c.event.data)['play_id'])
        if row.kind != CardType.MINION:
            return ()
        if (row.source_id,row.player_id,row.completed)!=(c.event.source_id,c.player_id,True):
            raise ResolutionError('Food Chain lost its original completed minion play')
        if not submitted_minion_types(row).matches_any(('beast',)):
            return ()
        # 34.0.1 moved this quest after Battlecry. This detached completed-play
        # context keeps that accepted current attack against later reactions.
        source = c.state.entities.get(row.source_id)
        if source is None:
            raise ResolutionError('Food Chain lost the original played minion allocation')
        attack = source.attack
        if attack not in ATTACKS:
            return ()
        q = c.source.quest_progress
        return (AdvanceQuest(c.source_id,q.id,q.stage,key='attack:'+str(attack)),)
    registry.register_behavior(PREFIX+'progress',progress)
    registry.register_behavior(PREFIX+'reward',lambda c:(AddToHand(c.player_id,REWARD,c.source_id),))
    registry.register_behavior(PREFIX+'discover',lambda c:tuple(DiscoverFromPool(c.player_id,POOL_ID,
        query=PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='any',tribes_any=('beast',),attack_equals=attack),
        source_id=c.source_id,cost=CostSpec(set_to=2),prompt=f'发现一张{attack}点攻击力的野兽牌') for attack in DISCOVER_ATTACKS))
    data = load_batch();raw = data['cards'][0]['record'];reward = data['dependencies'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('QUEST_PROGRESS_TOTAL')) != ('SPELL',1,4):
        raise TargetValidationError('Food Chain changed its four actual attack objectives')
    if ((reward['type'],reward['cost'],reward['attack'],reward['health']) != ('MINION',5,9,9) or
            reward['tags'].get('BATTLECRY')!=1 or reward['tags'].get('RUSH')!=1):
        raise TargetValidationError('Shokk changed its complete original body')
    quest = CardDefinition(ROOT,raw['name'],CardType.SPELL,cost=1,keywords=(Keyword.QUEST,),
        metadata=metadata_from_record(raw),quest=QuestSpec('quest',(
            QuestStageSpec(ROOT,4,('card_played',),PREFIX+'progress',PREFIX+'reward'),)))
    minion = CardDefinition(REWARD,reward['name'],CardType.MINION,cost=5,attack=9,health=9,
        keywords=(Keyword.RUSH,),battlecry=PREFIX+'discover',metadata=metadata_from_record(reward))
    for card in (quest,minion):
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
