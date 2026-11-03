"""Optional activation retries with durable checkpoints, separate from rollback.

R-091: the prototype retries the complete manually played card. RNG, action/event
cursors and allocated identities advance; game resources and histories rewind.
Terminal attempts are committed immediately. R-092 adds descending card-face
chains with the original accepted payment quote. Cumulative retained outcomes
are handled separately by rewind_outcomes (R-093). R-102 extends checkpoints to
manual Hero Powers; each activation gets a fresh budget, without hand face chains.
CN timing and indirect-source policies still need calibration.
"""
from copy import copy
from .runtime_copy import deepcopy
from dataclasses import dataclass, fields, replace

from .actions import PlayCard, UseHeroPower, action_from_dict, action_to_dict
from .effects import Effect, RequestChoice, ChoiceOption
from .errors import ResolutionError
from .information import Information
from .model import ChoicePurpose, GameState, Keyword, Zone
from .serialization import state_from_dict, state_to_dict


COUNTERS = ('next_entity_id', 'next_order', 'next_attachment_id', 'next_death_id',
            'next_death_batch', 'next_choice_id', 'next_window_id', 'next_resource_operation_id', 'next_hero_lethal_id', 'next_split_damage_root_id', 'next_card_summon_id', 'next_pool_summon_id', 'next_ordered_group_id', 'next_discovery_summon_id', 'next_recruit_summon_id', 'next_resurrection_summon_id')


def face_signature(card):
    """A retry face changes identity/remaining Rewind, never the underlying card."""
    excluded = {'id', 'name', 'rewind', 'keywords', 'metadata'}
    metadata = None if card.metadata is None else replace(card.metadata,
        collectible=False, deck_identity=None, max_copies=None)
    return (tuple(getattr(card, f.name) for f in fields(card) if f.name not in excluded),
            tuple(k for k in card.keywords if k != Keyword.REWIND), metadata)


def validate_definitions(registry):
    for card in registry.cards.values():
        spec = card.rewind
        if spec is None or spec.next_card_id is None:
            continue
        target = registry.card(spec.next_card_id)
        if (target.id == card.id or not target.hand_playable or
                face_signature(target) != face_signature(card)):
            raise ValueError('Rewind faces must preserve the underlying card definition')
        remaining = spec.retries - 1
        if remaining == 0:
            if target.rewind is not None:
                raise ValueError('Last Rewind face must be terminal')
        elif (target.rewind is None or target.rewind.retries != remaining or target.rewind.next_card_id is None):
            raise ValueError('Rewind face chain must strictly descend to a terminal form')


def attempt_card_id(registry, original_card_id, attempt):
    card = registry.card(original_card_id)
    if card.rewind is None or card.rewind.next_card_id is None:
        return card.id
    for _ in range(attempt):
        card = registry.card(card.rewind.next_card_id)
    return card.id


def retry_quote(r, source):
    """Payment belongs to the accepted root play/power, not a retry result."""
    from .costs import quote_cost
    value = r.game._rewind
    if value is not None and value.attempt and source.id == value.action.entity_id:
        return quote_cost(value.before, r.registry, value.before.entities[source.id])
    return quote_cost(r.state, r.registry, source)


@dataclass(frozen=True)
class HandSpellRewindAnchor:
    """Detached real retry origin; this is not a repeat acceptance window."""
    action: PlayCard
    before: GameState
    attempt: int
    event_start: int

    def __post_init__(self):
        from .effects import _integer
        if type(self.action) is not PlayCard or type(self.before) is not GameState:
            raise ValueError('Spell cost retry requires its real hand action and before state')
        _integer(self.attempt, 'Spell cost Rewind attempt', 0)
        _integer(self.event_start, 'Spell cost retry event cursor', 0)


def capture_hand_spell_anchor(r, source_id):
    value = capture_hand_spell_session(r, source_id)
    return value if value is not None and value.attempt > 0 else None


