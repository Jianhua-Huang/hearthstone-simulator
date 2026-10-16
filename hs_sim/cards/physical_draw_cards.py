"""Native physical draw groups, prior owner turns and real opening identity."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Draw, GainArmor
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.owner_turns import query_for_definition, query_previous_owner_turn, validate_history
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/physical-draw-groups-v1.json'
BATCH_HASH='e6e006517f8436222d4c5c96b73be61d4c3a7224e83433c86dbe1f20da0db93e'
PREFIX='cards.physical_draw.'
SCRIPTS={'MEND_043':'heartroot','TIME_770':'forward','JAIL_206':'bribe','TLC_222':'flight','TLC_236':'hybrid','EDR_251':'armaments'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH: raise TargetValidationError('Physical draw cards lost their complete reviewed pin')
    return data


def register_physical_draw_cards(registry):
    def group(c, slots, reward=DrawGroupReward()): return (DrawPhysicalGroup(c.player_id,c.source_id,slots,reward),)
    def heartroot(c):
        validate_history(c.state)
        previous=next((t for t in reversed(c.state.owner_turn_history)if t.player_id==c.player_id and t.closed),None)
        played=previous is not None and any(p.played_face.owner_turn_id==previous.id and p.player_id==c.player_id and p.kind==CardType.MINION for p in c.state.play_history)
        return tuple(effect for _ in range(1 if played else 2)for effect in (Draw(c.player_id,1,c.source_id),GainArmor(c.player_id,3)))
    def hybrid(c):
        enabled=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card('TLC_236'))).matched
        return group(c,tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)),current_cost=cost)for cost in (1,2,3,4)),
            DrawGroupReward('cost_all',1)if enabled else DrawGroupReward())
    bodies=dict(heartroot=heartroot,
        forward=lambda c:group(c,(DrawGroupSlot(),)*2,DrawGroupReward('cost_one',2)),
        bribe=lambda c:group(c,(DrawGroupSlot(),)*3,DrawGroupReward('give_one')),
        flight=lambda c:group(c,(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)),different_tribes=True),)*2,DrawGroupReward('buff_all',1)),
        hybrid=hybrid,
        armaments=lambda c:group(c,tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,)),starting_deck=value)for value in (True,False))))
    for name,body in bodies.items(): registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];school=raw['tags'].get('SPELL_SCHOOL')
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(raw['id'])!=recipe['script']:
            raise TargetValidationError('Physical draw recipe lost its reviewed complete spell face')
        if school is not None and school not in SCHOOLS: raise TargetValidationError('Unknown physical draw spell school')
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SCHOOLS.get(school),
            on_play=PREFIX+recipe['script'],metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
