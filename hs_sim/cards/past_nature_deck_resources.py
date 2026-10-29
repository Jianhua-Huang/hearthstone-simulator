"""Thirteen real Nature consumers: physical decks, mana and held upgrades."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import (Buff, ChangeManaCrystals, Destroy, Draw, GainArmor,
    Heal, InvokeBehavior, RefreshMana, ShuffleIntoDeck)
from hs_sim.engine.mana_ranks import ManaRankFamily
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    HandDerivativeSpec, HandProgressSpec, HealingKind, IntrinsicCostSpec, Keyword,
    PlayerEffectSpec, SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword
from hs_sim.engine.spell_sequences import DrawMatchingWithCostReduction
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-nature-deck-resources-v1.json'
BATCH_HASH = '5756a23c513c56433d62dac871324757b991f033678d4dc3dc76de3e03f1997d'
POLICY = 'cn37-local-past-nature-deck-resources-v1'
PREFIX = 'cards.past_nature_deck.'
ROOTS = ('AT_044', 'BAR_536', 'BOT_404', 'BOT_444', 'BT_132', 'DAL_351',
    'DRG_318', 'GIL_553', 'GVG_031', 'KAR_075', 'LOOT_309', 'NX2_011', 'REV_336')
DEPENDENCIES = ('BAR_536t', 'BAR_536t2', 'DAL_351ts', 'GIL_553t', 'NX2_011t', 'REV_336t3', 'REV_336t4')
EXISTING = ('REV_336t2',)
EVIDENCE = ('BAR_536e', 'BAR_536te', 'BAR_536t2e', 'BOT_444e', 'BT_132e', 'DAL_351e')
RANK = ManaRankFamily(PREFIX + 'living_seed.ranks-v1', ('BAR_536', 'BAR_536t', 'BAR_536t2'))
PROGRAM = PREFIX + 'gloop'
POOL = 'constructed.cards'
MINIONS = PoolQuery(kinds=(CardType.MINION,), collectible=True)
SIX = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=6, max_cost=6)


def make_definition(raw):
    cid = raw['id']; fields = {}
    if raw['type'] == 'MINION':
        return CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'] or 0,
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw))
    if cid in ('AT_044', 'BT_132', 'GVG_031'):
        fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,),
            relation='enemy' if cid == 'GVG_031' else 'any')
    elif cid == 'KAR_075':
        fields['targeting'] = TargetSpec()
    if cid == 'BT_132':
        fields['intrinsic_costs'] = (IntrinsicCostSpec(set_to=0, condition='permanent_mana_at_least',
            history_profile_id='mana.permanent-crystals-v1', mana_crystals=7),)
    if cid == 'DAL_351':
        fields.update(keywords=(Keyword.TWINSPELL,),
            hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL, 'DAL_351ts'),))
    if cid in ('NX2_011', 'REV_336'):
        fields.update(keywords=(Keyword.INFUSE,), hand_progress=HandProgressSpec('infuse',
            raw['tags']['TAG_SCRIPT_DATA_NUM_1'],
            'NX2_011t' if cid == 'NX2_011' else 'REV_336t4'))
    elif cid in ('NX2_011t', 'REV_336t4'):
        fields['keywords'] = (Keyword.INFUSED,)
    return CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=PREFIX + cid, spell_school=SpellSchool.NATURE,
        metadata=metadata_from_record(raw), **fields)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            tuple(v['record']['id'] for v in d['cards']) != ROOTS or
            tuple(v['record']['id'] for v in d['dependencies']) != DEPENDENCIES or
            tuple(v['record']['id'] for v in d['existing_dependencies']) != EXISTING or
            tuple(v['record']['id'] for v in d['evidence_only']) != EVIDENCE or
            len(d['official_observations']) != 40 or len(d['complete_druid_Nature_inventory']) != 85 or
            not set(ROOTS) <= set(d['original_missing_native_ids']) or
            d['infuse_thresholds'] != {'NX2_011': 6, 'REV_336': 5} or
            any(d[k] for k in ('new_standard_roots', 'membership_uses_executable_coverage',
                'source_scope_bound', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Nature deck/resource consumers require their complete real records and source')
    for row in d['cards'] + d['dependencies'] + d['existing_dependencies'] + d['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Nature deck/resource source lost a complete original row')
    return d


def register_past_nature_deck_resources(registry):
    d = load_batch()
    old, = d['existing_dependencies']
    if (canonical_digest(asdict(registry.card('REV_336t2'))) != old['definition_sha256'] or
            canonical_digest(asdict(registry.pool_card('REV_336t2'))) != old['pool_card_sha256']):
        raise TargetValidationError('Nature deck consumers changed the existing named Treant')
    prepared = []
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Nature consumers cannot replace an existing identity: ' + cid)
        card = make_definition(raw)
        if canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Nature consumer differs from its complete reviewed definition')
        prepared.append(card)

    def summon(c, token, count):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(token),), cause) for _ in range(count))

    def ironbark(c):
        ref = BoardPresenceReference.capture(c.state, c.target_id)
        return (BuffCapturedMinion(ref, 1, 3, c.source_id), GrantCapturedKeyword(ref, Keyword.TAUNT, c.source_id))

    def dragon_mana(c):
        held = (c.state.entities[i] for i in c.state.players[c.player_id].hand)
        if any(has_any_tribe(registry, e, ('dragon',)) for e in held if e.kind == CardType.MINION):
            return (ChangeManaCrystals(c.player_id, 1),)
        return ()

    def team(c):
        return tuple(Buff(i, 1, 1, c.source_id) for i in minions(c, registry, c.player_id))

    bodies = {
        'AT_044': lambda c: (Destroy(c.target_id, c.source_id),
            GenerateFromPool(3-c.player_id, POOL, MINIONS, source_id=c.source_id)),
        'BOT_404': lambda c: tuple(DrawMatching(c.player_id,
            PoolQuery(kinds=(CardType.MINION,), min_cost=n, max_cost=n), 'skip',
            source_id=c.source_id, cost_basis='local') for n in (7, 8, 9, 10)),
        'BOT_444': lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),),
        'gloop': lambda c: (RefreshMana(c.player_id, 1),),
        'BT_132': ironbark,
        'DAL_351': team, 'DAL_351ts': team,
        'DRG_318': lambda c: (Draw(c.player_id, 1, c.source_id), InvokeBehavior(PREFIX+'dragon_mana', c.source_id, c.player_id)),
        'dragon_mana': dragon_mana,
        'GIL_553': lambda c: summon(c, 'GIL_553t', len(c.state.players[c.player_id].hand)),
        'GVG_031': lambda c: (ShuffleIntoDeck(c.target_id, 3-c.player_id),),
        'KAR_075': lambda c: (Heal(c.target_id, 6, c.source_id, HealingKind.SPELL),
            SummonFromPool(c.player_id, POOL, SIX, source_id=c.source_id, cause=SummonCause.capture(c))),
        'LOOT_309': lambda c: (GainArmor(c.player_id, 6), SummonFromZone(c.player_id,
            query=PoolQuery(kinds=(CardType.MINION,), max_cost=4), source_id=c.source_id,
            cause=SummonCause.capture(c), cost_basis='local')),
        'NX2_011': lambda c: (Draw(c.player_id, 3, c.source_id),),
        'NX2_011t': lambda c: (Draw(c.player_id, 3, c.source_id),),
        'REV_336': lambda c: summon(c, 'REV_336t2', 2),
        'REV_336t4': lambda c: summon(c, 'REV_336t3', 2),
    }
    for cid, reduction in zip(RANK.forms, (1, 2, 3)):
        bodies[cid] = lambda c, reduction=reduction: (DrawMatchingWithCostReduction(c.player_id,
            reduction, c.source_id, PoolQuery(kinds=(CardType.MINION,), tribes_any=('beast',))),)
    for key, body in bodies.items():
        registry.register_behavior(PREFIX+key, body)
    for card in prepared:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, 'BOT_444', kind='turn_trigger',
        triggers=(TriggerSpec('minion_died', PREFIX+'gloop'),)))
    registry.register_mana_rank_family(RANK)
