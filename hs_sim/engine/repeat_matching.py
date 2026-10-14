"""Pure matching and strict static wire for accepted spell recipient metadata.

Callers supply the registered definition of PlayRecord.card_id and the hero
class from their own acceptance window. This module does not read live state.
"""
from .errors import ResolutionError
from .model import (CardClass, CardDefinition, CardMetadata, CardType, RecipientMetadataFilter,
                    RepeatMatchSpec, RepeatSourceEligibility, RepeatCostFilter,
                    CostQuoteFact, HandPlayCostReceipt, SpellCostFacts, SpellRepeatSpec, SpellSchool)


def validate_repeat_cost_declaration(registry, spec):
    """Check every declared cost policy before stale or matching short circuits."""
    if type(spec) is not SpellRepeatSpec:
        raise ValueError('Repeat cost declaration requires SpellRepeatSpec')
    spec.__post_init__()
    value = spec.match.recipient_cost if spec.match is not None else None
    if value is not None and value.basis == 'window_quote':
        registry.cost_query_profile(value.quote_profile_id).__post_init__()
    return value


def _validate_cost_input(registry, value):
    value.__post_init__()
    definition = registry.card(value.card_id)
    if definition.kind != value.kind:
        raise ValueError('Frozen cost quote face and physical kind disagree')
    from .repeat_source_conditions import validate_source_declaration
    for ability in value.abilities:
        if ability.spell_repeat is not None:
            validate_source_declaration(registry, ability.spell_repeat,
                allow_source=ability.kind == 'spell_repeat')
            validate_repeat_cost_declaration(registry, ability.spell_repeat)
    return definition


def validate_cost_quote_fact(registry, fact):
    """Recompute frozen operations without rejudging their current live sources."""
    from .costs import apply_cost, local_cost_values, matches_cost_contribution
    from .card_conditions import has_battlecry
    if type(fact) is not CostQuoteFact:
        raise ValueError('Cost history requires a complete CostQuoteFact')
    fact.__post_init__()
    if fact.profile_id is not None:
        registry.cost_query_profile(fact.profile_id).__post_init__()
    value = fact.quote_input
    definition = _validate_cost_input(registry, value)
    current_battlecry = has_battlecry(value.abilities)
    from .intrinsic_costs import validate_intrinsic_stage_fact
    validate_intrinsic_stage_fact(registry, fact.intrinsic)
    local = local_cost_values(fact.intrinsic.amount, value.enchantments,
        payment=definition.cost_payment)
    if local != (fact.local_amount, fact.local_payment):
        raise ValueError('Frozen local cost result differs from its complete operations')
    amount, payment = local
    for contribution in fact.contributions:
        if contribution.kind == 'local_enchantment':
            continue
        if contribution.kind == 'player_modifier':
            spec = contribution.modifier.spec
        else:
            aura = contribution.ability.cost_aura
            if (aura.relation != 'any' and
                    (contribution.player_id == value.player_id) != (aura.relation == 'friendly')):
                raise ValueError('Frozen cost aura payer relation does not match')
            spec = aura.cost
        if not matches_cost_contribution(registry, contribution, definition, current_battlecry, value.enchantments):
            raise ValueError('Frozen price contribution does not match its accepted input')
        amount = apply_cost(amount, spec.delta, spec.set_to, spec.minimum)
        if spec.payment is not None:
            payment = spec.payment
    if (max(amount, value.minimum_cost), payment) != (fact.amount, fact.payment):
        raise ValueError('Frozen complete cost result differs from its ordered operations')


def validate_spell_cost_facts(registry, facts):
    if type(facts) is not SpellCostFacts:
        raise ValueError('Spell cost history requires SpellCostFacts')
    facts.__post_init__()
    from .costs import local_cost_values
    definition = _validate_cost_input(registry, facts.cost_input)
    if definition.kind != CardType.SPELL or definition.cost != facts.printed_cost:
        raise ValueError('Spell cost facts differ from their registered accepted face')
    from .intrinsic_costs import validate_intrinsic_stage_fact
    validate_intrinsic_stage_fact(registry, facts.intrinsic)
    if local_cost_values(facts.intrinsic.amount, facts.cost_input.enchantments,
            payment=definition.cost_payment) != (facts.local_amount, facts.local_payment):
        raise ValueError('Spell cost facts differ from their local operations')
    for quote in facts.window_quotes:
        validate_cost_quote_fact(registry, quote)


