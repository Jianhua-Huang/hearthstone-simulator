"""Actual Astral Balance creates its two original named spells with local bonuses."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Damage, Draw
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, SpellSchool, TargetMode, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/created-spell-bonus-v1.json'
BATCH_HASH = '7f325904df631e8f1557b4647357896951c0bdb98806e242504d271cc352e930'
BALANCE = 'EDR_874'
MOONFIRE = 'CS2_008'
STARFIRE = 'EX1_173'
PREFIX = 'cards.created_spell_bonus.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Created spell bonus source pin changed')
    if (tuple(row['record']['id'] for row in data['cards']) != (BALANCE,) or
            tuple(row['record']['id'] for row in data['dependencies']) != (MOONFIRE, STARFIRE) or data['evidence_only']):
        raise TargetValidationError('Unreviewed named created spell family')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Created spell bonus complete source row changed')
    links = [x['face'].get('childIds') for x in data['official_observations'] if x['face']['id'] == 116980]
    if links != [[467, 823], [467, 823]]:
        raise TargetValidationError('Astral Balance lost its exact original named spell identities')
    return data


def register_created_spell_bonus_cards(registry):
    registry.register_behavior(PREFIX+'balance', lambda c: tuple(
        AddToHand(c.player_id, cid, c.source_id, spell_damage=1) for cid in (MOONFIRE, STARFIRE)))
    registry.register_behavior(PREFIX+'moonfire', lambda c: (Damage(c.target_id, 1, c.source_id, DamageKind.SPELL),))
    registry.register_behavior(PREFIX+'starfire', lambda c: (
        Damage(c.target_id, 5, c.source_id, DamageKind.SPELL), Draw(c.player_id, 1, c.source_id)))
    data = load_batch()
    for row in data['cards']+data['dependencies']:
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1 or not raw['collectible']:
            raise TargetValidationError('Named created spell lost its complete Arcane face')
        target = TargetSpec(TargetMode.REQUIRED) if cid != BALANCE else None
        script = {BALANCE:'balance', MOONFIRE:'moonfire', STARFIRE:'starfire'}[cid]
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'] or 0,
            on_play=PREFIX+script, targeting=target, spell_school=SpellSchool.ARCANE,
            metadata=replace(metadata_from_record(raw), deck_identity=cid))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
