"""Reviewed recruits, original drawn entities and finite historical cost consumers."""

from hs_sim.engine.deck_shuffles import shuffled
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeManaCrystals, Damage, Draw, GainArmor,
    Overload, RefreshMana, RevealHandCard, Summon, UnlockOverload)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CastWhenDrawnSpec,
    DamageKind, HandProgressSpec, IntrinsicCostSpec, Keyword, MinionDeathCostSpec,
    PlayerHeroPowerCountCostSpec, PlayerOverloadCostSpec, PlayerPlayedClassCostSpec,
    PlayerSpellCountCostSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .utility_cards import compile_body

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/recruit-effects-v1.json'
BATCH_HASH = '7f6349313362f50b57db1123c619129f1e351a6c8930184c0417d4745150dcea'
PREFIX = 'cards.recruits.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Recruit content differs from its reviewed source pin')
    return data


def successful_physical_draw(c):
    if c.event is None or c.event.kind != 'card_drawn':
        return False
    if (c.event.target_id, c.event.player_id) != (c.source_id, c.player_id):
        return False
    draw_id = dict(c.event.data).get('draw_id')
    if type(draw_id) is not int or not 1 <= draw_id <= len(c.state.draw_history):
        raise ResolutionError('Drawn minion requires its original physical draw fact')
    row = c.state.draw_history[draw_id - 1]
    if (row.entity_id, row.player_id, row.outcome) != (c.source_id, c.player_id, 'hand'):
        raise ResolutionError('Drawn minion disagrees with its original successful draw')
    return True


def drawn_minion(c, opponent=False):
    if not successful_physical_draw(c):
        raise ResolutionError('Drawn minion callback lost the original physical draw')
    return (RevealHandCard(c.source_id),
        SummonStoredCard(CardReference.capture(c.source), 3-c.player_id if opponent else c.player_id,
                         cause=SummonCause.capture(c)),
        Draw(c.player_id, source_id=c.source_id))


def shuffle(c, cid, count, opponent=False):
    owner=3-c.player_id if opponent else c.player_id
    return shuffled(c,(AddToDeck(owner,cid,source_id=c.source_id) for _ in range(count)),player_id=owner)


def recruit(c, zone=Zone.DECK, query=PoolQuery()):
    return SummonFromZone(c.player_id, zone=zone, query=query, source_id=c.source_id,
                          cause=SummonCause.capture(c))


def split_four(c):
    if c.cast is None or c.cast.source_id != c.source_id:
        raise ResolutionError('Arcane Tripwire requires its actual spell cast')
    return (RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 4),)


SCRIPTS = {
    'oak': lambda c: (GainArmor(c.state.players[c.player_id].hero_id, 6),
                       recruit(c, query=PoolQuery(max_cost=4))),
    'willow': lambda c: tuple(recruit(c, zone, PoolQuery(tribes_any=('demon',)))
                              for zone in (Zone.HAND, Zone.DECK)),
    'acorns': lambda c: shuffle(c, 'SW_439t', 4),
    'imps': lambda c: shuffle(c, 'CAP_400t2t', 2, True),
    'dragons': lambda c: shuffle(c, 'EDR_260t', 2),
    'equipment': lambda c: (GainArmor(c.state.players[c.player_id].hero_id, 2),
                             *shuffle(c, 'JAIL_386t', 5)),
    'plagues': lambda c: shuffle(c, 'JAIL_443t', 4),
    'tripwire': lambda c: (*split_four(c), *shuffle(c, 'JAIL_881t', 2)),
    'split_four': split_four,
    'draw_two': lambda c: (Draw(c.player_id, 2, c.source_id),),
    'empty_crystals': lambda c: tuple(ChangeManaCrystals(p, 1) for p in (1, 2)),
    'overload_three': lambda c: (Overload(c.player_id, 3),),
    'unlock': lambda c: (UnlockOverload(c.player_id),),
    'refresh_two': lambda c: (RefreshMana(c.player_id, 2),)
                             if c.event.player_id == c.player_id else (),
    'squirrel': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial('SW_439t2'),),
                                      SummonCause.capture(c)),),
    'armor_two': lambda c: (GainArmor(c.state.players[c.player_id].hero_id, 2),),
    'plague_damage': lambda c: (Damage(c.state.players[c.player_id].hero_id, 2,
                                      c.source_id, DamageKind.SPELL),),
}

