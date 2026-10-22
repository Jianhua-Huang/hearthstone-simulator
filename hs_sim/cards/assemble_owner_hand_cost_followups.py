"""Native owner-end clocks, original callback mana view and independent hand bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_end_conditions import AssembleNativeEndConditionSource, NATIVE_END_CONDITION_PREFIX
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import Draw
from hs_sim.engine.model import CostSpec, EndTurnSpec, Keyword
from hs_sim.engine.pools import PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('CORE_ULD_133', 'TLC_822')
CONDITION = NATIVE_END_CONDITION_PREFIX + 'cards.assemble_owner_hand.unused_mana'
DRAW = 'cards.assemble_owner_hand.draw_one'
DISCOUNT = 'cards.assemble_owner_hand.beast_discount'
QUERY = PoolQuery(tribes_any=('beast',))
COST = CostSpec(delta=-1)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-owner-hand-cost-followups-v1.json'
BATCH_HASH = '6e0146370ef926cc002d024cd326f4f8aa1375fb795d52e719dec2325ee5361d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            canonical_digest(asdict(QUERY)) != canonical_digest(data['native_query']) or
            canonical_digest(asdict(COST)) != canonical_digest(data['native_cost']) or
            data['tribe_basis'] != 'current' or
            data['native_callback_sources'] != [dict(card_id=SOURCES[0],
                original_behavior_id=data['reviewed_templates'][0]['original_end_turn_id'],
                condition_id=CONDITION)]):
        raise TargetValidationError('Owner hand assembly requires two complete native sources and exact stored query')
    return data


def register_assemble_owner_hand_cost_followups(registry):
    data = load_batch()
    for row, decl in zip(data['existing_dependencies'], data['reviewed_templates']):
        original = registry.card(row['record']['id'])
        if (canonical_digest(asdict(original)) != row['definition_sha256'] or
                len(original.triggers) != 1 or original.triggers[0].event != 'turn_ended' or
                original.triggers[0].behavior_id != decl['original_end_turn_id'] or
                canonical_digest(asdict(original.triggers[0].end_turn)) != canonical_digest(decl['end_turn'])):
            raise TargetValidationError('Owner hand assembly changed a complete native source or clock')
    registry.register_trigger_condition(CONDITION, lambda c: c.state.players[c.player_id].mana > 0)
    registry.register_assemble_native_end_condition(AssembleNativeEndConditionSource(
        **data['native_callback_sources'][0]))
    registry.register_behavior(DRAW, lambda c: (Draw(c.player_id, 1, c.source_id),))
    registry.register_behavior(DISCOUNT, lambda c: (RandomBuffStoredMinion(c.player_id,
        query=QUERY, source_id=c.source_id, cost=COST, tribe_basis='current'),))
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix('end_turn', tuple(Keyword(key) for key in decl['keywords']),
                EndTurnSpec(**decl['end_turn']), condition_id=decl['condition_id']),
            AssembleSuffix(decl['body_id'], tuple(decl['allowed_timings'])),
            original_end_turn_id=decl['original_end_turn_id']))
