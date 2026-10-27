"""Real Arcane consumers of selected original physical deck-card rewards."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-deck-rewards-v1.json'
BATCH_HASH = '2c361a6d98a3b172ff9e348dbf6fe4f266ee4e8aa347a3fd8d2c09c7614d7a35'
LEAVES = ('RLK_817', 'TOY_851')
DEPENDENCIES = LEAVES
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_deck_rewards.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(row['record']['id']for row in data['dependencies']) != LEAVES or
            len(data['official_observations']) != 4 or not set(LEAVES) <= set(reference['candidate_ids']) or
            any(data[k]for k in ('cards', 'existing_dependencies', 'evidence_only', 'skipped', 'numeric_normalizations',
                'display_normalizations', 'source_scope_bound', 'formal_pool_complete', 'cn_calibrated')) or
            any(canonical_digest(row['record']) != row['record_sha256']for row in data['dependencies'])):
        raise TargetValidationError('Original Arcane deck rewards changed their full pinned source')
    return data


def register_past_arcane_deck_rewards(registry):
    prepared = []
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Original Arcane deck reward cannot overwrite '+cid)
        if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1:
            raise TargetValidationError('Original Arcane deck reward changed its printed spell')
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], spell_school=SpellSchool.ARCANE,
            on_play=PREFIX+cid, metadata=metadata_from_record(raw))
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Original Arcane deck reward differs from printed metadata: '+cid)
        prepared.append(card)
    for cid, reward in (('RLK_817', 'arcane_spell_damage'), ('TOY_851', 'copy_with_spell_damage')):
        def body(c, reward=reward):
            query = PoolQuery(kinds=(CardType.SPELL,)) if reward == 'arcane_spell_damage' else PoolQuery()
            return (ChooseFromZone(c.player_id, c.player_id, Zone.DECK, query,
                operation='take', distinct='entity', source_id=c.source_id, discovery=True, selected_reward=reward),)
        registry.register_behavior(PREFIX+cid, body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
