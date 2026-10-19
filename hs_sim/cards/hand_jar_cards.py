"""Toru encloses real hand minions; the Jar's native Deathrattle releases them."""
import json
from pathlib import Path

from hs_sim.engine.hand_minion_jars import EncloseHandMinions, PROFILE
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

CARD, JAR = 'TLC_841', 'TLC_841t'
PREFIX = 'cards.hand_jars.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/hand-jars-v1.json'
BATCH_HASH = '924aad71e18001cc30a2e27e3b73e04bf1ced2dbfa022f7091a8b71f3843dbae'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (JAR,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TLC_841e',) or
            data['existing_dependencies'] or data['skipped'] or
            data['task']['numeric_normalizations'] != {JAR: {'attack': 0}}):
        raise TargetValidationError('Toru requires its complete reviewed source and explicit empty Jar')
    for item in (*data['cards'], *data['dependencies'], *data['evidence_only']):
        if canonical_digest(item['record']) != item['record_sha256']:
            raise TargetValidationError('Toru original source row changed')
    return data


def register_hand_jar_cards(registry):
    registry.register_behavior(PREFIX+'enclose', lambda c: (EncloseHandMinions(c.player_id, JAR, c.source_id),))
    def release(c):
        material = memory(c, 'copy_summon').summon_copy
        return () if material is None else (SummonByCard(c.player_id, (material,), SummonCause.capture(c)),)
    registry.register_behavior(PREFIX+'release', release)
    data=load_batch(); raw=data['cards'][0]['record']; jar=data['dependencies'][0]['record']
    for card in (
        CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], battlecry=PREFIX+'enclose', metadata=metadata_from_record(raw)),
        CardDefinition(JAR, jar['name'], CardType.MINION, cost=jar['cost'], attack=0, health=jar['health'],
            deathrattle=PREFIX+'release', native_deathrattle=PROFILE, metadata=metadata_from_record(jar)),
    ):
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
