"""Mechacycle consumes the ordinary original printed-mana summon chain."""
import json
from pathlib import Path

from hs_sim.engine.mana_worth_summons import SummonManaWorth
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

CARD, BODY = 'BE_900', 'cards.mechacycle.deathrattle'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/mechacycle-v1.json'
BATCH_HASH = 'd267a3eebb9e38acd3df385580e8593939f2ff3383aca41dabc60967fdd64004'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Mechacycle lost its complete source and primary faces')
    return data


def register_mechacycle_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
            raw['tags'].get('CLASS'), raw['tags'].get('RARITY'), raw['tags'].get('TAUNT'),
            raw['tags'].get('DEATHRATTLE'), raw['tags'].get('CARDRACE')) != ('MINION', 4, 3, 3, True, 3, 1, 1, 1, 17):
        raise TargetValidationError('Mechacycle requires the actual Hunter common 4-cost 3/3 Taunt Mech')
    registry.register_behavior(BODY, lambda c: (SummonManaWorth(c.player_id, 'constructed.cards', 4,
        SummonCause.capture(c), tribe='mech', position=deathrattle_position(c)),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=3, health=3,
        keywords=(Keyword.TAUNT,), deathrattle=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
