"""Prepare immutable damage/healing packets against one batch-start state.

Conversion, routing, source numeric rules, then recipient numeric rules form an
explicit prototype policy. Prevention/armor/shields remain in settlement. Rules
are data in abilities, so copying, silence, expiry and replay use one lifecycle.
"""
from dataclasses import dataclass, replace

from .effects import Damage, Heal
from .errors import ResolutionError
from .model import (CardType, DamageKind, HealingKind, HealthFlow, HealthLayer,
                    HealthOp, HealthFloorPlan, Keyword, SpellSchool, Zone)
from .random_split_damage import SplitBudgetQuote, SplitPacketLink


@dataclass(frozen=True)
class PreparedHealth:
    original_flow: HealthFlow
    flow: HealthFlow
    original_target_id: int
    target_id: int
    source_id: int | None
    source_controller: int | None
    source_keywords: frozenset[Keyword]
    base_amount: int
    amount: int
    damage_kind: DamageKind
    healing_kind: HealingKind
    school: SpellSchool | None = None
    spell_bonus: int = 0
    rule_ids: tuple[int, ...] = ()
    redirect_path: tuple[int, ...] = ()
    converted: bool = False
    from_lifesteal: bool = False
    prevented: bool = False
    floor_plan: HealthFloorPlan | None = None
    split_quote: SplitBudgetQuote | None = None
    split_packet: SplitPacketLink | None = None

    def event_data(self):
        return dict(base_amount=self.base_amount, spell_bonus=self.spell_bonus, modified_amount=self.amount,
                    source_controller=self.source_controller, original_target_id=self.original_target_id,
                    rule_ids=self.rule_ids, redirect_path=self.redirect_path, converted=self.converted,
                    spell_school=self.school.value if self.school else None)


def rule_sources(state):
    result = []
    for player in state.players.values():
        for entity_id in (player.hero_id, *player.board, *([player.weapon_id] if player.weapon_id else [])):
            entity = state.entities[entity_id]
            if not entity.active or entity.doomed or (entity.zone == Zone.WEAPON and entity.durability <= 0) or (
                    entity.zone != Zone.WEAPON and entity.health <= 0):
                continue
            result.extend((ability.id, entity.id, entity.controller, ability.health_rule)
                          for ability in entity.abilities if ability.kind == 'health_rule' and not ability.consumed)
    return tuple(sorted(result, key=lambda row: row[0]))


def relation_matches(relation, entity_id, controller, holder_id, holder_controller):
    if relation == 'any':
        return True
    if relation == 'self':
        return entity_id == holder_id
    if controller is None:
        return False
    return (controller == holder_controller) if relation == 'friendly' else (controller != holder_controller)


def matches(state, registry, packet, row):
    _, holder_id, controller, rule = row
    if packet.flow != rule.flow:
        return False
    if rule.damage_kinds and packet.damage_kind not in rule.damage_kinds:
        return False
    if rule.healing_kinds and packet.healing_kind not in rule.healing_kinds:
        return False
    if rule.schools and packet.school not in rule.schools:
        return False
    target = state.entities.get(packet.target_id)
    return (target is not None and target.active and registry.card(target.card_id).kind in rule.target_kinds and
            relation_matches(rule.source_relation, packet.source_id, packet.source_controller, holder_id, controller) and
            relation_matches(rule.target_relation, target.id, target.controller, holder_id, controller))


def validate_school_spell_damage_definition(card):
    from .model import _spell_damage_school_selector
    _spell_damage_school_selector(card.spell_damage_schools)
    if card.spell_damage_schools:
        from .stat_relations import validate_ordinary_face
        validate_ordinary_face(card)
        if type(card.spell_damage) is not int or card.spell_damage <= 0:
            raise ValueError('School spell damage requires a positive native amount')


def validate_school_spell_damage_carrier(registry, card_id, kind, abilities, components=()):
    rows=tuple(a for a in abilities if a.kind=='spell_damage')
    if not rows:return
    card=registry.card(card_id)
    if not card.spell_damage_schools and not any(a.spell_damage_schools for a in rows):return
    validate_school_spell_damage_definition(card)
    if kind!=CardType.MINION or components:
        raise ValueError('School spell damage requires an ordinary physical minion carrier')
    installed=0
    for ability in rows:
        ability.__post_init__()
        if ability.origin=='printed':
            if (not card.spell_damage or ability.spell_damage!=card.spell_damage or
                    ability.spell_damage_schools!=card.spell_damage_schools):
                raise ValueError('School spell damage differs from its complete native declaration')
            installed+=1
            if installed>1:raise ValueError('Duplicate native school spell damage instance')


