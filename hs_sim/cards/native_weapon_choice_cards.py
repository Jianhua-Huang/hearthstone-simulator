"""Actual EDR_525 uses native hand branches and ordinary weapon attachments."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch, GrantDeathrattle, GrantKeyword
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-weapon-choice-v1.json'
BATCH_HASH = '85ca4060ed212b3e8bc30d8d8c732b6449de6ee556af6fadcef95541182eb67c'
THORN = 'EDR_525'
POISON = 'EDR_525A'
SPIKES = 'EDR_525B'
CHOICE_ONLY = (POISON, SPIKES)
PREFIX = 'cards.native_weapon_choice.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native weapon choice lost its complete source pin')
    if (tuple(row['record']['id'] for row in data['cards']) != (THORN,) or
            tuple(row['record']['id'] for row in data['dependencies']) != CHOICE_ONLY or
            tuple(data['choice_only_ids']) != CHOICE_ONLY or data['evidence_only']):
        raise TargetValidationError('Unreviewed native weapon choice family')
    for row in data['cards'] + data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native weapon choice full source record changed')
    return data


def register_native_weapon_choice_cards(registry):
    data = load_batch()
    raws = {row['record']['id']: row['record'] for row in data['cards'] + data['dependencies']}

    def poison(c):
        return (GrantKeyword(c.source_id, Keyword.POISONOUS, c.source_id, c.state.turn),)

    def spikes(c):
        return (GrantDeathrattle(c.source_id, PREFIX+'damage', c.source_id),)

    def damage(c):
        enemy = c.state.players[3-c.player_id]
        targets = (enemy.hero_id, *enemy.board)
        return (DamageBatch(tuple(Damage(i, 2, c.source_id) for i in targets
            if c.state.entities[i].is_character and c.state.entities[i].active and
            c.state.entities[i].health > 0 and not c.state.entities[i].doomed)),)

    for name, body in (('poison', poison), ('spikes', spikes), ('damage', damage),
                       ('both', lambda c: (*poison(c), *spikes(c)))):
        registry.register_behavior(PREFIX+name, body)
    for cid, raw in raws.items():
        choice = cid in CHOICE_ONLY
        if raw['type'] != ('SPELL' if choice else 'WEAPON') or raw['collectible'] != (not choice):
            raise TargetValidationError('Native weapon choice changed actual card kind')
        spec = None if choice else ChooseOneSpec(
            (ChooseBranch(POISON, raws[POISON]['name'], PREFIX+'poison'),
             ChooseBranch(SPIKES, raws[SPIKES]['name'], PREFIX+'spikes')),
            ChooseBranch(THORN+':combined', '兼得', PREFIX+'both'))
        card = CardDefinition(cid, raw['name'], CardType.SPELL if choice else CardType.WEAPON,
            cost=0 if choice else raw['cost'], attack=raw['attack'] or 0,
            durability=0 if choice else raw['health'], choice_only=choice, choose_one=spec,
            metadata=replace(metadata_from_record(raw), deck_identity=cid))
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
