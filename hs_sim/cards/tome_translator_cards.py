"""Four real decoded Battlecries; the original hidden-clock root is pending."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.adjacent_stat_gains import GainRandomAdjacentStats
from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, CostSpec, DamageKind, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage, SplitDamageScope
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

FORMS = ('BE_327t', 'BE_327t1', 'BE_327t2', 'BE_327t3')
EVIDENCE_ONLY = ('BE_327', 'BE_327te', 'BE_327te2')
PREFIX = 'cards.tome_translator.'
POOL_ID = 'constructed.cards'
DEATHRATTLES = PoolQuery(kinds=(CardType.MINION,), min_cost=2, max_cost=2,
    collectible=True, deathrattle=True)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/tome-translator-v1.json'
BATCH_HASH = '52967cab848305b3857d2072e4290303c562279b277298bf6b7737c70d1c65e2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != FORMS or
            tuple(row['record']['id'] for row in data['evidence_only']) != EVIDENCE_ONLY or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != tuple(data['candidate_domain_ids']) or
            any(data[key] for key in ('dependencies', 'choice_only', 'skipped')) or
            canonical_digest(asdict(DEATHRATTLES)) != data['generation_query_sha256'] or
            canonical_digest(data['generation_query']) != data['generation_query_sha256']):
        raise TargetValidationError('Decoded Tome Translator lost its complete source or native domain')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Decoded Tome Translator source row changed')
    return data


def register_tome_translator_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Decoded Tome Translator changed an original complete dependency')

    def summon(c):
        request = SummonFromPool(c.player_id, POOL_ID, DEATHRATTLES, source_id=c.source_id,
            cause=SummonCause.capture(c))
        return (request, request)

    def split(c):
        source = c.source
        excluded = (BoardPresenceReference.capture(c.state, source.id)
            if source.kind == CardType.MINION and source.zone == Zone.BOARD else None)
        return (RandomSplitDamage(c.player_id, None, c.source_id, 6,
            scope=SplitDamageScope('any', (CardType.MINION,), excluded),
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)

    def adjacent(c):
        source = c.source
        if source.kind != CardType.MINION or source.zone != Zone.BOARD:
            return ()
        return (GainRandomAdjacentStats(BoardPresenceReference.capture(c.state, source.id), c.source_id),)

    bodies = (summon,
        lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-4, card_types=(CardType.SPELL,)),
            uses_remaining=1, source_id=c.source_id, expires_turn=c.state.turn),),
        split, adjacent)
    for cid, body in zip(FORMS, bodies):
        registry.register_behavior(PREFIX + cid, body)
    for row in data['cards']:
        raw = row['record']
        if (raw['type'] != 'MINION' or raw['collectible'] or raw['tags'].get('BATTLECRY') != 1 or
                (raw['cost'], raw['attack'], raw['health']) != (4, 5, 4)):
            raise TargetValidationError('Decoded Tome Translator form lost its complete printed minion')
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
            battlecry=PREFIX + raw['id'])
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
