"""Slime 'em! and the native Ectoplasm bound to each original destroyed side."""
import json
from pathlib import Path

from hs_sim.engine.destruction_resummon_spells import DestroyForResummonSpells, SpellResummonProfile, resummon
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SLIME, ECTOPLASM = 'CAP_805', 'CAP_805t'
PREFIX = 'cards.ectoplasmic_execution.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/ectoplasmic-execution-v1.json'
BATCH_HASH = '37daa4ebadac0cd465bac40ef9f514bd4f74c3443da6176ada8a81bbab6f9f4f'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (SLIME,) or
            tuple(x['record']['id'] for x in d['dependencies']) != (ECTOPLASM,) or
            any(d[k] for k in ('existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Ectoplasm requires both complete original sources and primary faces')
    for row in (*d['cards'], *d['dependencies']):
        raw = row['record']; expected = 4 if raw['id'] == SLIME else 3
        if (canonical_digest(raw) != row['record_sha256'] or
                (raw['type'],raw['cost'],raw['collectible'],raw['tags']['CLASS'],raw['tags']['SPELL_SCHOOL']) !=
                ('SPELL',expected,raw['id'] == SLIME,6,6)):
            raise TargetValidationError('Original Priest Shadow spell faces changed')
    return d


def register_ectoplasmic_execution_cards(registry):
    def destroy(c):
        if c.cast is None or (c.cast.card_id,c.cast.source_id,c.cast.player_id) != (SLIME,c.source_id,c.player_id):
            raise UnsupportedDefinitionError('Slime em requires its actual original spell cast')
        return (DestroyForResummonSpells(c.cast.id, ECTOPLASM),)
    registry.register_behavior(PREFIX+'destroy', destroy)
    registry.register_behavior(PREFIX+'resummon', lambda c: resummon(c, registry))
    d = load_batch()
    for row in (*d['cards'], *d['dependencies']):
        raw = row['record']; cid = raw['id']
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.SHADOW,
            on_play=PREFIX+('destroy' if cid == SLIME else 'resummon'),metadata=metadata_from_record(raw))
        registry.register_card(card)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_value_profile(SpellResummonProfile(ECTOPLASM, SLIME))
