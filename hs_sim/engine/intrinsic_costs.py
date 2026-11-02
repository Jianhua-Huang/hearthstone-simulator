"""Pure conditional intrinsic price stage, before physical local attachments.

Each finite policy retains its complete original history or zone operand.
It neither writes an entity cache nor allocates or consumes a cost source.
"""
from copy import deepcopy
from dataclasses import replace

from .model import (CardType, IntrinsicCostOperationFact, IntrinsicCostSpec,
                    IntrinsicCostStageFact, OwnerTurnQueryBoundaryFact, PlayedTypeQuery, HeroHealedTurnMatch, CurrentDeckCountMatch, PermanentManaMatch, HandOtherClassMatch,
                    CostPresenceMatch, PRESENCE_COST_CONDITIONS, DeckShuffleCostMatch, LocationUseCostMatch, CardDiscoveredTurnMatch, HeldOpponentCopyMatch, PreviousOwnerSpellCastMatch)
from .owner_turns import (query_for_definition, query_previous_owner_turn,
                          share_tribes, validate_accepted_prefix, validate_face,
                          validate_history)


from .deck_shuffles import intrinsic_amount

PROFILE = 'cost.intrinsic.before-local-v1'


def validate_definition_intrinsics(definition):
    from .previous_turn_spell_costs import validate_definition as validate_previous_cast_price
    validate_previous_cast_price(definition)
    from .held_opponent_copies import validate_definition as validate_held_copies
    validate_held_copies(definition)
    if type(definition.pay_health_if_hero_healed)is not bool:raise ValueError('Conditional health payment requires bool')
    if definition.pay_health_if_hero_healed:
        if definition.cost_payment.value!='mana' or definition.intrinsic_costs!=(IntrinsicCostSpec(
                condition='hero_healed_this_turn',history_profile_id='healing.hero-this-turn-v1'),):
            raise ValueError('Conditional health payment requires the sole original hero-healed fact without amount changes')
    from .board_minion_costs import validate_definition as validate_board_cost
    from .hand_count_costs import validate_definition as validate_hand_cost
    from .hero_missing_health_costs import validate_definition as validate_hero_cost
    from .player_spell_count_costs import validate_definition as validate_personal_cost
    validate_board_cost(definition)
    validate_hand_cost(definition)
    validate_hero_cost(definition)
    validate_personal_cost(definition)
    from .player_hero_power_count_costs import validate_definition as validate_power_cost
    validate_power_cost(definition)
    from .player_spell_mana_costs import validate_definition as validate_mana_cost
    validate_mana_cost(definition)
    from .minion_death_costs import validate_definition as validate_death_cost
    validate_death_cost(definition)
    from .player_overload_costs import validate_definition as validate_overload_cost
    validate_overload_cost(definition)
    from .player_played_class_costs import validate_definition as validate_class_cost
    validate_class_cost(definition)
    from .hero_health_change_costs import validate_definition as validate_health_cost
    validate_health_cost(definition)
    from .player_draw_count_costs import validate_definition as validate_draw_cost
    validate_draw_cost(definition)
    from .player_weapon_attack_costs import validate_definition as validate_weapon_cost
    validate_weapon_cost(definition)
    from .player_armor_costs import validate_definition as validate_armor_cost
    validate_armor_cost(definition)
    from .player_summon_count_costs import validate_definition as validate_summon_cost
    validate_summon_cost(definition)
    from .player_elemental_streak_costs import validate_definition as validate_streak_cost
    validate_streak_cost(definition)
    from .player_corpse_spend_costs import validate_definition as validate_corpse_cost
    validate_corpse_cost(definition)
    from .hero_damage_taken_costs import validate_definition as validate_damage_cost
    validate_damage_cost(definition)
    from .spell_damage_costs import validate_definition as validate_spell_damage_cost
    validate_spell_damage_cost(definition)
    from .character_attack_costs import validate_definition as validate_character_cost
    validate_character_cost(definition)
    if definition.intrinsic_costs and definition.intrinsic_costs[0].condition in ('own_deck_shuffle_count','own_location_use_count'):
        from dataclasses import fields
        if definition.kind != CardType.MINION or len(definition.intrinsic_costs) != 1 or any(getattr(definition,f.name) is not None for f in fields(definition) if f.name.endswith('_cost')):
            raise ValueError('Shuffle pricing requires one independent ordinary Minion formula')
    rules = definition.intrinsic_costs
    if type(rules) is not tuple or any(type(r) is not IntrinsicCostSpec for r in rules):
        raise ValueError('Intrinsic costs require complete immutable declarations')
    for rule in rules:
        rule.__post_init__()
    allowed_kinds=(CardType.MINION,CardType.WEAPON,CardType.LOCATION) if rules and rules[0].condition=='controlled_card' else (CardType.MINION,CardType.SPELL)
    if rules and (definition.kind not in allowed_kinds
                  or not definition.hand_playable):
        raise ValueError('Previous-owner intrinsic costs require a physical Minion or Spell')
    if len({rule.condition for rule in rules}) > 1:
        raise ValueError('Mixed intrinsic history conditions require a real reviewed source')
    if rules and rules[0].condition in ('current_deck_count', 'permanent_mana_at_least', 'hand_other_class'):
        expected_kind = CardType.MINION if rules[0].history_profile_id == 'deck.current-count-as-cost-v1' else CardType.SPELL
        if expected_kind == CardType.MINION:
            from .stat_relations import validate_ordinary_face
            validate_ordinary_face(definition)
        if definition.kind != expected_kind or len(rules) != 1 or any(value is not None for value in (
                definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost, definition.player_spell_count_cost, definition.player_hero_power_count_cost, definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost, definition.player_played_class_cost, definition.hero_health_change_cost, definition.player_draw_count_cost, definition.player_weapon_attack_cost, definition.player_armor_cost, definition.player_summon_count_cost, definition.player_elemental_streak_cost, definition.player_corpse_spend_cost, definition.hero_damage_taken_cost)):
            raise ValueError('Current deck price requires one physical Spell discount without other intrinsic formulas')
    if rules and rules[0].condition == 'hero_healed_this_turn' and definition.kind != CardType.MINION:
        raise ValueError('Hero-healed intrinsic condition requires an ordinary physical Minion')
    if rules and rules[0].condition == 'card_discovered_this_turn':
        from dataclasses import fields
        if (definition.kind != CardType.SPELL or len(rules) != 1 or
                any(getattr(definition, f.name) is not None for f in fields(definition) if f.name.endswith('_cost'))):
            raise ValueError('Discovery price requires one independent physical Spell rule')
    if rules and rules[0].condition in PRESENCE_COST_CONDITIONS:
        from .stat_relations import validate_ordinary_face
        expected_kind = CardType.SPELL if rules[0].condition in ('hand_edge', 'controlled_legendary') else CardType.MINION
        allowed_kinds=(CardType.MINION,CardType.WEAPON,CardType.LOCATION) if rules[0].condition=='controlled_card' else (expected_kind,)
        if definition.kind not in allowed_kinds or len(rules) != 1:
            raise ValueError('Presence condition requires one ordinary physical Minion rule')
        if definition.kind == CardType.MINION: validate_ordinary_face(definition)
    if rules and rules[0].condition == 'hero_healed_this_turn':
        from .stat_relations import validate_ordinary_face
        validate_ordinary_face(definition)
    if rules and rules[0].condition in ('previous_owner_turn_elemental', 'hero_healed_this_turn') and any(value is not None for value in (
            definition.board_minion_cost, definition.hand_count_cost, definition.hero_missing_health_cost,
            definition.player_spell_count_cost, definition.player_hero_power_count_cost,
            definition.player_spell_mana_cost, definition.minion_death_cost, definition.player_overload_cost,
            definition.player_played_class_cost, definition.hero_health_change_cost,
            definition.player_draw_count_cost, definition.player_weapon_attack_cost,
            definition.player_armor_cost, definition.player_summon_count_cost, definition.player_elemental_streak_cost)):
        from .crafted_faces import native_death_heal_price
        from dataclasses import fields
        # The actual Nefarius pool can pair a death-count Dragon with a
        # hero-healed Undead. Keep the existing death stage followed by the
        # ordinary zero assignment; neither formula is folded into a cache.
        if (not native_death_heal_price(definition.id,definition.kind,rules,definition.minion_death_cost) or
                any(getattr(definition,f.name) is not None for f in fields(definition)
                    if f.name.endswith('_cost') and f.name!='minion_death_cost')):
            raise ValueError('Multiple intrinsic formulas require a real reviewed source')


