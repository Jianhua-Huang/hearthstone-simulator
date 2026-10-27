"""Past Mage native quantities, original killed results and physical arrivals."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Damage, DamageBatch, InvokeBehavior
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyCharacter
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.health_rules import spell_bonus
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, DamageKind, MinionDeathCostSpec, PlayedTypeQuery, SpellSchool, TargetSpec
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.owner_turns import query_previous_owner_turn
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.random_split_damage import RandomSplitDamage, SplitDamageScope
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference, DrawMatching, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-summon-draw-chains-v1.json'
BATCH_HASH = 'f8c224a10add0b9b5ab10d269a6e3f12496f8acc86134c195173b02a24a7aaa6'
PREFIX = 'cards.past_mage_summon_draw_chains.'
LEAVES = ('BRM_003','TOY_371','TSC_055','BOT_254','DMF_104','TOY_377','REV_840','VAC_509','VAC_520')
TOKENS = ('DMF_104t','VAC_520t','VAC_520t2')
EXISTING = ('CS2_033','REV_845')
EVIDENCE = ('WW_377',)
POOL = 'constructed.cards'
COLLECTIBLE_ROOTS = ()


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(data['new_token_ids']) != TOKENS or
            tuple(r['record']['id'] for r in data['dependencies']) != LEAVES+TOKENS or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != EXISTING or
            tuple(r['record']['id'] for r in data['evidence_only']) != EVIDENCE or
            data['cards'] or data['skipped'] or data['source_scope_bound'] is not False or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Past Mage summon/draw batch lost its complete source or roles')
    for row in data['dependencies']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Past Mage summon/draw batch changed a complete original face')
    return data


def register_past_mage_summon_draw_chains(registry):
    data = load_batch(); prepared = []
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Mage summon/draw lost complete original dependency '+cid)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid in registry.cards:raise TargetValidationError('Past Mage summon/draw cannot overwrite '+cid)
        if cid == 'DMF_104t':
            if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('CARDRACE')) != ('MINION',8,8,8,False,18):
                raise TargetValidationError('Grand Finale requires its full original 8/8 Elemental')
            fields.update(attack=8,health=8)
        else:
            if raw['type'] != 'SPELL' or raw['collectible'] is not (cid in LEAVES):
                raise TargetValidationError('Past Mage spell changed its original collection role')
            fields.update(on_play=PREFIX+cid,spell_school=SpellSchool(row['spell_school']) if row['spell_school'] is not None else None)
            if cid in ('BRM_003','TOY_377'):fields['targeting'] = TargetSpec()
            if cid == 'BRM_003':fields['minion_death_cost'] = MinionDeathCostSpec('cost.minion-deaths-both-turn-v1')
        card = CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Past Mage summon/draw disagrees with original pool metadata')
        prepared.append(card)

    def named(c,cid,*,attack=False):
        # Result callbacks retain the original actual CAST; never pretend a
        # spell reward is an unrelated minion card effect.
        cast = c.cast or active_cast(c.state,c.source_id,c.player_id)
        if cast is None or not cast.payload_started or cast.card_id != c.source.card_id:
            raise UnsupportedDefinitionError('Native summon requires its original actual active SPELL')
        return SummonByCard(c.player_id,(SummonEntryMaterial(cid,on_summon=PREFIX+'attack' if attack else None),),
            SummonCause.capture(replace(c,cast=cast)))

    def manufacturing(c):
        no_minions = not any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck)
        return (DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*3,
            DrawGroupReward('cost_all',3) if no_minions else DrawGroupReward()),)

    def mech_prices(c):
        return tuple(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand for e in (c.state.entities[i],)
            if e.kind == CardType.MINION and has_any_tribe(registry,e,('mech',)))

    def experiment(c):
        cost = max(0,2+spell_bonus(c.state,c.player_id,registry,registry.card('BOT_254').spell_school,cast_id=c.cast.id))
        query = PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost)
        return tuple(SummonFromPool(c.player_id,POOL,query,source_id=c.source_id,cause=SummonCause.capture(c)) for _ in range(2))

    def finale(c):
        history = query_previous_owner_turn(c.state,c.player_id,PlayedTypeQuery(CardType.MINION,('elemental',)))
        return tuple(named(c,'DMF_104t') for _ in range(1+sum(row.matched for row in history.rows)))

    def result(c):
        r = c.health_result
        return (InvokeHealthResult(PREFIX+'kill_reward',c.event),) if r.target_kind == CardType.MINION.value and r.target_id == r.original_target_id else ()

    def kill_reward(c):
        r = c.health_result
        died = any(d.entity_id == r.original_target_id and d.cause is not None and d.cause.kind in ('damage','poison') and
            d.cause.result == r.payload() for d in c.state.death_history)
        return (named(c,'CS2_033' if c.source.card_id == 'TOY_377' else 'REV_845'),) if died else ()

    def deathborne(c):
        return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL,PREFIX+'result')
            for p in (1,2) for i in minions(c,registry,p))),)

    def drink(c,next_id):
        return (RandomSplitDamage(c.player_id,c.cast.id,c.source_id,2,SplitDamageScope(kinds=(CardType.MINION,))),
            *((AddToHand(c.player_id,next_id,c.source_id),) if next_id is not None else ()))

    bodies = {
        'BRM_003':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
        'TOY_371':manufacturing,
        'TSC_055':lambda c:(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,),tribes_any=('mech',)),'skip',source_id=c.source_id),
            InvokeBehavior(PREFIX+'mech_prices',c.source_id,c.player_id)),
        'BOT_254':experiment,'DMF_104':finale,
        'TOY_377':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'result'),),
        'REV_840':deathborne,
        'VAC_509':lambda c:tuple(named(c,'CS2_033',attack=True) for _ in range(3)),
        'VAC_520':lambda c:drink(c,'VAC_520t'),
        'VAC_520t':lambda c:drink(c,'VAC_520t2'),
        'VAC_520t2':lambda c:drink(c,None),
        'result':result,'kill_reward':kill_reward,'mech_prices':mech_prices,
        'attack':lambda c:(AttackRandomEnemyCharacter(original_named_reference(c),c.player_id,c.source_id),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
