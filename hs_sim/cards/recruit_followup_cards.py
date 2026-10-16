"""Real physical recruit beneficiaries and ordinary Kindred cost consumers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage, Draw, GainArmor, GrantDeathrattle, GrantKeyword
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HandActionSpec,
    IntrinsicCostSpec, Keyword, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/recruit-followup-effects-v1.json'
BATCH_HASH = 'ff8733c4488c4525af3a7af95c6d6a7f46440fd419e13a00acc1ef89c14c696f'
PREFIX = 'cards.recruit_followups.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Recruit followup content differs from its reviewed source pin')
    return data


def recruit(c, query, callback, count=1):
    return (SummonFromZone(c.player_id, count=count, query=query, source_id=c.source_id,
        cause=SummonCause.capture(c), on_summon=PREFIX+callback),)


def granted(c, keyword):
    return (GrantKeyword(c.target_id, keyword, c.source_id),)


SCRIPTS = {
    'recruit_rush': lambda c: recruit(c, PoolQuery(max_cost=2), 'rush', 2),
    'recruit_lifesteal': lambda c: recruit(c, PoolQuery(tribes_any=('beast',)), 'lifesteal'),
    'recruit_morag': lambda c: recruit(c, PoolQuery(tribes_any=('demon',)), 'morag_death'),
    'rush': lambda c: granted(c, Keyword.RUSH),
    'lifesteal': lambda c: granted(c, Keyword.LIFESTEAL),
    'morag_death': lambda c: (GrantDeathrattle(c.target_id, PREFIX+'morag_return', c.source_id),),
    'morag_return': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial('JAIL_906'),),
        SummonCause.capture(c)),),
    'duel': lambda c: (SummonFromZone(c.player_id, source_id=c.source_id, cause=SummonCause.capture(c)),
        SummonByCard(3-c.player_id, (SummonEntryMaterial('TIME_870t'),), SummonCause.capture(c))),
    'whelp': lambda c: (Damage(c.target_id, 5, c.source_id, DamageKind.EFFECT),
        GainArmor(c.state.players[c.player_id].hero_id, 5)),
    'draw_two': lambda c: (Draw(c.player_id, 2, c.source_id),),
}


def register_recruit_followup_cards(registry):
    for name, callback in SCRIPTS.items():
        registry.register_behavior(PREFIX+name, callback)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256']:
            raise TargetValidationError('Recruit followup record changed')
        kind = CardType(raw['type'].lower())
        if kind not in (CardType.MINION, CardType.SPELL) or (recipe['root'] and raw['collectible'] is not True):
            raise TargetValidationError('Unreviewed followup card type or root')
        if type(raw['cost']) is not int or raw['cost'] < 0:
            raise TargetValidationError('Followup cost must be explicit')
        kwargs = {}
        for entry, name in recipe['bodies'].items():
            if entry not in ('battlecry', 'deathrattle', 'on_play') or name not in SCRIPTS:
                raise TargetValidationError('Unknown recruit followup body')
            kwargs[entry] = PREFIX+name
        if recipe['kindred']:
            if raw['tags'].get('KINDRED') != 1:
                raise TargetValidationError('Unreviewed Kindred declaration')
            kwargs['intrinsic_costs'] = (IntrinsicCostSpec(delta=-2),)
        if recipe['prepare']:
            if raw['tags'].get('PREPARE') != 1:
                raise TargetValidationError('Unreviewed Prepare declaration')
            kwargs['hand_actions'] = (HandActionSpec('prepare', 'prepare', 1),)
        if recipe['target'] is not None:
            if recipe['target'] != 'character':
                raise TargetValidationError('Unreviewed followup target')
            kwargs['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.HERO, Zone.BOARD), kinds=(CardType.HERO, CardType.MINION))
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            keywords=tuple(Keyword(k) for k in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
