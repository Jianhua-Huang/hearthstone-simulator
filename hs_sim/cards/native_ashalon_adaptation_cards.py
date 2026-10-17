"""Ashalon's actual reward face and the missing fixed Adapt dependencies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.adapt_memory import SPORES, living_spores, remember_adaptations
from hs_sim.engine.model import CardDefinition, CardType, Keyword, PlayerEffectSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_229t14'
CHOICES = ('UNG_999t3', 'UNG_999t4', 'UNG_999t14', 'UNG_999t6', 'UNG_999t8', 'UNG_999t13', 'UNG_999t2')
PROGRAM = 'cards.ashalon.remembered_adaptations'
BODY = 'cards.ashalon.adapt_twice'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-ashalon-adaptations-v1.json'
BATCH_HASH = '9fa0311f4cc2cb319f1aa5f3cfd660f58fbd425885869a2c2a507e9949ea35bf'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD, *CHOICES)):
        raise TargetValidationError('Ashalon requires its complete reviewed source pin')
    for group in ('cards', 'existing_dependencies', 'evidence_only'):
        for item in data[group]:
            if canonical_digest(item['record']) != item['record_sha256']:
                raise TargetValidationError('Ashalon original source row changed')
    return data


def register_native_ashalon_adaptation_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Ashalon must preserve the complete existing Adapt dependency: ' + cid)
    registry.register_behavior(SPORES, living_spores)
    registry.register_behavior(BODY, lambda c: (remember_adaptations(c, PROGRAM),))
    for item in data['cards']:
        raw = item['record']; cid = raw['id']
        card = CardDefinition(cid, raw['name'], CardType.MINION if cid == CARD else CardType.SPELL,
            cost=raw['cost'] if cid == CARD else 0,
            attack=raw['attack'] if cid == CARD else 0, health=raw['health'] if cid == CARD else 0,
            keywords=(Keyword.RUSH,) if cid == CARD else (), battlecry=BODY if cid == CARD else None,
            choice_only=cid != CARD, metadata=metadata_from_record(raw))
        registry.register_card(card)
        if cid == CARD:
            registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, CARD, kind='adaptations'))
