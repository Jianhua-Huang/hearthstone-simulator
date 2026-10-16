"""Reviewed draw/resource cards, using the existing effect queue and accounts."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

from hs_sim.engine.effects import (
    Buff, Draw, GainArmor, GainResource, GainTemporaryMana, InvokeBehavior, Overload,
)
from hs_sim.engine.model import (
    CardDefinition, CardType, Keyword, Resource, SpellSchool, TargetMode, TargetSpec,
    TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard, PoolQuery
from .metadata import metadata_from_record
from hs_sim.engine.zones import CardReference, DrawMatching, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest

from .health_cards import HealthStep, SCHOOLS, health_body


BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/economy-effects-v1.json'
BATCH_HASH = '84e522c82a63034fdd628070c585db7032db6e9c8429166b31609bc985bf419b'


@dataclass(frozen=True)
class EconomyStep:
    operation: str
    amount: int
    scope: str = 'own_hero'
    attack: int = 0
    health: int = 0
    temporary: bool = False
    condition: str = 'always'
    query: PoolQuery | None = None

    def __post_init__(self):
        if self.operation not in ('draw', 'draw_until', 'draw_bottom', 'armor',
                                  'temporary_mana', 'overload', 'corpses', 'tutor',
                                  'damage', 'buff'):
            raise ValueError('Unsupported reviewed economy operation')
        if type(self.amount) is not int or self.amount < 0:
            raise ValueError('Economy amount requires a nonnegative integer')
        if self.scope not in ('own_hero', 'target', 'enemy_minions', 'all_enemies'):
            raise ValueError('Unreviewed economy recipient scope')
        if self.condition not in ('always', 'outcast'):
            raise ValueError('Unreviewed economy condition')
        if any(type(v) is not int or v < 0 for v in (self.attack, self.health)):
            raise ValueError('This batch only declares nonnegative ordinary buffs')
        if type(self.temporary) is not bool:
            raise ValueError('Temporary buff requires an explicit boolean')
        if self.operation != 'buff' and (self.attack or self.health or self.temporary):
            raise ValueError('Only buffs declare stats or expiry')
        if self.operation == 'buff' and (self.scope not in ('target', 'own_hero') or self.amount):
            raise ValueError('Reviewed buffs target one entity and use explicit stats')
        if self.operation not in ('buff', 'damage') and self.scope != 'own_hero':
            raise ValueError('Resource and draw instructions use the executing player')
        if self.operation == 'tutor':
            if type(self.query) is not PoolQuery:
                raise ValueError('Tutor requires an immutable explicit query')
            self.query.__post_init__()
        elif self.query is not None:
            raise ValueError('Only tutors carry a query')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Economy card batch differs from its reviewed pin')
    return data


def parse_step(raw):
    values = dict(raw)
    query = values.get('query')
    if query is not None:
        if set(query) - {'kinds', 'min_cost', 'spell_schools', 'tribes_any'}:
            raise ValueError('Unreviewed tutor query parameter')
        values['query'] = PoolQuery(
            kinds=tuple(CardType(k) for k in query.get('kinds', ())),
            min_cost=query.get('min_cost'),
            spell_schools=tuple(SpellSchool(s) for s in query.get('spell_schools', ())),
            tribes_any=tuple(query.get('tribes_any', ())),
        )
    return EconomyStep(**values)


def bottom_behavior_id(count):
    return f'cards.economy.bottom-draw-{count}'


def bottom_draw(context, count):
    """Each continuation selects the current bottom after the previous draw ends."""
    deck = context.state.players[context.player_id].deck
    if not deck:
        return (Draw(context.player_id, count, context.source_id),)
    reference = CardReference.capture(context.state.entities[deck[-1]])
    effects = [MoveCard(reference, context.player_id, Zone.HAND,
                        draw=True, source_id=context.source_id)]
    if count > 1:
        effects.append(InvokeBehavior(bottom_behavior_id(count-1),
                                      context.source_id, context.player_id))
    return tuple(effects)


def economy_body(context, steps, is_spell, trigger=None):
    if trigger == 'self_damaged':
        if context.event.target_id != context.source_id or context.event.amount <= 0:
            return ()
    elif trigger == 'friendly_hero_attack':
        if context.event.source_id != context.state.players[context.player_id].hero_id:
            return ()
    effects = []
    for step in steps:
        if step.condition == 'outcast':
            if context.spell_conditions is None:
                raise ValueError('Outcast needs the accepted original play/cast conditions')
            if not context.spell_conditions.outcast:
                continue
        if step.operation == 'draw':
            effects.append(Draw(context.player_id, step.amount, context.source_id))
        elif step.operation == 'draw_until':
            # Same count-at-execution convention as the existing DrawToHandLimit.
            count = max(0, step.amount-len(context.state.players[context.player_id].hand))
            effects.append(Draw(context.player_id, count, context.source_id))
        elif step.operation == 'draw_bottom':
            if step.amount:
                effects.append(InvokeBehavior(bottom_behavior_id(step.amount),
                                              context.source_id, context.player_id))
        elif step.operation == 'tutor':
            effects.append(DrawMatching(context.player_id, step.query, 'skip', step.amount,
                                        source_id=context.source_id))
        elif step.operation == 'armor':
            effects.append(GainArmor(context.player_id, step.amount))
        elif step.operation == 'temporary_mana':
            effects.append(GainTemporaryMana(context.player_id, step.amount))
        elif step.operation == 'overload':
            effects.append(Overload(context.player_id, step.amount))
        elif step.operation == 'corpses':
            effects.append(GainResource(context.player_id, Resource.CORPSES, step.amount))
        elif step.operation == 'damage':
            effects.extend(health_body(context, (HealthStep('damage', step.scope, step.amount),), is_spell))
        elif step.operation == 'buff':
            target = (context.target_id if step.scope == 'target'
                      else context.state.players[context.player_id].hero_id)
            effects.append(Buff(target, step.attack, step.health, context.source_id,
                                expires_turn=context.state.turn if step.temporary else None))
    return tuple(effects)


def register_economy_cards(registry):
    rows = load_batch()['cards']
    bottom_counts = {step['amount'] for row in rows for body in row['recipe']['bodies'].values()
                     for step in body if step['operation'] == 'draw_bottom'}
    for count in range(1, max(bottom_counts, default=0)+1):
        registry.register_behavior(bottom_behavior_id(count),
            lambda c, count=count: bottom_draw(c, count))
    registered = set()
    for row in rows:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256']:
            raise TargetValidationError('Economy record differs from its reviewed identity')
        kind = CardType(raw['type'].lower())
        if raw['collectible'] is not True or kind not in (CardType.SPELL, CardType.MINION, CardType.WEAPON):
            raise TargetValidationError('Economy recipes require reviewed collectible root cards')
        cost = recipe['cost']
        if type(cost) is not int or cost < 0 or (cost != raw['cost'] and not (
                raw['id'] == 'CORE_EX1_169' and raw['cost'] is None and cost == 0)):
            raise TargetValidationError('Unreviewed printed cost or missing zero-cost tag')
        keywords = tuple(Keyword(k) for k in recipe['keywords'])
        if len(set(keywords)) != len(keywords) or set(keywords) - {Keyword.TAUNT, Keyword.RUSH, Keyword.OUTCAST}:
            raise TargetValidationError('Unreviewed economy keyword declaration')
        if recipe['spell_damage'] != raw['tags'].get('SPELLPOWER', 0):
            raise TargetValidationError('Spell damage differs from printed metadata')
        trigger = recipe['trigger']
        if trigger not in (None, 'self_damaged', 'friendly_hero_attack'):
            raise TargetValidationError('Unreviewed economy trigger condition')
        if (trigger is not None) != ('on_trigger' in recipe['bodies']):
            raise TargetValidationError('Trigger condition requires its complete executable body')
        kwargs = {}
        for entry, raw_steps in recipe['bodies'].items():
            if entry not in ('on_play', 'battlecry', 'deathrattle', 'on_trigger'):
                raise TargetValidationError('Unreviewed economy body entry')
            if entry == 'battlecry' and kind != CardType.MINION or entry == 'deathrattle' and kind == CardType.SPELL:
                raise TargetValidationError('Economy body is incompatible with the printed card type')
            steps = tuple(parse_step(s) for s in raw_steps)
            if not steps:
                raise TargetValidationError('Economy bodies cannot be placeholders')
            if any(s.condition == 'outcast' for s in steps) and Keyword.OUTCAST not in keywords:
                raise TargetValidationError('Outcast body requires the printed keyword')
            condition = trigger if entry == 'on_trigger' else None
            identity = dict(entry=entry, spell=kind == CardType.SPELL, trigger=condition, steps=raw_steps)
            behavior_id = 'cards.economy.'+canonical_digest(identity)[:24]
            if behavior_id not in registered:
                registry.register_behavior(behavior_id,
                    lambda c, steps=steps, spell=kind == CardType.SPELL, trigger=condition:
                        economy_body(c, steps, spell, trigger))
                registered.add(behavior_id)
            if entry == 'on_trigger':
                event = 'damage_dealt' if trigger == 'self_damaged' else 'attack_finished'
                kwargs['triggers'] = (TriggerSpec(event, behavior_id),)
            else:
                kwargs[entry] = behavior_id
        if not kwargs:
            raise TargetValidationError('Economy card requires a complete body')
        target = recipe['target']
        if target is not None:
            if target not in ('character', 'minion'):
                raise TargetValidationError('Unreviewed economy target domain')
            minion_only = target == 'minion'
            kwargs['targeting'] = TargetSpec(TargetMode.REQUIRED,
                zones=(Zone.BOARD,) if minion_only else (Zone.HERO, Zone.BOARD),
                kinds=(CardType.MINION,) if minion_only else (CardType.HERO, CardType.MINION))
        school = raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:
            raise TargetValidationError('Unreviewed economy spell school')
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=cost,
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            durability=raw['health'] if kind == CardType.WEAPON else 0,
            keywords=keywords, spell_damage=recipe['spell_damage'], spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
