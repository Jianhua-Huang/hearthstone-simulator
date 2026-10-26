"""Pure cost quotes shared by validation, enumeration and transactional payment.

The prototype orders local enchantments first, then live auras/player modifiers
by attachment ID. Each operation clamps to its own minimum. Special card rules
and official ordering calibration must extend this explicit versioned contract.
"""
from dataclasses import dataclass, replace

from .effects import AddCostModifier, GrantCostAura, Effect
from .errors import ResolutionError
from .model import (CurrentDeckCountMatch, PermanentManaMatch, AbilityInstance, CardType, CostContribution, CostModifier,
                    CostQuoteFact, CostQuoteInput, CostScope, Enchantment,
                    HandPlayCostReceipt, PaymentType, PlayRecord, Resource,
                    SpellCostFacts, SpellRepeatSpec, Zone)


@dataclass(frozen=True)
class CostQuote:
    entity_id: int | None
    player_id: int
    amount: int
    payment: PaymentType
    modifier_ids: tuple[int, ...] = ()
    consumable_ids: tuple[int, ...] = ()
    current_deck: CurrentDeckCountMatch | None = None
    permanent_mana: PermanentManaMatch | None = None
    kindred_sources: tuple = ()


def capture_cost_input(entity, *, minimum_cost=None,hand_lifetime=...):
    # Caller of an accepted-hand profile supplies the original hand floor here.
    # No entity movement, synthetic history or live-zone fallback is performed.
    if minimum_cost is None:
        minimum_cost = entity.hand_lifetime.minimum_cost if entity.zone == Zone.HAND and entity.hand_lifetime is not None else 0
    if hand_lifetime is ...:hand_lifetime=entity.hand_lifetime if entity.zone==Zone.HAND else None
    return CostQuoteInput(entity.id, entity.controller, entity.card_id, entity.kind,
        entity.base_cost, tuple(entity.enchantments), tuple(entity.abilities), minimum_cost,hand_lifetime)


def local_cost_values(base_cost, enchantments, *, payment=PaymentType.MANA):
    amount = base_cost
    for enchantment in enchantments:
        amount = apply_cost(amount, enchantment.cost, enchantment.set_cost, enchantment.cost_minimum)
        if enchantment.payment is not None:
            payment = enchantment.payment
    return amount, payment


def intrinsic_payment(definition,stage):
    if definition.pay_health_if_hero_healed:
        from .model import HeroHealedTurnMatch
        if (len(stage.condition_facts)!=1 or type(stage.condition_facts[0])is not HeroHealedTurnMatch):
            raise ValueError('Conditional health payment lost its original hero healing fact')
        if stage.condition_facts[0].matched:return PaymentType.HEALTH
    return definition.cost_payment


def quote_input(state, registry, value, *, profile_id=None):
    """Quote explicit physical operands against this state's external layers.

    This never moves or inserts the subject. Original-window producers bind
    these operands to their real source; compact validators replay the saved
    operations without querying today's state.
    """
    if type(value) is not CostQuoteInput:
        raise ValueError('Physical cost quote requires CostQuoteInput')
    value.__post_init__()
    definition = registry.card(value.card_id)
    if definition.kind != value.kind:
        raise ValueError('Cost quote input face and kind disagree')
    if profile_id is not None:
        registry.cost_query_profile(profile_id).__post_init__()
        if value.kind != CardType.SPELL:
            raise ValueError('Accepted hand cost profile requires a Spell')
    from .card_conditions import has_battlecry
    from .intrinsic_costs import capture_intrinsic_stage
    intrinsic = capture_intrinsic_stage(state, registry, value.player_id, value.card_id, value.base_cost, source_id=value.source_id)
    local_amount, local_payment = local_cost_values(intrinsic.amount, value.enchantments,
        payment=intrinsic_payment(definition,intrinsic))
    amount, payment, external = _external_quote(state, registry, value.player_id,
        definition, local_amount, local_payment, has_battlecry(value.abilities), value.enchantments,
        abilities=value.abilities,hand_lifetime=value.hand_lifetime,minimum_cost=value.minimum_cost,
        physical_id=value.source_id)
    local = tuple(CostContribution('local_enchantment', value.player_id,
        value.source_id, enchantment=e) for e in value.enchantments)
    return CostQuoteFact(profile_id, value, local_amount, local_payment,
        max(amount, value.minimum_cost), payment, (*local, *external),
        tuple(c.id for c in external),
        tuple(c.id for c in external if c.kind == 'player_modifier' and
              c.modifier.uses_remaining is not None), intrinsic)


def capture_quote_fact(state, registry, value, profile_id=None):
    """Public fact producer sharing the authoritative quote traversal."""
    return quote_input(state, registry, value, profile_id=profile_id)