def _capture_current_deck_match(state, registry, player_id, rule):
    """Retain the full original physical inventory; no mutable count cache."""
    from .deck_conditions import DeckCountCondition, matches_deck_condition
    from .model import Zone
    rule.__post_init__()
    condition = DeckCountCondition(rule.card_count, rule.comparison)
    matched = matches_deck_condition(state, registry, player_id, condition)
    deck = tuple(state.players[player_id].deck)
    for eid in deck:
        entity = state.entities[eid]
        if entity.id != eid or entity.zone != Zone.DECK or entity.controller != player_id:
            raise ValueError('Deck-count price inventory differs from its physical zone/controller')
        if registry.card(entity.card_id).kind != entity.kind:
            raise ValueError('Deck-count price contains an unknown or inconsistent physical definition')
    return CurrentDeckCountMatch(player_id, state.turn, state.action_number,
        state.next_entity_id, deck, rule.card_count, rule.comparison, matched)


def _condition_query(definition):
    """One finite source query; the original same-subject policy stays unchanged."""
    if definition.intrinsic_costs[0].condition == 'previous_owner_turn_elemental':
        return PlayedTypeQuery(CardType.MINION, ('elemental',))
    if definition.intrinsic_costs[0].condition == 'hero_healed_this_turn':
        raise ValueError('Hero-healed condition uses its actual target history')
    return query_for_definition(definition)


