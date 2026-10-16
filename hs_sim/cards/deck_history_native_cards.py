"""Real selection, cross-deck draws and immutable-history card consumers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import DestroyBatch,InvokeBehavior,SetStats
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,ChooseBranch,
    ChooseOneSpec,Zone)
from hs_sim.engine.owner_turns import validate_history
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.tribes import tribe_state
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/deck-history-native-effects-v1.json'
BATCH_HASH='c377026a6b3988eaf9bf77bb6a6872d04521d249d49eca1cc10d5b7945378807'
PREFIX='cards.deck_history_native.'
SCRIPTS={'END_010':'twilight','END_010a':'attack','END_010b':'health','TIME_032':'chronogor',
 'TIME_103':'chromie','TIME_714':'epoch','TLC_110':'esho'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Native deck/history reviewed complete source changed')
    return data


def register_deck_history_native_cards(registry):
    def invoke(c,name):
        return(InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
            None if c.play is None else c.play.id),)
    def stat(c,attack=None,health=None):
        return tuple(SetStats(i,attack,health,c.source_id)for p in(1,2)
            for i in minions(c,registry,p)if i!=c.source_id)
    def chronogor(c):
        return(DrawMatching(c.player_id,PoolQuery(),'skip',2,'highest_cost',c.source_id),
            DrawMatching(3-c.player_id,PoolQuery(),'skip',2,'lowest_cost',c.source_id,owner_id=c.player_id))
    def chromie(c):
        validate_history(c.state,registry)
        ids=tuple(dict.fromkeys(p.card_id for p in played_cards(c.state,c.player_id)))
        return tuple(DrawMatching(c.player_id,PoolQuery(),'skip',source_id=c.source_id,card_ids=(cid,))for cid in ids)
    def epoch(c):
        validate_history(c.state,registry)
        last=next((t for t in reversed(c.state.owner_turn_history)if t.player_id==3-c.player_id and t.closed),None)
        if last is None:return ()
        # A hand play alone does not prove which current board residence it made.
        # The immutable successful-entry record supplies that original order.
        targets=[]
        for p in played_cards(c.state,3-c.player_id,kind=CardType.MINION):
            if p.played_face.owner_turn_id!=last.id or p.countered or p.minion_result!='summoned':continue
            entry=next((s for s in c.state.successful_summon_history
                if(s.entity_id,s.player_id,s.action,s.turn)==(p.source_id,3-c.player_id,p.action,p.turn)),None)
            if entry is None:raise TargetValidationError('Epoch lost a real ordinary played minion entry')
            e=c.state.entities[p.source_id]
            if(e.zone,e.kind,e.board_presence_id)==(Zone.BOARD,CardType.MINION,entry.minion.entered_order)and e.active and e.health>0 and not e.doomed:
                targets.append(e.id)
        return(DestroyBatch(tuple(dict.fromkeys(targets)),c.source_id),)if targets else ()
    def esho(c):
        common=None;excluded=set()
        for i in c.state.players[c.player_id].deck:
            e=c.state.entities[i]
            if e.kind!=CardType.MINION:continue
            tribes=tribe_state(registry,e)
            if tribes is None:raise UnsupportedDefinitionError('City Chief Esho requires complete current deck minion tribes')
            if tribes.members==('all',):excluded.update(tribes.excluded)
            else:common=set(tribes.members)if common is None else common.intersection(tribes.members)
        if common is not None and not(common-excluded):return ()
        return(BuffMinionsInZones(c.player_id,2,2,MinionScope(exclude_source=True),c.source_id),)
    bodies=dict(attack=lambda c:stat(c,attack=1),health=lambda c:stat(c,health=1),both=lambda c:stat(c,1,1),
        chronogor=chronogor,chromie=chromie,epoch=epoch,esho=esho)
    for name in('attack','health','both','chronogor','chromie','epoch','esho'):
        registry.register_behavior(PREFIX+name+'_now',bodies[name])
        registry.register_behavior(PREFIX+name,lambda c,name=name:invoke(c,name+'_now'))
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']}
    for row in data['enchantment_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Choose One stat-set enchantment source changed')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(cid)!=recipe['script']or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Unreviewed native deck/history face')
        if cid=='END_010':
            branches=tuple(ChooseBranch(x,raws[x]['name'],PREFIX+SCRIPTS[x])for x in('END_010a','END_010b'))
            kwargs['choose_one']=ChooseOneSpec(branches,ChooseBranch('END_010:combined','心志有限',PREFIX+'both'))
        elif recipe['root']:kwargs['deathrattle'if cid=='TIME_103'else'battlecry']=PREFIX+recipe['script']
        card=CardDefinition(cid,raw['name'],kind,cost=0 if recipe['choice_only']else raw['cost'],
            attack=raw['attack']or 0,health=raw['health']or 0,choice_only=recipe['choice_only'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card)
        if not recipe['choice_only']:registry.register_pool_card(PoolCard.from_definition(card))