def cost_quote_from_fact(fact):
    if type(fact) is not CostQuoteFact:
        raise ValueError('Payment quote requires a complete physical cost fact')
    fact.__post_init__()
    return CostQuote(fact.quote_input.source_id, fact.quote_input.player_id,
                     fact.amount, fact.payment, fact.modifier_ids, fact.consumable_ids,
                     current_deck=fact.intrinsic.condition_facts[0] if fact.intrinsic.condition_facts and type(fact.intrinsic.condition_facts[0]) is CurrentDeckCountMatch else None,
                     permanent_mana=fact.intrinsic.condition_facts[0] if fact.intrinsic.condition_facts and type(fact.intrinsic.condition_facts[0]) is PermanentManaMatch else None,
                     kindred_sources=fact.intrinsic.kindred_sources)


def _accepted_spell_input(state, registry, play):
    if type(play) is not PlayRecord or play.kind != CardType.SPELL:
        raise ValueError('Accepted hand cost requires a physical paid Spell record')
    play.__post_init__()
    receipt = play.submitted_cost
    if type(receipt) is not HandPlayCostReceipt:
        raise ValueError('Accepted hand price is missing its submitted cost receipt')
    receipt.__post_init__()
    source = state.entities.get(play.source_id)
    if (source is None or (source.id, source.controller, source.card_id, source.kind) !=
            (play.source_id, play.player_id, play.card_id, play.kind)):
        raise ValueError('Accepted hand cost source or face has changed')
    if (receipt.quote.quote_input.source_id, receipt.quote.quote_input.player_id) != (
            play.source_id, play.player_id):
        raise ValueError('Submitted cost belongs to a different physical source or payer')
    if (play.cost, play.payment) != (receipt.quote.amount, receipt.quote.payment):
        raise ValueError('Submitted cost differs from the paid hand quote')
    definition = registry.card(play.card_id)
    if definition.kind != CardType.SPELL or definition.cost != receipt.printed_cost:
        raise ValueError('Accepted Spell printed cost identity has changed')
    return capture_cost_input(source, minimum_cost=receipt.quote.quote_input.minimum_cost,
        hand_lifetime=receipt.quote.quote_input.hand_lifetime)


def quote_accepted_hand(state, registry, play, profile_id='repeat.cost.accepted_hand'):
    """Current full price with the accepted hand floor, even after leaving HAND."""
    registry.cost_query_profile(profile_id).__post_init__()
    return quote_input(state, registry, _accepted_spell_input(state, registry, play),
                       profile_id=profile_id)


def capture_spell_cost_facts(state, registry, play, declarations):
    """Capture required facts before any class/school/source false short circuit."""
    from .repeat_matching import validate_repeat_cost_declaration
    filters = []
    for spec in declarations:
        if type(spec) is not SpellRepeatSpec:
            raise ValueError('Cost fact declarations require complete SpellRepeatSpec values')
        spec.__post_init__()
        value = validate_repeat_cost_declaration(registry, spec)
        if value is not None:
            filters.append(value)
    if not filters:
        return None
    value = _accepted_spell_input(state, registry, play)
    from .intrinsic_costs import capture_intrinsic_stage
    intrinsic = capture_intrinsic_stage(state, registry, value.player_id, value.card_id, value.base_cost, source_id=value.source_id)
    local_amount, local_payment = local_cost_values(intrinsic.amount, value.enchantments,
        payment=intrinsic_payment(registry.card(value.card_id),intrinsic))
    profiles = sorted({f.quote_profile_id for f in filters if f.basis == 'window_quote'})
    quotes = tuple(quote_input(state, registry, value, profile_id=profile) for profile in profiles)
    return SpellCostFacts(registry.card(play.card_id).cost, value,
                          local_amount, local_payment, intrinsic, quotes)


def apply_cost(amount, delta, set_to, minimum):
    # A reduction with a floor must not increase a card already below it.
    if set_to is not None:
        return max(minimum, set_to)
    floor = min(amount, minimum) if delta < 0 else minimum
    return max(floor, amount + delta)


def is_final_floor(contribution):
    return (contribution.kind == 'cost_aura' and
        contribution.ability.cost_aura.relation == 'all_cards_minimum')


def final_floor(contributions):
    """Native continuous constraints apply after all numeric price changes."""
    return max((c.ability.cost_aura.cost.minimum for c in contributions if is_final_floor(c)), default=0)


def local_cost(entity):
    return local_cost_values(entity.base_cost, entity.enchantments)


def quote_cost(state, registry, entity):
    return cost_quote_from_fact(quote_input(state, registry, capture_cost_input(entity)))


def quote_unselected_cost(state, registry, entity):
    """Current physical card basis for held-card comparisons, never payment."""
    return quote_cost(state, registry, entity)


