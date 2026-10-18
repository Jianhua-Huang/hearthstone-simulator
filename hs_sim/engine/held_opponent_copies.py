"""Immediate copy provenance and one paid play while continuously held.

Copy origin is physical card state, independent of face/class and current source
control. The hand condition reuses existing progress and immutable PlayRecords.
"""
from dataclasses import replace
from .errors import ResolutionError

from .model import (CardCopyOrigin, CardType, HandProgressSpec,
                    HeldOpponentCopyMatch)


CONDITION = 'held_opponent_copy'
HISTORY = 'hand.held-opponent-copy-play-v1'
KIND = 'opponent_copy_play'


def copy_origin(source):
    return CardCopyOrigin(source.entity_id if hasattr(source, 'entity_id') else source.id,
                          source.card_id, source.owner, source.controller)


def validate_origin(state, registry, origin, recipient_id):
    if origin is None: return
    if type(origin) is not CardCopyOrigin:
        raise ValueError('Copied card requires its complete original source')
    origin.__post_init__()
    source = state.entities.get(origin.entity_id)
    if (source is None or source.owner != origin.owner or origin.entity_id >= recipient_id or
            registry.card(origin.card_id).kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON,
                                                      CardType.LOCATION, CardType.HERO)):
        raise ValueError('Copied card lost its original physical allocation or face')


def ability(entity):
    return next((a for a in entity.abilities if a.kind == 'hand_progress' and
                 a.hand_progress.kind == KIND), None)


def witness_ids(abilities):
    a = next((a for a in abilities if a.kind == 'hand_progress' and a.hand_progress.kind == KIND), None)
    if a is None: return ()
    if any(not key.startswith('play:') for key in a.progress_keys):
        raise ValueError('Held copied-play progress requires original hand-play witnesses')
    return tuple(int(key[5:]) for key in a.progress_keys)


def reset_entry(entity):
    a = ability(entity)
    if a is not None:
        entity.abilities[entity.abilities.index(a)] = replace(a, progress_value=0, progress_completions=0,
            progress_keys=(), progress_units=(), consumed=False)


def is_opponent_copy(record):
    return record.copy_origin is not None and record.copy_origin.controller != record.player_id


def note_play(state, record):
    """Called only with the genuine paid append, before commitment reactions."""
    if record.id != len(state.play_history) or state.play_history[-1] != record:
        raise ValueError('Held copied-play progress requires the actual next committed play')
    if not is_opponent_copy(record): return
    from .hand_progress import advance_value
    from .lifecycle import refresh_entity
    for entity_id in state.players[record.player_id].hand:
        if entity_id == record.source_id: continue
        entity = state.entities[entity_id]; a = ability(entity)
        if a is None or a.consumed: continue
        entity.abilities[entity.abilities.index(a)] = advance_value(a, f'play:{record.id}')
        refresh_entity(entity)


def validate_definition(definition):
    if not definition.intrinsic_costs or definition.intrinsic_costs[0].condition != CONDITION: return
    from dataclasses import fields
    if (definition.kind != CardType.SPELL or len(definition.intrinsic_costs) != 1 or
            definition.hand_progress != HandProgressSpec(KIND) or
            any(getattr(definition, f.name) is not None for f in fields(definition) if f.name.endswith('_cost'))):
        raise ValueError('Held copied-play price requires its independent Spell and native hand declaration')


def capture_cost(state, registry, player_id, source_id):
    if source_id is None:
        return HeldOpponentCopyMatch(player_id, state.turn, state.action_number, None, None,
                                     len(state.play_history) + 1, ())
    entity = state.entities.get(source_id)
    if entity is None or entity.controller != player_id:
        raise ValueError('Held copied-play price requires its actual physical payer')
    result = HeldOpponentCopyMatch(player_id, state.turn, state.action_number, source_id,
        entity.hand_entry_id, len(state.play_history) + 1, witness_ids(entity.abilities))
    validate_match(result, state, registry)
    return result


def validate_witnesses(state, registry, play_ids, turn, action):
    from .play_history import play_record
    for identity in play_ids:
        record = play_record(state, identity)
        if not is_opponent_copy(record) or record.turn > turn or record.action > action:
            raise ValueError('Held copied-play witness is not an original opponent-copy play')
        validate_origin(state, registry, record.copy_origin, record.source_id)


def validate_match(match, state, registry):
    match.__post_init__()
    if match.next_play_id > len(state.play_history) + 1:
        raise ValueError('Held copied-play price exceeds its original history prefix')
    if match.source_id is not None and match.source_id not in state.entities:
        raise ValueError('Held copied-play price lost its original physical subject')
    if match.hand_entry_id is not None:
        from .hand_history import hand_entry
        entry = hand_entry(state, match.hand_entry_id)
        if entry.entity_id != match.source_id or entry.turn > match.turn or entry.action > match.action:
            raise ValueError('Held copied-play price changed its original hand acquisition')
    validate_witnesses(state, registry, match.play_ids, match.turn, match.action)