def capture_intrinsic_stage(state, registry, player_id, card_id, base_cost, *, source_id=None):
    from .board_minion_costs import capture
    from .hand_count_costs import capture as capture_hand
    from .hero_missing_health_costs import capture as capture_hero
    from .player_spell_count_costs import capture as capture_personal
    definition = registry.card(card_id)
    board = capture(state, registry, player_id, definition, base_cost)
    hand = capture_hand(state, registry, player_id, definition, base_cost, source_id)
    hero = capture_hero(state, registry, player_id, definition, base_cost)
    personal = capture_personal(state, registry, player_id, definition, base_cost)
    from .player_hero_power_count_costs import capture as capture_powers
    powers = capture_powers(state, registry, player_id, definition, base_cost)
    from .player_spell_mana_costs import capture as capture_mana
    mana = capture_mana(state, registry, player_id, definition, base_cost)
    from .minion_death_costs import capture as capture_deaths
    deaths = capture_deaths(state, registry, player_id, definition, base_cost)
    from .player_overload_costs import capture as capture_overload
    overload = capture_overload(state, registry, player_id, definition, base_cost)
    from .player_played_class_costs import capture as capture_class
    played_class = capture_class(state, registry, player_id, definition, base_cost)
    from .hero_health_change_costs import capture as capture_health
    health_changes = capture_health(state, registry, player_id, definition, base_cost)
    from .player_draw_count_costs import capture as capture_draws
    draws = capture_draws(state, registry, player_id, definition, base_cost)
    from .player_weapon_attack_costs import capture as capture_weapon
    weapon = capture_weapon(state, registry, player_id, definition, base_cost)
    from .player_armor_costs import capture as capture_armor
    armor = capture_armor(state, registry, player_id, definition, base_cost)
    from .player_summon_count_costs import capture as capture_summons
    summons = capture_summons(state, registry, player_id, definition, base_cost)
    from .player_elemental_streak_costs import capture as capture_streak
    streak = capture_streak(state, registry, player_id, definition, base_cost)
    from .player_corpse_spend_costs import capture as capture_corpses
    corpses = capture_corpses(state, registry, player_id, definition, base_cost)
    from .hero_damage_taken_costs import capture as capture_damage
    damage = capture_damage(state, registry, player_id, definition, base_cost)
    from .spell_damage_costs import capture as capture_spell_damage
    spell_damage = capture_spell_damage(state, registry, player_id, definition, base_cost)
    from .character_attack_costs import capture as capture_character_attacks
    character_attacks = capture_character_attacks(state, registry, player_id, definition, base_cost)
    from .runtime_queries import audit_query_inputs
    return _capture_stage(state, registry, player_id, card_id, base_cost, board, hand, hero, personal,
                          powers, mana, deaths, overload, played_class, health_changes, draws, weapon, armor, summons, streak, corpses, damage, spell_damage, character_attacks, source_id=source_id,
                          _audit_history=audit_query_inputs(registry))


