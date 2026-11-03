"""One finite 0/1/2-Attack recruit group and its ordinary numeric reward.

Actual selection, physical movement, quantity, entry, reactions and buffs stay
with their original executors. Original entry Attack/remaining Health and one
final reward are explicit internal policy; exact CN timing remains unverified.
"""
from .runtime_copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
import json

from .effects import Effect, _integer
from .model import BoardPresenceReference, CardType, GameState, Zone
from .owner_turns import validate_accepted_prefix
from .pools import PoolQuery
from .registry import RuleContext
from .serialization import canonical_hash, state_to_dict
from .summon_quantities import SummonCause
from .summon_sources import SummonFromZone

ATTACKS = (0, 1, 2)
POLICY = 'original-entry-attack-and-nonnegative-remaining-health-v1'
ACCEPTED = 'recruit_stat_group_accepted'
SLOT = 'recruit_stat_group_slot'
REWARD = 'recruit_stat_group_reward'
FINISHED = 'recruit_stat_group_finished'


@dataclass(frozen=True)
class RecruitAttackGroupForStats(Effect):
    original: RuleContext

    def __post_init__(self):
        c = self.original
        if (type(c) is not RuleContext or c.source.kind != CardType.MINION or
                c.battlecry is None or not c.battlecry.payload_started or c.battlecry.failure is not None or
                (c.battlecry.source_id, c.battlecry.player_id) != (c.source_id, c.player_id)):
            raise ValueError('Recruit stat group requires its actual accepted minion Battlecry')


def original_presence(request):
    c = request.original
    return BoardPresenceReference.capture(c.state, c.source_id) if c.source.zone == Zone.BOARD else None


@dataclass(frozen=True)
class ContinueRecruitStatGroup(Effect):
    request: RecruitAttackGroupForStats
    accepted: RuleContext
    event_cursor: int
    recruit_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.request) is not RecruitAttackGroupForStats:
            raise ValueError('Recruit group lost its complete original request')
        self.request.__post_init__()
        c = self.accepted; old = self.request.original
        if (type(c) is not RuleContext or (c.source_id, c.player_id, c.battlecry) !=
                (old.source_id, old.player_id, old.battlecry)):
            raise ValueError('Recruit group changed its original actor or Battlecry')
        _integer(self.event_cursor, 'recruit group acceptance', 1)
        if (type(self.recruit_ids) is not tuple or len(self.recruit_ids) > len(ATTACKS) or
                any(type(i) is not int or i < 1 for i in self.recruit_ids) or
                tuple(sorted(set(self.recruit_ids))) != self.recruit_ids):
            raise ValueError('Recruit group requires its complete distinct ordered slot prefix')


@dataclass(frozen=True)
class FinishRecruitStatGroup(Effect):
    group: ContinueRecruitStatGroup
    success_ids: tuple[int, ...]
    attack: int
    health: int
    reward_event: int

    def __post_init__(self):
        if type(self.group) is not ContinueRecruitStatGroup or len(self.group.recruit_ids) != len(ATTACKS):
            raise ValueError('Recruit reward omitted an original slot')
        self.group.__post_init__()
        if (type(self.success_ids) is not tuple or any(type(i) is not int or i < 1 for i in self.success_ids) or
                len(set(self.success_ids)) != len(self.success_ids)):
            raise ValueError('Recruit reward needs complete unique successful deliveries')
        _integer(self.attack, 'recruit reward Attack', 0); _integer(self.health, 'recruit reward Health', 0)
        _integer(self.reward_event, 'recruit reward acceptance', 1)


CONTROL = (RecruitAttackGroupForStats, ContinueRecruitStatGroup, FinishRecruitStatGroup)


def signature(group):
    old = group.request.original; c = group.accepted; ref = original_presence(group.request)
    return dict(policy=POLICY, attacks=ATTACKS, source_card=old.source.card_id,
        battlecry=json.dumps(asdict(old.battlecry), sort_keys=True),
        original_state=canonical_hash(state_to_dict(old.state)), accepted_state=canonical_hash(state_to_dict(c.state)),
        first_recruit=c.state.next_recruit_summon_id,
        presence=None if ref is None else (ref.entity_id, ref.presence_id))


def child_request(group, index):
    c = group.request.original
    return SummonFromZone(c.player_id, query=PoolQuery(attack_equals=ATTACKS[index]),
        source_id=c.source_id, cause=SummonCause.capture(c), attack_basis='current', stat_group_id=group.event_cursor)


