"""Hiking Trail uses original submitted types and the existing physical Map followup."""
import json
from pathlib import Path

from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.minion_type_history import played_minion_type_facts
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import RACES, metadata_from_record, validate_race_pin

CARD, BODY, POOL = 'TLC_464', 'cards.hiking_trail.body', 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-hiking-trail-v1.json'
BATCH_HASH = '4b57181f8c461f24a59ef7a340cd98670ab02188c8b106ba27e7c8ff3629b6f1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Hiking Trail lost its complete fixed source')
    validate_race_pin()
    if (tuple(data['types']) != tuple(sorted(set(RACES.values()) - {'all'})) or
            data['race_source']['mapping'] != {str(k):v for k,v in RACES.items()}):
        raise TargetValidationError('Hiking Trail lost its complete reviewed type universe')
    return data


def register_native_hiking_trail_cards(registry):
    data = load_batch(); types = tuple(data['types'])
    def body(c):
        facts = played_minion_type_facts(c.state, c.player_id, completed=None)
        unknown = {t for _, value in facts for t in (*value.members, *value.excluded)} - set(types) - {'all'}
        if unknown: raise UnsupportedDefinitionError('Hiking Trail has an unreviewed submitted minion type')
        remaining = tuple(t for t in types if not any(value.matches_any((t,)) for _, value in facts))
        if not remaining: return ()
        return (DiscoverForPlayFollowup(DiscoverFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', tribes_any=remaining),
            source_id=c.source_id)),)
    registry.register_behavior(BODY, body)
    raw = data['cards'][0]['record']
    registry.register_card(CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=BODY, metadata=metadata_from_record(raw)))
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(registry.card(CARD)))