def capture_hand_spell_session(r, source_id):
    """Capture the real initial session as well as later quote-owning retries."""
    value = r.game._rewind
    if value is None:
        return None
    if type(value) is not RewindSession:
        raise ValueError('Invalid actual Rewind session for hand Spell payment')
    # Nested paid Spells have their own physical current-hand quote, even when
    # another card or Hero Power is being retried by the outer session.
    if type(value.action) is not PlayCard or value.action.entity_id != source_id:
        return None
    return HandSpellRewindAnchor(value.action, r.capture_state(value.before), value.attempt, value.event_start)


def normalized_hand_spell_retry(anchor, registry, payment_state):
    from .model import CardType
    return _normalized_hand_retry(anchor, registry, payment_state, CardType.SPELL)


def normalized_hand_play_retry(anchor, registry, payment_state):
    from .model import CardType
    return _normalized_hand_retry(anchor, registry, payment_state, CardType.MINION)


def _normalized_hand_retry(anchor, registry, payment_state, expected_kind):
    """Reproduce only actual restore/counter elevation/face/emit normalization.

    Current allocation cursors may advance across discarded attempts. Every
    other state field must remain the actual saved before state, with the one
    face transition already performed by RetryRewind before the next payment.
    """
    if type(anchor) is not HandSpellRewindAnchor or type(payment_state) is not GameState:
        raise ValueError('Invalid spell retry payment origin')
    anchor.__post_init__()
    if anchor.attempt < 1:
        raise ValueError('Retry normalization requires an actual retry after the initial attempt')
    before, action = anchor.before, anchor.action
    source = before.entities.get(action.entity_id)
    from .model import CardType
    if (before.status != 'playing' or before.action_number < 1 or
            source is None or source.kind != expected_kind or source.zone != Zone.HAND or
            source.controller != action.player_id or action.entity_id not in before.players[action.player_id].hand):
        raise ValueError('Spell retry before state lost its actual paid hand root')
    original = registry.card(source.card_id)
    if original.rewind is None or Keyword.REWIND not in source.keywords or anchor.attempt > original.rewind.retries:
        raise ValueError('Spell cost retry has no remaining real Rewind face')
    if (payment_state.action_number < before.action_number or payment_state.turn != before.turn or
            payment_state.active_player != before.active_player or payment_state.status != 'playing'):
        raise ValueError('Spell retry moved its root chronology or turn')
    restored = deepcopy(before)
    restored.action_number = payment_state.action_number
    for name in COUNTERS:
        current = getattr(payment_state, name)
        if type(current) is not int or current < getattr(before, name):
            raise ValueError('Spell retry moved an allocation cursor backwards')
        setattr(restored, name, current)
    face = attempt_card_id(registry, source.card_id, anchor.attempt)
    if face_signature(registry.card(face)) != face_signature(original):
        raise ValueError('Spell retry changed its underlying original card signature')
    entity = restored.entities[action.entity_id]
    if face != entity.card_id:
        from .choose_branch_state import rebind_face
        rebind_face(entity, registry, face)
        entity.card_id = face
        entity.zone_epoch += 1
        if registry.card(face).rewind is None:
            entity.abilities = [a for a in entity.abilities if not (a.kind == 'keyword' and a.keyword == Keyword.REWIND)]
        from .lifecycle import refresh_entity
        refresh_entity(entity)
    from .event_normalization import normalize_event_state
    normalize_event_state(restored, 'RetryRewind', registry=registry)
    return restored


def validate_hand_spell_anchor_live(anchor, game):
    """Bind the detached cost origin to the real current session and markers."""
    if anchor is None:
        return
    anchor.__post_init__()
    value = game._rewind
    if (type(value) is not RewindSession or type(value.action) is not PlayCard or
            (value.action, value.before, value.attempt, value.event_start) !=
            (anchor.action, anchor.before, anchor.attempt, anchor.event_start)):
        raise ValueError('Spell cost proof lost its real Rewind before/action/attempt/cursor')
    if not 0 <= anchor.event_start <= len(game._events):
        raise ValueError('Spell cost Rewind event cursor is outside actual history')
    if any(e.action >= anchor.before.action_number for e in game._events[:anchor.event_start]):
        raise ValueError('Spell cost Rewind before cursor includes its own activation')
    markers = [e for e in game._events[anchor.event_start:] if e.kind == 'timeline_rewound']
    if (len(markers) != anchor.attempt or any(e.amount != n or
            e.source_id != anchor.action.entity_id or e.player_id != anchor.action.player_id or
            dict(e.data).get('event_start') != anchor.event_start for n, e in enumerate(markers, 1))):
        raise ValueError('Spell cost Rewind anchor disagrees with actual retry markers')


