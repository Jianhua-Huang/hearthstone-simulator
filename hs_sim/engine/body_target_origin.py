"""Durable target reconstruction without nesting older GameState histories.

The complete entity universe contains every input of engine-owned predicates
and declarative stat/durability/keyword/printed-tribe rules. Source attachments are
kept separately as canonical Entity JSON. Neither is a player observation or
an authentication claim about an unsigned save's external origin.
"""
from copy import deepcopy
from dataclasses import asdict
import json

from .model import (CardType, Entity, GameState, PaidBodyTargetEntityFact,
                    PaidBodyTargetOrigin, PlayerState, Zone)
from .serialization import canonical_hash, entity_from_dict, entity_to_dict

AUDITED_PREDICATES = frozenset(('any_entity', 'any_character'))


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def entity_fact(entity):
    from .tribes import tribe_changes
    return PaidBodyTargetEntityFact(entity.id, entity.card_id, entity.owner,
        entity.controller, entity.zone, entity.kind, entity.active, entity.doomed,
        entity.health, entity.attack, entity.max_health, entity.damage, entity.durability,
        tuple(sorted(entity.keywords, key=lambda k: k.value)), tribe_changes(entity))


def origin_hash(origin):
    origin.__post_init__()
    return canonical_hash(asdict(origin))


def capture_origin(state, source, state_hash, observation=None):
    return PaidBodyTargetOrigin(state.turn, state.action_number,
        state.next_entity_id, state.next_attachment_id,
        tuple(state.players[source.controller].hand),
        tuple(state.players[source.controller].board),
        canonical_json(entity_to_dict(source)),
        tuple(entity_fact(state.entities[i]) for i in sorted(state.entities)),
        state_hash, observation)


def require_audited_predicate(registry, name):
    from .target_predicates import reconstructible
    if not reconstructible(registry, name) and registry.player_target_rule(name) is None:
        raise ValueError('Original target reconstruction requires an audited built-in predicate')


