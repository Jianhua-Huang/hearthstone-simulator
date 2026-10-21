"""Amitut freezes original Holy deck cards and delegates their copies and shuffle."""
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SpellSchool, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BODY = 'BE_143', 'cards.amitut.battlecry'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/amitut-v1.json'
BATCH_HASH = '52f71b35e660c7d4bd2e478520d456f96bfbc4c576e44ce0e2c0ab4cd709b720'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Amitut lost its complete fixed root and primary faces')
    return data


def register_amitut_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
            raw['tags'].get('CLASS'), raw['tags'].get('RARITY'), raw['tags'].get('TAUNT'),
            raw['tags'].get('BATTLECRY')) != ('MINION', 7, 5, 8, True, 5, 5, 1, 1):
        raise TargetValidationError('Amitut requires the actual Paladin legendary 7-cost 5/8 Taunt Battlecry')
    def body(c):
        materials = tuple(CapturedCardCopyMaterial.capture(c.state, c.state.entities[i])
            for i in tuple(c.state.players[c.player_id].deck)
            if c.state.entities[i].kind == CardType.SPELL and
            registry.card(c.state.entities[i].card_id).spell_school == SpellSchool.HOLY)
        return shuffled(c, (CopyCard(material, c.player_id, Zone.DECK, mode='current',
            source_id=c.source_id, cast_when_drawn=True) for material in materials))
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=5, health=8,
        keywords=(Keyword.TAUNT,), battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