def children(state, group, *, allow_last_active=False):
    """Exact producer IDs bind each slot; nested same-cause recruits are unrelated."""
    group.__post_init__()
    rows = []
    for index, identity in enumerate(group.recruit_ids):
        root = next((r for r in state.recruit_summon_history if r.id == identity), None)
        if root is None or root.spec != child_request(group, index):
            raise ValueError('Recruit slot borrowed another original producer or numeric query')
        if root.status == 'active' and not (allow_last_active and index == len(group.recruit_ids)-1):
            raise ValueError('Recruit group advanced before its original child completed')
        rows.append(root)
    return tuple(rows)


def successful_entries(state, group):
    return entries_from_roots(state, children(state, group), group.accepted.player_id)


def entries_from_roots(state, roots, player_id):
    result = []
    for root in roots:
        for selection in root.rounds:
            if selection.entry_root_id is None:
                continue
            child = next((r for r in state.card_summon_history if r.id == selection.entry_root_id), None)
            if child is None or child.status == 'active':
                raise ValueError('Recruit group lost its completed actual entry child')
            for delivery in child.deliveries:
                if delivery.entity is None:
                    continue
                fact = delivery.entity
                matches = [r for r in state.successful_summon_history if
                    (r.entity_id, r.minion.zone_epoch, r.minion.entered_order) ==
                    (fact.entity_id, fact.zone_epoch, fact.entered_order)]
                if len(matches) != 1 or matches[0].player_id != player_id:
                    raise ValueError('Recruit group lost an exact original successful delivery')
                result.append(matches[0])
    if len({r.id for r in result}) != len(result):
        raise ValueError('Recruit group counted a physical delivery twice')
    return tuple(result)


def reward_data(effect):
    return dict(group=effect.group.event_cursor, success_ids=effect.success_ids,
        attack=effect.attack, health=effect.health, policy=POLICY)


def timeline(game):
    from .hero_health_history import effective_events
    return tuple(effective_events(game._events))


def validate_group(game, group, *, allow_last_active=False):
    group.__post_init__(); old = group.request.original; accepted = group.accepted
    validate_accepted_prefix(old.state, accepted.state, game.registry)
    validate_accepted_prefix(accepted.state, game._state, game.registry)
    from .original_summon_groups import root_prefix
    root_prefix(accepted.state, game._state)
    if (game._state.successful_summon_history[:len(accepted.state.successful_summon_history)] !=
            accepted.state.successful_summon_history):
        raise ValueError('Recruit group rewrote its original successful prefix')
    events = timeline(game)
    event = next((e for e in events if e.sequence == group.event_cursor), None)
    if (event is None or event.kind != ACCEPTED or canonical_hash(dict(event.data)) != canonical_hash(signature(group)) or
            (event.source_id, event.player_id, event.action) !=
            (old.source_id, old.player_id, accepted.state.action_number)):
        raise ValueError('Recruit group lost its complete original acceptance')
    slots = [e for e in events if e.kind == SLOT and dict(e.data).get('group') == group.event_cursor]
    roots = children(game._state, group, allow_last_active=allow_last_active)
    if len(slots) != len(roots):
        raise ValueError('Recruit group changed its complete accepted slot inventory')
    for index, (slot, root) in enumerate(zip(slots, roots)):
        if (dict(slot.data) != dict(group=group.event_cursor, index=index, recruit_id=root.id) or
                (slot.source_id, slot.player_id) != (old.source_id, old.player_id) or
                root.event_cursor != slot.sequence or root.action != slot.action):
            raise ValueError('Recruit slot changed its exact original acceptance window')
    if roots and roots[0].id != accepted.state.next_recruit_summon_id:
        raise ValueError('Recruit group skipped its first original producer identity')
    return events


def validate_finish(game, effect):
    effect.__post_init__(); events = validate_group(game, effect.group)
    rows = successful_entries(game._state, effect.group)
    if (effect.success_ids, effect.attack, effect.health) != (tuple(r.id for r in rows),
            sum(r.entry_attack for r in rows), sum(max(0, r.entry_health) for r in rows)):
        raise ValueError('Recruit reward changed its complete original operands')
    event = next((e for e in events if e.sequence == effect.reward_event), None)
    c = effect.group.accepted
    if (event is None or event.kind != REWARD or dict(event.data) != reward_data(effect) or
            (event.source_id, event.player_id) != (c.source_id, c.player_id)):
        raise ValueError('Recruit reward lost its unique original acceptance')


