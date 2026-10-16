"""Reviewed stored native Deathrattle, fixed bottom cards and Kindred discard."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,DamageBatch,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import AddToDeck,DiscardMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/demon-zone-effects-v1.json'
BATCH_HASH='4317be013697b8b70e392145a4d03ba3da11211463d73252ff7ec740a5637cb3'
PREFIX='cards.demon_zones.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Demon zone content differs from its complete reviewed pin')
    return data


def register_demon_zone_cards(registry):
    def razidir(c):
        match=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card('TLC_463')))
        return(DiscardMatching(3-c.player_id if match.matched else c.player_id,count=1,source_id=c.source_id),)
    def diabolus(c):
        match=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card('DINO_138')))
        return(InvokeBehavior(PREFIX+'diabolus_now',c.source_id,c.player_id),)if match.matched else()
    def diabolus_now(c):
        ids=tuple(eid for eid in c.state.players[3-c.player_id].board if c.state.entities[eid].kind==CardType.MINION
                  and registry.card(c.state.entities[eid].card_id).interactable is None)
        return(DamageBatch(tuple(Damage(eid,6,c.source_id,DamageKind.MINION_ABILITY)for eid in(ids[0],ids[-1]))),)if ids else()
    bodies=dict(impfernal=lambda c:(InvokeBehavior(PREFIX+'impfernal_now',c.source_id,c.player_id),),
        impfernal_now=lambda c:(DamageBatch(tuple(Damage(eid,3,c.source_id,DamageKind.MINION_ABILITY)
            for pid in(1,2)for eid in characters(c,registry,pid)if eid!=c.source_id)),),
        stooge=lambda c:tuple(AddToDeck(c.player_id,'JAIL_399t1',position='bottom',source_id=c.source_id)for _ in range(2)),
        razidir=razidir,diabolus=diabolus,diabolus_now=diabolus_now)
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']}
    for link in data['dependency_links']:
        if raws[link['root_id']]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID']!=raws[link['card_id']]['dbf_id']or link['dbf_id']!=raws[link['card_id']]['dbf_id']:
            raise TargetValidationError('Demon bottom card differs from its exact source DBF')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Demon zone card lost its complete reviewed native face')
        if cid=='JAIL_398':kwargs.update(deathrattle=PREFIX+'impfernal',stored_deathrattle=True)
        elif cid=='JAIL_399':kwargs['deathrattle']=PREFIX+'stooge'
        elif cid=='TLC_463':kwargs['battlecry']=PREFIX+'razidir'
        elif cid=='DINO_138':kwargs['on_play']=PREFIX+'diabolus'
        elif cid!='JAIL_399t1':raise TargetValidationError('Unreviewed Demon zone recipe')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=tuple(Keyword(x)for x in recipe['keywords']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