def capture_generated_quote_fact(state, registry, player_id, card_id, *, cost=None, minimum_cost=0):
    """Pure hypothetical hand quote; no entity, acquisition or modifier consumption."""
    from .effects import _player, _integer
    from .model import CostSpec, GeneratedCostQuoteInput, GeneratedCostQuoteFact
    from .intrinsic_costs import capture_intrinsic_stage
    _player(player_id); _integer(minimum_cost,'generated minimum cost',0)
    definition=registry.card(card_id)
    if not definition.hand_playable:raise ValueError('Generated quote requires a physical hand card')
    mana_numbers = (state.players[player_id].mana if definition.kind == CardType.SPELL and
        card_id in registry.remaining_mana_numbers_profiles else None)
    base_cost = definition.cost if mana_numbers is None else max(1, mana_numbers)
    intrinsic = capture_intrinsic_stage(state, registry, player_id, card_id, base_cost)
    amount, payment = intrinsic.amount, intrinsic_payment(definition,intrinsic)
    if cost is not None:
        if type(cost) is not CostSpec:raise ValueError('Generated quote requires CostSpec')
        cost.__post_init__()
        if not matches_cost(cost,definition):raise ValueError('Generated quote cost does not match the card')
        amount=apply_cost(amount,cost.delta,cost.set_to,cost.minimum)
        if cost.payment is not None:payment=cost.payment
    local_amount, local_payment = amount, payment
    amount, payment, external = _external_quote(state, registry, player_id, definition, amount, payment, None,minimum_cost=minimum_cost)
    value = GeneratedCostQuoteInput(player_id, card_id, definition.kind, base_cost, cost, minimum_cost, mana_numbers)
    return GeneratedCostQuoteFact(value, intrinsic, local_amount, local_payment,
        max(amount, minimum_cost), payment, external, tuple(c.id for c in external),
        tuple(c.id for c in external if c.kind == 'player_modifier' and c.modifier.uses_remaining is not None))


def quote_generated_cost(state, registry, player_id, card_id, *, cost=None, minimum_cost=0):
    fact = capture_generated_quote_fact(state, registry, player_id, card_id, cost=cost, minimum_cost=minimum_cost)
    return CostQuote(None, player_id, fact.amount, fact.payment, fact.modifier_ids, fact.consumable_ids)


def validate_cost_aura_definition(card):
    """Only the necessary native ordinary source is added to existing cost auras."""
    if card.kind==CardType.HERO_POWER and card.cost_auras:
        from .passive_hero_powers import validate_native_face
        validate_native_face(card)
        return
    held = tuple(s for s in card.cost_auras if s.hand_adjacent)
    if held and (card.kind != CardType.SPELL or len(card.cost_auras) != 1 or
            card.secret is not None or card.quest is not None or card.ongoing_effect_id is not None):
        raise ValueError('Adjacent hand cost source requires one native ordinary spell declaration')
    tribal = tuple(s for s in card.cost_auras if s.tribes_any or s.first_per_turn or s.every_nth_per_turn is not None)
    if tribal:
        from .stat_relations import validate_ordinary_face
        validate_ordinary_face(card)
        if len(set(tribal)) != len(tribal):
            raise ValueError('Duplicate native tribal cost aura declaration')


def validate_cost_aura_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'cost_aura')
    if not rows:
        return
    if kind==CardType.HERO_POWER:
        from .passive_hero_powers import validate_carrier
        validate_carrier(registry,card_id,kind,abilities,components)
        return
    native=registry.cards.get(card_id)
    if native is not None and native.native_condition is not None or any(a.native_condition is not None for a in rows):
        from .native_conditions import validate_carrier as validate_native_provider
        validate_native_provider(registry,card_id,kind,abilities,components)
    for ability in rows:
        ability.__post_init__()
    card = registry.card(card_id)
    floor_rows = tuple(a for a in rows if a.cost_aura.relation == 'all_cards_minimum')
    if floor_rows:
        from collections import Counter
        declared = Counter(s for s in card.cost_auras if s.relation == 'all_cards_minimum')
        installed = Counter(a.cost_aura for a in floor_rows)
        if kind != CardType.MINION or any(n > declared[s] for s, n in installed.items()):
            raise ValueError('Native final price floor lost its original minion declaration')
    held = tuple(a for a in rows if a.cost_aura.hand_adjacent)
    if held or any(s.hand_adjacent for s in card.cost_auras):
        validate_cost_aura_definition(card)
        if (kind != CardType.SPELL or components or len(rows) != 1 or
                rows[0].origin != 'printed' or rows[0].cost_aura not in card.cost_auras):
            raise ValueError('Adjacent hand cost carrier lost its native spell declaration')
    if not any(a.cost_aura.tribes_any or a.cost_aura.first_per_turn or a.cost_aura.every_nth_per_turn is not None for a in rows) and not any(
            s.tribes_any or s.first_per_turn or s.every_nth_per_turn is not None for s in card.cost_auras):
        return
    if kind != CardType.MINION or components:
        raise ValueError('Tribal cost auras require non-composite minion carriers')
    from collections import Counter
    from .stat_relations import validate_ordinary_face
    validate_cost_aura_definition(card)
    validate_ordinary_face(card)
    declared, installed = Counter(card.cost_auras), Counter()
    for ability in rows:
        ability.__post_init__()
        if ability.origin == 'printed':
            if ability.cost_aura not in declared:
                raise ValueError('Tribal cost aura differs from its native declaration')
            installed[ability.cost_aura] += 1
            if installed[ability.cost_aura] > declared[ability.cost_aura]:
                raise ValueError('Duplicate native tribal cost aura instance')


