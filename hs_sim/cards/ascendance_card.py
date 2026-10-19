"""Ascendance retains original board material in an ordinary granted Deathrattle."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import MinionScope, TransformMinionsInZones
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

CARD = 'CATA_567'
BODY, RETURN = 'cards.ascendance.transform', 'cards.ascendance.return_original'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/ascendance-originals-v1.json'
BATCH_HASH = 'b440486e970ebb113be1740cd4e775d5f17f149d55b2c2d6d747ecf1091e83ca'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (CARD,)
            or tuple(x['record']['id'] for x in d['evidence_only']) != ('CATA_567e',)
            or any(d[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('Ascendance requires its complete original spell and enchantment evidence')
    for row in (*d['cards'], *d['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Ascendance original source changed')
    return d


def register_ascendance_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags']['CLASS'], raw['tags']['RARITY'], raw['tags']['SPELL_SCHOOL']) != ('SPELL', 4, 8, 4, 4):
        raise TargetValidationError('Ascendance original Shaman Epic Nature face changed')
    registry.register_behavior(BODY, lambda c: (TransformMinionsInZones(c.player_id, 'constructed.cards', 1,
        scope=MinionScope(zones=(Zone.BOARD,)), source_id=c.source_id, deathrattle_behavior_id=RETURN),))

    def summon(c):
        material = memory(c, 'copy_summon').summon_copy
        if material is None:
            raise TargetValidationError('Ascendance grant lost its actual pre-transformation minion')
        board = c.state.players[c.player_id].board
        position = c.death.position if c.death is not None else board.index(c.source_id) + 1 if c.source_id in board else None
        return (SummonByCard(c.player_id, (material,), SummonCause.capture(c), position=position),)
    registry.register_behavior(RETURN, summon)
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=4, spell_school=SpellSchool.NATURE,
        metadata=metadata_from_record(raw), on_play=BODY)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
