"""Kronn delegates each original minion's own attack damage to the shared core."""
import json
from pathlib import Path

from hs_sim.engine.minion_attack_damage import EachMinionDealsAttackDamage
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_732'
BODY='cards.kronn_impaler.damage'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/kronn-impaler-v1.json'
BATCH_HASH='7520431259288272da37a15f8469a0881a75a1015b275346a233f4dce21bce72'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(row['record']['id']for row in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in data['cards'])):
        raise TargetValidationError('Kronn lost its original complete reviewed face')
    return data


def register_kronn_impaler_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('CARDRACE'),raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'))!=('MINION',10,6,6,3,18,5,1):
        raise TargetValidationError('Kronn requires its original legendary Hunter Elemental 10-cost 6/6 battlecry')
    registry.register_behavior(BODY,lambda c:(EachMinionDealsAttackDamage(c.player_id,c.source_id),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=10,attack=6,health=6,battlecry=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
