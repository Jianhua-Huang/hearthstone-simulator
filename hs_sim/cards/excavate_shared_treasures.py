"""Native shared treasures; the full real Excavation profile stays unbound."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, Draw, Heal, InvokeBehavior, RandomDamage, ReturnToHand
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, EndTurnSpec,
    HealingKind, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference, SetCapturedMinionStats
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position, minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/excavate-shared-treasures-v1.json'
BATCH_HASH = '10d2c38b0e00497e95678e0e7f434fdc9b0e14ddeb8c0e074c8e388dc1b97d78'
FLOWER, CLUSTER, FIST, COLLAPSE, MOLE, CRYSTAL, LIVING, WATER, FOOL, TROGG, CANARY, GLYPH, CHUNK = (
    'DEEP_999t1','DEEP_999t2','WW_001t11','WW_001t12','WW_001t13','WW_001t14','WW_001t16',
    'WW_001t2','WW_001t3','WW_001t4','WW_001t7','WW_001t8','WW_001t9')
CARDS = (FLOWER,CLUSTER,FIST,COLLAPSE,MOLE,CRYSTAL,LIVING,WATER,FOOL,TROGG,CANARY,GLYPH,CHUNK)
EXISTING = ('WW_001t','WW_001t18','WW_001t5','WW_001t17','WW_001t23','WW_001t24','WW_001t25',
    'WW_001t26','WW_001t27','DEEP_999t4','DEEP_999t5')
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.excavate_shared.'
POOL = 'constructed.cards'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(r['record']['id'] for r in data['cards']) != CARDS or data['dependencies'] or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != EXISTING or
            tuple(r['record']['id'] for r in data['evidence_only']) != ('DEEP_999t3','WW_009') or
            len(data['official_observations']) != 52 or len(data['inventory']['member_ids']) != 25 or
            data['inventory']['runtime_bound'] is not False or
            any(data[k] for k in ('source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for key in
                ('cards','existing_dependencies','evidence_only') for r in data[key])):
        raise TargetValidationError('Excavate treasures lost their complete faces or explicitly unbound inventory')
    return data


def register_excavate_shared_treasures(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Excavate treasure changed a complete original dependency')
    prepared = []
    keywords = {MOLE:(Keyword.TAUNT,Keyword.REBORN,Keyword.ELUSIVE),LIVING:(Keyword.TAUNT,),TROGG:(Keyword.RUSH,)}
    for row in data['cards']:
        raw = row['record'];cid = raw['id'];kind = CardType[raw['type']]
        if raw['collectible'] is not False or raw['tags'].get('2823') != 1 or cid in registry.cards:
            raise TargetValidationError('Excavate treasure must be a new original noncollectible face')
        fields = {}
        if kind == CardType.SPELL: fields['on_play'] = PREFIX+cid
        if cid == FIST: fields.update(durability=raw['health'],on_use=PREFIX+cid)
        if cid == LIVING: fields['deathrattle'] = PREFIX+cid
        if cid == CANARY: fields['battlecry'] = PREFIX+cid
        if cid == CLUSTER: fields['triggers'] = (TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec()),)
        if cid in (FLOWER,FIST,GLYPH,CANARY):
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE if cid==CANARY else TargetMode.REQUIRED,
                zones=(Zone.BOARD,),kinds=(CardType.MINION,),
                relation='friendly' if cid==FLOWER else 'enemy' if cid==CANARY else 'any')
        if cid == WATER: fields['targeting'] = TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
        card = CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack'] or 0,
            health=raw['health'] if kind==CardType.MINION else 0,keywords=keywords.get(cid,()),
            metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Excavate treasure differs from existing complete printed metadata')
        prepared.append(card)

    def glyph(c):
        target = c.state.entities[c.target_id];board = c.state.players[target.controller].board
        if target.id not in minions(c,registry,target.controller): return ()
        index = board.index(target.id)
        ids = board[max(0,index-1):index+2]
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),1,2,c.source_id)
            for i in ids if i in minions(c,registry,target.controller))

    def discover(c,cost):
        return (DiscoverFromPool(c.player_id,POOL,
            PoolQuery(collectible=True,class_mode='current',min_cost=cost,max_cost=cost),
            source_id=c.source_id,cost=CostSpec(set_to=0)),)

    bodies = {
        FLOWER:lambda c:(BuffCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),2,2,c.source_id),
            InvokeBehavior(PREFIX+'flower_damage',c.source_id,c.player_id)),
        'flower_damage':lambda c:(RandomDamage(minions(c,registry,3-c.player_id),2,c.source_id,DamageKind.SPELL),),
        CLUSTER:lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id)for i in characters(c,registry,3-c.player_id))),),
        FIST:lambda c:(SetCapturedMinionStats(MinionReference.capture(c.state.entities[c.target_id]),6,7,c.source_id),),
        COLLAPSE:lambda c:(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.SPELL)for i in characters(c,registry,3-c.player_id))),),
        CRYSTAL:lambda c:discover(c,5),
        LIVING:lambda c:(SummonFromPool(c.player_id,POOL,
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2),source_id=c.source_id,
            cause=SummonCause.capture(c),position=deathrattle_position(c)),),
        WATER:lambda c:(Heal(c.target_id,3,c.source_id,HealingKind.SPELL),Draw(c.player_id,source_id=c.source_id)),
        FOOL:lambda c:discover(c,2),
        CANARY:lambda c:(ReturnToHand(c.target_id),)if c.target_id is not None else (),
        GLYPH:glyph,
        CHUNK:lambda c:discover(c,3),
    }
    for key,body in bodies.items(): registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
