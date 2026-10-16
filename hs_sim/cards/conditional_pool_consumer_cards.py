"""Real starting-deck, holding-Dragon and other-Mech generation consumers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.deck_conditions import DeckCondition,matches_deck_condition
from hs_sim.engine.model import CardDefinition,CardType,CostSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/conditional-pool-consumers-v1.json'
BATCH_HASH='94a426b0301de76a2830b8b0797311d8b893bf3348a46da9d63be70923430bb2'
OFFICER='JAIL_806';HISTORIAN='CORE_KAR_062';GORILLA='CORE_LOE_039'
ROOTS=(OFFICER,HISTORIAN,GORILLA);POOL_ID='constructed.cards';PREFIX='cards.conditional_pool.'
IDENTITIES={OFFICER:OFFICER,HISTORIAN:'KAR_062',GORILLA:'LOE_039'}
QUERIES={OFFICER:PoolQuery(kinds=(CardType.SPELL,),min_cost=5,collectible=True),
    HISTORIAN:PoolQuery(kinds=(CardType.MINION,),tribes_any=('dragon',),collectible=True,class_mode='current'),
    GORILLA:PoolQuery(kinds=(CardType.MINION,),tribes_any=('mech',),collectible=True,class_mode='current')}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or
            tuple(x['record']['id']for x in data['evidence_only'])!=('KAR_062','LOE_039') or
            data['dependencies']or data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed complete conditional generation recipes')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Incomplete conditional generation original row')
    return data


def register_conditional_pool_consumer_cards(registry):
    def officer(c):
        discounted=matches_deck_condition(c.state,registry,c.player_id,DeckCondition('starting','no_spells'))
        return (GenerateFromPool(c.player_id,POOL_ID,QUERIES[OFFICER],source_id=c.source_id,
            cost=CostSpec(delta=-5)if discounted else None),)
    def historian(c):
        if not any(has_any_tribe(registry,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand):
            return ()
        return (DiscoverFromPool(c.player_id,POOL_ID,QUERIES[HISTORIAN],source_id=c.source_id),)
    def gorilla(c):
        if not any(i!=c.source_id and has_any_tribe(registry,c.state.entities[i],('mech',))
                   for i in minions(c,registry,c.player_id)):
            return ()
        return (DiscoverFromPool(c.player_id,POOL_ID,QUERIES[GORILLA],source_id=c.source_id),)
    for cid,body in ((OFFICER,officer),(HISTORIAN,historian),(GORILLA,gorilla)):
        registry.register_behavior(PREFIX+cid,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION' or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):
            raise TargetValidationError('Conditional consumers require complete printed minion faces')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),battlecry=PREFIX+cid)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