def start(r, request):
    request.__post_init__()
    accepted = replace(request.original, state=deepcopy(r.state))
    group = ContinueRecruitStatGroup(request, accepted, len(r.game._events)+1)
    r.emit(ACCEPTED, source_id=accepted.source_id, player_id=accepted.player_id,
        _capture=False, **signature(group))
    return (group,)


def advance(r, group):
    validate_group(r.game, group)
    c = group.accepted
    if len(group.recruit_ids) < len(ATTACKS):
        index = len(group.recruit_ids); identity = r.state.next_recruit_summon_id
        r.emit(SLOT, source_id=c.source_id, player_id=c.player_id, group=group.event_cursor,
            index=index, recruit_id=identity, _capture=False)
        return (child_request(group, index), replace(group, recruit_ids=(*group.recruit_ids, identity)))
    rows = successful_entries(r.state, group)
    finish = FinishRecruitStatGroup(group, tuple(row.id for row in rows),
        sum(row.entry_attack for row in rows), sum(max(0, row.entry_health) for row in rows), len(r.game._events)+1)
    r.emit(REWARD, source_id=c.source_id, player_id=c.player_id, _capture=False, **reward_data(finish))
    from .sacrifice import BuffCapturedMinion
    ref = original_presence(group.request)
    return ((BuffCapturedMinion(ref, finish.attack, finish.health, c.source_id),)
        if ref is not None and (finish.attack or finish.health) else ()) + (finish,)


def finish(r, effect):
    validate_finish(r.game, effect); c = effect.group.accepted
    r.emit(FINISHED, source_id=c.source_id, player_id=c.player_id, group=effect.group.event_cursor,
        reward=effect.reward_event, _capture=False)
    return ()


