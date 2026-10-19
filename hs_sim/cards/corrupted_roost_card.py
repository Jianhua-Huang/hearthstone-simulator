"""A real location seeds an original Dragon copy into the native Egg Deathrattle."""
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DeathrattleMemory, NativeDeathrattleSpec, TargetSpec, Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import TribeState, has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

CARD, EGG = 'EDR_454', 'EDR_454t'
PROFILE = NativeDeathrattleSpec('copy_summon')
PREFIX = 'cards.corrupted_roost.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/corrupted-roost-v1.json'
BATCH_HASH = '4fa541d60e896ccea1ada86eb839e581f4062bc7e084dae14357092335876f1c'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,)
            or tuple(x['record']['id'] for x in d['dependencies']) != (EGG,)
            or any(d[k] for k in ('existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Clutch requires its complete original location and Egg')
    for row in (*d['cards'], *d['dependencies']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Clutch source row changed')
    if d['task']['numeric_normalizations'] != {EGG: {'attack': 0}}:
        raise TargetValidationError('Egg requires its strictly reviewed printed zero')
    return d


def register_corrupted_roost_card(registry):
    def dragon(c):
        tribes = c.target.get('tribes')
        if tribes is None:
            raise ResolutionError('Clutch requires known current public Dragon tribes')
        return TribeState(tuple(sorted(tribes)), tuple(sorted(c.target.get('tribes_excluded', ())))).matches_any(('dragon',))
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX + 'dragon', 'current-public-dragon-v1'), dragon)
    def seed(c):
        target = c.state.entities.get(c.target_id)
        if (target is None or target.kind != CardType.MINION or target.zone != Zone.BOARD
                or target.controller != c.player_id or not target.active or target.health <= 0 or target.doomed
                or not has_any_tribe(registry, target, ('dragon',))):
            return ()
        material = CopyEntryMaterial.capture(c.state, target, 'remembered_copy', 'current', registry=registry)
        return (SummonByCard(c.player_id, (SummonEntryMaterial(EGG,
            deathrattle_memory=DeathrattleMemory(PROFILE, summon_copy=material)),), SummonCause.capture(c)),)
    def hatch(c):
        material = memory(c, 'copy_summon').summon_copy
        return () if material is None else (SummonByCard(c.player_id, (material,), SummonCause.capture(c)),)
    registry.register_behavior(PREFIX + 'seed', seed)
    registry.register_behavior(PREFIX + 'hatch', hatch)
    d = load_batch(); raw = d['cards'][0]['record']; egg = d['dependencies'][0]['record']
    if ((raw['type'], raw['cost'], raw['health']) != ('LOCATION', 2, 2) or
            (egg['type'], egg['cost'], egg['attack'], egg['health']) != ('MINION', 1, None, 2) or 'ATK' in egg['tags']):
        raise TargetValidationError('Clutch or Egg changed the original printed body')
    definitions = (
        CardDefinition(CARD, raw['name'], CardType.LOCATION, cost=2, durability=2, on_use=PREFIX + 'seed',
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly'),
            target_rule=PREFIX + 'dragon', metadata=metadata_from_record(raw)),
        CardDefinition(EGG, egg['name'], CardType.MINION, cost=1, attack=0, health=2,
            deathrattle=PREFIX + 'hatch', native_deathrattle=PROFILE, metadata=metadata_from_record(egg)),
    )
    for definition in definitions:
        registry.register_card(definition)
        if definition.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(definition))
