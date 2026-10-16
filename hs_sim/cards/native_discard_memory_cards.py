"""A real chosen discard, remembered by its original native Deathrattle."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deathrattle_memory import DiscardForDeathrattle
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,NativeDeathrattleSpec,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard,HAND_TYPES
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-discard-memory-v1.json'
BATCH_HASH='f1fd8335b9a63b31cde3c3b7477f26cfc07481209a02e6a70ebf512d5d0cb2f6'
HOARDER='CATA_897'
PREFIX='cards.native_discard_memory.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Native discard memory lost its complete reviewed source pin')
    if tuple(row['record']['id']for row in data['cards'])!=(HOARDER,)or data['dependencies']:
        raise TargetValidationError('Unreviewed native discard-memory roots or dependencies')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Native discard-memory complete source row changed')
    return data


def register_native_discard_memory_cards(registry):
    def discard(c):
        target=c.state.entities.get(c.target_id)
        if target is None or target.zone!=Zone.HAND or target.controller!=c.player_id:return ()
        card=CardReference.capture(target)
        if c.source.kind!=CardType.MINION or c.source.zone!=Zone.BOARD:
            return(DiscardCard(card,c.source_id),)
        ids=tuple(a.id for a in active_abilities(c.source,'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind=='discard_link')
        return(DiscardForDeathrattle(card,MinionReference.capture(c.source),ids),)
    def recover(c):
        value=memory(c,'discard_link')
        return tuple(CopyCard(c.state.discard_history[i-1],c.player_id,mode='base',
            source_id=c.source_id,cost=CostSpec(delta=-1))for i in value.discard_ids)
    registry.register_behavior(PREFIX+'discard',discard)
    registry.register_behavior(PREFIX+'recover',recover)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('BATTLECRY'),raw['tags'].get('DEATHRATTLE'))!=(
            'MINION',3,3,4,True,1,1):raise TargetValidationError('Unreviewed complete Gemstone Hoarder face')
    card=CardDefinition(HOARDER,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=PREFIX+'discard',deathrattle=PREFIX+'recover',native_deathrattle=NativeDeathrattleSpec('discard_link'),
        targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.HAND,),kinds=HAND_TYPES,relation='friendly'),
        metadata=replace(metadata_from_record(raw),deck_identity=HOARDER))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