def validate_spell_cost_history(state, registry):
    """Compact facts remain frozen; no current board price is queried here."""
    for play in state.play_history:
        play.__post_init__()
        submitted = play.submitted_cost
        if submitted is not None:
            validate_cost_quote_fact(registry, submitted.quote)
            if registry.card(submitted.quote.quote_input.card_id).cost != submitted.printed_cost:
                raise ValueError('Submitted cost printed face differs from its registered origin')
        for receipt in (play.spell_submission, play.spell_payload):
            if receipt is None:
                continue
            if receipt.cost_facts is not None:
                validate_spell_cost_facts(registry, receipt.cost_facts)
                value = receipt.cost_facts.cost_input
                if (value.source_id, value.player_id, value.card_id) != (play.source_id, play.player_id, play.card_id):
                    raise ValueError('Accepted Spell cost facts belong to another physical root')
                if submitted is None or value.minimum_cost != submitted.quote.quote_input.minimum_cost:
                    raise ValueError('Accepted-hand price must retain its submitted hand floor')
        if play.spell_submission is not None:
            for modifier in play.spell_submission.modifiers:
                validate_repeat_cost_declaration(registry, modifier.spec)
        if play.spell_payload is not None:
            for contributor in play.spell_payload.contributors:
                validate_repeat_cost_declaration(registry, contributor.ability.spell_repeat)


def _cost_matches(value, definition, submitted_cost, facts):
    if value is None:
        return True
    if type(facts) is not SpellCostFacts:
        raise ValueError('Cost-filtered Spell requires its original window cost facts')
    facts.__post_init__()
    if facts.card_id != definition.id or facts.printed_cost != definition.cost:
        raise ValueError('Spell cost facts belong to another accepted face')
    if value.basis == 'printed':
        amount = facts.printed_cost
    elif value.basis == 'local':
        amount = facts.local_amount
    elif value.basis == 'submitted_quote':
        if type(submitted_cost) is not HandPlayCostReceipt:
            raise ValueError('Submitted cost matching requires its payment-before receipt')
        submitted_cost.__post_init__()
        if (submitted_cost.quote.quote_input.source_id, submitted_cost.quote.quote_input.player_id) != (facts.cost_input.source_id, facts.cost_input.player_id):
            raise ValueError('Submitted cost receipt belongs to another physical Spell')
        amount = submitted_cost.quote.amount
    else:
        quotes = [q for q in facts.window_quotes if q.profile_id == value.quote_profile_id]
        if len(quotes) != 1:
            raise ValueError('Window cost matching requires its exact captured query profile')
        amount = quotes[0].amount
    return (value.minimum is None or amount >= value.minimum) and (value.maximum is None or amount <= value.maximum)


def spell_repeat_recipient_matches(spec: SpellRepeatSpec, *, recipient_definition: CardDefinition,
                         hero_class: CardClass | None, submitted_cost=None, cost_facts=None) -> bool:
    if type(spec) is not SpellRepeatSpec:
        raise ValueError('Spell repetition requires SpellRepeatSpec')
    spec.__post_init__()
    if type(recipient_definition) is not CardDefinition:
        raise ValueError('Spell matching requires an accepted CardDefinition')
    if type(recipient_definition.kind) is not CardType:
        raise ValueError('Spell matching requires a CardType')
    if recipient_definition.kind != CardType.SPELL:
        return False
    if recipient_definition.spell_school is not None and type(recipient_definition.spell_school) is not SpellSchool:
        raise ValueError('Spell matching requires a SpellSchool or None')
    if hero_class is not None and type(hero_class) is not CardClass:
        raise ValueError('Spell matching requires a CardClass or None')
    class_matches = True
    if spec.class_mode == 'other':
        if recipient_definition.metadata is None or hero_class in (None, CardClass.NEUTRAL):
            raise ResolutionError('Cross-class repeat requires known spell and current hero classes')
        if type(recipient_definition.metadata) is not CardMetadata:
            raise ValueError('Cross-class repeat requires CardMetadata')
        recipient_definition.metadata.__post_init__()
        classes = recipient_definition.metadata.classes
        class_matches = classes != (CardClass.NEUTRAL,) and hero_class not in classes
    metadata_filter = spec.match.recipient_metadata if spec.match is not None else None
    cost_filter = spec.match.recipient_cost if spec.match is not None else None
    cost_matches = _cost_matches(cost_filter, recipient_definition, submitted_cost, cost_facts)
    school_matches = (metadata_filter is None or not metadata_filter.spell_schools or
                      recipient_definition.spell_school in metadata_filter.spell_schools)
    return class_matches and school_matches and cost_matches