def apply_retry_face(r, value):
    source = r.state.entities[value.action.entity_id]
    card_id = attempt_card_id(r.registry, value.before.entities[source.id].card_id, value.attempt)
    if card_id == source.card_id:
        return
    if source.zone != Zone.HAND:
        raise ResolutionError('Rewind face changes require the restored hand card')
    # Form signatures match; retain all base instance stats, attachments, their
    # consumption, damage, hand acquisition and temporary lifetime exactly.
    from .choose_branch_state import rebind_face
    rebind_face(source, r.registry, card_id)
    source.card_id = card_id
    source.zone_epoch += 1
    if r.registry.card(card_id).rewind is None:
        source.abilities = [a for a in source.abilities if not (a.kind == 'keyword' and a.keyword == Keyword.REWIND)]
    from .lifecycle import refresh_entity
    refresh_entity(source)
    for knowledge in r.game._information.players.values():
        knowledge.remember(source)
    r.emit('rewind_face_changed', source_id=source.id, target_id=source.id,
           player_id=value.action.player_id, amount=value.attempt, _capture=False)


@dataclass(frozen=True)
class RewindSession:
    action: PlayCard | UseHeroPower
    before: GameState
    information: Information
    event_start: int
    attempt: int = 0

    def to_dict(self):
        return dict(action=action_to_dict(self.action), before=state_to_dict(self.before),
                    information=self.information.to_dict(), event_start=self.event_start,
                    attempt=self.attempt)

    @classmethod
    def from_dict(cls, value, game):
        if type(value) is not dict or set(value) != {'action', 'before', 'information', 'event_start', 'attempt'}:
            raise ValueError('Invalid Rewind checkpoint fields')
        action = action_from_dict(value['action'])
        if type(action) not in (PlayCard,UseHeroPower):
            raise ValueError('A Rewind checkpoint requires a hand play or hero power')
        before = state_from_dict(value['before'])
        base = copy(game)
        base._state = before
        information = Information.from_dict(value['information'], base)
        return cls(action, before, information, value['event_start'], value['attempt'])


@dataclass(frozen=True)
class OfferRewind(Effect):
    root_action: int


@dataclass(frozen=True)
class KeepRewind(Effect):
    root_action: int


@dataclass(frozen=True)
class RetryRewind(Effect):
    root_action: int


def activation(action):
    from .resolver import PlayFromHand
    from .hero_powers import ActivateHeroPower
    if type(action) is PlayCard: return PlayFromHand(action)
    if type(action) is UseHeroPower: return ActivateHeroPower(action)
    raise ResolutionError('Unsupported Rewind activation')


def attempt_record(state, value):
    if type(value.action) is UseHeroPower:
        return state.hero_power_history[len(value.before.hero_power_history)]
    return state.play_history[len(value.before.play_history)]


def unsuccessful(record):
    return (getattr(record,'countered',False) or getattr(record,'failure',None) is not None or
            getattr(record,'minion_result',None) == 'board_full')


def start(game, action, *, _resolution=None):
    """Called once at the root action, before payment or activation reactions."""
    source = game._state.entities[action.entity_id]
    spec = game.registry.card(source.card_id).rewind
    if spec is None or Keyword.REWIND not in source.keywords:
        return [activation(action)]
    if game._rewind is not None:
        raise ResolutionError('Nested root Rewind sessions are unsupported')
    before = deepcopy(game._state) if _resolution is None else _resolution.capture_state()
    game._rewind = RewindSession(action, before, deepcopy(game._information), len(game._events))
    return [activation(action), OfferRewind(game._state.action_number)]


