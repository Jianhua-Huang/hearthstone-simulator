"""Torch uses the original damage and spent-card return pipelines."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.retained_spell_damage import DamageReturningSpell, ReturningDamageProfile
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'CATA_585'
BODY = 'cards.torch.play'
TARGET = 'cards.torch.damaged'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/torch-v1.json'
BATCH_HASH = 'fc28dd497b7ec96d48e4bb2b79d9cd2f4d0d1097dc6ccf95cedefa009bfd6a8b'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            data['dependencies'] or data['existing_dependencies'] or data['evidence_only'] or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Torch requires its complete original printed spell')
    return data


def register_torch_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'),
            raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 1, 8, 2):
        raise TargetValidationError('Torch changed its actual initial eight-damage Fire spell')
    def play(c):
        if c.cast is None or c.cast.source_id != c.source_id:
            raise UnsupportedDefinitionError('Torch requires its actual original spell cast')
        target = c.state.entities.get(c.target_id)
        if target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION: return ()
        return (DamageReturningSpell(c.cast.id, MinionReference.capture(target)),)
    registry.register_behavior(BODY, play)
    registry.register_target_predicate(TargetPredicateSpec(TARGET, damaged=True))
    card = CardDefinition(ROOT, raw['name'], CardType.SPELL, cost=1, on_play=BODY,
        spell_school=SpellSchool.FIRE, target_rule=TARGET,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
        metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    registry.register_spell_value_profile(ReturningDamageProfile(ROOT, 8))
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
