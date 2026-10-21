"""Therazane's independent original next-spell budget for each actual school."""
import json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, RecipientMetadataFilter,
    RepeatMatchSpec, SpellRepeatSpec, SpellSchool)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_337'
BEHAVIOR = 'cards.therazane.next_schools'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/therazane-v1.json'
BATCH_HASH = 'ba1a7323e05d1d490dba2a07a6003fb00dc86e27db8b5e85c04baeef8f8cf951'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['cards'])):
        raise TargetValidationError('Therazane lost her complete original root and primary faces')
    return d


def register_therazane_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],
            raw['tags'].get('CLASS'),raw['tags'].get('CARDRACE'),raw['tags'].get('RARITY'),
            raw['tags'].get('BATTLECRY')) != ('MINION',6,5,5,True,8,18,5,1):
        raise TargetValidationError('Therazane requires her real six-cost 5/5 Shaman Elemental battlecry')
    def battlecry(c):
        return tuple(AddSpellRepeatModifier(c.player_id,
            SpellRepeatSpec(2,'any',RepeatMatchSpec(
                recipient_metadata=RecipientMetadataFilter(spell_schools=(school,)))),
            source_id=c.source_id, uses=1, automatic=True) for school in SpellSchool)
    registry.register_behavior(BEHAVIOR, battlecry)
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=6,attack=5,health=5,
        battlecry=BEHAVIOR,metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
