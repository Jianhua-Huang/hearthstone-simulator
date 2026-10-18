"""Costume Merchant's finite Mask domain and original Battlecry recipient."""
import json
from pathlib import Path

from hs_sim.engine.battlecry_weapon_outputs import GenerateBattlecryCard, combo_card
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Keyword
from hs_sim.engine.pools import GenerateFromCandidates, PoolCard, PoolQuery, matches_metadata
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'DINO_427'
MASKS = ('DINO_402', 'DINO_403', 'DINO_428', 'DINO_429', 'DINO_432')
PREFIX = 'cards.costume_merchant.'
QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='other', include_neutral=False)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/mask-battlecry-combo-v1.json'
BATCH_HASH = '954ee3eeb25b15f7bc7485b668f5d6f3cba032ebf672d5eba04e41140432ac9a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != MASKS):
        raise TargetValidationError('Costume Merchant requires its complete reviewed Mask domain')
    for row in data['cards'] + data['existing_dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Mask source')
    return data


def register_mask_battlecry_combo_card(registry):
    raw = load_batch()['cards'][0]['record']

    def battlecry(c):
        if c.battlecry is None:
            raise ValueError('Costume Merchant requires its actual Battlecry')
        current_class = c.state.players[c.player_id].hero_class
        candidates = []
        # This finite content list comes from both official parent faces, not
        # from the executable subset, a name search, or the open format pool.
        for cid in MASKS:
            row = registry.pool_card(cid)
            if matches_metadata(QUERY, card_id=cid, kind=row.kind, cost=row.cost,
                    meta=row.metadata, spell_school=row.spell_school, keywords=row.keywords,
                    current_class=current_class):
                candidates.append(cid)
        return (GenerateBattlecryCard(c.battlecry.id,
            GenerateFromCandidates(c.player_id, tuple(candidates), c.source_id)),)

    def combo(c):
        card = combo_card(c, registry, kind=CardType.SPELL)
        return () if card is None else (BuffStoredCard(card, cost=CostSpec(delta=-2), source_id=c.source_id),)

    registry.register_behavior(PREFIX + 'battlecry', battlecry)
    registry.register_behavior(PREFIX + 'combo', combo)
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.COMBO,),
        battlecry=PREFIX + 'battlecry', combo=PREFIX + 'combo', metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
