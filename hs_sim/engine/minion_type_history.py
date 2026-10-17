"""Original submitted minion tribes and finite, one-play-per-type matching.

The caller supplies a pinned complete type universe. ALL is never expanded from
the currently implemented card sample; ordinary summons are absent from plays.
"""
from dataclasses import dataclass
from .effects import Effect
from .model import CardType, PlayRecord, _int
from .registry import UnsupportedDefinitionError
from .tribes import apply_change, normalized


def submitted_minion_types(record):
    if type(record) is not PlayRecord or record.kind != CardType.MINION:
        raise ValueError('Submitted minion types require an original physical minion play')
    face, cost = record.played_face, record.submitted_cost
    if face is None or cost is None:
        raise ValueError('Submitted minion types lost original face or paid operands')
    original = cost.quote.quote_input
    expected = (record.source_id, record.player_id, record.card_id, record.kind)
    if ((face.source_id, face.player_id, face.card_id, face.kind) != expected or
            (original.source_id, original.player_id, original.card_id, original.kind) != expected):
        raise ValueError('Submitted minion types borrowed another original play')
    meta = face.metadata
    value = None if meta is None or meta.tribes is None else normalized(meta.tribes)
    for change in original.enchantments:
        if change.tribe_change is not None: value = apply_change(value, change.tribe_change)
    if value is None: raise UnsupportedDefinitionError('Unknown submitted minion types: ' + record.card_id)
    return value


def played_minion_type_facts(state, player_id, *, exclude_ids=(), completed=True):
    from .play_history import played_cards
    if type(exclude_ids) is not tuple or list(exclude_ids) != sorted(set(exclude_ids)):
        raise ValueError('Original excluded completed plays require an ordered distinct tuple')
    for identity in exclude_ids:
        _int(identity, 'original completed play exclusion', 1)
        if identity > len(state.play_history) or not state.play_history[identity-1].completed:
            raise ValueError('Excluded play is not an actual completed original root')
    return tuple((row.id, submitted_minion_types(row)) for row in played_cards(
        state, player_id, kind=CardType.MINION, completed=completed) if row.id not in exclude_ids)


def validate_types(types):
    from .model import _name
    if type(types) is not tuple or not types or types != tuple(sorted(set(types))) or 'all' in types:
        raise ValueError('A complete pinned canonical finite type universe is required')
    for value in types: _name(value, 'reviewed minion type')


def match_minion_type_plays(facts, types):
    """Maximum distinct assignment, at most one type per physical play occurrence."""
    validate_types(types)
    choices = {}
    for identity, value in facts:
        _int(identity, 'original type-matching play', 1)
        value.__post_init__()
        if identity in choices: raise ValueError('Duplicated physical play in type matching')
        if value.members != ('all',) and set(value.members)-set(types):
            raise UnsupportedDefinitionError('Submitted type is outside the complete pinned universe')
        choices[identity] = tuple(t for t in types if value.matches_any((t,)))
    owners = {}
    def assign(identity, seen):
        for tribe in choices[identity]:
            if tribe in seen: continue
            seen.add(tribe)
            if tribe not in owners or assign(owners[tribe], seen):
                owners[tribe] = identity
                return True
        return False
    for identity in choices: assign(identity, set())
    return tuple(sorted((identity, tribe) for tribe, identity in owners.items()))


@dataclass(frozen=True)
class AdvanceQuestFromPlayedTypes(Effect):
    target_id: int
    instance_id: int
    stage: int
    types: tuple[str, ...]

    def __post_init__(self):
        from .quests import AdvanceQuest
        AdvanceQuest(self.target_id, self.instance_id, self.stage).__post_init__()
        validate_types(self.types)


def advance(r, effect):
    from .quests import AdvanceQuest, advance as advance_quest, matching
    effect.__post_init__()
    target = matching(r, effect)
    if target is None or target.quest_progress.completing: return ()
    progress = target.quest_progress
    facts = played_minion_type_facts(r.state, target.controller, exclude_ids=progress.completed_before)
    total = len(match_minion_type_plays(facts, effect.types))
    # Recompute in the existing effect window. Nested completed plays can have
    # advanced this quest after its callback was captured; no stale delta is used.
    return advance_quest(r, AdvanceQuest(target.id, progress.id, progress.stage, max(0, total-progress.value)))


def register(mechanics): mechanics.register(AdvanceQuestFromPlayedTypes, advance)
