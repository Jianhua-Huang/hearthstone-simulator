"""Timeway Warden binds actual imprisonment to its original native Deathrattle."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deathrattle_memory import ImprisonForDeathrattle, AwakenRememberedDormancy
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition, CardType, NativeDeathrattleSpec, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'TIME_442'
BODY = 'cards.timeway_warden.imprison'
DEATH = 'cards.timeway_warden.awaken'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/timeway-warden-v1.json'
BATCH_HASH = '75a2736d53953fdb8dfbac54d15788030a4757fa37fca0bbab4f3a66b2c3b92a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (ROOT,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (ROOT+'e',) or
            data['dependencies'] or data['existing_dependencies'] or
            any(canonical_digest(x['record']) != x['record_sha256']
                for section in ('cards', 'evidence_only') for x in data[section])):
        raise TargetValidationError('Timeway Warden requires its complete real source and enchantment evidence')
    return data


def register_timeway_warden_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 4, 2, 6) or \
            data['evidence_only'][0]['record']['tags'].get('SCORE_VALUE_1') != 10000:
        raise TargetValidationError('Timeway Warden changed its printed body or original dormancy count')
    def imprison(c):
        if c.battlecry is None:
            raise UnsupportedDefinitionError('Imprisonment requires its actual Battlecry acceptance')
        target = c.state.entities.get(c.target_id)
        if (target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION or
                not target.active or target.doomed or target.health <= 0): return ()
        ref = MinionReference.capture(c.source) if c.source.zone == Zone.BOARD and c.source.kind == CardType.MINION else None
        ids = () if ref is None else tuple(a.id for a in active_abilities(c.source, 'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind == 'dormancy_link')
        return (ImprisonForDeathrattle(c.battlecry.id, MinionReference.capture(target), ref, ids),)
    def awaken(c):
        memory = None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'dormancy_link':
            raise UnsupportedDefinitionError('Warden awakening lacks its original native captive memory')
        return tuple(AwakenRememberedDormancy(c.deathrattle.id, link) for link in memory.dormancies)
    registry.register_behavior(BODY, imprison); registry.register_behavior(DEATH, awaken)
    card = CardDefinition(ROOT, raw['name'], CardType.MINION, cost=4, attack=2, health=6,
        battlecry=BODY, deathrattle=DEATH, native_deathrattle=NativeDeathrattleSpec('dormancy_link'),
        targeting=TargetSpec(mode=TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'),
        metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
