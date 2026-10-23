"""Astral Vigilant consumes the original played-minion base recipe."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

VIGILANT = 'GDB_461'
LEAVES = DEPENDENCIES = (VIGILANT,)
COLLECTIBLE_ROOTS = ()
BEHAVIOR = 'cards.past_played_draenei_copy.'+VIGILANT
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-played-draenei-copy-v1.json'
BATCH_HASH = 'a698569220b59b93d8d74dad201dd6e886556c814ea6606da2e72749d5d0ec6e'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(x['record']['id'] for x in data['dependencies']) != LEAVES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                                 'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Played Draenei copy lost its complete original source')
    return data


def register_past_played_draenei_copy_card(registry):
    data = load_batch(); raw = data['dependencies'][0]['record']
    if (raw['id'], raw['type'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('BATTLECRY'), raw['tags'].get('CARDRACE')) != (VIGILANT, 'MINION', 1, 1, 2, 1, None):
        raise TargetValidationError('Astral Vigilant lost its native non-Draenei battlecry face')
    def body(c):
        rows = played_cards(c.state, c.player_id, kind=CardType.MINION,
            registry=registry, tribes_any=('draenei',))
        return () if not rows else (CopyCard(rows[-1].minion_copy_material,
            c.player_id, mode='base', source_id=c.source_id),)
    registry.register_behavior(BEHAVIOR, body)
    card = CardDefinition(VIGILANT, raw['name'], CardType.MINION, cost=1, attack=1, health=2,
        battlecry=BEHAVIOR, metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
