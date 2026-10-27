"""Fifteen original past Arcane identities compose the existing public effects."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, InvokeBehavior, RandomDamage, Transform
from hs_sim.engine.model import CardClass, CardDefinition, CardType, CostSpec, DamageKind, Keyword, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-simple-spells-v1.json'
BATCH_HASH = 'f36a51430e6106554623b56abed8862f06e041b387230cf8b4dc8e06ac7bade4'
LEAVES = ('AT_005','BOT_101','CFM_623','CS2_022','CS2_023','CS2_025','DAL_608','DS1_185',
    'EX1_180','GVG_003','OG_090','TID_001','TID_708','UNG_941','WON_037')
TOKENS = ('AT_005t','TID_708t')
DEPENDENCIES = (*LEAVES,*TOKENS)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_simple_spells.'
POOL = 'constructed.cards'
TRANSFORMS = {'AT_005':'AT_005t','CS2_022':'CS2_tk1','TID_708':'TID_708t'}
ALIASES = {'CS2_023':'CORE_CS2_023','DS1_185':'CORE_DS1_185'}
MINIONS = PoolQuery(kinds=(CardType.MINION,),collectible=True)
MAGE_SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',
    classes=(CardClass.MAGE,),include_neutral=False)
SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')
SMALL_SPELLS = replace(SPELLS,max_cost=3)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(v['record']['id'] for v in data['dependencies']) != DEPENDENCIES or
            tuple(v['record']['id'] for v in data['existing_dependencies']) != ('CS2_tk1',*ALIASES.values()) or
            any(data[k] for k in ('cards','evidence_only','skipped','formal_pool_complete','cn_calibrated','source_scope_bound')) or
            data['named_transform_faces'] != TRANSFORMS or data['existing_body_aliases'] != ALIASES or
            len(data['official_observations']) != 36 or len(reference['candidate_ids']) != 84 or
            not set(LEAVES) <= set(reference['candidate_ids']) or reference['runtime_bindings_added']):
        raise TargetValidationError('Past Arcane spells lost complete original identities, forms or source reference')
    if any(canonical_digest(v['record']) != v['record_sha256'] for v in
            data['dependencies']+data['existing_dependencies']+reference['candidate_records']):
        raise TargetValidationError('Past Arcane spells require their complete original raw records')
    return data


def register_past_arcane_simple_spells(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                row['pool_card_sha256'] is not None and
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Arcane spells changed an existing full native dependency: '+cid)
    prepared = []
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards: raise TargetValidationError('Past Arcane spells cannot overwrite a native identity: '+cid)
        if cid in ALIASES:
            card = replace(registry.card(ALIASES[cid]),id=cid,name=raw['name'],cost=raw['cost'],metadata=metadata_from_record(raw))
        elif cid in TOKENS:
            card = CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                keywords=(Keyword.CHARGE,) if cid == 'AT_005t' else (),spell_damage=2 if cid == 'TID_708t' else 0,
                metadata=metadata_from_record(raw))
        else:
            target = (TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)) if cid in TRANSFORMS else
                TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='enemy') if cid == 'TID_001' else None)
            card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.ARCANE,
                on_play=PREFIX+cid,targeting=target,metadata=metadata_from_record(raw))
        registry._validate_card(card); printed = PoolCard.from_definition(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != printed:
            raise TargetValidationError('Past Arcane spell metadata contradicts its complete printed source: '+cid)
        prepared.append(card)
    def missiles(c):
        # A new ordinary native callback queries the current candidates for
        # each of three shots. The kernel owns RNG, damage and death boundaries.
        return (RandomDamage(characters(c,registry,3-c.player_id),3,c.source_id,DamageKind.SPELL),)
    bodies = {
        'CFM_623':lambda c:tuple(InvokeBehavior(PREFIX+'missile',c.source_id,c.player_id) for _ in range(3)),
        'CS2_025':lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)
            for i in minions(c,registry,3-c.player_id))),),
        'TID_001':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),Damage(c.target_id,1,c.source_id,DamageKind.SPELL)),
        'BOT_101':lambda c:(GenerateFromPool(c.player_id,POOL,MINIONS,count=2,source_id=c.source_id),),
        'GVG_003':lambda c:(GenerateFromPool(c.player_id,POOL,MINIONS,source_id=c.source_id,cost=CostSpec(delta=-3)),),
        'EX1_180':lambda c:(GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,source_id=c.source_id),),
        'OG_090':lambda c:(GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,count=3,source_id=c.source_id),),
        'WON_037':lambda c:(GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,count=3,source_id=c.source_id),),
        'DAL_608':lambda c:(DiscoverFromPool(c.player_id,POOL,SMALL_SPELLS,source_id=c.source_id),),
        'UNG_941':lambda c:(DiscoverFromPool(c.player_id,POOL,SPELLS,source_id=c.source_id,cost=CostSpec(delta=-2)),),
    }
    for cid,form in TRANSFORMS.items():
        bodies[cid] = lambda c,form=form:(Transform(c.target_id,form),)
    registry.register_behavior(PREFIX+'missile',missiles)
    for cid,body in bodies.items(): registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