def validated_cost_source_inventory(state, registry):
    """Validate every raw cost declaration, including inactive and false ones."""
    from .repeat_provenance import checked_live_attachments
    catalogue = checked_live_attachments(state)
    for player in state.players.values():
        for modifier in player.cost_modifiers:
            if type(modifier) is not CostModifier:
                raise ValueError('Cost source requires a complete CostModifier')
            modifier.__post_init__()
    for entity in state.entities.values():
        for ability in entity.abilities:
            if ability.kind == 'cost_aura':
                if type(ability) is not AbilityInstance:
                    raise ValueError('Cost aura requires a complete AbilityInstance')
                ability.__post_init__()
                registry.card(entity.card_id)
        validate_cost_aura_carrier(registry, entity.card_id, entity.kind, entity.abilities, entity.components)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind == 'cost_aura':
                ability.__post_init__()
                registry.card(death.card_id)
        validate_cost_aura_carrier(registry, death.card_id, registry.card(death.card_id).kind,
                                   death.abilities, death.components)
    return catalogue


def _external_quote(state, registry, player_id, definition, amount, payment, current_battlecry, enchantments=(),
                    *,abilities=None,hand_lifetime=None,minimum_cost=0,physical_id=None):
    validated_cost_source_inventory(state, registry)
    player = state.players[player_id]
    modifiers = [(m.id, m.spec, CostContribution('player_modifier', player.id,
        None, modifier=m)) for m in player.cost_modifiers if m.scope == CostScope.CARD]
    sources = [i for owner in state.players.values()
               for i in (*owner.board, *([owner.weapon_id] if owner.weapon_id is not None else []))]
    from .passive_hero_powers import cost_sources as passive_power_cost_sources
    sources.extend(passive_power_cost_sources(state,registry))
    subject = state.entities.get(physical_id)
    if subject is not None and (subject.controller, subject.card_id, subject.kind) == (
            player_id, definition.id, definition.kind):
        from .hand_neighbors import current_hand_neighbors
        sources.extend(current_hand_neighbors(state, physical_id))
    first_rows = cast_rows = tribal_inputs = None
    from .native_conditions import matches as native_provider_matches
    for source_id in sources:
        source = state.entities[source_id]
        if not source.active or source.doomed or (source.is_character and source.health <= 0) or (
                source.kind in (CardType.WEAPON, CardType.LOCATION) and source.durability <= 0):
            continue
        for ability in source.abilities:
            if (ability.kind != 'cost_aura' or ability.consumed or not (
                    ability.cost_aura.relation in ('any', 'all_cards_minimum') or
                    (source.controller == player_id) == (ability.cost_aura.relation in ('friendly','friendly_arcane_spells')))):
                continue
            if ability.cost_aura.hand_adjacent != (source.zone == Zone.HAND):
                continue
            if not native_provider_matches(state,source,ability.native_condition,registry=registry):continue
            first = None
            if ability.cost_aura.first_per_turn or ability.cost_aura.every_nth_per_turn is not None:
                # Unrelated types neither activate nor spend this qualification.
                if definition.kind not in ability.cost_aura.cost.card_types:
                    continue
                from .model import FirstPlayCostFact
                from .player_played_class_costs import _rows
                if first_rows is None:
                    first_rows = _rows(state, registry)
                rows = first_rows
                spells = None
                if ability.cost_aura.every_nth_per_turn is not None and definition.kind == CardType.SPELL:
                    if cast_rows is None:
                        from .spell_casts import validate_history
                        from .player_spell_count_costs import row_for
                        validate_history(state, registry)
                        cast_rows = tuple(row_for(c, registry) for c in state.cast_history)
                    spells = cast_rows
                original_inputs = None
                if ability.cost_aura.tribes_any:
                    if tribal_inputs is None:
                        tribal_inputs = tuple(p.submitted_cost.quote.quote_input for p in state.play_history)
                    original_inputs = tribal_inputs
                first = FirstPlayCostFact(player_id, definition.kind, state.turn,
                    state.action_number, state.next_entity_id, len(rows), rows,
                    spells, None if spells is None else len(spells),
                    ability.cost_aura.tribes_any, original_inputs)
            contribution = CostContribution('cost_aura', source.controller, source.id,
                                            ability=ability, first_play=first)
            modifiers.append((ability.id, ability.cost_aura.cost, contribution))
    # A price-bounded account switch has no numeric operation. Compute the
    # complete price once, then match the payment-only switches without cycles.
    candidates=[];complete_amount=amount
    for modifier_id,spec,contribution in sorted(modifiers,key=lambda row:row[0]):
        if matches_cost_contribution(registry,contribution,definition,current_battlecry,enchantments,
                abilities=abilities,hand_lifetime=hand_lifetime,ignore_maximum=True):
            candidates.append((modifier_id,spec,contribution))
            if not is_final_floor(contribution):
                complete_amount=apply_cost(complete_amount,spec.delta,spec.set_to,spec.minimum)
    complete_amount=max(complete_amount,minimum_cost,final_floor(c for _,_,c in candidates))
    applied = []
    for modifier_id,spec,contribution in candidates:
        if (contribution.modifier is not None and contribution.modifier.maximum_cost is not None and
                complete_amount>contribution.modifier.maximum_cost and spec.payment!=PaymentType.OPPONENT_HEALTH):continue
        if not is_final_floor(contribution):
            amount = apply_cost(amount, spec.delta, spec.set_to, spec.minimum)
        if spec.payment is not None:
            payment = spec.payment
        applied.append(contribution)
    return max(amount, final_floor(applied)), payment, tuple(applied)


