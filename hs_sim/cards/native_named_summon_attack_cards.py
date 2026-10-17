"""Time Traveler's original successful Shadow, followed by ordinary combat."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-named-summon-attack-v1.json'
BATCH_HASH = '60c440a21d9ea4efa963d31db51f942070f01ed70fa2747f2094b90cdb1a5ef4'
TRAVELER = 'TIME_434'
SHADOW = 'TIME_434t'
PREFIX = 'cards.native_named_summon_attack.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (TRAVELER,) or
            tuple(x['record']['id'] for x in d['existing_dependencies']) != (SHADOW,) or
            any(d[k] for k in ('dependencies', 'evidence_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in d['cards']+d['existing_dependencies'])):
        raise TargetValidationError('Native Time Traveler complete source changed')
    return d


def register_native_named_summon_attack_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('Original Shadow dependency changed')
    raw = d['cards'][0]['record']
    if raw['type'] != 'MINION' or raw['tags'].get('DEATHRATTLE') != 1:
        raise TargetValidationError('Time Traveler requires its actual native Deathrattle')
    registry.register_behavior(PREFIX+'death', lambda c: (SummonByCard(c.player_id,
        (SummonEntryMaterial(SHADOW, on_summon=PREFIX+'attack'),), SummonCause.capture(c)),))
    registry.register_behavior(PREFIX+'attack', lambda c: (AttackRandomEnemyMinion(
        original_named_reference(c), c.player_id, c.source_id),))
    card = CardDefinition(TRAVELER, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), deathrattle=PREFIX+'death')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
