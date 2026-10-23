"""Historical native self-Attack readers; no card-local mutable counters."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, StatRelationLayer, StatRelationOperand, StatRelationSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


PUPPET, LIBRARIAN = 'MIS_710', 'REV_242'
LEAVES = DEPENDENCIES = (PUPPET, LIBRARIAN)
COLLECTIBLE_ROOTS = ()
HERO_ATTACK = StatRelationSpec(operand=StatRelationOperand.CONTROLLER_HERO_ATTACK,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=1)
IMP_COUNT = StatRelationSpec(operand=StatRelationOperand.CONTROLLER_IMP_COUNT,
    layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=1)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-continuous-attack-v1.json'
BATCH_HASH = '1bdce817da889a9bcf94b3997081ba415e24c9100c514565055ed105b725c71c'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(d['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in d['dependencies']) != LEAVES or
            canonical_digest(d['native_stat_relations']) != canonical_digest({PUPPET: asdict(HERO_ATTACK), LIBRARIAN: asdict(IMP_COUNT)}) or
            any(d[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in d['dependencies'])):
        raise TargetValidationError('Native self-Attack readers lost their complete sources or exact relations')
    return d


def register_past_continuous_attack_cards(registry):
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        expected = (1, 1, 2) if cid == PUPPET else (1, 1, 3)
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or
                (raw['cost'], raw['attack'], raw['health']) != expected):
            raise TargetValidationError('Native self-Attack reader lost its printed minion body')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=1, health=raw['health'],
            stat_relations=(HERO_ATTACK if cid == PUPPET else IMP_COUNT,), metadata=metadata_from_record(raw))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