def _capture_stage(state, registry, player_id, card_id, base_cost, board, hand, hero, personal,
                   powers, mana, deaths, overload, played_class, health_changes, draws, weapon, armor, summons, streak, corpses, damage, spell_damage, character_attacks, *, current_deck=None, permanent_mana=None, current_hand_class=None, current_presence=None, current_shuffle=None, current_location_uses=None, current_discovery=None, current_held_copy=None, source_id=None, current_kindred=None, current_previous_cast=None, _audit_history=True):
    """Retained replay passes frozen original quantity/zone operands, never today's zones.

Original payment/window proof uses capture_intrinsic_stage to requery the
complete actual zone inventories. Compact history cannot authenticate an unsigned origin.
"""
    from .costs import apply_cost
    definition = registry.card(card_id)
    validate_definition_intrinsics(definition)
    if _audit_history:
        validate_history(state, registry)
    boundary = OwnerTurnQueryBoundaryFact(state.turn, state.action_number,
        state.status, len(state.owner_turn_history), len(state.play_history),
        state.owner_turn_history[-1] if state.owner_turn_history else None,
        None if state.opening is None else state.opening.stage,
        None if state.opening is None else state.opening.first_player)
    # Query validates every relevant row before returning the aggregate.
    from .healing_history import capture_hero_healed_turn
    from .hand_conditions import capture_hand_other_class
    from .cost_presence import capture as capture_presence
    from .deck_shuffles import capture_cost as capture_shuffles
    from .location_uses import capture_cost as capture_location_uses
    from .card_discoveries import capture_turn_match
    from .held_opponent_copies import capture_cost as capture_held_copy
    from .previous_turn_spell_costs import capture as capture_previous_cast
    conditions = (() if not definition.intrinsic_costs else
        (current_previous_cast if current_previous_cast is not None else capture_previous_cast(state,registry,player_id,boundary),)
            if definition.intrinsic_costs[0].condition == 'previous_owner_turn_spell_cast' else
        (current_held_copy if current_held_copy is not None else capture_held_copy(state, registry, player_id, source_id),)
            if definition.intrinsic_costs[0].condition == 'held_opponent_copy' else
        (current_discovery if current_discovery is not None else capture_turn_match(state, player_id),)
            if definition.intrinsic_costs[0].condition == 'card_discovered_this_turn' else
        (current_location_uses if current_location_uses is not None else capture_location_uses(state,player_id),) if definition.intrinsic_costs[0].condition == 'own_location_use_count' else
        (current_shuffle if current_shuffle is not None else capture_shuffles(state,player_id),) if definition.intrinsic_costs[0].condition == 'own_deck_shuffle_count' else
        (current_presence if current_presence is not None else capture_presence(state,registry,player_id,
            definition.intrinsic_costs[0].condition,source_id,card_ids=definition.intrinsic_costs[0].card_ids),)
            if definition.intrinsic_costs[0].condition in PRESENCE_COST_CONDITIONS else
        (current_hand_class if current_hand_class is not None else capture_hand_other_class(state,registry,player_id),)
            if definition.intrinsic_costs[0].condition == 'hand_other_class' else
        (permanent_mana if permanent_mana is not None else PermanentManaMatch(player_id,state.turn,
            state.action_number,state.players[player_id].max_mana,definition.intrinsic_costs[0].mana_crystals),)
            if definition.intrinsic_costs[0].condition == 'permanent_mana_at_least' else
        (current_deck if current_deck is not None else _capture_current_deck_match(state, registry, player_id, definition.intrinsic_costs[0]),) if definition.intrinsic_costs[0].condition == 'current_deck_count' else
        (capture_hero_healed_turn(state, player_id),) if definition.intrinsic_costs[0].condition == 'hero_healed_this_turn' else
        (query_previous_owner_turn(state, player_id, _condition_query(definition)),))
    count = (board if board is not None else hand if hand is not None else
             hero if hero is not None else personal if personal is not None else
             powers if powers is not None else mana if mana is not None else
             deaths if deaths is not None else overload if overload is not None else
             played_class if played_class is not None else health_changes if health_changes is not None else
             draws if draws is not None else weapon if weapon is not None else
             armor if armor is not None else summons if summons is not None else
             streak if streak is not None else corpses if corpses is not None else
             damage if damage is not None else spell_damage if spell_damage is not None else character_attacks)
    amount, operations = base_cost if count is None else count.after, []
    from .kindred import sources as kindred_sources
    profile=registry.kindred_profiles.get(card_id)
    kindreds=(kindred_sources(state,registry,player_id)if current_kindred is None else current_kindred)if profile is not None and profile.mode=='cost'else()
    for index, rule in enumerate(definition.intrinsic_costs):
        matched = conditions[0].matched
        after=amount
        if matched:
            for _ in range(2 if kindreds else 1):after=intrinsic_amount(after,rule,conditions[0])
        operations.append(IntrinsicCostOperationFact(index, rule, 0, matched, amount, after))
        amount = after
    return IntrinsicCostStageFact(PROFILE, player_id, card_id, definition.kind,
        definition.cost, base_cost, amount, boundary, definition.intrinsic_costs,
        conditions, tuple(operations), board, hand, hero, personal, powers, mana, deaths, overload,
        played_class, health_changes, draws, weapon, armor, summons, streak, corpses, damage, spell_damage, character_attacks,kindreds)