def matches_cost_contribution(registry, contribution, definition, current_battlecry, enchantments=(),
                              *,abilities=None,hand_lifetime=None,complete_amount=None,ignore_maximum=False):
    """Replay the same recipient predicate over complete original operands.

    Generated subjects have no enchantments and use their fresh printed face;
    physical subjects use their original ordered current-tribe changes.
    """
    spec = contribution.modifier.spec if contribution.modifier is not None else contribution.ability.cost_aura.cost
    if contribution.ability is not None and contribution.ability.cost_aura.relation=='friendly_arcane_spells':
        from .model import SpellSchool
        if definition.kind!=CardType.SPELL or definition.spell_school!=SpellSchool.ARCANE:return False
    if not matches_cost_values(spec, definition, current_battlecry):
        return False
    modifier=contribution.modifier
    if modifier is not None:
        if modifier.combo_only and not (definition.combo is not None if abilities is None else
                any(a.kind=='combo'and not a.consumed for a in abilities)):return False
        if modifier.deathrattle_only and not (definition.deathrattle is not None if abilities is None else
                any(a.kind=='deathrattle'and not a.consumed for a in abilities)):return False
        if modifier.temporary_only and hand_lifetime is None:return False
        if modifier.maximum_cost is not None and not ignore_maximum:
            if type(complete_amount)is not int:raise ValueError('Qualified Health payment lost its complete current price')
            if complete_amount>modifier.maximum_cost and spec.payment!=PaymentType.OPPONENT_HEALTH:return False
    if contribution.modifier is not None and contribution.modifier.tribes_any:
        from .tribes import tribe_state_for
        current=tribe_state_for(registry,definition.id,tuple(e for e in enchantments if e.tribe_change is not None))
        if current is None:
            from .registry import UnsupportedDefinitionError
            raise UnsupportedDefinitionError('Unknown current tribe set: '+definition.id)
        if not current.matches_any(contribution.modifier.tribes_any):return False
    aura_tribes = () if contribution.ability is None else contribution.ability.cost_aura.tribes_any
    current_tribes = None
    if aura_tribes:
        from .tribes import tribe_state_for
        current_tribes = tribe_state_for(registry, definition.id,
            tuple(e for e in enchantments if e.tribe_change is not None), basis='current')
        # A known unrelated recipient needs no first-matching history verdict.
        if current_tribes is not None and not current_tribes.matches_any(aura_tribes):
            return False
    if contribution.first_play is not None:
        from .owner_turns import validate_face
        for row in contribution.first_play.rows:
            validate_face(row.face, registry)
        for row in contribution.first_play.cast_rows or ():
            card = registry.card(row.card_id)
            if card.kind != CardType.SPELL or card.spell_school != row.spell_school:
                raise ValueError('Periodic spell price changed its registered physical spell face')
        aura = contribution.ability.cost_aura
        if aura.first_per_turn and not contribution.first_play.is_first:
            return False
        if aura.every_nth_per_turn is not None and contribution.first_play.ordinal % aura.every_nth_per_turn:
            return False
    if aura_tribes and current_tribes is None:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Unknown current tribe set: ' + definition.id)
    return True


def validate_first_play_cost_prefix(state, registry, fact):
    """Bind a frozen price to actual retained hand roots; allow later progress."""
    if fact is None:
        return
    fact.__post_init__()
    from .player_played_class_costs import _rows
    rows = _rows(state, registry)
    if (fact.next_entity_id > state.next_entity_id or fact.turn > state.turn or
            fact.action > state.action_number or len(fact.rows) > len(rows) or
            fact.rows != rows[:len(fact.rows)]):
        raise ValueError('First-play price rewrote its complete original paid-hand prefix')
    if fact.tribal_inputs is not None and fact.tribal_inputs != tuple(
            p.submitted_cost.quote.quote_input for p in state.play_history[:fact.play_history_length]):
        raise ValueError('First-tribe price rewrote its original submitted current-tribe operands')
    if fact.cast_rows is not None:
        from .spell_casts import validate_history
        from .player_spell_count_costs import row_for
        validate_history(state, registry)
        if fact.cast_history_length > len(state.cast_history):
            raise ValueError('Periodic spell price lost its original physical cast prefix')
        for old, current in zip(fact.cast_rows, state.cast_history):
            new = row_for(current, registry)
            # A pending original attempt may later accept or fail; its quoted
            # count stays frozen. Accepted payloads cannot be withdrawn.
            adjusted = replace(old, payload_started=new.payload_started,
                failure=new.failure) if not old.payload_started and old.failure is None else old
            if adjusted != new:
                raise ValueError('Periodic spell price rewrote its original cast identity or acceptance')


