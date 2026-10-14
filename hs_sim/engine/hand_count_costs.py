"""Finite pure hand-count price operand with an explicit physical subject."""
from .model import CardType, HandCountCostSpec, HandCountCostFact, Zone


def validate_definition(definition):
    spec = definition.hand_count_cost
    if spec is None:
        return
    if type(spec) is not HandCountCostSpec:
        raise ValueError('Expected HandCountCostSpec')
    spec.__post_init__()
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.starship_for:
        raise ValueError('Hand count cost belongs to an ordinary physical minion')
    if definition.board_minion_cost is not None:
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost, subject_id=None):
    validate_definition(definition)
    spec = definition.hand_count_cost
    if spec is None:
        return None
    hands = []
    for pid in (1, 2):
        hand = tuple(state.players[pid].hand)
        for eid in hand:
            entity = state.entities[eid]
            if entity.zone != Zone.HAND or entity.controller != pid:
                raise ValueError('Hand price inventory differs from its physical zone/controller')
            registry.card(entity.card_id)
        hands.append(hand)
    hands = tuple(hands)
    if subject_id is not None:
        entity = state.entities.get(subject_id)
        if entity is None or entity.controller != player_id:
            raise ValueError('Physical hand price subject differs from its actual payer')
    # An absent/generated subject is an additional hypothetical card. Its own
    # slot is excluded, so all currently held cards are its "other" cards.
    count = (len(hands[player_id - 1]) - int(subject_id in hands[player_id - 1])
        if spec.scope == 'friendly_other' else len(hands[2 - player_id]))
    return HandCountCostFact(spec, player_id, state.next_entity_id, hands,
        subject_id, count, base_cost, max(0, base_cost - count))


def validate_fact(definition, fact):
    validate_definition(definition)
    if definition.hand_count_cost is None:
        if fact is not None:
            raise ValueError('A minion without hand pricing invented a count stage')
        return
    if type(fact) is not HandCountCostFact:
        raise ValueError('Hand-priced minion lost its complete original count stage')
    fact.__post_init__()
    if fact.spec != definition.hand_count_cost:
        raise ValueError('Hand count changed its pinned declaration')
