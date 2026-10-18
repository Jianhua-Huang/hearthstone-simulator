"""Physical nonstarting spell draw and chosen complete Animal Companions."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .fixed_companion_cards import companion_effects,load_batch as companion_batch
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p13-v1.json'
BATCH_HASH='3e34b556be606d5291c728a5cdca9621a64b131ff98a6af0baa973a9cd01fb6f'
SABRE='TLC_247';SHOVEL='JAIL_380';SPEAKER='MEND_301';ROOTS=(SHOVEL,SPEAKER)
COMPANIONS=('NEW1_034','NEW1_033','NEW1_032');PREFIX='cards.simple_followup_p13.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P13 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or
       tuple(x['record']['id']for x in data['skipped'])!=(SABRE,)or
       {x['record']['id']for x in data['existing_dependencies']}!=set(COMPANIONS)or
       tuple(data['companion_choice_order'])!=COMPANIONS or data['dependencies']or data['evidence_only']):
        raise TargetValidationError('Unreviewed P13 roots or fixed dependencies')
    for row in data['cards']+data['skipped']+data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P13 source row')
    return data

def register_simple_followup_p13_cards(registry):
    data=load_batch();old={x['record']['id']:x['record']for x in companion_batch()['cards']}
    for row in data['existing_dependencies']:
        raw=row['record'];card=registry.card(raw['id'])
        if raw!=old.get(raw['id'])or card.kind!=CardType.MINION or card.metadata!=replace(metadata_from_record(raw),deck_identity=raw['id']):
            raise TargetValidationError('P13 lost its complete existing companion definition')
    def shovel(c):
        return(DrawPhysicalGroup(c.player_id,c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,)),starting_deck=False),)),)
    def speaker(c):
        return companion_effects(c,registry,'choice')
    registry.register_behavior(PREFIX+'shovel',shovel);registry.register_behavior(PREFIX+'speaker',speaker)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if raw['collectible']is not True:raise TargetValidationError('P13 requires complete collectible roots')
        if cid==SHOVEL:kwargs.update(durability=raw['health'],deathrattle=PREFIX+'shovel')
        else:kwargs.update(health=raw['health'],battlecry=PREFIX+'speaker')
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],attack=raw['attack'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
