"""Proto-Pandaren consumes one original successful hand-acquisition fact."""
import json
from pathlib import Path

from hs_sim.engine.hand_history import EVENT, from_event
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_997'
BODY = 'cards.hand_entry_spell_provider.give'
POOL = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/hand-entry-spell-provider-v1.json'
BATCH_HASH = '0c787f6984a259c6b1b63f73938edce9ccf4c117f361eeb8eb1a03ba8d988cf3'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped'))):
        raise TargetValidationError('Proto-Pandaren lost its complete original source face')
    return data


def register_hand_entry_spell_provider_card(registry):
    row = load_batch()['cards'][0]; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS')) != ('MINION', 2, 3, 2, 12)):
        raise TargetValidationError('Proto-Pandaren requires its actual neutral two-cost 3/2 face')
    def body(c):
        entry = from_event(c.state, c.event)
        if c.state.entities[c.source_id].controller != c.player_id:
            raise ValueError('Proto-Pandaren requires its original captured observer controller')
        if entry.player_id != c.player_id or entry.source_id == c.source_id:
            return ()
        return tuple(GenerateFromPool(pid, POOL, QUERY, source_id=c.source_id)
            for pid in (c.player_id, 3-c.player_id))
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=2, attack=3, health=2,
        triggers=(TriggerSpec(EVENT, BODY),), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