def validate_ability(state, registry, a):
    if a.hand_progress.kind != KIND: return
    ids = witness_ids((a,))
    validate_witnesses(state, registry, ids, state.turn, state.action_number)
    if (len(ids) > 1 or a.progress_value != len(ids) or a.progress_completions != len(ids) or
            a.consumed != bool(ids)):
        raise ValueError('Held copied-play progress differs from its first committed witness')


def needs_battlecry_fact(registry, payload):
    spec = registry.card(payload.card_id).hand_progress
    return spec is not None and spec.kind == KIND


def freeze_play(state, registry, play, payload):
    if not needs_battlecry_fact(registry, payload): return None
    if play.submitted_cost is None:
        raise ResolutionError('Held copied-play Battlecry lost its original paid hand input')
    original = play.submitted_cost.quote.quote_input
    a = next((a for a in original.abilities if a.kind == 'hand_progress' and a.hand_progress.kind == KIND), None)
    if a is None:
        raise ResolutionError('Original Battlecry hand input has no held copied-play declaration')
    result = HeldOpponentCopyMatch(play.player_id, play.turn, play.action, play.source_id,
        play.hand_entry_id, play.id, witness_ids(original.abilities))
    validate_match(result, state, registry)
    return result


def freeze_carrier(state, registry, source, payload):
    if not needs_battlecry_fact(registry, payload): return None
    if ability(source) is None:
        raise ResolutionError('Effect Battlecry carrier has no original held copied-play declaration')
    return capture_cost(state, registry, source.controller, source.id)


def freeze_physical(state, registry, source_id, payloads):
    payload = next((p for p in payloads if needs_battlecry_fact(registry, p)), None)
    return None if payload is None else freeze_carrier(state, registry, state.entities[source_id], payload)


def _effect_fact(state, registry, value, fact):
    if type(fact) is not HeldOpponentCopyMatch or fact.source_id != value.source_id:
        raise ValueError('Effect Battlecry lost its original held copied-play source')
    validate_match(fact, state, registry)
    if value.physical_child_id is not None:
        from .whole_card_physical import child_for
        expected = child_for(state, value.physical_child_id).physical.held_opponent_copy
    elif value.indirect_body_id is not None:
        # Mind Sweeper has no target declaration or registered bound producer.
        # Do not invent a target-profile combination to add this native card.
        raise ValueError('Held copied-play Battlecry has no reviewed bound-target origin')
    else:
        if fact.player_id != value.player_id:
            raise ValueError('Held copied-play effect changed its original captured player')
        expected = fact
        # While the original declaration and hand residence still exist, the
        # accepted state cannot borrow an unrelated witness. Reentry, silence
        # or replacement legitimately leaves only the frozen original fact.
        source = state.entities[value.source_id]
        a = ability(source)
        if (a is not None and source.hand_entry_id == fact.hand_entry_id and
                any(b.id == value.payload.ability_id for b in source.abilities) and
                witness_ids(source.abilities) != fact.play_ids):
            raise ValueError('Held copied-play effect differs from its unchanged original carrier')
    if fact != expected:
        raise ValueError('Held copied-play Battlecry differs from its accepted physical or bound fact')
    return fact


def indirect_fact(state, registry, value):
    if not needs_battlecry_fact(registry, value.payload):
        if value.held_opponent_copy is not None:
            raise ValueError('Unrelated Battlecry cannot invent a held copied-play condition')
        return None
    if value.origin == 'history':
        from .battlecries import battlecry_record
        original = battlecry_record(state, value.history_id)
        if original.held_opponent_copy is None:
            raise ValueError('Historical Battlecry lost its original held copied-play condition')
        return original.held_opponent_copy
    if value.origin == 'played_history':
        from .play_history import play_record
        return freeze_play(state, registry, play_record(state, value.history_play_id), value.payload)
    return _effect_fact(state, registry, value, value.held_opponent_copy)


def validate_battlecry(state, registry, record):
    if record.origin == 'hand':
        from .play_history import play_record
        expected = freeze_play(state, registry, play_record(state, record.play_id), record.payload)
    else:
        expected = indirect_fact(state, registry, record)
    if record.held_opponent_copy != expected:
        raise ValueError('Battlecry changed its original held copied-play condition')
    fact = record.held_opponent_copy
    if fact is not None:
        validate_match(fact, state, registry)
        if fact.turn > record.turn or fact.action > record.action:
            raise ValueError('Held copied-play condition postdates its original Battlecry')


def satisfied(context):
    record = context.battlecry
    if (record is None or record.id > len(context.state.battlecry_history) or
            context.state.battlecry_history[record.id - 1] != record or
            (record.source_id, record.player_id) != (context.source_id, context.player_id) or
            record.held_opponent_copy is None):
        raise ResolutionError('Held copied-play body requires its original accepted Battlecry')
    return record.held_opponent_copy.matched
