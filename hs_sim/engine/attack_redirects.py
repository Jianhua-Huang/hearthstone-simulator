"""Secret redirection inside one original attack, with compact selection facts.

The frozen board basis includes noncharacters and inactive physical slots. It
does not retain a GameState inside the permanent attack history.
"""
from dataclasses import asdict, dataclass, replace
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .interrupts import attack_live, find_window
from .model import ActionWindow, BoardPresenceReference, CardType, Zone, validate_end_turn_rng

PROFILES = ('other_character', 'attacker_neighbor')
RELATION = 'any_characters'


@dataclass(frozen=True)
class RedirectCharacter:
    allocation: SourceAllocationFact
    presence: BoardPresenceReference | None
    health: int
    active: bool
    doomed: bool

    def __post_init__(self):
        if type(self.allocation) is not SourceAllocationFact:
            raise ValueError('Redirect basis requires its complete physical allocation')
        self.allocation.__post_init__()
        if type(self.health) is not int or type(self.active) is not bool or type(self.doomed) is not bool:
            raise ValueError('Redirect basis requires exact health and activity facts')
        a = self.allocation
        if a.zone not in (Zone.BOARD, Zone.HERO):
            raise ValueError('Redirect basis must contain actual battlefield or hero residents')
        if (a.kind == CardType.MINION) != (self.presence is not None):
            raise ValueError('Redirect basis lost a physical minion residence')
        if self.presence is not None:
            if type(self.presence) is not BoardPresenceReference or self.presence.entity_id != a.entity_id:
                raise ValueError('Redirect basis borrowed another physical residence')
            self.presence.__post_init__()
            if self.presence.presence_id >= a.next_order:
                raise ValueError('Redirect basis has a future residence')
        if self.active and a.kind not in (CardType.MINION, CardType.HERO):
            raise ValueError('A noncharacter physical slot cannot become a combat candidate')

    @property
    def live(self):
        return self.active and self.health > 0 and not self.doomed


def capture_character(state, ident):
    e = state.entities[ident]
    return RedirectCharacter(SourceAllocationFact.capture(state, e),
        BoardPresenceReference.capture(state, ident) if e.kind == CardType.MINION else None,
        e.health, e.active and e.is_character, e.doomed)


def candidates(window, profile, boards, heroes):
    if type(profile) is not str or profile not in PROFILES:
        raise ValueError('Unknown finite attack redirection profile')
    if profile == 'other_character':
        # Each physical character has one weight, in player/hero/board order.
        return tuple(x.allocation.entity_id for p in range(2) for x in (heroes[p], *boards[p])
            if x.live and x.allocation.entity_id not in (window.source_id, window.target_id))
    board = next((b for b in boards if any(x.allocation.entity_id == window.source_id for x in b)), ())
    index = next((i for i, x in enumerate(board) if x.allocation.entity_id == window.source_id), None)
    if index is None:
        return ()
    return tuple(board[i].allocation.entity_id for i in (index-1, index+1) if 0 <= i < len(board)
        and board[i].allocation.kind == CardType.MINION and board[i].live)


