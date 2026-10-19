"""One fixed target's newest printed edition advances original dormancy."""
import json
from pathlib import Path
from types import MappingProxyType

from hs_sim.engine.dormancy import AdvanceCapturedDormancy
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Keyword, TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_063'
BODY = 'cards.timelord_nozdormu.advance'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/time-lord-nozdormu-v1.json'
BATCH_HASH = '8b0e9d8f436b2cc315250db23d8b0c9e68f76955ebaa14c5c7a016a7b7f94632'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TIME_063e1', 'TIME_063e2') or
            len(data['printed_card_sets']) != data['source_record_count'] or data['source_record_count'] != 23452 or
            data['latest_expansion']['card_set_id'] != 1988):
        raise TargetValidationError('Timelord requires the full printed edition inventory and fixed target policy')
    for row in (*data['cards'], *data['evidence_only']):
        if (canonical_digest(row['record']) != row['record_sha256'] or
                data['printed_card_sets'][row['record']['id']] != row['record']['card_set_id']):
            raise TargetValidationError('Timelord source or actual printed edition changed')
    return data


def register_time_lord_nozdormu_card(registry):
    data = load_batch()
    editions = MappingProxyType(dict(data['printed_card_sets']))
    latest = data['latest_expansion']['card_set_id']
    def advance(c):
        if c.event is None or c.event.kind != 'card_played':
            raise ResolutionError('Timelord requires an original completed card-play event')
        row = play_record(c.state, dict(c.event.data).get('play_id'))
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Timelord lost its actual completed play')
        if row.player_id != c.player_id:
            return ()
        if row.card_id not in editions or editions[row.card_id] is None:
            raise UnsupportedDefinitionError('Unreviewed original played-card edition: ' + row.card_id)
        if editions[row.card_id] != latest or c.source.dormancy is None:
            return ()
        return (AdvanceCapturedDormancy(MinionReference.capture(c.source), c.source.dormancy.id,
                                         source_id=c.source_id),)
    registry.register_behavior(BODY, advance)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CLASS'], raw['tags']['CARDRACE']) != (
            'MINION', 3, 8, 8, 12, 24):
        raise TargetValidationError('Timelord lost its original neutral Dragon face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=8, health=8,
        keywords=(Keyword.RUSH,), dormant_turns=5, dormant_triggers=(TriggerSpec('card_played', BODY),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