COSTS = {
    'overload': ('player_overload_cost', PlayerOverloadCostSpec()),
    'hero_power': ('player_hero_power_count_cost', PlayerHeroPowerCountCostSpec()),
    'fel_spells': ('player_spell_count_cost', PlayerSpellCountCostSpec('cost.player-fel-spell-count-v1')),
    'deaths_this_turn': ('minion_death_cost', MinionDeathCostSpec('cost.minion-deaths-both-turn-v1')),
    'nonstarter': ('player_played_class_cost', PlayerPlayedClassCostSpec(
        None, 'cost.player-played-outside-starting-deck-v1')),
    'large_deck': ('intrinsic_costs', (IntrinsicCostSpec(delta=-2, condition='current_deck_count',
        history_profile_id='deck.current-count-v1', card_count=25, comparison='at_least'),)),
}


def register_recruit_cards(registry):
    for name, handler in SCRIPTS.items():
        registry.register_behavior(PREFIX+name, handler)
    registry.register_trigger_condition(PREFIX+'physical_draw', successful_physical_draw)
    for name, opponent in (('drawer', False), ('opponent', True)):
        registry.register_behavior(PREFIX+'draw_'+name,
            lambda c, opponent=opponent: drawn_minion(c, opponent))
    two_waves = compile_body(registry, [dict(operation='damage', scope='all_minions', amount=2)]*2,
                             True, set())
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256']:
            raise TargetValidationError('Recruit record changed')
        kind = CardType(raw['type'].lower())
        if kind not in (CardType.MINION, CardType.SPELL) or (
                recipe['root'] and raw['collectible'] is not True):
            raise TargetValidationError('Unreviewed recruit root or dependency type')
        if type(raw['cost']) is not int or raw['cost'] < 0:
            raise TargetValidationError('Recruit printed cost must be explicit')
        kwargs = {}
        for entry, script in recipe['bodies'].items():
            body = two_waves if script == 'two_waves' else PREFIX+script
            if script != 'two_waves' and script not in SCRIPTS:
                raise TargetValidationError('Unknown recruit body')
            if entry == 'own_power_used':
                kwargs['triggers'] = (TriggerSpec('hero_power_used', body),)
            elif entry in ('on_play', 'battlecry', 'deathrattle'):
                kwargs[entry] = body
            else:
                raise TargetValidationError('Unreviewed recruit body entry')
        if recipe['cost_profile'] is not None:
            if recipe['cost_profile'] not in COSTS:
                raise TargetValidationError('Unknown recruit cost profile')
            field, spec = COSTS[recipe['cost_profile']]
            kwargs[field] = spec
        if recipe['draw_summon'] is not None:
            if kind != CardType.MINION or recipe['draw_summon'] not in ('drawer', 'opponent'):
                raise TargetValidationError('Unreviewed drawn minion recipient')
            kwargs['hand_progress'] = HandProgressSpec('event', event='card_drawn',
                condition_id=PREFIX+'physical_draw', on_complete=PREFIX+'draw_'+recipe['draw_summon'], repeat=True)
        keywords = tuple(Keyword(k) for k in recipe['keywords'])
        if recipe['draw_cast']:
            if kind != CardType.SPELL or 'on_play' not in kwargs:
                raise TargetValidationError('Drawn spell needs its complete ordinary body')
            keywords += (Keyword.CASTS_WHEN_DRAWN,)
            kwargs['cast_when_drawn'] = CastWhenDrawnSpec()
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            keywords=keywords, disguised=recipe['disguised'], spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
