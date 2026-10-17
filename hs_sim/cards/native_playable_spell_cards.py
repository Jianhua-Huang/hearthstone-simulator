"""Actual Frantic Forger uses complete shared playable Temporary generation."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.playable_spell_generation import GeneratePlayableTemporarySpell
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-playable-spell-v1.json'
BATCH_HASH = '534490bd84835b4b69602e98167d6b878f99e3cc33ec2d48455199605f593bc7'
FORGER = 'JAIL_986'
POOL_ID = 'constructed.cards'
BODY = 'cards.native_playable_spell.forger'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (FORGER,):
        raise TargetValidationError('Frantic Forger complete original source changed')
    row, = data['cards']
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Frantic Forger original row changed')
    return data


def register_native_playable_spell_cards(registry):
    data = load_batch(); row, = data['cards']; raw = row['record']
    if (raw['cost'], raw['attack'], raw['health'], raw['type']) != (2, 2, 2, 'MINION'):
        raise TargetValidationError('Unreviewed Frantic Forger physical face')
    registry.register_behavior(BODY, lambda c: (GeneratePlayableTemporarySpell(c.player_id, c.source_id, POOL_ID),))
    card = CardDefinition(FORGER, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], metadata=metadata_from_record(raw), battlecry=BODY)
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
