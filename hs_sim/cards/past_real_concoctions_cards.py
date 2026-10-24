"""Concoctor and the twenty actual client Concoctions, using declared hand recipes."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Draw, InvokeBehavior
from hs_sim.engine.hand_combinations import HandCombinationProfile
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, CostSpec, TargetSpec, Zone
from hs_sim.engine.pools import GenerateFromCandidates, GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.spell_targets import ApplySpellTarget, DamageResidentSpellTarget, RandomDestroyEnemySpellGroup
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'RLK_568'
SINGLES = tuple('RLK_570t'+str(i) for i in range(1, 6))
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_real_concoctions.'
MIXTURE_VERSION = 'hand-spell-mixture-v1'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-real-concoctions-v1.json'
BATCH_HASH = '59a6f8d82340df3daf91ccc8889120cb6ddcf6319b32401f1b5abefa93d5b527'
THREE_COST = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=3, max_cost=3)
OTHER_CLASS = PoolQuery(collectible=True, class_mode='other', include_neutral=False)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['collectible_leaf_ids'] != [ROOT] or len(d['dependencies']) != 21 or
            len({x['record']['id'] for x in d['dependencies']}) != 21 or
            any(d[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['dependencies'])):
        raise TargetValidationError('Real Concoctions require all original rows, actual recipes and complete source pins')
    return d


def register_past_real_concoctions_cards(registry):
    rows = {x['record']['id']: x for x in load_batch()['dependencies']}
    plans = {cid: row['recipe'] for cid, row in rows.items() if cid != ROOT}

    def cast(c):
        record = active_cast(c.state, c.source_id, c.player_id)
        if (record is None or not record.payload_started or record.failure is not None or
                record.card_id not in plans or record.target_id != c.target_id):
            raise UnsupportedDefinitionError('A Concoction component requires its actual original physical CAST')
        return record

    def damage(c, count):
        cast(c)
        target = c.state.entities.get(c.target_id)
        if target is None:
            return ()
        if target.kind == CardType.MINION and target.zone == Zone.BOARD:
            request = DamageResidentSpellTarget(BoardPresenceReference.capture(c.state, target.id), c.source_id, 3)
        elif target.kind == CardType.HERO:
            request = ApplySpellTarget(target.id, c.source_id, 'damage', 3)
        else:
            return ()
        return (request,)*count

    def summon(c, count):
        record = cast(c)
        cause = SummonCause.capture(replace(c, cast=record))
        if count == 1:
            return (SummonFromPool(c.player_id, 'constructed.minions', THREE_COST, c.source_id, cause=cause),)
        return (GenerateFromPool(c.player_id, 'constructed.minions', THREE_COST, count=count,
            source_id=c.source_id, destination='board', cause=cause),)

    def destroy(c, count):
        record = cast(c)
        return (RandomDestroyEnemySpellGroup(c.player_id, record.id, c.source_id, count),)

    def generate(c, count):
        cast(c)
        return (GenerateFromPool(c.player_id, 'constructed.cards', OTHER_CLASS, count=count,
            source_id=c.source_id, cost=CostSpec(delta=-3)),)

    def draw(c, count):
        cast(c)
        return (Draw(c.player_id, count, c.source_id),)

    handlers = dict(damage=damage, summon=summon, destroy=destroy, generate=generate, draw=draw)
    steps = {tuple(step) for plan in plans.values() for step in plan['steps']}
    for kind, count in sorted(steps):
        if kind not in handlers or type(count) is not int or count not in (1, 2, 4):
            raise TargetValidationError('Unreviewed Concoction body step')
        registry.register_behavior(PREFIX+kind+str(count),
            lambda c, kind=kind, count=count: handlers[kind](c, count))
    registry.register_behavior(PREFIX+'random', lambda c: (GenerateFromCandidates(c.player_id, SINGLES, c.source_id),))
    for cid, plan in plans.items():
        registry.register_behavior(PREFIX+cid, lambda c, plan=plan: tuple(
            InvokeBehavior(PREFIX+kind+str(count), c.source_id, c.player_id, c.target_id)
            for kind, count in plan['steps']))
    for cid, item in rows.items():
        raw = item['record']
        if cid == ROOT:
            if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 1, 1, 2, 1):
                raise TargetValidationError('Concoctor lost its complete real 1/1/2 Battlecry face')
            kwargs = dict(attack=1, health=2, battlecry=PREFIX+'random')
        else:
            if raw['type'] != 'SPELL' or raw['cost'] != 3 or raw['tags'].get('2500') != 1:
                raise TargetValidationError('A real Concoction needs its original three-cost spell family')
            kwargs = dict(on_play=PREFIX+cid)
            if any(kind == 'damage' for kind, count in plans[cid]['steps']):
                kwargs['targeting'] = TargetSpec()
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), cost=raw['cost'],
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    pairs = set()
    for cid, plan in plans.items():
        if cid in SINGLES:
            if plan['parts'] != [cid]: raise TargetValidationError('Single Concoction lost its original identity')
            continue
        left, right = plan['parts']
        if left not in SINGLES or right not in SINGLES:
            raise TargetValidationError('Mixed Concoction borrowed an unreviewed ingredient')
        pair = tuple(sorted((left, right)))
        if pair in pairs: raise TargetValidationError('Two actual faces claim the same Concoction recipe')
        pairs.add(pair)
        registry.register_hand_combination(HandCombinationProfile(cid, left, right, MIXTURE_VERSION))
    if len(pairs) != 15:
        raise TargetValidationError('The complete actual Concoction mixture family is required')