def spell_repeat_matches(spec: SpellRepeatSpec, *, recipient_definition: CardDefinition,
                         hero_class: CardClass | None, submitted_cost=None, cost_facts=None) -> bool:
    """Complete static matcher; board conditions require their separate context."""
    if type(spec) is not SpellRepeatSpec:
        raise ValueError('Spell repetition requires SpellRepeatSpec')
    spec.__post_init__()
    if spec.match is not None and spec.match.source_eligibility is not None:
        raise ValueError('Conditional spell repetition requires a physical board source context')
    return spell_repeat_recipient_matches(spec, recipient_definition=recipient_definition,
        hero_class=hero_class, submitted_cost=submitted_cost, cost_facts=cost_facts)


def repeat_matches(spec: SpellRepeatSpec, definition: CardDefinition, hero_class: CardClass | None,
                   *, submitted_cost=None, cost_facts=None) -> bool:
    """Compatibility entry for existing three-argument spell policy matching."""
    return spell_repeat_matches(spec, recipient_definition=definition, hero_class=hero_class,
        submitted_cost=submitted_cost, cost_facts=cost_facts)


def repeat_match_to_dict(match: RepeatMatchSpec | None) -> dict | None:
    """Return detached JSON parameters, never engine identities or proof data."""
    if match is None:
        return None
    if type(match) is not RepeatMatchSpec:
        raise ValueError('Repeat matching requires RepeatMatchSpec')
    match.__post_init__()
    metadata = match.recipient_metadata
    condition = match.source_eligibility
    return {'recipient_metadata': None if metadata is None else {
        'basis': metadata.basis,
        'spell_schools': [school.value for school in metadata.spell_schools],
    }, 'source_eligibility': None if condition is None else {
        'profile_id': condition.profile_id, 'tribes_any': list(condition.tribes_any),
        'exclude_carrier': condition.exclude_carrier,
    }, 'recipient_cost': repeat_cost_to_dict(match.recipient_cost)}


def repeat_cost_to_dict(value):
    if value is None:
        return None
    if type(value) is not RepeatCostFilter:
        raise ValueError('Repeat cost matching requires RepeatCostFilter')
    value.__post_init__()
    return dict(basis=value.basis, minimum=value.minimum, maximum=value.maximum,
                quote_profile_id=value.quote_profile_id)


def repeat_cost_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'basis', 'minimum', 'maximum', 'quote_profile_id'}:
        raise ValueError('RepeatCostFilter requires exactly its declared fields')
    return RepeatCostFilter(**value)


def _recipient_from_dict(metadata):
    if metadata is not None:
        if type(metadata) is not dict or set(metadata) != {'basis', 'spell_schools'}:
            raise ValueError('RecipientMetadataFilter requires exactly its declared fields')
        schools = metadata['spell_schools']
        if type(schools) is not list or any(type(school) is not str for school in schools):
            raise ValueError('Repeat schools must be a JSON array of school strings')
        metadata = RecipientMetadataFilter(metadata['basis'], tuple(SpellSchool(school) for school in schools))
    return metadata


def repeat_match_from_dict(value: dict | None) -> RepeatMatchSpec | None:
    """Decode the complete supported JSON declaration; missing is not null."""
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'recipient_metadata', 'source_eligibility', 'recipient_cost'}:
        raise ValueError('RepeatMatchSpec requires exactly its declared fields')
    metadata = _recipient_from_dict(value['recipient_metadata'])
    condition = value['source_eligibility']
    if condition is not None:
        if type(condition) is not dict or set(condition) != {'profile_id','tribes_any','exclude_carrier'}:
            raise ValueError('RepeatSourceEligibility requires exactly its declared fields')
        tribes = condition['tribes_any']
        if type(tribes) is not list or any(type(tribe) is not str for tribe in tribes):
            raise ValueError('Repeat witness tribes must be a JSON array of strings')
        condition = RepeatSourceEligibility(condition['profile_id'], tuple(tribes), condition['exclude_carrier'])
    return RepeatMatchSpec(metadata, condition, repeat_cost_from_dict(value['recipient_cost']))


def repeat_match_public_to_dict(match):
    """Public parameters exclude board-only conditions and all price proof data."""
    value = repeat_match_to_dict(match)
    if value is None:
        return None
    if value['source_eligibility'] is not None:
        raise ValueError('Player spell policies cannot expose a board carrier condition')
    return {'recipient_metadata': value['recipient_metadata'], 'recipient_cost': value['recipient_cost']}


def repeat_match_public_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'recipient_metadata', 'recipient_cost'}:
        raise ValueError('Public repeat matching requires only recipient metadata and cost parameters')
    return RepeatMatchSpec(_recipient_from_dict(value['recipient_metadata']),
        recipient_cost=repeat_cost_from_dict(value['recipient_cost']))
