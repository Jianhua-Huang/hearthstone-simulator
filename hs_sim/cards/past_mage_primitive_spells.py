"""Fifteen real past Mage spells over existing damage, freeze, draw and cast effects."""
import json
from pathlib import Path

from hs_sim.engine.effects import (CopyMinion, Damage, DamageBatch, Destroy, DestroyBatch, Draw, Freeze, RandomDamage)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardClass, CardDefinition, CardType, DamageKind, SpellSchool,
    TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-primitive-spells-v1.json'
BATCH_HASH = '22cbdd96166e9d0d2320b5a8cbef5b0441c9681cb2877fc1ea592f99abeda09d'
LEAVES = ('AT_001','WON_341','CFM_065','CS2_026','CS2_031','EX1_179','GVG_001','GIL_147',
    'DMF_103','BOT_600','OG_081','WC_041','ULD_216','TOY_372','UNG_948')
DEPENDENCIES = LEAVES
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_mage_primitive_spells.'
POOL = 'constructed.cards'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(x['record']['id']for x in data['dependencies']) != LEAVES or
            len(data['official_observations']) != 30 or not set(LEAVES) <= set(reference['candidate_ids']) or
            any(data[k]for k in ('cards','existing_dependencies','evidence_only','skipped','numeric_normalizations',
                'display_normalizations','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record']) != x['record_sha256']for x in data['dependencies'])):
        raise TargetValidationError('Past Mage primitives changed complete sources or the original full reference')
    return data


def register_past_mage_primitive_spells(registry):
    prepared = []
    for row in load_batch()['dependencies']:
        raw = row['record'];cid = raw['id'];metadata = metadata_from_record(raw)
        if raw['type'] != 'SPELL' or raw['collectible'] is not True or CardClass.MAGE not in metadata.classes:
            raise TargetValidationError('Past Mage primitive changed its original collectible Mage spell face')
        if cid in registry.cards:raise TargetValidationError('Past Mage primitive cannot overwrite '+cid)
        fields = {}
        if cid in ('AT_001','WON_341','EX1_179','OG_081','UNG_948'):
            fields['targeting'] = TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),
                relation='friendly'if cid == 'UNG_948'else'any')
        elif cid == 'CS2_031':fields['targeting'] = TargetSpec()
        if cid == 'OG_081':fields['target_rule'] = PREFIX+'frozen'
        if cid == 'GVG_001':fields['use_rule'] = PREFIX+'enemy_minion'
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata,
            spell_school=SpellSchool(row['spell_school'])if row['spell_school']is not None else None,
            on_play=PREFIX+cid,**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Mage primitive differs from its original printed metadata: '+cid)
        prepared.append(card)

    def all_minions(c):return (*minions(c,registry,1),*minions(c,registry,2))
    def frozen(c):return c.state.entities[c.target_id].frozen
    def ice_lance(c):
        return (Damage(c.target_id,4,c.source_id,DamageKind.SPELL),)if frozen(c)else(Freeze(c.target_id,c.source_id),)
    def ice_bolt(c):
        draw = frozen(c)
        return (Damage(c.target_id,2,c.source_id,DamageKind.SPELL),*((Draw(c.player_id,1,c.source_id),)if draw else()))
    def split(c,amount):
        if c.cast is None or c.cast.source_id != c.source_id:
            raise ResolutionError('Past Mage split requires its actual original spell cast')
        return (RandomSplitDamage(c.player_id,c.cast.id,c.source_id,amount),)
    def box(c):
        minimum = None if any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck)else 5
        return (CastFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=minimum),
            count=5,source_id=c.source_id),)
    bodies = {
        'AT_001':lambda c:(Damage(c.target_id,25,c.source_id,DamageKind.SPELL),),
        'WON_341':lambda c:(Damage(c.target_id,25,c.source_id,DamageKind.SPELL),),
        'CFM_065':lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)for i in all_minions(c))),),
        'CS2_026':lambda c:tuple(Freeze(i,c.source_id)for i in minions(c,registry,3-c.player_id)),
        'CS2_031':ice_lance,'EX1_179':ice_bolt,
        'GVG_001':lambda c:(RandomDamage(minions(c,registry,3-c.player_id),4,c.source_id,DamageKind.SPELL),),
        'GIL_147':lambda c:split(c,5),'DMF_103':lambda c:split(c,10),
        'BOT_600':lambda c:(Draw(c.player_id,2,c.source_id),Draw(3-c.player_id,2,c.source_id)),
        'OG_081':lambda c:(Destroy(c.target_id,c.source_id),),
        'WC_041':lambda c:(DestroyBatch(tuple(i for i in all_minions(c)if c.state.entities[i].frozen),c.source_id),),
        'ULD_216':lambda c:(CastFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True),count=10,source_id=c.source_id),),
        'TOY_372':box,
        'UNG_948':lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
    }
    registry.register_target_rule(PREFIX+'frozen',lambda c:c.target is not None and c.target.get('frozen')is True,visibility='player')
    def enemy_minion(c):
        enemy = next(p for p in c.observation['players']if p['id'] == 3-c.player_id)
        return any(e.get('kind') == CardType.MINION.value and e.get('health',0) > 0 and
            not e.get('interactable')for e in enemy['board'])
    registry.register_use_rule(PREFIX+'enemy_minion',enemy_minion,visibility='player')
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
