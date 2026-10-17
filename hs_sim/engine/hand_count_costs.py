"""Finite pure hand-count price operand with an explicit physical subject."""
from .model import (CardType, CoinHandCountCostSpec, CoinHandCountCostFact,
    HandCountCostSpec, HandCountCostFact, Zone)


def validate_definition(definition):
    spec = definition.hand_count_cost
    if spec is None:
        return
    if type(spec) not in (HandCountCostSpec, CoinHandCountCostSpec):
        raise ValueError('Expected HandCountCostSpec')
    spec.__post_init__()
    if type(spec) is CoinHandCountCostSpec:
        from dataclasses import fields
        if (definition.kind != CardType.WEAPON or not definition.hand_playable or
                definition.starship_for or definition.interactable or definition.id in spec.card_ids or
                definition.intrinsic_costs or any(getattr(definition, f.name) is not None
                    for f in fields(definition) if f.name.endswith('_cost') and f.name != 'hand_count_cost')):
            raise ValueError('Coin hand pricing requires its one independent ordinary weapon formula')
        return
    if definition.kind not in (CardType.MINION, CardType.SPELL) or not definition.hand_playable or definition.starship_for or definition.interactable:
        raise ValueError('Hand count cost belongs to an ordinary physical minion or spell')
    if definition.board_minion_cost is not None:
        raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')


def capture(state, registry, player_id, definition, base_cost, subject_id=None):
    validate_definition(definition)
    spec = definition.hand_count_cost
    if spec is None:
        return None
    hands = []
    faces = []
    for pid in (1, 2):
        hand = tuple(state.players[pid].hand)
        for eid in hand:
            entity = state.entities[eid]
            if entity.zone != Zone.HAND or entity.controller != pid:
                raise ValueError('Hand price inventory differs from its physical zone/controller')
            registry.card(entity.card_id)
        hands.append(hand)
        if type(spec) is CoinHandCountCostSpec:
            from .zones import CardReference
            refs = tuple(CardReference.capture(state.entities[eid]) for eid in hand)
            for ref in refs:
                if registry.card(ref.card_id).kind != state.entities[ref.entity_id].kind:
                    raise ValueError('Coin price captured an inconsistent physical card face')
            faces.append(refs)
    hands = tuple(hands)
    if subject_id is not None:
        entity = state.entities.get(subject_id)
        if entity is None or entity.controller != player_id:
            raise ValueError('Physical hand price subject differs from its actual payer')
    if type(spec) is CoinHandCountCostSpec:
        quantity = sum(ref.card_id in spec.card_ids for ref in faces[player_id - 1])
        return CoinHandCountCostFact(spec, player_id, state.next_entity_id, hands,
            subject_id, quantity, base_cost, max(0, base_cost - quantity), tuple(faces))
    # An absent/generated subject is an additional hypothetical card. Its own
    # slot is excluded, so all currently held cards are its "other" cards.
    count = (len(hands[player_id - 1]) - int(subject_id in hands[player_id - 1])
        if spec.scope == 'friendly_other' else
        len(hands[player_id - 1]) + int(subject_id not in hands[player_id - 1])
        if spec.scope == 'friendly' else len(hands[2 - player_id]))
    return HandCountCostFact(spec, player_id, state.next_entity_id, hands,
        subject_id, count, base_cost, max(0, base_cost - count))


def validate_fact(definition, fact, registry=None):
    validate_definition(definition)
    if definition.hand_count_cost is None:
        if fact is not None:
            raise ValueError('A minion without hand pricing invented a count stage')
        return
    expected = CoinHandCountCostFact if type(definition.hand_count_cost) is CoinHandCountCostSpec else HandCountCostFact
    if type(fact) is not expected:
        raise ValueError('Hand-priced minion lost its complete original count stage')
    fact.__post_init__()
    if fact.spec != definition.hand_count_cost:
        raise ValueError('Hand count changed its pinned declaration')
    if type(fact) is CoinHandCountCostFact and registry is not None:
        for hand in fact.faces:
            for ref in hand:
                card = registry.card(ref.card_id)
                if ref.card_id in fact.spec.card_ids and card.kind != CardType.SPELL:
                    raise ValueError('Coin hand price family member is not a physical spell')


def fact_from_dict(value):
    from .serialization import _row, _list
    if type(value) is not dict or type(value.get('spec')) is not dict:
        raise ValueError('Hand count requires a complete structured original declaration')
    filtered = value.get('spec', {}).get('profile_id') == 'cost.coin-hand-count-v1'
    kind = CoinHandCountCostFact if filtered else HandCountCostFact
    row = _row(value, kind)
    spec_type = CoinHandCountCostSpec if filtered else HandCountCostSpec
    spec = _row(row['spec'], spec_type)
    if filtered:
        from .zones import CardReference
        spec['card_ids'] = tuple(_list(spec['card_ids'], 'Coin hand price family'))
        faces = []
        for hand in _list(row['faces'], 'Coin hand price face inventories'):
            refs = []
            for item in _list(hand, 'Coin hand price faces'):
                ref = _row(item, CardReference)
                ref['zone'] = Zone(ref['zone'])
                refs.append(CardReference(**ref))
            faces.append(tuple(refs))
        row['faces'] = tuple(faces)
    row['spec'] = spec_type(**spec)
    row['hands'] = tuple(tuple(_list(ids, 'hand count physical IDs')) for ids in _list(row['hands'], 'hand count inventories'))
    return kind(**row)