def matches_cost_values(spec, definition, current_battlecry):
    from .card_conditions import matches_ability, matches_ability_values
    return (definition.kind in spec.card_types and (not spec.card_ids or definition.id in spec.card_ids)
            and (spec.ability is None or (matches_ability(spec.ability, definition) if spec.ability.ability in ('outcast', 'secret')
                else matches_ability_values(spec.ability,
                printed=definition.battlecry is not None,
                current=definition.battlecry is not None if current_battlecry is None else current_battlecry))))


def _quote_card(state, registry, player_id, card_id, amount, payment, entity_id, minimum_cost):
    from .card_conditions import has_battlecry
    entity = state.entities[entity_id] if entity_id is not None else None
    current = None if entity is None else has_battlecry(entity.abilities)
    amount, payment, external = _external_quote(state, registry, player_id,
        registry.card(card_id), amount, payment, current, () if entity is None else tuple(entity.enchantments),
        abilities=None if entity is None else tuple(entity.abilities),
        hand_lifetime=entity.hand_lifetime if entity is not None and entity.zone==Zone.HAND else None,minimum_cost=minimum_cost)
    return CostQuote(entity_id, player_id, max(amount, minimum_cost), payment,
        tuple(c.id for c in external), tuple(c.id for c in external if
            c.kind == 'player_modifier' and c.modifier.uses_remaining is not None))


def matches_cost(spec, definition, entity=None):
    from .card_conditions import matches_ability
    return (definition.kind in spec.card_types and (not spec.card_ids or definition.id in spec.card_ids)
            and (spec.ability is None or matches_ability(spec.ability, definition, entity)))


def payment_error(state, quote):
    player = state.players[quote.player_id]
    hero = state.entities[player.hero_id]
    if quote.payment == PaymentType.MANA:
        return 'Insufficient mana' if player.mana < quote.amount else None
    if quote.payment == PaymentType.OPPONENT_HEALTH:
        limits=[m.maximum_cost for m in player.cost_modifiers if m.id in quote.modifier_ids
            and m.spec.payment==PaymentType.OPPONENT_HEALTH and m.maximum_cost is not None]
        if not limits:
            return 'Opponent Health payment lost its original bounded source'
        return 'Card exceeds the opponent Health payment limit' if quote.amount>min(limits) else None
    if quote.payment == PaymentType.HEALTH:
        from .health_loss import replacement_for
        from .model import HealthLossKind
        if replacement_for(state, hero.id, HealthLossKind.PAYMENT) is not None:
            return None
        return 'Insufficient health' if hero.health + hero.armor <= quote.amount else None
    if quote.payment == PaymentType.ARMOR:
        return 'Insufficient armor' if hero.armor < quote.amount else None
    return 'Insufficient corpses' if player.resources[Resource.CORPSES] < quote.amount else None


def pay_cost(r, player, source):
    pay_quote(r, player, source, quote_cost(r.state, r.registry, source))


def pay_quote(r, player, source, quote, *, exclude_held_source=False):
    from .remaining_mana_numbers import payment_window
    with payment_window(r,source.id):
        return _pay_quote(r,player,source,quote,exclude_held_source=exclude_held_source)


def _pay_quote(r, player, source, quote, *, exclude_held_source=False):
    """Apply the shared resource plan; preserve each original capture boundary."""
    if (quote.entity_id, quote.player_id) != (source.id, player.id):
        raise ResolutionError('Payment quote has a different payer or source')
    from .payment_projection import payment_plan, apply_resource_writes, consume_quoted_modifiers
    plan = payment_plan(r.state, quote)
    apply_resource_writes(r.state, plan.resource_writes)
    # HEALTH resource writes/growth precede these events. Cost uses still remain.
    for event in plan.health_events:
        r.emit(event.kind, **dict(event.data))
    # Compact global cost-use facts include every paid entry, not just Spells.
    consume_quoted_modifiers(r.state, quote, origin='payment', exclude_held_source=exclude_held_source)
    # Original expenditure event; corpse payments include their committed account row.
    r.emit(f'{quote.payment.value}_spent', source_id=source.id, player_id=player.id,
           amount=quote.amount, modifier_ids=quote.modifier_ids, consumed_ids=quote.consumable_ids,
           **dict(plan.hero_health_data),
           _corpse_spend_record=None if plan.corpse_spend_id is None else r.state.corpse_spend_history[plan.corpse_spend_id-1])


def consume_modifiers(player, ids):
    updated = []
    for modifier in player.cost_modifiers:
        if modifier.id not in ids:
            updated.append(modifier)
        elif modifier.uses_remaining > 1:
            updated.append(replace(modifier, uses_remaining=modifier.uses_remaining - 1))
    player.cost_modifiers = updated


