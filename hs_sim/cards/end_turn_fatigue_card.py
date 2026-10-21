"""Blade of The Black Empire uses original cast facts and actual fatigue ticks."""
import json
from pathlib import Path

from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.fatigue import TakeFatigue
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, SpellSchool, TriggerSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_history import SpellHistoryQuery, spell_history_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_227'
BODY = 'cards.end_turn_fatigue.blade'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/end-turn-fatigue-v1.json'
BATCH_HASH = 'fccf0a9acb7c8e6b97d031fd5a8bea461a272ddd84ab93840c25195109bd5986'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Blade lost its complete original source face')
    return data


def register_end_turn_fatigue_card(registry):
    def resolve(c):
        query = SpellHistoryQuery(cards=PoolQuery(spell_schools=(SpellSchool.SHADOW,)),
            min_turn=c.state.turn, max_turn=c.state.turn)
        shadow_cast = bool(spell_history_candidates(c.state, registry, c.player_id, query, c.source_id))
        return (TakeFatigue(3-c.player_id if shadow_cast else c.player_id, c.source_id),)
    # Conditions read the actual resolution window after earlier end bodies.
    # The resulting fatigue request then keeps its accepted recipient.
    registry.register_behavior(BODY, lambda c: (InvokeBehavior(BODY+'.resolve', c.source_id, c.player_id),))
    registry.register_behavior(BODY+'.resolve', resolve)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS')) != ('WEAPON', 3, None, 3, 6):
        raise TargetValidationError('Blade requires its original non-attacking Priest 3-cost 3-durability face')
    card = CardDefinition(CARD, raw['name'], CardType.WEAPON, cost=3, durability=3,
        triggers=(TriggerSpec('turn_ended', BODY, EndTurnSpec()),), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