def spell_damage_sources(state, player_id, registry, school=..., *, cast_id=None):
    """Pure providers; omitted school is the original aggregate scalar query.

    Actual spell packets always pass their school explicitly, including None.
    This preserves nonspell consumers without treating untyped spells as Nature.
    """
    if school is not Ellipsis and school is not None and type(school) is not SpellSchool:
        raise ValueError('Spell damage query requires an explicit SpellSchool or None')
    player = state.players[player_id]
    rows=[]
    for entity_id in (player.hero_id,*player.board):
        entity=state.entities[entity_id]
        if not entity.active or entity.health<=0 or entity.doomed:continue
        for ability in entity.abilities:
            if (ability.kind=='spell_damage' and not ability.consumed and
                    (school is Ellipsis or not ability.spell_damage_schools or school in ability.spell_damage_schools)):
                rows.append((entity,ability,None,ability.spell_damage))
    rows.extend((None,None,e,registry.player_effect(e.spec_id).spell_damage) for e in player.player_effects
                if registry.player_effect(e.spec_id).kind != 'next_spell_damage')
    if cast_id is not None:
        from .spell_casts import cast_record
        cast = cast_record(state,cast_id)
        if cast.player_id != player_id:
            raise ValueError('Scoped Spell Damage belongs to another caster')
        if cast.payload_started and not cast.completed and not cast.interrupted:
            for effect in cast.spell_damage_effects:
                spec = registry.player_effect(effect.spec_id)
                if spec.kind != 'next_spell_damage':
                    raise ValueError('Cast invented an unrelated player Spell Damage effect')
                rows.append((None,None,effect,spec.spell_damage))
    return tuple(rows)


def spell_bonus(state, player_id, registry, school=..., *, cast_id=None):
    return sum(row[3] for row in spell_damage_sources(state,player_id,registry,school,cast_id=cast_id))


