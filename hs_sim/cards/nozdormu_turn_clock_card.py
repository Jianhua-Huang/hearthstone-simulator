"""Nozdormu the Eternal; opening condition and host clock live in the engine."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, OpeningHook
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.turn_clocks import ActivateOriginalDeckClock, TurnClockProfile
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CS3_035'
BEHAVIOR = 'cards.nozdormu_turn_clock.opening'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/nozdormu-turn-clock-v1.json'
BATCH_HASH = 'b353e52c46e1b570ff07e86dd0586f06362075f936dcef1a4b7bd6c1534031f8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            any(data[key] for key in ('dependencies','existing_dependencies','evidence_only')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Nozdormu requires its complete original Core face and reviewed source')
    return data


def register_nozdormu_turn_clock_card(registry):
    item = load_batch()['cards'][0]; raw = item['record']; meta = metadata_from_record(raw)
    if canonical_digest(asdict(meta)) != canonical_digest(item['metadata']): raise TargetValidationError('Nozdormu metadata drift')
    registry.register_behavior(BEHAVIOR, lambda c: (ActivateOriginalDeckClock(c.source_id,c.player_id,CARD),))
    definition = CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        opening_hooks=(OpeningHook('before_deal',BEHAVIOR),),metadata=meta)
    registry.register_card(definition)
    member = PoolCard.from_definition(definition)
    if CARD in registry.pool_cards:
        if registry.pool_cards[CARD] != member: raise TargetValidationError('Nozdormu changed an existing pool row')
    else: registry.register_pool_card(member)
    registry.register_turn_clock_profile(TurnClockProfile(CARD,BEHAVIOR))
