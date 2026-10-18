"""Flashback keeps the original Combo bonus on each selected pool entry."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-past-entry-grant-v1.json'
BATCH_HASH = '942c3c0839b67552417afb500a352d804209e7c64db265cf631421e35bb73803'
FLASHBACK = 'TIME_711'
PREFIX = 'cards.native_past_entry_grant.'
POOL_ID = 'constructed.past.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=1, max_cost=1)
ENTRY_POLICY = 'original-combo-relative-attack-before-pool-entry-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['entry_policy'] != ENTRY_POLICY or
            tuple(x['record']['id'] for x in data['cards']) != (FLASHBACK,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Flashback requires its complete reviewed source and entry policy')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Flashback original source row is incomplete')
    return data


def register_native_past_entry_grant_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('COMBO'),
            raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, 7, 1, None):
        raise TargetValidationError('Flashback requires its original Rogue Combo spell face')

    def body(c):
        return (GenerateFromPool(c.player_id, POOL_ID, QUERY, count=2, source_id=c.source_id,
            destination='board', cause=SummonCause.capture(c),
            entry_grant=CreatedMinionGrant(attack=1) if c.spell_conditions.combo else None),)

    registry.register_behavior(PREFIX + 'summon', body)
    card = CardDefinition(FLASHBACK, raw['name'], CardType.SPELL, cost=2,
        metadata=metadata_from_record(raw), keywords=(Keyword.COMBO,), on_play=PREFIX + 'summon')
    registry.register_card(card)
    if FLASHBACK not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
