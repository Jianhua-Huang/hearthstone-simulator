"""Twelve original Mage consumers over existing copies, reveals and Secrets."""
from dataclasses import asdict, replace
import hashlib, json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.deck_reveals import RevealRandomDeckCard, deck_reveal_result
from hs_sim.engine.effects import CopyMinion, Damage, DamageBatch, Freeze, GrantDeathrattle, GrantHealthRule, InvokeBehavior
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, DamageKind, HandActionSpec,
    HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword, SecretSpec, TargetSpec, Zone)
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.sacrifice import DestroyCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CopyLowestCostMinion
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-mage-effect-consumers-v1.json'
BATCH_HASH = 'c13accc84e33509d13449e7b4b9583a4b52b7326bc19009ba9123343434325d8'
POLICY = 'cn37-local-past-mage-effect-consumers-v1'
LEAVES = DEPENDENCIES = ('BAR_812','EX1_594','GIFT_02','ICC_823','LOOT_101','LOOT_172',
    'MIS_302','ONY_029','REV_504','TOY_374','TSC_056','ULD_239')
EXISTING = ('CORE_BAR_812','CORE_LOOT_101','CS2_023','CS2_024','CS2_029','CS2_033')
ALIASES = {'BAR_812':'CORE_BAR_812', 'LOOT_101':'CORE_LOOT_101'}
SECRETS = ('BAR_812','EX1_594','LOOT_101','ULD_239')
GIFT_IDS = ('CS2_024','CS2_023','CS2_029')
GIFT_POOL = 'cards.past_mage_gift.named-spells'
POOL = 'constructed.cards'
PREFIX = 'cards.past_mage_effect_consumers.'
COLLECTIBLE_ROOTS = ()
CAP = HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET, target_kinds=(CardType.HERO,))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or d['cards'] or
            tuple(d['collectible_leaf_ids']) != LEAVES or d['existing_body_aliases'] != ALIASES or
            tuple(row['record']['id'] for row in d['dependencies']) != LEAVES or
            tuple(row['record']['id'] for row in d['existing_dependencies']) != EXISTING or
            len(d['official_observations']) != 24 or d['new_standard_roots'] or d['gift_domain_bound'] is not True or
            any(d[k] for k in ('full_past_mage_source_bound','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            d['gift_inventory'] != dict(pool_id=GIFT_POOL, candidate_ids=list(GIFT_IDS), weights=[1]*3,
                excluded_card_ids=[], complete_for_declared_named_inventory=True)):
        raise TargetValidationError('Past Mage consumers require their full original records and named gift domain')
    path = ROOT/d['reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest() != d['reference_sha256']:
        raise TargetValidationError('Past Mage consumers changed their full original reference')
    if not set(LEAVES) <= set(json.loads(path.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Past Mage consumers escaped the original full source scope')
    if any(canonical_digest(row['record']) != row['record_sha256'] for row in d['dependencies']+d['existing_dependencies']):
        raise TargetValidationError('Past Mage consumers changed a complete source row')
    return d


def _existing(registry, d):
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_metadata_sha256']):
            raise TargetValidationError('Past Mage consumer changed a complete native dependency: '+cid)


def register_past_mage_effect_consumers(registry):
    d = load_batch(); _existing(registry, d); prepared = []
    specs = {cid:SecretSpec(cid, (event,), PREFIX+cid, PREFIX+cid) for cid,event in (
        ('EX1_594','attack_declared'), ('ULD_239','attack_finished'))}
    for row in d['dependencies']:
        raw = row['record']; cid = raw['id']; school = SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))
        if (raw['type'] != 'SPELL' or cid in registry.cards or cid in registry.pool_cards or
                (cid in SECRETS) != (raw['tags'].get('SECRET') == 1)):
            raise TargetValidationError('Past Mage consumer requires its original new spell face: '+cid)
        if cid in ALIASES:
            old = registry.card(ALIASES[cid])
            if (old.cost, old.spell_school) != (raw['cost'], school):
                raise TargetValidationError('Past Mage alias changed the native printed cost or school')
            card = replace(old, id=cid, name=raw['name'], metadata=metadata_from_record(raw))
        else:
            fields = dict(secret=specs[cid], keywords=(Keyword.SECRET,)) if cid in specs else dict(on_play=PREFIX+cid)
            if cid in ('MIS_302','TSC_056'):
                fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if cid == 'ONY_029': fields['hand_actions'] = (HandActionSpec('trade','trade',1),)
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'],
                spell_school=school, metadata=metadata_from_record(raw), **fields)
        prepared.append(card)

    def all_minions(c): return tuple(i for p in (1,2) for i in minions(c, registry, p))
    def reveal_result(c):
        result = deck_reveal_result(c.event)
        if result is None or result.player_id != c.player_id or c.event.source_id != c.source_id:
            raise ValueError('Dragons Fury requires its actual original public deck reveal')
        return () if result.card is None else (DamageBatch(tuple(
            Damage(i, result.card.cost, c.source_id, DamageKind.SPELL) for i in all_minions(c))),)
    def copy_frozen(c):
        ref = BoardPresenceReference.capture(c.state, c.target_id)
        return (Freeze(c.target_id, c.source_id), CopyMinion(ref, c.player_id, cause=SummonCause.capture(c)))
    def discover_three(c):
        return DiscoverFromPool(c.player_id, POOL, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            min_cost=3, max_cost=3, class_mode='current'), source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c))
    def repeat_spot(c):
        return () if any(c.state.entities[i].kind == CardType.MINION for i in c.state.players[c.player_id].deck) else (discover_three(c),)
    def vaporize(c):
        if not attack_live(c.state, c.window): return ()
        return (DestroyCapturedMinion(MinionReference.capture(c.state.entities[c.window.source_id]), c.source_id),)
    def attacks_hero(c):
        if not attack_live(c.state, c.window): return False
        return (c.state.entities[c.window.source_id].kind == CardType.MINION and
            c.state.entities[c.window.source_id].controller != c.player_id and
            c.window.target_id == c.state.players[c.player_id].hero_id)
    def attacked_hero(c):
        row = completed_attack(c)
        return (row is not None and row.source_kind == CardType.MINION and
            row.declaration.player_id != c.player_id and row.delivery.target_id == c.state.players[c.player_id].hero_id)
    bodies = {
        'GIFT_02':lambda c:(DiscoverFromPool(c.player_id, GIFT_POOL, PoolQuery(kinds=(CardType.SPELL,), collectible=True),
            source_id=c.source_id, temporary_until_turn=c.state.turn),),
        'ICC_823':lambda c:(CopyLowestCostMinion(c.player_id, (), c.source_id),),
        'LOOT_172':lambda c:(RevealRandomDeckCard(c.player_id, source_id=c.source_id, on_result=PREFIX+'reveal_result'),),
        'MIS_302':copy_frozen,
        'ONY_029':lambda c:(DiscoverFromPool(c.player_id, POOL, PoolQuery(kinds=(CardType.MINION,), collectible=True,
            tribes_any=('dragon',), class_mode='current'), source_id=c.source_id, discoveries=2,
            destination='board', delivery='after_all', cause=SummonCause.capture(c)),),
        'REV_504':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_id, CAP,
            c.source_id, until_owner_turn_start=c.player_id),),
        'TOY_374':lambda c:(discover_three(c), InvokeBehavior(PREFIX+'repeat_spot', c.source_id, c.player_id)),
        'TSC_056':lambda c:(GrantDeathrattle(c.target_id, PREFIX+'bomb', c.source_id),),
        'ULD_239':lambda c:(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.SPELL)
            for i in minions(c,registry,3-c.player_id))),),
        'EX1_594':vaporize,
        'reveal_result':reveal_result, 'repeat_spot':repeat_spot,
        'bomb':lambda c:(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.EFFECT) for i in all_minions(c))),),
    }
    registry.register_secret_condition(PREFIX+'EX1_594', attacks_hero)
    registry.register_secret_condition(PREFIX+'ULD_239', attacked_hero)
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    for card in prepared:
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))


def gift_pool(registry, context):
    d = load_batch(); _existing(registry, d)
    if registry.card('GIFT_02').on_play != PREFIX+'GIFT_02':
        raise TargetValidationError('Named gift pool requires the actual original spell consumer')
    return PoolDefinition(GIFT_POOL, POLICY+'-'+BATCH_HASH, context.target_id, context.mode,
        tuple(PoolMember(cid, weight) for cid, weight in zip(d['gift_inventory']['candidate_ids'], d['gift_inventory']['weights'])),
        excluded_card_ids=tuple(d['gift_inventory']['excluded_card_ids']), complete=True)
