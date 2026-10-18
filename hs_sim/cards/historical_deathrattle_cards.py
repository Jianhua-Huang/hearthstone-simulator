"""Two real friendly death-history consumers share the native DR interpreter."""
import json
from pathlib import Path

from hs_sim.engine.historical_deathrattles import TriggerHistoricalDeathrattles
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SENTENCE, UMBRA = 'JAIL_940', 'TLC_106'
PREFIX = 'cards.historical_deathrattles.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/historical-deathrattle-native-v1.json'
BATCH_HASH = '6c3cd41c25ac67e484fb59f36795d08b876bc2754b91c422846e46cc8271e722'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (SENTENCE, UMBRA)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Historical Deathrattles require their complete native source')
    return data


def register_historical_deathrattle_cards(registry):
    registry.register_behavior(PREFIX + 'one', lambda c: (
        TriggerHistoricalDeathrattles(c.player_id, 1, c.source_id),))
    registry.register_behavior(PREFIX + 'five', lambda c: (
        TriggerHistoricalDeathrattles(c.player_id, 5, c.source_id),))
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        if cid == SENTENCE:
            if (raw['type'], raw['cost'], row['spell_school']) != ('SPELL', 1, 'shadow'):
                raise TargetValidationError('Undeath Sentence changed its original face')
            card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=1,
                spell_school=SpellSchool.SHADOW, on_play=PREFIX + 'one',
                metadata=metadata_from_record(raw))
        else:
            if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 7, 6, 6)
                    or raw['tags'].get('BATTLECRY') != 1):
                raise TargetValidationError('Endbringer Umbra changed its original face')
            card = CardDefinition(cid, raw['name'], CardType.MINION, cost=7, attack=6, health=6,
                battlecry=PREFIX + 'five', metadata=metadata_from_record(raw))
        registry.register_card(card)
        if cid == SENTENCE:
            registry.register_historical_deathrattle_spell(cid)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
