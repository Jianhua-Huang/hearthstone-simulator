"""Actual stored-cost, typed-draw, summon and temporary Arcane consumers."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.board_conditions import IfBoardFull
from hs_sim.engine.effects import AddToHand, Buff, Damage, DamageBatch, InvokeBehavior, RefreshMana
from hs_sim.engine.model import CardClass, CardDefinition, CardType, CostSpec, DamageKind, Keyword, SpellSchool, TargetSpec, Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-draw-capacity-v1.json'
BATCH_HASH = 'df3012d147fc8f8098d688444d31d60100e2401e98b3af951f3f34d710cb5a0d'
LEAVES = ('BOT_257','BOT_453','BT_002','BT_006','CFM_811','GDB_852','GDB_882','GDB_883','RLK_544','ULD_726','YOP_019')
PULSAR, GOLEM, BISCUIT = TOKENS = ('GDB_882t','RLK_544t','YOP_019t')
DEPENDENCIES = (*LEAVES,*TOKENS)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_draw_capacity.'
POOL = 'constructed.cards'
TWOS = PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2)
MAGE_SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',
    classes=(CardClass.MAGE,),include_neutral=False)
SECRETS = PoolQuery(kinds=(CardType.SPELL,),keywords_all=(Keyword.SECRET,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id'] for v in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','skipped','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            len(data['official_observations']) != 28 or data['numeric_normalizations'] != {BISCUIT:{'cost':0}} or
            not set(LEAVES) <= set(reference['candidate_ids'])):
        raise TargetValidationError('Past Arcane draw consumers require their complete original records and fixed dependencies')
    if any(canonical_digest(v['record']) != v['record_sha256'] for v in data['dependencies']):
        raise TargetValidationError('Past Arcane draw consumer original row changed')
    return data


def register_past_arcane_draw_capacity(registry):
    data = load_batch(); prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards: raise TargetValidationError('Past Arcane consumers cannot overwrite a native identity: '+cid)
        if cid in (PULSAR,GOLEM):
            card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                keywords=(Keyword.TAUNT,Keyword.ELUSIVE) if cid == GOLEM else (Keyword.TAUNT,),metadata=metadata_from_record(raw))
        else:
            card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if cid == BISCUIT else raw['cost'],
                spell_school=None if cid == BISCUIT else SpellSchool.ARCANE,on_play=PREFIX+cid,
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid == 'BOT_453' else None,
                metadata=metadata_from_record(raw))
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Arcane consumer metadata differs from its original native face: '+cid)
        prepared.append(card)
    def deck_cost(c,kind,cost):
        return tuple(ModifyStoredCost(CardReference.capture(e),cost,c.source_id)
            for i in c.state.players[c.player_id].deck for e in (c.state.entities[i],) if e.kind == kind)
    def named(c,cid,count):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),cause) for _ in range(count))
    def cosmic(c):
        return (*named(c,PULSAR,3),IfBoardFull(c.player_id,
            (InvokeBehavior(PREFIX+'cosmic_buff',c.source_id,c.player_id),),c.source_id))
    def shooting_star(c):
        target = c.state.entities[c.target_id]; board = c.state.players[target.controller].board
        index = board.index(target.id)
        ids = (target.id,*(board[i] for i in (index-1,index+1) if 0 <= i < len(board)))
        live = set(minions(c,registry,target.controller))
        return (DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL) for i in ids if i in live)),)
    bodies = {
        'BOT_257':lambda c:deck_cost(c,CardType.MINION,CostSpec(set_to=1)),
        'BT_002':lambda c:deck_cost(c,CardType.SPELL,CostSpec(delta=-1)),
        'CFM_811':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*2,DrawGroupReward('cost_drawn_minions',2)),),
        'GDB_852':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),),DrawGroupReward('cost_drawn_spells',1)),),
        'ULD_726':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(SECRETS),),DrawGroupReward('set_cost_all',0)),),
        'RLK_544':lambda c:named(c,GOLEM,2),
        'GDB_882':cosmic,
        'GDB_883':lambda c:(GenerateFromPool(c.player_id,POOL,TWOS,count=2,source_id=c.source_id,
            destination='board',cause=SummonCause.capture(c)),RefreshMana(c.player_id,2)),
        'YOP_019':lambda c:(AddToHand(c.player_id,BISCUIT,c.source_id),),
        BISCUIT:lambda c:(RefreshMana(c.player_id,2),),
        'BT_006':lambda c:(FillHandFromPool(GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,
            source_id=c.source_id,temporary_until_turn=c.state.turn)),),
        'BOT_453':shooting_star,
        'cosmic_buff':lambda c:tuple(Buff(i,1,1,c.source_id) for i in minions(c,registry,c.player_id)),
    }
    for cid,body in bodies.items(): registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