@dataclass(frozen=True)
class AttackRedirectSelection:
    window: ActionWindow
    source: SourceAllocationFact
    profile: str
    boards: tuple[tuple[RedirectCharacter, ...], ...]
    heroes: tuple[RedirectCharacter, ...]
    candidates: tuple[int, ...]
    selected_id: int
    rng_before: tuple
    rng_after: tuple
    action: int
    event_cursor: int

    def __post_init__(self):
        request = RandomRedirectAttack(self.window, self.source, self.profile)
        request.__post_init__()
        for n in ('action', 'event_cursor'):
            _integer(getattr(self, n), 'redirect selection '+n, 0)
        if type(self.boards) is not tuple or len(self.boards) != 2 or any(type(b) is not tuple for b in self.boards):
            raise ValueError('Redirect selection requires both complete ordered boards')
        if type(self.heroes) is not tuple or len(self.heroes) != 2:
            raise ValueError('Redirect selection requires both original physical heroes')
        facts = []
        for p in range(2):
            for x in (self.heroes[p], *self.boards[p]):
                if type(x) is not RedirectCharacter:
                    raise ValueError('Redirect selection requires typed physical basis facts')
                x.__post_init__(); a = x.allocation
                if a.controller != p+1 or (a.next_entity_id, a.next_order) != (self.source.next_entity_id, self.source.next_order):
                    raise ValueError('Redirect selection changed a board owner or allocator window')
                facts.append(x)
            if self.heroes[p].allocation.kind != CardType.HERO or self.heroes[p].allocation.zone != Zone.HERO:
                raise ValueError('Redirect selection lost its original hero slot')
            if any(x.allocation.zone != Zone.BOARD or x.allocation.kind not in (CardType.MINION, CardType.LOCATION)
                    for x in self.boards[p]):
                raise ValueError('Redirect selection moved a physical board slot')
        by_id = {x.allocation.entity_id: x for x in facts}
        if len(by_id) != len(facts) or self.window.source_id not in by_id or self.window.target_id not in by_id:
            raise ValueError('Redirect selection duplicated or omitted original combatants')
        attacker, defender = by_id[self.window.source_id], by_id[self.window.target_id]
        if (not attacker.live or not defender.live or attacker.allocation.controller != self.window.player_id or
                defender != self.heroes[self.source.controller-1] or
                attacker.presence != self.window.attack_source_presence or self.window.attack_target_presence is not None or
                self.profile == 'attacker_neighbor' and attacker.allocation.kind != CardType.MINION):
            raise ValueError('Redirect selection changed its original live attacking/protected characters')
        if (type(self.candidates) is not tuple or any(type(i) is not int for i in self.candidates) or
                not self.candidates or self.candidates != candidates(self.window, self.profile, self.boards, self.heroes) or
                type(self.selected_id) is not int or self.selected_id not in self.candidates):
            raise ValueError('Redirect selection cropped or changed its complete physical domain')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        rng = Random(); rng.setstate(self.rng_before)
        selected = self.candidates[0] if len(self.candidates) == 1 else rng.choice(self.candidates)
        if selected != self.selected_id or rng.getstate() != self.rng_after:
            raise ValueError('Redirect selection changed its actual random draw')

    @property
    def selected(self):
        return next(x for p in range(2) for x in (self.heroes[p], *self.boards[p])
            if x.allocation.entity_id == self.selected_id)


@dataclass(frozen=True)
class RandomRedirectAttack(Effect):
    window: ActionWindow
    source: SourceAllocationFact
    profile: str

    def __post_init__(self):
        if type(self.window) is not ActionWindow or type(self.source) is not SourceAllocationFact:
            raise ValueError('Secret redirect requires its original attack window and revealed source')
        self.window.__post_init__(); self.source.__post_init__()
        if (type(self.profile) is not str or self.profile not in PROFILES or self.window.kind != 'attack' or
                self.source.kind != CardType.SPELL or self.source.zone != Zone.GRAVEYARD or
                self.source.controller == self.window.player_id):
            raise ValueError('Secret redirect lost its finite opposing source policy')

    def validate_in_state(self, state, registry, events=None):
        from .character_attacks import record
        self.__post_init__(); validate_allocation(state, registry, self.source)
        row = record(state, self.window.id); original = row.declaration
        if (replace(self.window, target_id=original.target_id, attack_target_presence=original.attack_target_presence,
                combat_relation=original.combat_relation) != original or row.delivery is not None or
                row.terminal is not None or find_window(state, self.window.id) is None or
                registry.card(self.source.card_id).secret is None or
                self.window.target_id != state.players[self.source.controller].hero_id or
                self.profile == 'attacker_neighbor' and row.source_kind != CardType.MINION):
            raise ValueError('Secret redirect borrowed a foreign or closed original attack')
        if events is not None:
            validate_reveal(state, self.window.id, self.source, events)


def pending_attack(state, event, player_id, profile):
    if event is None or event.kind != 'attack_declared' or event.player_id == player_id:
        return None
    from .native_attack_targets import original_event
    row = original_event(state, event); w = find_window(state, row.declaration.id)
    if (not attack_live(state, w) or w.target_id != state.players[player_id].hero_id or
            state.entities[w.source_id].controller == player_id or
            profile == 'attacker_neighbor' and state.entities[w.source_id].kind != CardType.MINION):
        return None
    boards = tuple(tuple(capture_character(state, i) for i in state.players[p].board) for p in (1, 2))
    heroes = tuple(capture_character(state, state.players[p].hero_id) for p in (1, 2))
    return w if candidates(w, profile, boards, heroes) else None


