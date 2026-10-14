"""Finite pure prices from the actual payer's current hero Health facts."""
from .model import CardType, HeroMissingHealthCostSpec, HeroMissingHealthCostFact, Zone


def validate_definition(definition):
    spec = definition.hero_missing_health_cost
    if spec is None:
        return
    if type(spec) is not HeroMissingHealthCostSpec:
        raise ValueError('Expected HeroMissingHealthCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Hero missing-health cost belongs to an ordinary physical minion')
    if definition.board_minion_cost is not None or definition.hand_count_cost is not None:
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost):
    validate_definition(definition)
    spec = definition.hero_missing_health_cost
    if spec is None:
        return None
    hero = state.entities[state.players[player_id].hero_id]
    if (hero.kind, hero.zone, hero.owner, hero.controller) != (CardType.HERO, Zone.HERO, player_id, player_id):
        raise ValueError('Hero price differs from its actual payer hero')
    if registry.card(hero.card_id).kind != CardType.HERO:
        raise ValueError('Hero price requires a supported hero face')
    quantity = (hero.max_health - hero.health if spec.profile_id == 'cost.hero-missing-health-v1'
                else 5 if hero.health <= 15 else 0)
    return HeroMissingHealthCostFact(spec, player_id, state.next_entity_id,
        hero.id, hero.card_id, hero.max_health, hero.health, quantity,
        base_cost, max(0, base_cost - quantity))


def validate_fact(registry, definition, fact):
    validate_definition(definition)
    if definition.hero_missing_health_cost is None:
        if fact is not None:
            raise ValueError('A minion without hero pricing invented a health stage')
        return
    if type(fact) is not HeroMissingHealthCostFact:
        raise ValueError('Hero-priced minion lost its complete original health stage')
    fact.__post_init__()
    if fact.spec != definition.hero_missing_health_cost:
        raise ValueError('Hero price changed its pinned declaration')
    if registry.card(fact.hero_card_id).kind != CardType.HERO:
        raise ValueError('Hero price changed its original hero face to a nonhero')