def reconstruct_origin(state, registry, play, receipt):
    """Validate the original universe/hand/authority and rebuild target inputs.

Entity IDs are never deleted or reused by this kernel. Newly created entities
have larger IDs, so current retained identities certify the original universe's
extent while its frozen facts retain earlier zones and selectable protection.
Current target eligibility is deliberately not used as original eligibility.
"""
    origin = receipt.origin
    origin.__post_init__()
    if receipt.origin_hash != origin_hash(origin):
        raise ValueError('Original body target input digest differs from its complete facts')
    if ((origin.turn, origin.action) != (play.turn, play.action)
            or origin.next_entity_id > state.next_entity_id
            or origin.next_attachment_id > state.next_attachment_id):
        raise ValueError('Original body target boundary exceeds its actual play window')
    original_ids = tuple(e.id for e in origin.entities)
    if original_ids != tuple(sorted(i for i in state.entities if i < origin.next_entity_id)):
        raise ValueError('Original body target universe lost or added a physical identity')
    source = entity_from_dict(json.loads(origin.source_json))
    if canonical_json(entity_to_dict(source)) != origin.source_json:
        raise ValueError('Original physical source requires exact canonical Entity JSON')
    if ((source.id, source.card_id, source.kind, source.controller, source.zone) !=
            (play.source_id, play.card_id, play.kind, play.player_id, Zone.HAND)
            or source.id not in origin.hand or source.hand_entry_id != play.hand_entry_id):
        raise ValueError('Original body authority differs from its physical paid hand source')
    from .paid_body_retries import accepted_zone_epoch
    if (len(origin.hand) != play.hand_size or origin.hand.index(source.id) != play.hand_index
            or source.zone_epoch != accepted_zone_epoch(registry, play, receipt)):
        raise ValueError('Original target input rewrote its physical hand/payment facts')
    by_id = {e.id: e for e in origin.entities}
    if source.id not in by_id or by_id[source.id] != entity_fact(source):
        raise ValueError('Original target source differs from its complete universe fact')
    for entity in origin.entities:
        if registry.card(entity.card_id).kind != entity.kind:
            raise ValueError('Original target kind differs from its registered card')
    for entity_id in origin.hand:
        entity = by_id.get(entity_id)
        if entity is None or entity.zone != Zone.HAND or entity.controller != play.player_id:
            raise ValueError('Original target hand is not its owned physical hand universe')
    if tuple(e.id for e in origin.entities if e.zone == Zone.HAND and e.controller == play.player_id) != tuple(sorted(origin.hand)):
        raise ValueError('Original target hand omitted a current physical hand member')
    for entity_id in origin.board:
        entity = by_id.get(entity_id)
        if entity is None or entity.zone != Zone.BOARD or entity.controller != play.player_id:
            raise ValueError('Original target board is not its owned physical board universe')
    if tuple(e.id for e in origin.entities if e.zone == Zone.BOARD and e.controller == play.player_id) != tuple(sorted(origin.board)):
        raise ValueError('Original target board omitted a current physical board member')
    ability_ids = [a.id for a in source.abilities]
    if (len(set(ability_ids)) != len(ability_ids)
            or any(type(i) is not int or not 0 < i < origin.next_attachment_id for i in ability_ids)):
        raise ValueError('Original body authority lost its unique original attachment identities')
    prior = state.play_history[:play.id-1]
    owned = [p for p in prior if p.player_id == play.player_id]
    if (len(owned) != play.prior_game_plays
            or sum(p.turn == play.turn for p in owned) != play.prior_turn_plays):
        raise ValueError('Original target conditions differ from actual preceding hand plays')
    from .player_target_inputs import validate_origin
    validate_origin(registry, origin, source, play=play, prior=prior)
    entities = {}
    for fact in origin.entities:
        entities[fact.id] = Entity(fact.id, fact.card_id, fact.owner, fact.controller,
            fact.zone, base_attack=fact.attack, base_health=fact.max_health, damage=fact.damage,
            kind=fact.kind, keywords=set(fact.keywords), doomed=fact.doomed,
            durability=fact.durability, starship_building=not fact.active,
            enchantments=list(fact.tribe_changes))
    entities[source.id] = deepcopy(source)
    heroes = [e.id for e in origin.entities if e.zone == Zone.HERO and e.controller == play.player_id and e.kind == CardType.HERO]
    if len(heroes) != 1:
        raise ValueError('Original target board requires its single installed owned hero')
    player = PlayerState(play.player_id, heroes[0], hand=list(origin.hand), board=list(origin.board))
    original = GameState({play.player_id: player}, entities, active_player=play.player_id, turn=origin.turn,
        action_number=origin.action, next_entity_id=origin.next_entity_id,
        next_attachment_id=origin.next_attachment_id)
    from .kindred_targets import restore_original_history
    restore_original_history(original, state, registry, play)
    return original, entities[source.id]


def origin_from_dict(value):
    from .model import Keyword, CardType
    from .serialization import _row, _list, _enchantment_from_dict
    row = _row(value, PaidBodyTargetOrigin)
    from .model import PaidTargetObservation
    if row['observation'] is not None:
        observed = _row(row['observation'], PaidTargetObservation)
        observed['references'] = tuple(tuple(_list(v, 'original player reference'))
            for v in _list(observed['references'], 'original player references'))
        row['observation'] = PaidTargetObservation(**observed)
    row['hand'] = tuple(_list(row['hand'], 'original target hand'))
    row['board'] = tuple(_list(row['board'], 'original target board'))
    entities = []
    for value in _list(row['entities'], 'original target entities'):
        fact = _row(value, PaidBodyTargetEntityFact)
        fact['zone'] = Zone(fact['zone'])
        fact['kind'] = CardType(fact['kind'])
        fact['keywords'] = tuple(Keyword(k) for k in _list(fact['keywords'], 'original target keywords'))
        fact['tribe_changes'] = tuple(_enchantment_from_dict(c) for c in _list(fact['tribe_changes'], 'original target tribe changes'))
        entities.append(PaidBodyTargetEntityFact(**fact))
    row['entities'] = tuple(entities)
    return PaidBodyTargetOrigin(**row)
