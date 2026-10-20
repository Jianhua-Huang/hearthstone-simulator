"""Neptulon's real future-Elemental program, before entry notifications and BC."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, SummonStats
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_entry_stats import SummonEntryStatsProfile
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

NEPTULON, LIGHTSPAWN = 'BE_209', 'TIME_427'
ROOTS = COLLECTIBLE_ROOTS = (NEPTULON,)
DEPENDENCIES = ()
PROGRAM = 'cards.neptulon.elemental_entry_stats'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/elemental-pre-entry-stats-v1.json'
BATCH_HASH = '45cfd0bcce78afcfb42c8da39e2743b03ffcf51e26fe83a85aa30966379f374b'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS or
            tuple(x['record']['id'] for x in d['existing_dependencies']) != (LIGHTSPAWN,) or
            tuple(x['record']['id'] for x in d['evidence_only']) != ('BE_209e1', 'BE_209e2') or
            any(d[k] for k in ('dependencies', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for key in ('cards','existing_dependencies','evidence_only') for x in d[key])):
        raise TargetValidationError('Neptulon requires its complete original source and real timing representative')
    return d


def register_neptulon_entry_stat_card(registry):
    d = load_batch()
    if canonical_digest(asdict(registry.card(LIGHTSPAWN))) != d['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Neptulon timing representative changed its complete existing definition')
    registry.register_behavior(PROGRAM, lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),))
    raw = d['cards'][0]['record']
    card = CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),battlecry=PROGRAM)
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, NEPTULON))
    registry.register_summon_entry_stats_profile(SummonEntryStatsProfile(PROGRAM, NEPTULON, ('elemental',), SummonStats(5,5)))
