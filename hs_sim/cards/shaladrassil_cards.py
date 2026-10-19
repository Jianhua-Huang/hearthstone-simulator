"""Shaladrassil's five actual Dreams use a frozen held condition and order."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, ChoiceOption, RequestChoice
from hs_sim.engine.held_higher_cost import satisfied
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .fixed_dream_source import DREAMS
from .metadata import metadata_from_record

ROOT = 'EDR_846'
CORRUPTED = tuple('EDR_846t'+str(i) for i in range(1, 6))
PREFIX = 'cards.shaladrassil.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/shaladrassil-v1.json'
BATCH_HASH = '94aad3c852321694c060caa83c47a25a07d7cf21197162006e8edabe4fe19d29'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            data['dependencies'] or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != DREAMS+CORRUPTED or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('EDR_846t1e', 'EDR_846t3e', 'EDR_846te2')):
        raise TargetValidationError('Shaladrassil requires its complete real Dream inventory')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Incomplete original Shaladrassil source row')
    return data


def register_shaladrassil_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Shaladrassil changed an existing complete Dream definition')

    def dreams(c):
        cards = CORRUPTED if satisfied(c) else DREAMS
        return (RequestChoice(c.player_id, tuple(ChoiceOption(cid, registry.card(cid).name,
            card_id=cid) for cid in cards), c.source_id, min_count=0, max_count=0,
            sample_size=5, on_select=PREFIX+'ordered'),)

    def ordered(c):
        result = c.choice
        if result is None or result.selected_ids:
            raise ValueError('Dream creation requires its original complete automatic permutation')
        choice = result.choice
        ids = tuple(x.card_id for x in choice.options)
        if ((choice.min_count, choice.max_count) != (0, 0) or len(ids) != 5 or
                set(ids) not in (set(DREAMS), set(CORRUPTED)) or
                any(x.id != x.card_id for x in choice.options)):
            raise ValueError('Dream creation lost or mixed its original five-card set')
        return tuple(AddToHand(c.player_id, cid, c.source_id) for cid in ids)

    registry.register_behavior(PREFIX+'dreams', dreams)
    registry.register_behavior(PREFIX+'ordered', ordered)
    raw = data['cards'][0]['record']
    card = CardDefinition(ROOT, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=PREFIX+'dreams', spell_school=SpellSchool.NATURE,
        hand_progress=HandProgressSpec('higher_cost_play'),
        metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