def validate_intrinsic_stage_fact(registry, fact):
    """Replay all saved true/false rows and ordered operations, without live quotes."""
    from .costs import apply_cost
    if type(fact) is not IntrinsicCostStageFact:
        raise ValueError('Cost quote requires its complete intrinsic stage')
    fact.__post_init__()
    definition = registry.card(fact.card_id)
    validate_definition_intrinsics(definition)
    from .kindred import validate_sources
    validate_sources(registry,fact.kindred_sources)
    profile=registry.kindred_profiles.get(fact.card_id)
    if fact.kindred_sources and(profile is None or profile.mode!='cost'):
        raise ValueError('Intrinsic repeat sources have no native Kindred cost declaration')
    from .board_minion_costs import validate_fact as validate_board_fact
    validate_board_fact(registry, definition, fact.board_minions)
    from .hand_count_costs import validate_fact as validate_hand_fact
    validate_hand_fact(definition, fact.hand_cards, registry)
    from .hero_missing_health_costs import validate_fact as validate_hero_fact
    validate_hero_fact(registry, definition, fact.hero_missing_health)
    from .player_spell_count_costs import validate_fact as validate_personal_fact
    validate_personal_fact(registry, definition, fact.player_spells)
    from .player_hero_power_count_costs import validate_fact as validate_power_fact
    validate_power_fact(registry, definition, fact.player_hero_powers)
    from .player_spell_mana_costs import validate_fact as validate_mana_fact
    validate_mana_fact(registry, definition, fact.player_spell_mana)
    from .minion_death_costs import validate_fact as validate_death_fact
    validate_death_fact(registry, definition, fact.minion_deaths)
    from .player_overload_costs import validate_fact as validate_overload_fact
    validate_overload_fact(registry, definition, fact.player_overload)
    from .player_played_class_costs import validate_fact as validate_class_fact
    validate_class_fact(registry, definition, fact.player_played_class)
    from .hero_health_change_costs import validate_fact as validate_health_fact
    validate_health_fact(registry, definition, fact.hero_health_changes)
    from .player_draw_count_costs import validate_fact as validate_draw_fact
    validate_draw_fact(registry, definition, fact.player_draws)
    from .player_weapon_attack_costs import validate_fact as validate_weapon_fact
    validate_weapon_fact(registry, definition, fact.weapon_attack)
    from .player_armor_costs import validate_fact as validate_armor_fact
    validate_armor_fact(registry, definition, fact.player_armor)
    from .player_summon_count_costs import validate_fact as validate_summon_fact
    validate_summon_fact(registry, definition, fact.player_summons)
    from .player_elemental_streak_costs import validate_fact as validate_streak_fact
    validate_streak_fact(registry, definition, fact.player_elemental_streak)
    from .player_corpse_spend_costs import validate_fact as validate_corpse_fact
    validate_corpse_fact(registry, definition, fact.player_corpses)
    from .hero_damage_taken_costs import validate_fact as validate_damage_fact
    validate_damage_fact(registry, definition, fact.hero_damage_taken)
    from .spell_damage_costs import validate_fact as validate_spell_damage_fact
    validate_spell_damage_fact(registry, definition, fact.player_spell_damage)
    from .character_attack_costs import validate_fact as validate_character_fact
    validate_character_fact(registry, definition, fact.player_character_attacks)
    if (fact.kind, fact.printed_cost, fact.rules) != (definition.kind, definition.cost, definition.intrinsic_costs):
        raise ValueError('Frozen intrinsic stage differs from its pinned declaration')
    if fact.rules and fact.rules[0].condition == 'previous_owner_turn_spell_cast':
        from .previous_turn_spell_costs import validate_match as validate_previous_cast_match
        validate_previous_cast_match(fact.condition_facts[0],registry)
    elif fact.rules and fact.rules[0].condition == 'held_opponent_copy':
        # Typed shape, independent declaration and exact original window are
        # checked above. Live history qualification is checked by validate_match
        # in validate_accepted_intrinsic_prefix, never an owner-turn query.
        fact.condition_facts[0].__post_init__()
    elif fact.rules and fact.rules[0].condition == 'own_location_use_count':
        from .location_uses import validate_cost_match
        validate_cost_match(fact.condition_facts[0],registry)
    elif fact.rules and fact.rules[0].condition == 'own_deck_shuffle_count':
        fact.condition_facts[0].__post_init__()
    elif fact.rules and fact.rules[0].condition in PRESENCE_COST_CONDITIONS:
        from .cost_presence import validate_match
        validate_match(fact.condition_facts[0],registry)
    elif fact.rules and fact.rules[0].condition == 'current_deck_count':
        condition = fact.condition_facts[0]
        if (condition.card_count, condition.comparison) != (definition.intrinsic_costs[0].card_count, definition.intrinsic_costs[0].comparison):
            raise ValueError('Frozen current deck condition changed its printed threshold')
    elif fact.rules and fact.rules[0].condition == 'hand_other_class':
        from .hand_conditions import validate_hand_other_class_match
        validate_hand_other_class_match(fact.condition_facts[0],registry)
    elif fact.rules and fact.rules[0].condition == 'permanent_mana_at_least':
        if fact.condition_facts[0].threshold != definition.intrinsic_costs[0].mana_crystals:
            raise ValueError('Frozen permanent mana condition changed its printed threshold')
    elif fact.rules and fact.rules[0].condition == 'card_discovered_this_turn':
        from .card_discoveries import validate_turn_match
        validate_turn_match(fact.condition_facts[0], registry)
    elif fact.rules and fact.rules[0].condition == 'hero_healed_this_turn':
        from .healing_history import validate_hero_healed_match
        validate_hero_healed_match(fact.condition_facts[0], registry)
    elif fact.rules:
        condition = fact.condition_facts[0]
        if condition.query != _condition_query(definition):
            raise ValueError('Frozen intrinsic condition changed its printed subject')
        # Validate every row, including later unknown/false rows after a true one.
        expected = []
        if condition.query.kind == CardType.MINION and condition.query.tribes is None:
            raise ValueError('Intrinsic subject has unknown Minion tribes')
        for row in condition.rows:
            validate_face(row.face, registry)
            if condition.query.kind == CardType.MINION:
                tribes = None if row.face.metadata is None else row.face.metadata.tribes
                expected.append(share_tribes(condition.query.tribes, tribes))
            else:
                expected.append(condition.query.spell_school is not None
                                and condition.query.spell_school == row.face.spell_school)
        if tuple(expected) != tuple(row.matched for row in condition.rows):
            raise ValueError('Frozen intrinsic relation changed a complete true/false row')
        if any(expected) != condition.matched:
            raise ValueError('Frozen intrinsic aggregate differs from its complete relation')
    count = (fact.board_minions if fact.board_minions is not None else
             fact.hand_cards if fact.hand_cards is not None else
             fact.hero_missing_health if fact.hero_missing_health is not None else
             fact.player_spells if fact.player_spells is not None else
             fact.player_hero_powers if fact.player_hero_powers is not None else
             fact.player_spell_mana if fact.player_spell_mana is not None else
             fact.minion_deaths if fact.minion_deaths is not None else
             fact.player_overload if fact.player_overload is not None else
             fact.player_played_class if fact.player_played_class is not None else
             fact.hero_health_changes if fact.hero_health_changes is not None else
             fact.player_draws if fact.player_draws is not None else
             fact.weapon_attack if fact.weapon_attack is not None else
             fact.player_armor if fact.player_armor is not None else
             fact.player_summons if fact.player_summons is not None else
             fact.player_elemental_streak if fact.player_elemental_streak is not None else
             fact.player_corpses if fact.player_corpses is not None else
             fact.hero_damage_taken if fact.hero_damage_taken is not None else
             fact.player_spell_damage if fact.player_spell_damage is not None else fact.player_character_attacks)
    amount = fact.base_cost if count is None else count.after
    for index, operation in enumerate(fact.operations):
        rule = fact.rules[index]
        matched = fact.condition_facts[operation.condition_index].matched
        after=amount
        if matched:
            for _ in range(2 if fact.kindred_sources else 1):after=intrinsic_amount(after,rule,fact.condition_facts[operation.condition_index])
        if (operation.before, operation.after, operation.applied) != (amount, after, matched):
            raise ValueError('Frozen intrinsic operation differs from its complete condition or order')
        amount = after
    if amount != fact.amount:
        raise ValueError('Frozen intrinsic result differs from its ordered operations')