def paid_death_modifiers(state,play):
    if play.kind!=CardType.MINION or play.submitted_cost is None:
        raise ValueError('Paid minion death requires its original minion price')
    quote=play.submitted_cost.quote
    modifiers=tuple(c.modifier for c in quote.contributions if
        c.modifier is not None and c.modifier.destroy_after_play)
    if not modifiers:return ()
    receipts=[row for row in state.cost_use_history if
        (row.origin,row.source_id,row.player_id,row.source_card_id,row.turn,row.action,
            row.amount,row.payment,row.modifier_ids,row.consumable_ids)==
        ('payment',play.source_id,play.player_id,play.card_id,play.turn,play.action,
            quote.amount,quote.payment,quote.modifier_ids,quote.consumable_ids)]
    if len(receipts)!=1 or any(m.id not in quote.consumable_ids or m not in receipts[0].player_modifiers
            or m.source_id not in state.entities for m in modifiers):
        raise ValueError('Paid minion death lost its exact original consumed price sources')
    return modifiers


@dataclass(frozen=True)
class DestroyPaidMinion(Effect):
    play_id:int
    entry:object

    def __post_init__(self):
        from .effects import _integer
        from .allocation_facts import SourceAllocationFact
        _integer(self.play_id,'paid minion death play',1)
        if type(self.entry)is not SourceAllocationFact:
            raise ValueError('Paid minion death requires its original full board entry')
        self.entry.__post_init__()
        if (self.entry.kind,self.entry.zone)!=(CardType.MINION,Zone.BOARD)or self.entry.entered_order<1:
            raise ValueError('Paid minion death requires a real original minion entry')

    def validate_in_state(self,state):
        from .play_history import play_record
        self.__post_init__();play=play_record(state,self.play_id);entry=self.entry
        if (play.source_id!=entry.entity_id or play.minion_result!='summoned' or
                play.completed or play.interrupted or not paid_death_modifiers(state,play)):
            raise ValueError('Paid minion death substituted its original accepted payment/entry')
        entity=state.entities.get(entry.entity_id)
        if (entity is None or entry.owner!=entity.owner or entry.zone_epoch>entity.zone_epoch or
                entry.next_entity_id>state.next_entity_id or entry.next_order>state.next_order):
            raise ValueError('Paid minion death borrowed a future or unrelated physical entry')


def paid_minion_death_tail(r,play,entity):
    if not paid_death_modifiers(r.state,play):return ()
    from .allocation_facts import SourceAllocationFact
    return(DestroyPaidMinion(play.id,SourceAllocationFact.capture(r.state,entity)),)


def destroy_paid_minion(r,effect):
    from .play_history import play_record
    from .allocation_facts import validate_allocation
    from .board_presence import resolve_board_presence
    from .model import BoardPresenceReference
    from .resolver import destroy
    from .effects import Destroy
    effect.validate_in_state(r.state);validate_allocation(r.state,r.registry,effect.entry)
    target=resolve_board_presence(r.state,BoardPresenceReference(effect.entry.entity_id,effect.entry.entered_order))
    if target is None or not target.active or target.doomed or target.health<=0:return ()
    modifiers=paid_death_modifiers(r.state,play_record(r.state,effect.play_id))
    destroy(r,Destroy(target.id,modifiers[0].source_id))
    return ()


def defer_paid_minion_root(r,work,play_id):
    """Keep the original proofs alive through the accepted paid-death tail."""
    from .battlecry_repeats import FinishBattlecryAcceptance
    from .combo_acceptance import FinishComboAcceptance
    from .resolver import FinishPlay
    queue=r._work_queue
    tails=[(i,w)for i,w in enumerate(queue)if type(w)is DestroyPaidMinion and w.play_id==play_id]
    if not tails:return False
    if len(tails)!=1:raise ValueError('Paid minion death lost its unique original tail')
    index,tail=tails[0];tail.validate_in_state(r.state)
    ends=[i for i,w in enumerate(queue)if type(w)is FinishPlay and w.play_id==play_id]
    if len(ends)!=1 or index>=ends[0]:raise ValueError('Paid death must precede its enclosing hand completion')
    position=index+1
    while position<len(queue):
        closer=queue[position]
        if (type(closer)is FinishBattlecryAcceptance or
                type(closer)is FinishComboAcceptance and closer.phase!='play')and closer.context.play.id==play_id:
            position+=1
        else:break
    queue.insert(position,work)
    return True