def session(r, root_action):
    value = r.game._rewind
    if value is None or type(root_action) is not int or value.before.action_number != root_action:
        raise ResolutionError('Rewind work does not match its checkpoint')
    return value


def options(root_action):
    return (ChoiceOption('keep', '保留当前结果', (KeepRewind(root_action),)),
            ChoiceOption('retry', '回溯并重试', (RetryRewind(root_action),)))


def offer(r, effect):
    value = session(r, effect.root_action)
    source = value.before.entities[value.action.entity_id]
    spec = r.registry.card(source.card_id).rewind
    record = attempt_record(r.state,value)
    if not record.completed or record.interrupted:
        raise ResolutionError('Rewind offer preceded completed activation')
    from .rewind_outcomes import retention_sources
    if value.attempt == spec.retries or unsuccessful(record) or retention_sources(value.before, value.action.player_id):
        return keep(r, KeepRewind(effect.root_action))
    return [RequestChoice(value.action.player_id, options(effect.root_action),
                          source_id=value.action.entity_id, prompt='保留结果，还是回溯重试？',
                          purpose=ChoicePurpose.REWIND)]


def keep(r, effect):
    value = session(r, effect.root_action)
    r.game._rewind = None
    r.emit('rewind_kept', source_id=value.action.entity_id, player_id=value.action.player_id,
           amount=value.attempt, _capture=False)


def retry(r, effect):
    """Interpreter control operation: do not generate combat checkpoints for reset."""
    value = session(r, effect.root_action)
    spec = r.registry.card(value.before.entities[value.action.entity_id].card_id).rewind
    if value.attempt >= spec.retries:
        raise ResolutionError('No Rewind retries remain')
    previous = r.state
    restored = r.capture_state(value.before)
    restored.action_number = previous.action_number
    for name in COUNTERS:
        setattr(restored, name, max(getattr(restored, name), getattr(previous, name)))
    # Restore pre-attempt identities, retaining memory only when the same handle
    # still identified the same card. Hidden deck positions never gain handles.
    knowledge = deepcopy(value.information)
    for player_id, base in knowledge.players.items():
        observed = r.game._information.players[player_id]
        for entity_id, card_id in observed.known.items():
            entity = restored.entities.get(int(entity_id))
            if (entity is not None and base.refs.get(entity_id) == observed.refs.get(entity_id)
                    and entity.card_id == card_id):
                base.known[entity_id] = card_id
        base.next_ref = observed.next_ref
        base.next_choice = observed.next_choice
        base.next_body_ref = observed.next_body_ref
        base.events = deepcopy(observed.events)
        base.pending = None
    r.state = r.game._state = restored
    r.game._information = knowledge
    r.game._rewind = replace(value, attempt=value.attempt + 1)
    r._captured.clear()
    r.removed_weapons.clear()
    r.death_deferrals = 0
    # The reset marker carries only viewer-local cursors in the player log.
    r.emit('timeline_rewound', source_id=value.action.entity_id, player_id=value.action.player_id,
           amount=value.attempt + 1, event_start=value.event_start,
           player_cursors=tuple(len(value.information.players[i].events) for i in (1, 2)), _capture=False)
    apply_retry_face(r, r.game._rewind)
    action = value.action
    if type(action) is PlayCard and action.body_target_profile_id is not None:
        from .paid_body_retries import retry_action
        action = retry_action(r.state, r.registry, action)
    return [activation(action), OfferRewind(effect.root_action)]


