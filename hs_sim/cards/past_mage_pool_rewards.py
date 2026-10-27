"""Real past Mage pool consumers, native prices and complete named rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier, AddToHand, Damage, GainArmor, InvokeBehavior, RandomDamage
from hs_sim.engine.model import (CardDefinition, CardType, CostAuraSpec, CostSpec, DamageKind,
    IntrinsicCostSpec, Keyword, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.pools import (DiscoverFromPool, FillBoardFromPool, FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery, SummonFromPool)
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.spell_casts import cast_spells
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckBatch
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-pool-rewards-v1.json'
BATCH_HASH = 'ec0dc66d79fb7287282c09bef0db24e799b15fe5b87b54f6e7bea17565d4c835'
LEAVES = ('ETC_535','WORK_012','GDB_301','KAR_076','BT_291','WW_427','TTN_476','DEEP_031','TOY_037',
    'TRL_310','TRL_313','LOE_002','REV_505','AV_282','DEEP_002')
TOKENS = ('AV_282t','AV_282t2','AV_282t3','AV_282t4','AV_282t5','DEEP_002t','DEEP_002t2','DEEP_002t3','LOE_002t')
COLLECTIBLE_DEPENDENCIES = ('REV_845',)
EXISTING = ('CS2_033',)
DEPENDENCIES = LEAVES+TOKENS+COLLECTIBLE_DEPENDENCIES
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_mage_pool_rewards.'
POOL = 'constructed.cards'
FIRE_SPELLS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FIRE,))
SECRETS = PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',keywords_all=(Keyword.SECRET,))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/d['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or canonical_digest(reference) != d['reference_canonical_sha256'] or
            tuple(d['collectible_leaf_ids']) != LEAVES or tuple(d['new_token_ids']) != TOKENS or
            tuple(d['additional_collectible_dependency_ids']) != COLLECTIBLE_DEPENDENCIES or
            tuple(r['record']['id']for r in d['dependencies']) != DEPENDENCIES or
            tuple(r['record']['id']for r in d['existing_dependencies']) != EXISTING or
            len(d['official_observations']) != 52 or not set(LEAVES) <= set(reference['candidate_ids']) or
            d['numeric_normalizations'] != {'TRL_310':{'cost':0}} or
            any(d[k]for k in ('cards','evidence_only','skipped','display_normalizations','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(r['record']) != r['record_sha256']for r in (*d['dependencies'],*d['existing_dependencies']))):
        raise TargetValidationError('Past Mage pool rewards lost complete original sources')
    return d


def register_past_mage_pool_rewards(registry):
    d = load_batch();prepared = []
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Mage pool rewards changed existing Water Elemental')
    for row in d['dependencies']:
        raw = row['record'];cid = raw['id'];fields = {};zero = d['numeric_normalizations'].get(cid,{})
        if cid in registry.cards:raise TargetValidationError('Past Mage pool rewards cannot overwrite '+cid)
        if cid in LEAVES or cid in ('AV_282t2','AV_282t4','LOE_002t'):
            if raw['type'] != 'SPELL' or raw['collectible'] is not (cid in LEAVES):
                raise TargetValidationError('Past Mage spell reward changed original type or collection role')
            fields.update(on_play=PREFIX+cid,spell_school=SpellSchool(row['spell_school'])if row['spell_school']is not None else None)
            if cid in ('KAR_076','BT_291','DEEP_031','LOE_002','LOE_002t'):fields['targeting'] = TargetSpec()
            if cid == 'TRL_313':fields.update(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
                intrinsic_costs=(IntrinsicCostSpec(set_to=1,condition='previous_owner_turn_elemental'),))
        else:
            if raw['type'] != 'MINION' or raw['collectible'] is not (cid == 'REV_845'):
                raise TargetValidationError('Past Mage minion reward changed original type or collection role')
            fields.update(attack=raw['attack'],health=raw['health'])
            if cid in ('AV_282t','AV_282t3','AV_282t5'):fields['triggers'] = registry.card('CS2_033').triggers
            elif cid == 'DEEP_002t':fields['cost_auras'] = (CostAuraSpec(CostSpec(delta=-1,card_types=(CardType.SPELL,))),)
            elif cid == 'DEEP_002t2':fields['spell_damage'] = 2
            elif cid == 'DEEP_002t3':fields['keywords'] = (Keyword.ELUSIVE,)
            elif cid == 'REV_845':fields['deathrattle'] = PREFIX+'skeleton'
        card = CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=zero.get('cost',raw['cost']),metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Mage reward differs from original metadata: '+cid)
        prepared.append(card)

    def summon(c,cost):return SummonFromPool(c.player_id,POOL,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost),source_id=c.source_id,cause=SummonCause.capture(c))
    def named(c,cid):return SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c))
    def apexis(c):
        empty = not any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck)
        return (Damage(c.target_id,5,c.source_id,DamageKind.SPELL),*((summon(c,5),)if empty else()))
    def magic(c):
        used = {registry.card(row.card_id).spell_school for row in cast_spells(c.state,c.player_id,successful=True)}
        schools = tuple(s for s in SpellSchool if s not in used)
        return (DiscoverFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=schools),source_id=c.source_id),)if schools else()
    def bottom(c):
        refs = tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck[-6:])
        return (DestroyDeckBatch(refs,c.source_id),)if refs else()
    def skeleton(c):
        targets = (c.state.players[3-c.player_id].hero_id,*minions(c,registry,3-c.player_id))
        return (RandomDamage(targets,2,c.source_id,DamageKind.MINION_ABILITY),)
    bodies = {
        'ETC_535':lambda c:tuple(GenerateFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=cost,max_cost=cost,tribes_any=('elemental',)),source_id=c.source_id)for cost in(1,2,3)),
        'WORK_012':lambda c:(FillBoardFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('naga',)),c.source_id,SummonCause.capture(c)),),
        'GDB_301':lambda c:(FillHandFromPool(GenerateFromPool(c.player_id,POOL,FIRE_SPELLS,source_id=c.source_id,cost=CostSpec(set_to=1))),),
        'KAR_076':lambda c:(Damage(c.target_id,6,c.source_id,DamageKind.SPELL),summon(c,6)),
        'BT_291':apexis,
        'WW_427':lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,10),summon(c,10)),
        'TTN_476':magic,
        'DEEP_031':lambda c:(Damage(c.target_id,6,c.source_id,DamageKind.SPELL),summon(c,6),InvokeBehavior(PREFIX+'bottom',c.source_id,c.player_id)),
        'bottom':bottom,
        'TOY_037':lambda c:(DiscoverFromPool(c.player_id,POOL,SECRETS,source_id=c.source_id,cost=CostSpec(set_to=1)),),
        'TRL_310':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.MINION,)),uses_remaining=1,
            source_id=c.source_id,expires_turn=c.state.turn,tribes_any=('elemental',)),),
        'TRL_313':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
        'LOE_002':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),AddToDeck(c.player_id,'LOE_002t','random',c.source_id)),
        'LOE_002t':lambda c:(Damage(c.target_id,6,c.source_id,DamageKind.SPELL),),
        'REV_505':lambda c:(named(c,'REV_845'),named(c,'REV_845'),GainArmor(c.player_id,4)),
        'skeleton':skeleton,
        'AV_282':lambda c:(named(c,'AV_282t'),AddToHand(c.player_id,'AV_282t2',c.source_id)),
        'AV_282t2':lambda c:(named(c,'AV_282t3'),AddToHand(c.player_id,'AV_282t4',c.source_id)),
        'AV_282t4':lambda c:(named(c,'AV_282t5'),),
        'DEEP_002':lambda c:(SummonByCard(c.player_id,tuple(SummonEntryMaterial(cid)for cid in('DEEP_002t','DEEP_002t2','DEEP_002t3')),
            SummonCause.capture(c),selection='random'),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