def prepare_health(state, registry, instruction, *, rules=None, from_lifesteal=False, source_packet=None, split_link=None):
    """A complete numeric/routing quote, without changing live state or counters."""
    flow = HealthFlow.DAMAGE if isinstance(instruction, Damage) else HealthFlow.HEALING
    source = state.entities.get(instruction.source_id)
    if instruction.source_id is not None and source is None:
        raise ResolutionError('Health effect source does not exist')
    definition = registry.card(source.card_id) if source else None
    split_quote = None
    if split_link is not None:
        from .random_split_damage import packet_source
        split_quote = packet_source(state, registry, split_link)
        if (type(instruction) is not Damage or instruction.kind != DamageKind.SPELL or
                instruction.source_id != split_quote.source.entity_id or instruction.amount != 1 or
                instruction.spell_bonus_multiplier != 1 or from_lifesteal):
            raise ResolutionError('Internal split linkage requires exactly its original SPELL unit')
    elif source_packet is not None:
        split_quote = source_packet.split_quote
    if split_quote is not None:
        definition = registry.card(split_quote.source.card_id)
    if flow == HealthFlow.DAMAGE:
        damage_kind = instruction.kind
        healing_kind = (HealingKind.SPELL if damage_kind == DamageKind.SPELL else
                        HealingKind.HERO_POWER if damage_kind == DamageKind.HERO_POWER else HealingKind.EFFECT)
        if damage_kind == DamageKind.COMBAT and definition.kind not in (CardType.HERO, CardType.MINION):
            raise ResolutionError('Combat damage requires a character source')
    else:
        healing_kind = instruction.kind
        damage_kind = (DamageKind.SPELL if healing_kind == HealingKind.SPELL else
                       DamageKind.HERO_POWER if healing_kind == HealingKind.HERO_POWER else DamageKind.EFFECT)
    if damage_kind == DamageKind.SPELL and definition.kind != CardType.SPELL:
        raise ResolutionError('Spell damage/healing requires a spell source')
    if damage_kind == DamageKind.MINION_ABILITY and (definition is None or definition.kind != CardType.MINION):
        raise ResolutionError('Minion ability damage requires a minion source')
    keywords = frozenset(source.keywords) if source else frozenset()
    if source and source.zone == Zone.HERO and damage_kind != DamageKind.COMBAT:
        keywords = frozenset(a.keyword for a in source.abilities if a.kind == 'keyword' and not a.consumed)
    packet = PreparedHealth(flow, flow, instruction.target_id, instruction.target_id, instruction.source_id,
                            source.controller if source else None, keywords, instruction.amount, instruction.amount,
                            damage_kind, healing_kind, definition.spell_school if definition else None,
                            from_lifesteal=from_lifesteal, split_quote=split_quote, split_packet=split_link)
    if split_quote is not None:
        packet = replace(packet, source_controller=split_quote.cast.player_id,
            source_keywords=frozenset(split_quote.source_keywords), school=split_quote.school)
    if source_packet is not None:
        packet = replace(packet, source_controller=source_packet.source_controller,
                         source_keywords=source_packet.source_keywords, school=source_packet.school)
    target = state.entities.get(packet.target_id)
    if target is None or not target.active or not target.is_character or target.zone not in (Zone.HERO, Zone.BOARD):
        return packet
    rules = rule_sources(state) if rules is None else rules
    # Exactly one flow replacement for this packet. A conflicting inverse rule
    # does not bounce an already converted packet indefinitely.
    for row in rules:
        if row[3].operation == HealthOp.CONVERT and matches(state, registry, packet, row):
            packet = replace(packet, flow=HealthFlow.HEALING if flow == HealthFlow.DAMAGE else HealthFlow.DAMAGE,
                             converted=True, rule_ids=(row[0],))
            break
    path = [packet.target_id]
    used = set()
    while True:
        selected = None
        for row in rules:
            rule_id, holder_id, controller, rule = row
            if rule.operation != HealthOp.REDIRECT or rule_id in used or not matches(state, registry, packet, row):
                continue
            destination = holder_id if rule.redirect_to == 'self' else state.players[
                controller if rule.redirect_to == 'friendly_hero' else 3 - controller].hero_id
            entity = state.entities[destination]
            if not entity.active or not entity.is_character or destination == packet.target_id or entity.zone not in (Zone.HERO, Zone.BOARD):
                continue
            selected = (rule_id, destination)
            break
        if selected is None:
            break
        rule_id, destination = selected
        if destination in path:
            raise ResolutionError('Health redirection cycle; action rolled back')
        path.append(destination)
        used.add(rule_id)
        packet = replace(packet, target_id=destination, rule_ids=(*packet.rule_ids, rule_id), redirect_path=tuple(path))
    # Lifesteal is based on damage already dealt. Do not add spell damage twice
    # if its restorative packet is subsequently converted back into damage.
    if packet.flow == HealthFlow.DAMAGE and packet.damage_kind == DamageKind.SPELL and not from_lifesteal and split_link is None:
        # This coefficient scales only the provider bonus, never the base
        # amount. Quote it here so earlier effects can change live providers.
        multiplier = instruction.spell_bonus_multiplier if isinstance(instruction, Damage) else 1
        cast_id = None
        if damage_kind == DamageKind.SPELL and instruction.source_id is not None:
            from .spell_casts import active_cast
            cast = active_cast(state,instruction.source_id,packet.source_controller)
            if cast is not None: cast_id = cast.id
        bonus = spell_bonus(state, packet.source_controller, registry, packet.school,cast_id=cast_id) * multiplier
        packet = replace(packet, amount=packet.amount + bonus, spell_bonus=bonus)
    phases = {HealthOp.ADD: 0, HealthOp.SCALE: 1, HealthOp.SET: 2, HealthOp.CAP: 3, HealthOp.PREVENT: 4}
    numeric = sorted((row for row in rules if row[3].operation in phases),
                     key=lambda row: (row[3].layer != HealthLayer.SOURCE, phases[row[3].operation], row[0]))
    for row in numeric:
        if not matches(state, registry, packet, row):
            continue
        rule = row[3]
        amount = packet.amount
        if rule.operation == HealthOp.ADD:
            amount = max(0, amount + rule.amount)
        elif rule.operation == HealthOp.SCALE:
            amount = amount * rule.amount // rule.denominator
        elif rule.operation == HealthOp.SET:
            amount = rule.amount
        elif rule.operation == HealthOp.CAP:
            amount = min(amount, rule.amount)
        else:
            amount = 0
        packet = replace(packet, amount=amount, rule_ids=(*packet.rule_ids, row[0]),
                         prevented=rule.operation == HealthOp.PREVENT)
        if packet.prevented:
            break
    from .health_floors import capture_plan
    floor_plan = capture_plan(state, registry, packet, rules)
    if floor_plan is not None:
        packet = replace(packet, floor_plan=floor_plan,
            rule_ids=(*packet.rule_ids, *(row.ability.id for row in floor_plan.rows)))
    return packet
