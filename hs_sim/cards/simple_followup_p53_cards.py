"""Reviewed printed zeros, native blood-priced gifts and immune spell split."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import Buff
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    CostSpec, EndTurnSpec, Keyword, PaymentType, SpellSchool, TriggerSpec)
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p53-v1.json'
BATCH_HASH = '609c91aa5ce04f3e4f2fd51a87fd144328835f415de80d844dd093a30ace76fe'
STONE = 'TLC_467'
BARRAGE = 'TIME_027'
INGREDIENT = 'JAIL_201'
LEGS = ('CATA_139t', 'CATA_139t2', 'CATA_139t3', 'CATA_139t4')
CREATION = 'CATA_470t1'
SHADE = 'TIME_610t2'
ATTACK = 'JAIL_201a'
DRUID = 'JAIL_201b'
SHRED = 'TIME_025t'
ROOTS = (STONE, BARRAGE, INGREDIENT, *LEGS, CREATION, SHADE)
DEPENDENCIES = (ATTACK, DRUID)
PARENTS = ('CATA_139', 'CATA_470', 'TIME_610')
PREFIX = 'cards.simple_followup_p53.'
POOL_ID = 'constructed.cards'
FEL_QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, spell_schools=(SpellSchool.FEL,))
DRUID_QUERY = PoolQuery(collectible=True, class_mode='specified', classes=(CardClass.DRUID,), include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (SHRED,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != PARENTS or
            tuple(data['choice_only_ids']) != DEPENDENCIES or data['skipped']):
        raise TargetValidationError('P53 complete reviewed zero/child/choice scope changed')
    for section in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P53 complete original source row changed')
    return data


def printed_number(data, raw, field):
    value = raw[field]
    if type(value) is int:
        return value
    declared = data['numeric_normalizations'].get(raw['id'], {})
    tag = {'cost': 'COST', 'attack': 'ATK'}.get(field)
    if (value is None and field in declared and type(declared[field]) is int and declared[field] == 0
            and tag is not None and tag not in raw['tags'] and (field != 'attack' or raw['type'] == 'MINION')):
        return 0
    raise TargetValidationError('P53 has no explicit reviewed printed numeric value: ' + raw['id'] + ':' + field)


def register_simple_followup_p53_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P53 exact existing Shred definition changed')
    raws = {row['record']['id']: row['record'] for section in ('cards', 'dependencies') for row in data[section]}

    def stone(c):
        return (GenerateFromPool(c.player_id, POOL_ID, FEL_QUERY, count=2, source_id=c.source_id,
            cost=CostSpec(payment=PaymentType.HEALTH, card_types=(CardType.SPELL,))),)

    def barrage(c):
        if raws[BARRAGE]['tags'].get('349') != 1 or c.cast is None:
            raise TargetValidationError('Barrage requires its original actual immune SPELL cast')
        return (RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 6,
            spell_bonus_multiplier=0, on_complete=PREFIX + 'shuffle'),)

    def shuffle(c):
        return shuffled(c, tuple(AddToDeck(c.player_id, SHRED, source_id=c.source_id) for _ in range(2)))

    def attack(c):
        return (Buff(c.state.players[c.player_id].hero_id, attack=2, source_id=c.source_id,
                     expires_turn=c.state.turn),)

    def druid(c):
        return (GenerateFromPool(c.player_id, POOL_ID, DRUID_QUERY, source_id=c.source_id),)

    def leg(c):
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),)

    bodies = {'stone': stone, 'barrage': barrage, 'shuffle': shuffle, ATTACK: attack, DRUID: druid,
              'both': lambda c: (*attack(c), *druid(c)), 'leg': leg}
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards'] + data['dependencies']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        choice = cid in DEPENDENCIES
        kwargs = {}
        if cid == STONE:
            kwargs.update(keywords=(Keyword.TAUNT,), deathrattle=PREFIX + 'stone')
        if cid == BARRAGE:
            kwargs['on_play'] = PREFIX + 'barrage'
        if cid == INGREDIENT:
            kwargs['choose_one'] = ChooseOneSpec(tuple(ChooseBranch(i, raws[i]['name'], PREFIX + i)
                for i in DEPENDENCIES), ChooseBranch(INGREDIENT + ':combined', '兼得', PREFIX + 'both'))
        if cid in LEGS:
            kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX + 'leg', EndTurnSpec()),)
        card = CardDefinition(cid, raw['name'], kind, cost=printed_number(data, raw, 'cost'),
            attack=printed_number(data, raw, 'attack') if kind == CardType.MINION else 0,
            health=printed_number(data, raw, 'health') if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), choice_only=choice, **kwargs)
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
