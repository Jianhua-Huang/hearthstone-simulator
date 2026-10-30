"""Original-deck turn limits and deterministic, trusted host time inputs.

The interpreter never reads a wall clock. Time is retained in the complete
event ledger, including abandoned Rewind attempts, and committed to snapshots.
Timeout choice/pause policies are explicit local policies pending CN evidence.
"""
from dataclasses import dataclass
import json
from random import Random

from .effects import Effect
from .errors import IllegalAction, ResolutionError
from .model import CardType, OpeningHook

CARD = 'CS3_035'
POLICY = 'original-decks-turn-time-v1'
INSTALL = 'turn_clock_installed'
ADVANCE = 'turn_time_advanced'
TIMEOUT = 'turn_choice_timed_out'
KINDS = frozenset((INSTALL, ADVANCE, TIMEOUT))


def positive(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(name + ' requires a positive integer')


@dataclass(frozen=True)
class TurnClockProfile:
    source_card_id: str
    behavior_id: str
    limit_ms: int = 15000
    policy: str = POLICY

    def __post_init__(self):
        if (self.source_card_id != CARD or type(self.behavior_id) is not str or not self.behavior_id.strip()
                or type(self.limit_ms) is not int or self.limit_ms != 15000 or self.policy != POLICY):
            raise ValueError('Unreviewed original-deck turn clock')


def validate_profile(registry, profile):
    from .battlefield_turn_clocks import BattlefieldTurnClockProfile,validate_profile as validate_battlefield
    if type(profile)is BattlefieldTurnClockProfile:
        validate_battlefield(registry,profile);return
    if type(profile) is not TurnClockProfile: raise ValueError('Expected a typed native turn clock')
    profile.__post_init__()
    card = registry.card(profile.source_card_id)
    if card.kind != CardType.MINION or card.opening_hooks != (OpeningHook('before_deal', profile.behavior_id),):
        raise ValueError('Native turn clock lost its original opening hook')


@dataclass(frozen=True)
class ActivateOriginalDeckClock(Effect):
    source_id: int
    player_id: int
    profile_id: str


@dataclass(frozen=True)
class AdvanceTurnTime:
    """Trusted host input; deliberately absent from the player command codec."""
    owner_turn_id: int
    elapsed_ms: int

    def __post_init__(self):
        positive(self.owner_turn_id, 'owner_turn_id')
        positive(self.elapsed_ms, 'elapsed_ms')


def history_action_to_dict(action):
    from .actions import action_to_dict
    if type(action) is not AdvanceTurnTime: return action_to_dict(action)
    action.__post_init__()
    return dict(type='advance_turn_time', version=1,
                owner_turn_id=action.owner_turn_id, elapsed_ms=action.elapsed_ms)


def history_action_from_dict(value):
    from .actions import action_from_dict
    if type(value) is not dict or value.get('type') != 'advance_turn_time': return action_from_dict(value)
    if (set(value) != {'type', 'version', 'owner_turn_id', 'elapsed_ms'} or
            type(value['version']) is not int or value['version'] != 1):
        raise ValueError('Malformed host time input')
    return AdvanceTurnTime(value['owner_turn_id'], value['elapsed_ms'])


def original_source(game):
    """Return the sole native installation, never infer original decks in Scenario."""
    opening = game._state.opening
    profile = game.registry._turn_clock_profiles.get(CARD)
    if opening is None or profile is None: return None
    decks = [game._state.players[pid].original_deck for pid in (1, 2)]
    # Verify the complete original domain, including cards after the first match.
    for deck in decks:
        for cid in deck: game.registry.card(cid)
    if not all(CARD in deck for deck in decks): return None
    first = opening.first_player
    index = decks[first - 1].index(CARD)
    return profile, opening.original_entities[first - 1][index], first


def installation(game):
    if not game.registry._turn_clock_profiles: return None
    if not hasattr(game, '_events'):
        # Frozen legality probes can prove absence from the original decks.
        # An eligible source still requires the genuine installation/time log.
        if original_source(game) is None: return None
        raise ValueError('Eligible turn-clock projection requires its original event receipts')
    return next((e for e in game._events if e.kind == INSTALL), None)


def activate(r, effect):
    expected = original_source(r.game)
    from .opening_deck_copies import is_hook_source
    profile = r.registry._turn_clock_profiles.get(effect.profile_id)
    if (profile is None or not is_hook_source(r.state, effect.source_id, effect.player_id, profile.source_card_id)):
        raise ResolutionError('Turn clock requires its genuine opening source')
    if expected is None or (effect.source_id, effect.player_id) != expected[1:]: return
    if installation(r.game) is not None: raise ResolutionError('Original turn clock already installed')
    r.emit(INSTALL, source_id=effect.source_id, player_id=effect.player_id,
           amount=profile.limit_ms, profile_id=profile.source_card_id, policy=profile.policy, _capture=False)


def elapsed(game, owner_turn_id):
    return sum(e.amount for e in game._events if e.kind == ADVANCE and dict(e.data)['owner_turn_id'] == owner_turn_id)


def current(game):
    """Trusted host clock token. Players receive only the public projection."""
    from .battlefield_turn_clocks import sources,start_boundary
    if game._state.status != 'playing':return None
    if installation(game) is None and not sources(game):return None
    opening = game._state.opening
    if opening is not None and opening.stage != 'complete' or not game._state.owner_turn_history:return None
    if not hasattr(game,'_events'):raise ValueError('Battlefield clock requires its original time receipts')
    from .owner_turns import current_owner_turn
    interval = current_owner_turn(game._state)
    if start_boundary(interval)is None or interval.end_event is not None:return None
    used = elapsed(game, interval.id)
    limit = 15000
    choice = game._state.pending_choice
    return dict(owner_turn_id=interval.id, player_id=interval.player_id, limit_ms=limit,
                elapsed_ms=used, remaining_ms=limit-used,
                paused=choice is not None and choice.player_id != interval.player_id)


def public_view(game):
    value = current(game)
    if value is None: return None
    return {key: v for key, v in value.items() if key != 'owner_turn_id'}


def snapshot_value(game):
    from .serialization import event_to_dict
    rows = [event_to_dict(e) for e in game._events if e.kind in KINDS]
    from .battlefield_turn_clocks import POLICY as battlefield_policy,sources
    battlefield=bool(sources(game))or any(dict(e.data).get('policy')==battlefield_policy for e in game._events if e.kind==ADVANCE)
    return dict(policy=battlefield_policy if battlefield else POLICY,events=rows)if rows or battlefield else None


def validate_input(game, action):
    game._require_boundary()
    try: action.__post_init__()
    except (ValueError, TypeError) as exc: raise IllegalAction(str(exc)) from exc
    value = current(game)
    if value is None: raise IllegalAction('There is no running turn clock')
    if action.owner_turn_id != value['owner_turn_id']: raise IllegalAction('Stale host turn-clock token')
    if value['paused']: raise IllegalAction('The active clock is paused for the other player decision')
    if value['remaining_ms'] == 0: raise IllegalAction('This turn clock has already expired')


def advance(r, action):
    value = current(r.game)
    from .battlefield_turn_clocks import POLICY as battlefield_policy,encode_sources,sources
    rows=sources(r.game);original=installation(r.game);extra={}
    if rows:extra['battlefield_sources']=encode_sources(rows)
    source_id=original.source_id if original is not None else rows[0]['allocation']['entity_id']
    r.emit(ADVANCE, source_id=source_id, player_id=value['player_id'],
        amount=min(action.elapsed_ms, value['remaining_ms']), owner_turn_id=action.owner_turn_id,
        elapsed_ms=action.elapsed_ms, previous_ms=value['elapsed_ms'],
        policy=battlefield_policy if rows else POLICY,_capture=False,**extra)


def settle_expired(r):
    """Finish the original paid work, then request the ordinary natural end once."""
    from .actions import SelectChoice
    from .choices import resume_choice
    from .resolver import Resolution, EndTurnPhase
    from .serialization import rng_to_json
    while (value := current(r.game)) is not None and value['remaining_ms'] == 0:
        choice = r.state.pending_choice
        if choice is not None:
            if choice.player_id != value['player_id']: return
            # Check the original paid boundary before consuming random input.
            from .paid_hand_acceptance import validate_choice_boundary
            validate_choice_boundary(r.game, resume=False)
            options = tuple(o.id for o in choice.options)
            before = r.game._rng.getstate()
            count = choice.min_count if choice.min_count == choice.max_count else r.game._rng.randint(choice.min_count, choice.max_count)
            sampled = set(r.game._rng.sample(options, count)) if count else set()
            selected = tuple(o for o in options if o in sampled)
            charged_policy=next(dict(e.data)['policy']for e in reversed(r.game._events)if e.kind==ADVANCE and dict(e.data)['owner_turn_id']==value['owner_turn_id'])
            proof = dict(owner_turn_id=value['owner_turn_id'], choice_id=choice.id, options=options,
                min_count=choice.min_count, max_count=choice.max_count, selected=selected,
                rng_before=rng_to_json(before), rng_after=rng_to_json(r.game._rng.getstate()), policy=charged_policy)
            r.emit(TIMEOUT, source_id=choice.source_id, player_id=choice.player_id,
                   proof=json.dumps(proof, sort_keys=True, separators=(',', ':')), _capture=False)
            resume_choice(r, SelectChoice(choice.player_id, choice.id, selected), host_timeout=True)
        else:
            # Pure time inputs do not invalidate a suspended paid choice. The
            # actual natural end owns its next action identity, as EndTurn does.
            r.state.action_number += 1
            end = Resolution(r.game)
            end.run([EndTurnPhase(value['player_id'])])
            return  # overflow never charges a later (including extra) turn


def validate_boundary(game):
    """Bind original opening, every charged interval and each timeout RNG proof."""
    expected = original_source(game)
    installs = [e for e in game._events if e.kind == INSTALL]
    advances = [e for e in game._events if e.kind == ADVANCE]
    timeouts = [e for e in game._events if e.kind == TIMEOUT]
    source_id=None
    if expected is None:
        if installs:raise ValueError('Clock has no matching original decks')
        if not advances and not timeouts:return
    else:
        profile, source_id, first = expected
        hooks = [e for e in game._events if e.kind == 'opening_effect' and e.source_id == source_id
             and e.player_id == first and dict(e.data).get('behavior_id') == profile.behavior_id]
        if len(installs) > 1 or (game._state.opening.stage != 'dealing' or hooks) and len(installs) != 1:
            raise ValueError('Original opening lost its unique clock installation')
        if not installs:
            if advances or timeouts:raise ValueError('Time input preceded clock installation')
            return
        event = installs[0]
        if (len(hooks) != 1 or event.sequence != hooks[0].sequence + 1 or
            dict(hooks[0].data).get('stage') != 'dealing' or
            (event.source_id, event.player_id, event.target_id, event.amount) != (source_id, first, None, profile.limit_ms) or
            dict(event.data) != dict(profile_id=profile.source_card_id, policy=POLICY)):
            raise ValueError('Clock installation differs from its original source and limit')
    pending, paused_inputs, requests = {}, set(), {}
    for prior in game._events:
        if prior.kind == 'choice_requested':
            choice_id = dict(prior.data)['choice_id']
            pending[choice_id] = prior.player_id
            requests.setdefault(choice_id, []).append(prior)
        elif prior.kind == 'choice_selected': pending.pop(dict(prior.data)['choice_id'], None)
        elif prior.kind == ADVANCE and any(pid != prior.player_id for pid in pending.values()):
            paused_inputs.add(prior.sequence)
    from .battlefield_turn_clocks import POLICY as battlefield_policy,start_boundary,validate_sources
    totals, expirations,expiration_policies = {}, {},{}
    for event in advances:
        data = dict(event.data)
        fields={'owner_turn_id','elapsed_ms','previous_ms','policy'};event_source=source_id
        if data.get('policy')==battlefield_policy:
            if set(data)!=fields|{'battlefield_sources'}:raise ValueError('Malformed battlefield host time receipt')
            rows=validate_sources(game,data['battlefield_sources'])
            if event_source is None:event_source=rows[0]['allocation']['entity_id']
        elif set(data)!=fields or data.get('policy')!=POLICY or source_id is None:
            raise ValueError('Malformed original host time receipt')
        token, requested, old = data['owner_turn_id'], data['elapsed_ms'], data['previous_ms']
        positive(token, 'charged owner interval'); positive(requested, 'elapsed host time')
        if token > len(game._state.owner_turn_history): raise ValueError('Clock charged an unknown owner interval')
        turn = game._state.owner_turn_history[token-1]
        start=start_boundary(turn)
        if (start is None or event.sequence <= start[0] or event.action < start[1]or
                turn.end_event is not None and event.sequence >= turn.end_event or
                type(old) is not int or old != totals.get(token, 0) or old >= 15000 or
                (event.source_id, event.player_id, event.target_id) != (event_source, turn.player_id, None) or
                event.amount != min(requested, 15000-old)):
            raise ValueError('Clock changed its original interval, elapsed time or accepted charge')
        totals[token] = old + event.amount
        if totals[token] == 15000:
            expirations[token]=event.sequence;expiration_policies[token]=data['policy']
        if event.sequence in paused_inputs:
            raise ValueError('Clock charged time reserved for the other player decision')
    from .serialization import rng_from_json
    seen = set()
    for event in timeouts:
        if event.amount != 0 or event.target_id is not None or set(dict(event.data)) != {'proof'}:
            raise ValueError('Malformed timeout event')
        proof = json.loads(dict(event.data)['proof'])
        if (type(proof) is not dict or set(proof) != {'owner_turn_id','choice_id','options','min_count','max_count',
                'selected','rng_before','rng_after','policy'} or proof['policy'] not in(POLICY,battlefield_policy)):
            raise ValueError('Malformed timeout selection proof')
        token, choice_id = proof['owner_turn_id'], proof['choice_id']
        positive(token, 'timeout interval'); positive(choice_id, 'timeout choice')
        if choice_id in seen or token > len(game._state.owner_turn_history): raise ValueError('Duplicate or borrowed timeout')
        seen.add(choice_id)
        turn = game._state.owner_turn_history[token-1]
        start=start_boundary(turn)
        if (token not in expirations or proof['policy']!=expiration_policies[token]or expirations[token] >= event.sequence or event.player_id != turn.player_id or
                start is None or event.action < start[1]or
                turn.end_event is not None and event.sequence >= turn.end_event):
            raise ValueError('Choice timeout has no original expired active turn')
        original_requests = requests.get(choice_id, ())
        following = game._events[event.sequence:event.sequence+1]
        if len(original_requests) != 1 or len(following) != 1: raise ValueError('Timeout lost its real pending choice')
        request, selected_event = original_requests[0], following[0]
        if request.sequence >= event.sequence: raise ValueError('Timeout preceded its real pending choice')
        request_data = dict(request.data)
        options = proof['options']
        if (type(options) is not list or options != list(request_data['option_ids']) or
                proof['min_count'] != request_data['min_count'] or proof['max_count'] != request_data['max_count'] or
                type(proof['min_count']) is not int or type(proof['max_count']) is not int or
                not 0 <= proof['min_count'] <= proof['max_count'] <= len(options) or
                (event.source_id,event.player_id) != (request.source_id, request.player_id)):
            raise ValueError('Timeout changed the original options or cardinality')
        rng = Random(); rng.setstate(rng_from_json(proof['rng_before']))
        count = proof['min_count'] if proof['min_count'] == proof['max_count'] else rng.randint(proof['min_count'],proof['max_count'])
        sampled = set(rng.sample(options,count)) if count else set()
        selected = [o for o in options if o in sampled]
        if (selected != proof['selected'] or rng.getstate() != rng_from_json(proof['rng_after']) or
                selected_event.kind != 'choice_selected' or selected_event.source_id != event.source_id or
                selected_event.action != event.action or
                selected_event.player_id != event.player_id or dict(selected_event.data).get('choice_id') != choice_id or
                list(dict(selected_event.data).get('option_ids', ())) != selected):
            raise ValueError('Timeout changed its original random selection or genuine continuation')
    value = current(game)
    if value is not None and value['remaining_ms'] == 0 and not value['paused']:
        raise ValueError('Expired clock lost its owed choice continuation or natural end')


def register(mechanics):
    mechanics.register(ActivateOriginalDeckClock, activate)
