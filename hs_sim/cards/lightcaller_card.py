"""The original Lightcaller weapon uses two ordinary Lifesteal restorations."""
import json
from pathlib import Path

from hs_sim.engine.lifesteal_recipients import LifestealRecipientProfile
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_000'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/lightcaller-v1.json'
BATCH_HASH = '02810566a6409c3c1d4c3bd2127aae79ba72070ba7e7d75eb08610bcdfee629c'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['cards'])):
        raise TargetValidationError('Lightcaller lost its complete original root and primary faces')
    return d


def register_lightcaller_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],
            raw['tags'].get('CLASS'),raw['tags'].get('RARITY'),raw['tags'].get('LIFESTEAL')) != ('WEAPON',3,4,2,True,5,1,1):
        raise TargetValidationError('Lightcaller requires its real three-cost 4/2 Paladin Lifesteal weapon')
    card = CardDefinition(CARD,raw['name'],CardType.WEAPON,cost=3,attack=4,durability=2,
        keywords=(Keyword.LIFESTEAL,),metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_lifesteal_recipient_profile(LifestealRecipientProfile(CARD))
