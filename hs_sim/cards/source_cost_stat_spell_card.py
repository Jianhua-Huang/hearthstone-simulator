"""Floating Lessons uses one original source-cost value and ordinary stat effects."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import Buff
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_source_costs import SpellSourceCostProfile, amount
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_094'
BODY = 'cards.source_cost_stat_spell.grow'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/source-cost-stat-spell-v1.json'
BATCH_HASH = '168d596fc7f8298ec9030b39f43a71e5733e0a6b86a0e752db0692c7c00970b8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped'))):
        raise TargetValidationError('Floating Lessons lost its complete original source face')
    return data


def register_source_cost_stat_spell_card(registry):
    row = load_batch()['cards'][0]; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 1, 9, 6)):
        raise TargetValidationError('Floating Lessons requires its real one-cost Warlock Shadow face')
    def body(c):
        value = 2*amount(c, registry)
        target = c.cast.target_origin
        if c.cast.card_id != CARD or target is None or target.kind != CardType.MINION:
            raise ValueError('Floating Lessons requires its original accepted minion target')
        if value == 0:
            return ()
        return (Buff(target.entity_id, value, value, c.source_id),
                RandomBuffStoredMinion(c.player_id, value, value, source_id=c.source_id))
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=1, spell_school=SpellSchool.SHADOW,
        on_play=BODY, targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_source_cost_profile(SpellSourceCostProfile(CARD))