def validate_boundary(game):
    from .paid_body_retries import validate_retry_events
    validate_retry_events(game)
    value = game._rewind
    frame, choice = game._frame, game._state.pending_choice
    work = (*frame.prefix, *frame.continuation) if frame is not None else ()
    controls = [w for w in work if type(w) in (OfferRewind, KeepRewind, RetryRewind)]
    if value is None:
        if controls or choice is not None and choice.purpose == ChoicePurpose.REWIND:
            raise ValueError('Rewind continuation has no checkpoint')
        return
    if type(value) is not RewindSession or type(value.action) not in (PlayCard,UseHeroPower):
        raise ValueError('Invalid Rewind session')
    if (type(value.attempt) is not int or value.attempt < 0 or type(value.event_start) is not int
            or not 0 <= value.event_start <= len(game._events)):
        raise ValueError('Invalid Rewind attempt/cursor')
    before = value.before
    base = copy(game)
    base._state, base._information = deepcopy(before), deepcopy(value.information)
    # The checkpoint owns only the original event prefix. Later attempt events
    # must never be validated against its earlier allocation/history domain.
    base._events = list(game._events[:value.event_start])
    base._rewind = base._frame = None
    base._resolving = False
    base._assert_stable()
    base.validate(value.action)
    source = before.entities[value.action.entity_id]
    spec = game.registry.card(source.card_id).rewind
    if spec is None or Keyword.REWIND not in source.keywords or value.attempt > spec.retries:
        raise ValueError('Invalid Rewind eligibility or remaining retries')
    current = game._state
    if (frame is None or current.status != 'playing' or before.action_number < 1 or
            frame.root_action_number != before.action_number or
            current.turn != before.turn or current.active_player != before.active_player or
            any(getattr(current, n) < getattr(before, n) for n in COUNTERS)):
        raise ValueError('Rewind checkpoint does not match the active resolution')
    if (any(e.action >= before.action_number for e in game._events[:value.event_start]) or
            any(e.action < before.action_number for e in game._events[value.event_start:])):
        raise ValueError('Rewind checkpoint event cursor includes its own attempt')
    markers = [e for e in game._events[value.event_start:] if e.kind == 'timeline_rewound']
    if (len(markers) != value.attempt or any(e.amount != n or
            dict(e.data).get('event_start') != value.event_start for n, e in enumerate(markers, 1))):
        raise ValueError('Rewind attempt does not match its branch markers')
    for player_id, old in value.information.players.items():
        now = game._information.players[player_id]
        if (now.events[:len(old.events)] != old.events or now.next_ref < old.next_ref or
                now.next_choice < old.next_choice or now.next_body_ref < old.next_body_ref):
            raise ValueError('Rewind knowledge is not an earlier information boundary')
    field = 'hero_power_history' if type(value.action) is UseHeroPower else 'play_history'
    previous_records, current_records = getattr(before,field), getattr(current,field)
    if current_records[:len(previous_records)] != previous_records:
        raise ValueError('Rewind activation history is not an earlier prefix')
    if len(current_records) <= len(previous_records):
        raise ValueError('Rewind attempt has no activation record')
    play = attempt_record(current,value)
    if type(value.action) is UseHeroPower and (play.origin != 'manual' or play.parent_id is not None):
        raise ValueError('Rewind hero power requires its manual root activation')
    if (play.source_id != value.action.entity_id or play.player_id != value.action.player_id or
            play.card_id != attempt_card_id(game.registry, source.card_id, value.attempt) or
            play.target_id != value.action.target_id):
        raise ValueError('Rewind attempt has a different play provenance')
    if choice.purpose == ChoicePurpose.REWIND:
        if (controls or frame.continuation or frame.on_select is not None or
                frame.options != options(before.action_number) or value.attempt >= spec.retries or
                choice.player_id != value.action.player_id or choice.source_id != value.action.entity_id or
                choice.min_count != 1 or choice.max_count != 1 or
                not play.completed or unsuccessful(play) or play.source_id != value.action.entity_id):
            raise ValueError('Invalid Rewind result choice')
    else:
        if len(controls) != 1 or controls[0].root_action != before.action_number or work[-1] != controls[0]:
            raise ValueError('Rewind checkpoint has no final attempt continuation')
        if type(controls[0]) is not OfferRewind and (not play.completed or unsuccessful(play) or value.attempt >= spec.retries):
            raise ValueError('Rewind decision preceded a valid result')


def register(mechanics):
    mechanics.register(OfferRewind, offer)
    mechanics.register(KeepRewind, keep)
    mechanics.register(RetryRewind, retry)