def install_paid_minion_keywords(r, play, entity):
    """Install only bonuses belonging to this original paid price, before entry.

    Finite usage is already consumed by the existing payment receipt. No second
    next-minion counter or current-tribe query can choose a different recipient.
    """
    if play.submitted_cost is None:
        raise ResolutionError('Paid minion entry lost its original cost receipt')
    quote = play.submitted_cost.quote
    bonuses = tuple(c.modifier for c in quote.contributions
        if c.modifier is not None and c.modifier.minion_keyword is not None)
    if not bonuses:
        return
    if play.kind != CardType.MINION or entity.id != play.source_id or entity.zone != Zone.PLAY:
        raise ResolutionError('Cost keyword requires the original pending paid minion')
    receipts = [row for row in r.state.cost_use_history if
        (row.origin,row.source_id,row.player_id,row.source_card_id,row.turn,row.action,
            row.amount,row.payment,row.modifier_ids,row.consumable_ids) ==
        ('payment',play.source_id,play.player_id,play.card_id,play.turn,play.action,
            quote.amount,quote.payment,quote.modifier_ids,quote.consumable_ids)]
    if len(receipts) != 1 or any(m.id not in quote.consumable_ids or m not in receipts[0].player_modifiers
            or m.source_id not in r.state.entities for m in bonuses):
        raise ResolutionError('Next-minion keyword lost its exact consumed payment sources')
    from .lifecycle import attachment_id, refresh_entity
    for modifier in bonuses:
        for _ in range(modifier.minion_keyword_repetitions):
            entity.abilities.append(AbilityInstance(attachment_id(r.state),'keyword',
                source_id=modifier.source_id,keyword=modifier.minion_keyword))
    refresh_entity(entity)


def validate_creation_cost(state, effect, definitions):
    """Validate every eligible result before generation consumes randomness."""
    validate_cost_targets(state, effect, ((definition, None) for definition in definitions))


def validate_cost_targets(state, effect, targets):
    """Validate fresh definitions or physical instances before an atomic operation."""
    if effect.expires_turn is not None and effect.expires_turn < state.turn:
        raise ResolutionError('Generated cost has already expired')
    if effect.cost is not None and any(not matches_cost(effect.cost, d, e) for d, e in targets):
        raise ResolutionError('Cost does not match the card type, ID or ability condition')


def attach_cost(state, entity, spec, source_id=None, expires_turn=None):
    """Install the common cost record, including during atomic card creation."""
    from .lifecycle import attachment_id, refresh_entity
    attachment = Enchantment(attachment_id(state), source_id=source_id,
        cost=spec.delta, set_cost=spec.set_to, cost_minimum=spec.minimum,
        payment=spec.payment, expires_turn=expires_turn, label='cost')
    entity.enchantments.append(attachment)
    refresh_entity(entity)
    return attachment


def modify_cost(r, effect, *, player_effect_id=None, allow_dormant=False):
    from .lifecycle import attachment_id, refresh_entity
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Cost attachment source does not exist')
    if effect.expires_turn is not None and effect.expires_turn < r.state.turn:
        raise ResolutionError('Cost attachment has already expired')
    spec = effect.spec
    if isinstance(effect, AddCostModifier):
        player = r.player(effect.player_id)
        modifier = CostModifier(r.state.next_attachment_id, spec, effect.source_id,
                                effect.uses_remaining, effect.expires_turn, effect.scope,effect.tribes_any,
                                effect.combo_only,effect.temporary_only,effect.maximum_cost,effect.minion_keyword,effect.minion_keyword_repetitions,
                                player_effect_id,deathrattle_only=effect.deathrattle_only,destroy_after_play=effect.destroy_after_play)
        if player_effect_id is not None:
            from .player_effects import validate_modifier_owner
            validate_modifier_owner(r.state, r.registry, player.id, modifier)
        if attachment_id(r.state) != modifier.id:
            raise ResolutionError('Cost source allocation changed before installation')
        player.cost_modifiers.append(modifier)
        r.emit('cost_modifier_added', player_id=player.id, source_id=effect.source_id, modifier_id=modifier.id)
        return
    entity = r.state.entities.get(effect.target_id)
    dormant = (allow_dormant and entity is not None and entity.zone == Zone.BOARD and
               entity.dormancy is not None and entity.health > 0 and not entity.doomed)
    if entity is None or not entity.active and not dormant:
        r.stale(effect, effect.target_id)
        return
    if isinstance(effect, GrantCostAura):
        if entity.zone not in (Zone.BOARD, Zone.WEAPON):
            r.stale(effect, entity.id)
            return
        attachment = AbilityInstance(attachment_id(r.state), 'cost_aura', source_id=effect.source_id,
                                     cost_aura=spec, expires_turn=effect.expires_turn)
        entity.abilities.append(attachment)
    else:
        kind = r.registry.card(entity.card_id).kind
        if kind == CardType.HERO and (not r.registry.card(entity.card_id).hero_card or entity.zone not in (Zone.HAND, Zone.DECK)):
            raise ResolutionError('Hero entities have no playable cost')
        if not matches_cost(spec, r.registry.card(entity.card_id), entity):
            r.emit('effect_skipped', target_id=entity.id, reason='cost_filter_mismatch', effect='ModifyCost')
            return
        attachment = attach_cost(r.state, entity, spec, effect.source_id, effect.expires_turn)
    r.emit('cost_modified', target_id=entity.id, source_id=effect.source_id, attachment_id=attachment.id)