def encoded(value):
    return json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_reveal(state, window_id, source, events, before=None):
    from .character_attacks import record
    from .hero_health_history import effective_events
    row = record(state, window_id)
    matches = [e for e in effective_events(events) if e.kind == 'secret_revealed' and
        (e.source_id, e.player_id) == (source.entity_id, source.controller) and
        e.sequence > row.declaration_event_cursor and (before is None or e.sequence <= before)]
    if len(matches) != 1:
        raise ValueError('Attack redirect borrowed a source outside its actual Secret reveal')


def validate_selections(state, registry, row, event_limit=None):
    def allocation(value):
        validate_allocation(state, registry, value)
        current = state.entities[value.entity_id]
        if current.zone_epoch == value.zone_epoch and (current.card_id, current.kind) != (value.card_id, value.kind):
            raise ValueError('Attack redirect changed an unchanged physical allocation face')
    for value in row.secret_redirects:
        allocation(value.source)
        if registry.card(value.source.card_id).secret is None:
            raise ValueError('Attack redirect source has no actual Secret declaration')
        for p in range(2):
            for x in (value.heroes[p], *value.boards[p]):
                allocation(x.allocation)
                if x.presence is not None and x.presence.presence_id >= state.next_order:
                    raise ValueError('Attack redirect borrowed a future residence')
        if value.action > state.action_number or event_limit is not None and value.event_cursor >= event_limit:
            raise ValueError('Attack redirect selection is from a future event/action')


def redirect_attack(r, effect):
    from .character_attacks import record, update
    from .interrupts import redirect, RedirectAttack
    effect.validate_in_state(r.state, r.registry, r.game._events)
    w = find_window(r.state, effect.window.id)
    if w != effect.window or not attack_live(r.state, w):
        return ()
    boards = tuple(tuple(capture_character(r.state, i) for i in r.state.players[p].board) for p in (1, 2))
    heroes = tuple(capture_character(r.state, r.state.players[p].hero_id) for p in (1, 2))
    domain = candidates(w, effect.profile, boards, heroes)
    if not domain:
        return ()
    # Rebase only allocator bounds after legitimate reveal/wait allocations.
    source = replace(effect.source, next_entity_id=r.state.next_entity_id, next_order=r.state.next_order)
    before = r.game._rng.getstate()
    target = domain[0] if len(domain) == 1 else r.game._rng.choice(domain)
    selection = AttackRedirectSelection(w, source, effect.profile, boards, heroes, domain, target,
        before, r.game._rng.getstate(), r.state.action_number, len(r.game._events))
    row = record(r.state, w.id)
    update(r.state, row, secret_redirects=(*row.secret_redirects, selection))
    redirect(r, RedirectAttack(w.id, target), secret_selection=selection)
    return ()


def selection_from_dict(value):
    from .serialization import _row, _list, end_turn_rng_from_json
    from .model import TriggerCandidate
    row = _row(value, AttackRedirectSelection)
    w = _row(row['window'], ActionWindow)
    for name in ('attack_source_presence', 'attack_target_presence'):
        w[name] = None if w[name] is None else BoardPresenceReference(**_row(w[name], BoardPresenceReference))
    w['spellburst_candidates'] = tuple(TriggerCandidate(**_row(x, TriggerCandidate))
        for x in _list(w['spellburst_candidates'], 'redirect spellburst basis'))
    row['window'] = ActionWindow(**w); row['source'] = allocation_from_dict(row['source'])
    def character(raw):
        d = _row(raw, RedirectCharacter); d['allocation'] = allocation_from_dict(d['allocation'])
        d['presence'] = None if d['presence'] is None else BoardPresenceReference(**_row(d['presence'], BoardPresenceReference))
        return RedirectCharacter(**d)
    row['boards'] = tuple(tuple(character(x) for x in _list(board, 'redirect physical board'))
        for board in _list(row['boards'], 'redirect two physical boards'))
    row['heroes'] = tuple(character(x) for x in _list(row['heroes'], 'redirect physical heroes'))
    row['candidates'] = tuple(_list(row['candidates'], 'redirect complete candidate domain'))
    for name in ('rng_before', 'rng_after'):
        row[name] = end_turn_rng_from_json(row[name])
    return AttackRedirectSelection(**row)


def register(mechanics):
    mechanics.register(RandomRedirectAttack, redirect_attack)
    mechanics.register_payload_type(RedirectCharacter)
    mechanics.register_payload_type(AttackRedirectSelection)