def validate_intrinsic_origin(fact, state, registry):
    validate_intrinsic_stage_fact(registry, fact)
    source_id = None if fact.hand_cards is None else fact.hand_cards.subject_id
    if fact.condition_facts and type(fact.condition_facts[0]) is CostPresenceMatch:
        source_id = fact.condition_facts[0].source_id
    if capture_intrinsic_stage(state, registry, fact.player_id, fact.card_id, fact.base_cost, source_id=source_id) != fact:
        raise ValueError('Intrinsic stage changed its complete original quotation window')


def validate_generated_quote_fact(registry, fact):
    from .model import GeneratedCostQuoteFact
    from .costs import apply_cost, matches_cost, matches_cost_contribution, is_final_floor, final_floor
    if type(fact) is not GeneratedCostQuoteFact:
        raise ValueError('Expected a complete generated quote fact')
    fact.__post_init__()
    validate_intrinsic_stage_fact(registry, fact.intrinsic)
    value = fact.quote_input
    definition = registry.card(value.card_id)
    native_numbers = definition.kind == CardType.SPELL and value.card_id in registry.remaining_mana_numbers_profiles
    expected_base = max(1, value.mana_numbers) if native_numbers and value.mana_numbers is not None else definition.cost
    if (not definition.hand_playable or definition.kind != value.kind or value.base_cost != expected_base or
            native_numbers != (value.mana_numbers is not None)):
        raise ValueError('Generated quote changed its pinned printed base')
    from .costs import intrinsic_payment
    amount, payment = fact.intrinsic.amount, intrinsic_payment(definition,fact.intrinsic)
    if value.initial_cost is not None:
        spec = value.initial_cost
        if not matches_cost(spec, definition):
            raise ValueError('Generated initial cost does not match its printed subject')
        amount = apply_cost(amount, spec.delta, spec.set_to, spec.minimum)
        if spec.payment is not None: payment = spec.payment
    if (amount, payment) != (fact.local_amount, fact.local_payment):
        raise ValueError('Generated local result differs from its complete initial operation')
    for contribution in fact.contributions:
        if contribution.modifier is not None:
            spec = contribution.modifier.spec
        else:
            aura = contribution.ability.cost_aura
            from .costs import cost_aura_payer_matches
            if not cost_aura_payer_matches(aura.relation,contribution.player_id,value.player_id):
                raise ValueError('Generated aura relation changed its hypothetical payer')
            spec = aura.cost
        from .cost_polarities import validate_basis as validate_polarity_basis
        validate_polarity_basis(registry,contribution,fact.local_amount)
        if not matches_cost_contribution(registry, contribution, definition, None,complete_amount=fact.amount):
            raise ValueError('Generated external operation does not match its printed subject')
        if not is_final_floor(contribution):
            amount = apply_cost(amount, spec.delta, spec.set_to, spec.minimum)
        if spec.payment is not None: payment = spec.payment
    if (max(amount, value.minimum_cost, final_floor(fact.contributions)), payment) != (fact.amount, fact.payment):
        raise ValueError('Generated result differs from its complete ordered operations')


