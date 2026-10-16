"""Reviewed conditional targets/prices and original health-result continuations."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage, DamageBatch, Destroy, Heal
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HandActionSpec, HealingKind,
    IntrinsicCostSpec, Keyword, Rarity, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import RandomSplitDamage, SplitDamageScope
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/conditional-health-effects-v1.json'
BATCH_HASH = '26080b01f24270810da544cbdca7d4517c4f008e7169a5348ebd2aad32163df4'
PREFIX = 'cards.conditional_health.'
SCRIPTS = {'CORE_CS2_072':'backstab', 'CORE_BT_801':'eye_beam', 'CORE_BAR_311':'plague',
           'CATA_203':'garona', 'CATA_303':'purifying_breath', 'CATA_308':'medivh'}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Conditional health cards differ from their reviewed full source pin')
    for row in data['known_unrarified_legacy']:
        raw = row['record']
        if canonical_digest(raw) != row['record_sha256'] or raw['collectible'] or 'RARITY' in raw['tags']:
            raise TargetValidationError('Known unrarified evidence lacks its complete original face')
    return data


def register_conditional_health_cards(registry):
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'undamaged', damaged=False))
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'legendary', printed_rarities=(Rarity.LEGENDARY,)))

    def plague(c):
        if c.cast is None or c.cast.source_id != c.source_id:
            raise ValueError('Plague requires its real current SPELL cast')
        return (RandomSplitDamage(c.player_id, c.cast.id, c.source_id, 4,
                                  SplitDamageScope(kinds=(CardType.MINION,))),)

    def purify_result(c):
        result = c.health_result
        if result.target_id != result.original_target_id:
            return ()
        return (InvokeHealthResult(PREFIX+'purify_after_death', c.event),)

    def purify_after_death(c):
        result = c.health_result
        died = any(death.entity_id == result.original_target_id and death.cause is not None
                   and death.cause.kind in ('damage', 'poison')
                   and death.cause.result == result.payload() for death in c.state.death_history)
        return (Heal(c.state.players[3-c.player_id].hero_id, 5, c.source_id, HealingKind.SPELL),) if died else ()

    bodies = {
        'backstab': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        'eye_beam': lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),),
        'plague': plague,
        'garona': lambda c: (Destroy(c.target_id, c.source_id),),
        'purifying_breath': lambda c: (Damage(c.target_id, 5, c.source_id, DamageKind.SPELL, PREFIX+'purify_result'),),
        'purify_result': purify_result,
        'purify_after_death': purify_after_death,
        'medivh': lambda c: (DamageBatch(tuple(Damage(eid, 4, c.source_id, DamageKind.SPELL)
            for p in (1, 2) for eid in minions(c, registry, p))),),
    }
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or SCRIPTS.get(raw['id']) != recipe['script']
                or raw['type'] != 'SPELL' or not raw['collectible']
                or raw['cost'] != recipe['cost'] and not (raw['id'] == 'CORE_CS2_072' and raw['cost'] is None and recipe['cost'] == 0)):
            raise TargetValidationError('Conditional health card lost its reviewed complete face')
        target = recipe['target']; kwargs = {}
        if target is not None:
            kwargs['targeting'] = TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,), kinds=(CardType.MINION,))
            if target == 'undamaged_minion': kwargs['target_rule'] = PREFIX+'undamaged'
            elif target == 'legendary_minion': kwargs['target_rule'] = PREFIX+'legendary'
            elif target != 'minion': raise TargetValidationError('Unreviewed conditional health target')
        if recipe['intrinsic'] is not None:
            condition = recipe['intrinsic']
            profile = {'hand_edge':'hand.current-edge-v1', 'controlled_legendary':'controlled.current-legendary-v1'}[condition]
            kwargs['intrinsic_costs'] = (IntrinsicCostSpec(set_to=1, condition=condition, history_profile_id=profile),)
        keywords = ((Keyword.LIFESTEAL,) if recipe['lifesteal'] else ())
        if raw['id'] == 'CORE_BT_801':
            keywords += (Keyword.OUTCAST,)
        if recipe['tradeable']:
            kwargs['hand_actions'] = (HandActionSpec('trade', 'trade', 1),)
        definition = CardDefinition(raw['id'], raw['name'], CardType.SPELL, cost=recipe['cost'],
            keywords=keywords, spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']),
            on_play=PREFIX+recipe['script'], **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