def work_items(value, depth=0):
    if depth > 64:
        raise ValueError('Recruit stat group frame nesting exceeds limit')
    if type(value) in CONTROL:
        yield value
    elif type(value) in (RuleContext, GameState):
        return
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from work_items(item, depth+1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from work_items(item, depth+1)
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from work_items(getattr(value, field.name), depth+1)


def reject_choice_control(options):
    if any(type(v) is not RecruitAttackGroupForStats for v in work_items(options)):
        raise ValueError('Choice options cannot inject internal recruit group control')


def validate_boundary(game):
    events = timeline(game)
    accepted = {e.sequence: e for e in events if e.kind == ACCEPTED}
    linked = {}
    for e in events:
        if e.kind == 'recruit_summon_accepted':
            root = json.loads(dict(e.data)['root'])
            key = root['spec'].get('stat_group_id')
            if key is not None:
                if type(key) is not int or key not in accepted:
                    raise ValueError('Physical recruit lost its original stat group acceptance')
                linked.setdefault(key, []).append(root['id'])
    if not accepted:
        if any(e.kind in (SLOT, REWARD, FINISHED) for e in events):
            raise ValueError('Recruit stat group diagnostics lost their acceptance')
        return
    frame = game._frame
    works = [] if frame is None else list(work_items((frame.prefix, frame.continuation)))
    if frame is not None:
        reject_choice_control(frame.options)
        if works != list(work_items(frame.paid_hand_choice_boundary.work)):
            raise ValueError('Recruit stat group changed its original owed choice work')
    pending = {}
    for work in works:
        if type(work) is RecruitAttackGroupForStats:
            work.__post_init__(); continue
        group = work.group if type(work) is FinishRecruitStatGroup else work
        validate_group(game, group, allow_last_active=type(work) is ContinueRecruitStatGroup)
        if type(work) is FinishRecruitStatGroup:
            validate_finish(game, work)
        pending[group.event_cursor] = pending.get(group.event_cursor, 0)+1
    finished = {}
    for e in events:
        if e.kind not in (SLOT, REWARD, FINISHED):
            continue
        key = dict(e.data).get('group')
        if key not in accepted or e.sequence <= key or (e.source_id, e.player_id) != (
                accepted[key].source_id, accepted[key].player_id):
            raise ValueError('Recruit group diagnostic borrowed another root')
        if e.kind == FINISHED:
            finished[key] = finished.get(key, 0)+1
    for key in accepted:
        if finished.get(key, 0) > 1 or (key in finished and key in pending):
            raise ValueError('Recruit stat group completed or queued twice')
        if key not in finished and (game._state.status != 'finished' or key in pending) and pending.get(key) != 1:
            raise ValueError('Recruit stat group lost its unique remaining continuation')
        header = accepted[key]; data = dict(header.data)
        expected_keys = {'policy', 'attacks', 'source_card', 'battlecry', 'original_state',
            'accepted_state', 'first_recruit', 'presence'}
        if (set(data) != expected_keys or data.get('policy') != POLICY or data.get('attacks') != ATTACKS or
                type(data.get('first_recruit')) is not int or data['first_recruit'] < 1 or
                type(data.get('source_card')) is not str or type(data.get('battlecry')) is not str or
                any(type(data.get(k)) is not str or len(data[k]) != 64 or
                    set(data[k])-set('0123456789abcdef') for k in ('original_state', 'accepted_state'))):
            raise ValueError('Recruit stat group changed its finite original policy')
        cry = json.loads(data['battlecry'])
        if (type(cry) is not dict or type(cry.get('id')) is not int or cry['id'] < 1 or
                (cry.get('source_id'), cry.get('player_id')) != (header.source_id, header.player_id)):
            raise ValueError('Recruit stat group changed its original Battlecry identity')
        slots = [e for e in events if e.kind == SLOT and dict(e.data).get('group') == key]
        rewards = [e for e in events if e.kind == REWARD and dict(e.data).get('group') == key]
        closes = [e for e in events if e.kind == FINISHED and dict(e.data).get('group') == key]
        if len(slots) > len(ATTACKS) or len(rewards) > 1 or closes and not rewards:
            raise ValueError('Recruit stat group duplicated or omitted an original stage')
        if linked.get(key, []) != [dict(e.data).get('recruit_id') for e in slots]:
            raise ValueError('Recruit group lost its complete actual linked producer inventory')
        roots = []
        cause = None
        for index, slot in enumerate(slots):
            identity = dict(slot.data).get('recruit_id')
            root = next((r for r in game._state.recruit_summon_history if r.id == identity), None)
            if root is None:
                raise ValueError('Recruit slot omitted its actual physical producer')
            cause = root.spec.cause if cause is None else cause
            expected = SummonFromZone(header.player_id, query=PoolQuery(attack_equals=ATTACKS[index]),
                source_id=header.source_id, cause=cause, attack_basis='current', stat_group_id=key)
            if (type(identity) is not int or dict(slot.data) != dict(group=key, index=index, recruit_id=identity) or
                    root.spec != expected or root.event_cursor != slot.sequence or root.action != slot.action or
                    (cause.source.entity_id, cause.source.card_id, cause.player_id) !=
                    (header.source_id, data.get('source_card'), header.player_id) or
                    index == 0 and identity != data.get('first_recruit')):
                raise ValueError('Recruit group changed its exact original slot or query')
            if roots:
                previous = [e for e in events if e.kind == 'recruit_summon_finished' and
                    dict(e.data).get('recruit_id') == roots[-1].id]
                if len(previous) != 1 or previous[0].sequence >= slot.sequence:
                    raise ValueError('Recruit group started a later slot before original completion')
            roots.append(root)
        if rewards:
            if len(roots) != len(ATTACKS) or any(r.status == 'active' for r in roots):
                raise ValueError('Recruit group rewarded before all original slots completed')
            rows = entries_from_roots(game._state, roots, header.player_id)
            expected = dict(group=key, success_ids=tuple(r.id for r in rows),
                attack=sum(r.entry_attack for r in rows), health=sum(max(0, r.entry_health) for r in rows), policy=POLICY)
            if dict(rewards[0].data) != expected or rewards[0].sequence <= slots[-1].sequence:
                raise ValueError('Closed recruit reward changed its complete original operands')
        if closes and (dict(closes[0].data) != dict(group=key, reward=rewards[0].sequence) or
                closes[0].sequence <= rewards[0].sequence):
            raise ValueError('Recruit group closed against a different original reward')


def register(mechanics):
    mechanics.register(RecruitAttackGroupForStats, start)
    mechanics.register(ContinueRecruitStatGroup, advance)
    mechanics.register(FinishRecruitStatGroup, finish)
