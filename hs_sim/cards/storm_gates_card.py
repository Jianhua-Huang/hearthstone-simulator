"""Storm the Gates uses the original Sidequest and crafted-minion pipelines."""
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import CraftedMinionBlueprint
from hs_sim.engine.crafted_offers import CraftMinion
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.minion_type_history import submitted_minion_types
from hs_sim.engine.model import CardDefinition,CardType,Keyword,QuestSpec,QuestStageSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TLC_EVENT_400';TEMPLATE='ICC_828t'
FIRST='crafted.zombeast.first';SECOND='crafted.zombeast.second'
PARTS=('UNG_803','BT_201','CS2_171','GIL_545')
PREFIX='cards.storm_gates.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/storm-gates-v1.json'
BATCH_HASH='2e4f8e89f45f25713580cf18908b087f0b2ae728d048f89d401d2a9ba034d34b'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=(*data['cards'],*data['dependencies'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,TEMPLATE,*PARTS)or
            data['evidence_only']or data['skipped']or any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Zombeast source requires its complete original Sidequest, template and reviewed parts')
    raw=data['cards'][0]['record'];template=data['dependencies'][0]['record']
    if ((raw['type'],raw['cost'],raw['tags'].get('SIDE_QUEST'),raw['tags'].get('QUEST_PROGRESS_TOTAL'))!=('SPELL',1,1,3)or
            (template['type'],template['cost'],template['attack'],template['health'])!=('MINION',None,1,1)or
            data['numeric_normalizations']!={TEMPLATE:{'cost':0}}):
        raise TargetValidationError('Zombeast source changed its actual quest or complete zero-cost template observation')
    return data


def register_storm_gates_card(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record'];old=registry.card(raw['id'])
        if (old.cost,old.attack,old.health,old.metadata)!=(raw['cost'],raw['attack'],raw['health'],metadata_from_record(raw)):
            raise TargetValidationError('Zombeast donation changed an existing original part')
        registry.register_crafted_minion_part(old.id)
    raw=data['dependencies'][0]['record']
    template=CardDefinition(TEMPLATE,raw['name'],CardType.MINION,cost=0,attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw))
    registry.register_card(template)
    registry.register_crafted_minion_blueprint(CraftedMinionBlueprint(TEMPLATE,'beast','beast'))
    def progress(c):
        if c.event is None or c.event.kind!='card_played' or c.event.player_id!=c.player_id:return ()
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if row.kind!=CardType.MINION:return ()
        if (row.source_id,row.player_id,row.completed)!=(c.event.source_id,c.player_id,True):
            raise ResolutionError('Sidequest lost its actual completed original play')
        if not submitted_minion_types(row).matches_any(('beast','undead')):return ()
        q=c.source.quest_progress
        return(AdvanceQuest(c.source_id,q.id,q.stage),)
    registry.register_behavior(PREFIX+'progress',progress)
    registry.register_behavior(PREFIX+'reward',lambda c:(CraftMinion(c.player_id,TEMPLATE,FIRST,SECOND,c.source_id,
        discount_amount=3,max_part_cost=5),))
    raw=data['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword('sidequest'),),metadata=metadata_from_record(raw),
        quest=QuestSpec('sidequest',(QuestStageSpec(CARD,3,('card_played',),PREFIX+'progress',PREFIX+'reward'),)))
    registry.register_card(card)
    for card in (card,template):
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