def validate_intrinsic_history_prefix(fact, state, registry, *, _within_cast_history_check=False):
    """Bind a saved query boundary to the retained timeline, allowing real progress.

    Full original payment/acceptance states separately authenticate capture.
    This compact check does not authenticate an unsigned archive's provenance.
    """
    validate_intrinsic_stage_fact(registry, fact)
    boundary = fact.boundary
    for source in fact.kindred_sources:
        if(source.id>=state.next_attachment_id or source.entered_order>=state.next_order or
                source.created_turn>boundary.turn or source.source_id not in state.entities):
            raise ValueError('Intrinsic Kindred source changed its original physical allocation prefix')
    if fact.board_minions is not None and (fact.board_minions.next_entity_id > state.next_entity_id or
            any(row.entity_id not in state.entities for board in fact.board_minions.boards for row in board)):
        raise ValueError('Board cost lost its original physical allocation prefix')
    if fact.board_minions is not None and fact.board_minions.next_attachment_id is not None:
        if fact.board_minions.next_attachment_id > state.next_attachment_id or any(
                change.source_id is not None and change.source_id not in state.entities
                for board in fact.board_minions.boards for row in board for change in row.tribe_changes or ()):
            raise ValueError('Board tribe cost lost its original physical allocation prefix')
    hand = fact.hand_cards
    if hand is not None and (hand.next_entity_id > state.next_entity_id or
            any(eid not in state.entities for ids in hand.hands for eid in ids) or
            (hand.subject_id is not None and hand.subject_id not in state.entities)):
        raise ValueError('Hand count lost its original physical allocation prefix')
    from .model import CoinHandCountCostFact
    if type(hand) is CoinHandCountCostFact and any(ref.zone_epoch > state.entities[ref.entity_id].zone_epoch
            for rows in hand.faces for ref in rows):
        raise ValueError('Coin price contains a future original hand residence')
    hero = fact.hero_missing_health
    if hero is not None and (hero.next_entity_id > state.next_entity_id or hero.hero_id not in state.entities):
        raise ValueError('Hero price lost its original physical allocation prefix')
    if hero is not None:
        retained = state.entities[hero.hero_id]
        # Hero replacement retains the old physical hero, with its original face
        # and ownership. Health/stat changes may progress; heroes cannot transform
        # or change control through the minion-only lifecycle operations.
        if (retained.kind, retained.owner, retained.controller, retained.card_id) != (
                CardType.HERO, hero.player_id, hero.player_id, hero.hero_card_id):
            raise ValueError('Hero price borrowed another physical hero or changed its retained identity')
    if fact.player_spells is not None:
        from .player_spell_count_costs import validate_prefix
        validate_prefix(fact.player_spells, state, registry,
                        _within_cast_history_check=_within_cast_history_check)
    if fact.player_hero_powers is not None:
        from .player_hero_power_count_costs import validate_prefix as validate_power_prefix
        validate_power_prefix(fact.player_hero_powers, state, registry)
    if fact.player_spell_mana is not None:
        from .player_spell_mana_costs import validate_prefix as validate_mana_prefix
        validate_mana_prefix(fact.player_spell_mana, state, registry)
    if fact.minion_deaths is not None:
        from .minion_death_costs import validate_prefix as validate_death_prefix
        validate_death_prefix(fact.minion_deaths, state, registry)
    if fact.player_overload is not None:
        from .player_overload_costs import validate_prefix as validate_overload_prefix
        validate_overload_prefix(fact.player_overload, state, registry)
    if fact.player_played_class is not None:
        from .player_played_class_costs import validate_prefix as validate_class_prefix
        validate_class_prefix(fact.player_played_class, state, registry)
    if fact.hero_health_changes is not None:
        from .hero_health_change_costs import validate_prefix as validate_health_prefix
        validate_health_prefix(fact.hero_health_changes, state, registry)
    if fact.player_draws is not None:
        from .player_draw_count_costs import validate_prefix as validate_draw_prefix
        validate_draw_prefix(fact.player_draws, state, registry)
    if fact.weapon_attack is not None:
        from .player_weapon_attack_costs import validate_prefix as validate_weapon_prefix
        validate_weapon_prefix(fact.weapon_attack, state, registry)
    if fact.player_armor is not None:
        from .player_armor_costs import validate_prefix as validate_armor_prefix
        validate_armor_prefix(fact.player_armor, state, registry)
    if fact.player_summons is not None:
        from .player_summon_count_costs import validate_prefix as validate_summon_prefix
        validate_summon_prefix(fact.player_summons, state, registry)
    if fact.player_elemental_streak is not None:
        from .player_elemental_streak_costs import validate_prefix as validate_streak_prefix
        validate_streak_prefix(fact.player_elemental_streak, state, registry)
    if fact.player_corpses is not None:
        from .player_corpse_spend_costs import validate_prefix as validate_corpse_prefix
        validate_corpse_prefix(fact.player_corpses, state, registry)
    if fact.hero_damage_taken is not None:
        from .hero_damage_taken_costs import validate_prefix as validate_damage_prefix
        validate_damage_prefix(fact.hero_damage_taken, state, registry)
    if fact.player_spell_damage is not None:
        from .spell_damage_costs import validate_prefix as validate_spell_damage_prefix
        validate_spell_damage_prefix(fact.player_spell_damage, state, registry)
    if fact.player_character_attacks is not None:
        from .character_attack_costs import validate_prefix as validate_character_prefix
        validate_character_prefix(fact.player_character_attacks, state, registry)
    if fact.condition_facts and type(fact.condition_facts[0]) is PreviousOwnerSpellCastMatch:
        from .previous_turn_spell_costs import validate_prefix as validate_previous_cast_prefix
        validate_previous_cast_prefix(fact.condition_facts[0],state,registry,_within_cast_history_check=_within_cast_history_check)
    if (boundary.owner_history_length > len(state.owner_turn_history)
            or boundary.play_history_length > len(state.play_history)
            or boundary.action > state.action_number or boundary.turn > state.turn):
        raise ValueError('Intrinsic quotation lost its complete history prefix')
    if fact.condition_facts and type(fact.condition_facts[0]) is CurrentDeckCountMatch:
        condition = fact.condition_facts[0]
        if condition.next_entity_id > state.next_entity_id or any(eid not in state.entities for eid in condition.deck):
            raise ValueError('Current deck price lost its original physical allocation prefix')
    if fact.condition_facts and type(fact.condition_facts[0]) is HandOtherClassMatch:
        from .hand_conditions import validate_hand_other_class_prefix
        validate_hand_other_class_prefix(fact.condition_facts[0],state,registry)
    if fact.condition_facts and type(fact.condition_facts[0]) is CostPresenceMatch:
        from .cost_presence import validate_prefix
        validate_prefix(fact.condition_facts[0],state,registry)
    if fact.condition_facts and type(fact.condition_facts[0]) is HeldOpponentCopyMatch:
        from .held_opponent_copies import validate_match
        validate_match(fact.condition_facts[0], state, registry)
    # This retained-history projection is consumed only by the pure validators
    # below. Every field we rewrite gets its own list/value; the other (often
    # large) inventories are read, never modified or passed to card callbacks.
    before = replace(state)
    if fact.condition_facts and type(fact.condition_facts[0]) is CardDiscoveredTurnMatch:
        from .card_discoveries import validate_turn_prefix
        condition = fact.condition_facts[0]
        validate_turn_prefix(condition, state, registry)
        before.card_discovery_history = list(condition.records)
    if fact.condition_facts and type(fact.condition_facts[0]) is LocationUseCostMatch:
        from .location_uses import validate_cost_prefix as validate_location_prefix
        condition=fact.condition_facts[0];validate_location_prefix(condition,state,registry)
        before.location_use_history=list(condition.records)
    if fact.condition_facts and type(fact.condition_facts[0]) is DeckShuffleCostMatch:
        from .deck_shuffles import validate_cost_prefix
        condition=fact.condition_facts[0];validate_cost_prefix(condition,state,registry)
        before.deck_shuffle_history=list(condition.records)
    if fact.condition_facts and type(fact.condition_facts[0]) is HeroHealedTurnMatch:
        from .healing_history import validate_hero_healed_prefix
        condition = fact.condition_facts[0]
        validate_hero_healed_prefix(condition, state, registry)
        before.healing_history = list(condition.records)
        before.next_healing_id = condition.next_healing_id
    before.turn, before.action_number, before.status = boundary.turn, boundary.action, boundary.status
    before.owner_turn_history = before.owner_turn_history[:boundary.owner_history_length]
    before.play_history = before.play_history[:boundary.play_history_length]
    if before.owner_turn_history:
        before.owner_turn_history[-1] = boundary.last_owner_turn
        before.active_player = boundary.last_owner_turn.player_id
    if boundary.opening_stage is None:
        if before.opening is not None:
            raise ValueError('Intrinsic scenario quotation invented an opening origin')
    else:
        if before.opening is None or before.opening.first_player != boundary.opening_first_player:
            raise ValueError('Intrinsic quotation changed its original opening identity')
        before.opening = replace(before.opening, stage=boundary.opening_stage,
            starting_hands=before.opening.starting_hands if boundary.opening_stage == 'complete' else None)
    validate_accepted_prefix(before, state, registry)
    expected = _capture_stage(before, registry, fact.player_id, fact.card_id, fact.base_cost,
                              fact.board_minions, fact.hand_cards, fact.hero_missing_health,
                              fact.player_spells, fact.player_hero_powers, fact.player_spell_mana, fact.minion_deaths,
                              fact.player_overload, fact.player_played_class, fact.hero_health_changes,
                              fact.player_draws, fact.weapon_attack, fact.player_armor, fact.player_summons, fact.player_elemental_streak, fact.player_corpses, fact.hero_damage_taken, fact.player_spell_damage, fact.player_character_attacks,
                              current_deck=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is CurrentDeckCountMatch else None,
                              permanent_mana=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is PermanentManaMatch else None,
                              current_hand_class=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is HandOtherClassMatch else None,
                              current_presence=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is CostPresenceMatch else None,
                              current_location_uses=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is LocationUseCostMatch else None,
                              current_shuffle=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is DeckShuffleCostMatch else None,
                              current_discovery=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is CardDiscoveredTurnMatch else None,
                              current_held_copy=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is HeldOpponentCopyMatch else None,
                              current_kindred=fact.kindred_sources,
                              current_previous_cast=fact.condition_facts[0] if fact.condition_facts and type(fact.condition_facts[0]) is PreviousOwnerSpellCastMatch else None)
    if expected != fact:
        raise ValueError('Intrinsic relation differs from its complete captured history prefix')
    # A closed selected interval cannot receive additional later hand submissions.
    if fact.condition_facts and type(fact.condition_facts[0]) not in (PreviousOwnerSpellCastMatch, HeroHealedTurnMatch, CardDiscoveredTurnMatch, CurrentDeckCountMatch, PermanentManaMatch, HandOtherClassMatch, CostPresenceMatch, DeckShuffleCostMatch, LocationUseCostMatch, HeldOpponentCopyMatch) and fact.condition_facts[0].owner_turn is not None:
        selected = fact.condition_facts[0]
        current_faces = tuple(play.played_face for play in state.play_history
            if (play.played_face.owner_turn_id, play.player_id, play.kind) ==
               (selected.owner_turn.id, fact.player_id, selected.query.kind))
        if current_faces != tuple(row.face for row in selected.rows):
            raise ValueError('Intrinsic closed interval lost a complete submitted-face row')
