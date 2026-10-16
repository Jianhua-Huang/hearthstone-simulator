"""Real Leech providers and whole-group original summon beneficiaries."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember,OrderedSummonGroupSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/summon-beneficiary-native-effects-v1.json'
BATCH_HASH='30d8a9733d5b95c3a9e7478a38a7c46034eddb347180de337e3e4b9eb8993ea7'
PREFIX='cards.summon_beneficiary.'

def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Real summon beneficiaries lost their complete reviewed source pin')
    return value

def leech_theft_amount(context):
    return 1+sum(e.card_id=='EDR_810'and e.kind==CardType.MINION and e.active and e.health>0 and not e.doomed and not e.silenced
        for eid in context.state.players[context.player_id].board for e in(context.state.entities[eid],))

def register_summon_beneficiary_cards(registry):
    data=load_batch();rows={x['record']['id']:x for x in data['cards']}
    if set(rows)!={'EDR_810','TLC_240','TLC_240t'}:raise TargetValidationError('Unreviewed summon beneficiary family')
    dependency=data['existing_dependencies'][0]
    if dependency['record']['id']!='EDR_810t'or canonical_digest(dependency['record'])!=dependency['record_sha256']:
        raise TargetValidationError('Husk lost the real Leech dependency')
    registry.card('EDR_810t')
    def husk(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial('EDR_810t'),),SummonCause.capture(c))
        return(request,request)
    def tyrannogill(c):
        board=c.state.players[c.player_id].board
        position=c.death.position if c.death is not None else board.index(c.source_id)+1 if c.source_id in board else None
        members=tuple(OrderedGroupMember('dinoloc.'+str(i),SummonEntryMaterial('TLC_240t'),None if position is None else position+i)for i in range(3))
        return(SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id,SummonCause.capture(c),members),bonus_effects=True),)
    registry.register_behavior(PREFIX+'husk',husk);registry.register_behavior(PREFIX+'tyrannogill',tyrannogill)
    for cid,row in rows.items():
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Unreviewed complete summon beneficiary face')
        kwargs={'battlecry':PREFIX+'husk'}if cid=='EDR_810'else{'deathrattle':PREFIX+'tyrannogill','keywords':(Keyword.RUSH,)}if cid=='TLC_240'else{}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
