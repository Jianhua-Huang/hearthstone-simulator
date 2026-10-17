"""Finite native resurrection completion: original returned bodies attack in order.

Selection and combat delegate to the existing random-enemy and forced-attack
executors. The controls preserve their reaction windows and actual window IDs.
"""
from dataclasses import dataclass, replace
import json

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, ForceAttack, _integer
from .model import BoardPresenceReference, CardType, Zone


@dataclass(frozen=True)
class ResurrectionAttacks:
    members: tuple[SourceAllocationFact, ...]
    index: int = 0
    stage: str = 'ready'
    attack: ForceAttack | None = None
    window_id: int | None = None
    status: str = 'active'

    def __post_init__(self):
        if type(self.members) is not tuple or any(type(x) is not SourceAllocationFact for x in self.members):
            raise ValueError('Complete original resurrection deliveries required')
        for member in self.members:
            member.__post_init__()
            if member.kind != CardType.MINION or member.zone != Zone.BOARD:
                raise ValueError('Resurrection attack member was not an actual minion delivery')
        if len({x.entity_id for x in self.members}) != len(self.members):
            raise ValueError('Duplicated original resurrection attack body')
        _integer(self.index, 'resurrection attack index', 0)
        if self.index > len(self.members) or self.stage not in ('ready', 'chosen', 'applied'):
            raise ValueError('Invalid resurrection attack progress')
        if self.status not in ('active', 'completed', 'interrupted'):
            raise ValueError('Unknown resurrection attack status')
        if (self.status == 'completed') != (self.index == len(self.members)):
            raise ValueError('Resurrection attack completion changed the original group')
        if self.stage == 'ready' and (self.attack is not None or self.window_id is not None):
            raise ValueError('Unselected resurrection attack borrowed combat work')
        if self.attack is not None:
            if type(self.attack) is not ForceAttack or self.index == len(self.members):
                raise ValueError('Typed original forced attack required')
            self.attack.__post_init__()
            if (self.attack.attacker_id != reference(self.members[self.index]) or
                    type(self.attack.defender_id) is not BoardPresenceReference or
                    self.attack.combat_relation != 'opponent'):
                raise ValueError('Resurrection attack changed its original returned body')
        if self.window_id is not None:
            _integer(self.window_id, 'actual resurrection attack window', 1)
            if self.stage != 'applied' or self.attack is None:
                raise ValueError('Resurrection attack borrowed an undeclared window')
        if self.status == 'completed' and self.stage != 'ready':
            raise ValueError('Completed resurrection attack retained a pending step')


def reference(member):
    return BoardPresenceReference(member.entity_id, member.entered_order)


def members(root, children):
    return tuple(delivery.entity for pick in root.picks for delivery in children[pick.entry_root_id].deliveries
                 if delivery.entity is not None)


def initial(root, children):
    group = members(root, children)
    return ResurrectionAttacks(group, status='active' if group else 'completed')


@dataclass(frozen=True)
class ContinueResurrectionAttacks(Effect):
    root_id: int
    def __post_init__(self): _integer(self.root_id, 'resurrection attack root', 1)


@dataclass(frozen=True)
class ApplyResurrectionAttack(Effect):
    root_id: int
    index: int
    def __post_init__(self):
        _integer(self.root_id, 'resurrection attack root', 1)
        _integer(self.index, 'resurrection attack step', 0)


@dataclass(frozen=True)
class FinishResurrectionAttack(ApplyResurrectionAttack):
    pass


CONTROLS = (ContinueResurrectionAttacks, ApplyResurrectionAttack, FinishResurrectionAttack)


def change(r, root, phase, attacks):
    from .resurrection_summons import update, encoded
    root = update(r.state, root, attacks=attacks)
    r.emit('resurrection_attacks_progress', source_id=root.spec.cause.source.entity_id,
           player_id=root.spec.player_id, resurrection_batch_id=root.id, phase=phase,
           root=encoded(root), _capture=False)
    return root


def require(state, effect, stage):
    from .resurrection_summons import record
    effect.__post_init__()
    root = record(state, effect.root_id)
    plan = root.attacks
    if (plan is None or plan.status != 'active' or plan.stage != stage or
            hasattr(effect, 'index') and effect.index != plan.index):
        raise ValueError('Stale or foreign resurrection attack continuation')
    return root, plan


def continue_attacks(r, effect):
    from .forced_attack_sequences import AttackRandomEnemyMinion, execute
    root, plan = require(r.state, effect, 'ready')
    work = tuple(execute(r, AttackRandomEnemyMinion(reference(plan.members[plan.index]),
        root.spec.player_id, root.spec.source_id)))
    if len(work) > 1 or work and type(work[0]) is not ForceAttack:
        raise ValueError('Random enemy attack did not return its ordinary forced combat')
    attack = work[0] if work else None
    change(r, root, 'chosen', replace(plan, stage='chosen', attack=attack))
    # The random_choice reactions run before Apply, exactly as for the native effect.
    return ((ApplyResurrectionAttack(root.id, plan.index),) if attack is not None else ()) + (
        FinishResurrectionAttack(root.id, plan.index),)


def apply_attack(r, effect):
    from .resolver import force_attack
    from .interrupts import ResolveAttack
    root, plan = require(r.state, effect, 'chosen')
    if plan.attack is None: raise ValueError('Skipped resurrection attack has no combat to apply')
    from .board_presence import resolve_board_presence
    attacker = resolve_board_presence(r.state, plan.attack.attacker_id)
    work = tuple(force_attack(r, plan.attack) or ()) if attacker is not None and attacker.controller == root.spec.player_id else ()
    if len(work) > 1 or work and type(work[0]) is not ResolveAttack:
        raise ValueError('Forced combat did not return its actual native attack window')
    change(r, root, 'applied', replace(plan, stage='applied', window_id=work[0].window_id if work else None))
    return work


def finish_attack(r, effect):
    from .resurrection_summons import record
    root = record(r.state, effect.root_id)
    plan = root.attacks
    require(r.state, effect, 'applied' if plan is not None and plan.attack is not None else 'chosen')
    if plan.window_id is not None:
        from .character_attacks import record as attack_record
        if attack_record(r.state, plan.window_id).terminal is None:
            raise ValueError('Resurrection group advanced before ordinary combat completed')
    index = plan.index + 1
    next_plan = ResurrectionAttacks(plan.members, index, status='completed' if index == len(plan.members) else 'active')
    change(r, root, 'step_finished', next_plan)
    return (ContinueResurrectionAttacks(root.id),) if next_plan.status == 'active' else ()


def interrupt(r):
    for root in tuple(r.state.resurrection_summon_history):
        if root.attacks is not None and root.attacks.status == 'active':
            change(r, root, 'interrupted', replace(root.attacks, status='interrupted'))


def validate_plan(state, registry, root, children, *, closed=False):
    plan = root.attacks
    expected = root.spec.attack_after_all and root.status not in ('active', 'interrupted')
    if (plan is not None) != expected:
        raise ValueError('Resurrection lost/invented its whole-batch attack obligation')
    if plan is None: return
    if type(plan) is not ResurrectionAttacks: raise ValueError('Typed resurrection attack plan required')
    plan.__post_init__()
    if plan.members != members(root, children):
        raise ValueError('Resurrection attacks cropped/reordered the actual returned group')
    for member in plan.members: validate_allocation(state, registry, member, closed=closed)
    if not closed:
        if plan.status == 'interrupted' and state.status == 'playing':
            raise ValueError('Playing resurrection attacks cannot be terminal interrupted')
        if plan.attack is not None: plan.attack.validate_in_state(state)
        if plan.window_id is not None:
            from .character_attacks import record as attack_record
            declaration = attack_record(state, plan.window_id).declaration
            if (declaration.attack_source_presence, declaration.attack_target_presence, declaration.player_id,
                    declaration.forced, declaration.combat_relation) != (
                    plan.attack.attacker_id, plan.attack.defender_id, root.spec.player_id, True, 'opponent'):
                raise ValueError('Resurrection attack borrowed another actual combat window')


def validate_control(state, control):
    if type(control) is ContinueResurrectionAttacks: require(state, control, 'ready')
    elif type(control) is ApplyResurrectionAttack:
        root, plan = require(state, control, 'chosen')
        if plan.attack is None: raise ValueError('Skipped resurrection attack retained combat work')
    else:
        from .resurrection_summons import record
        plan = record(state, control.root_id).attacks
        require(state, control, 'applied' if plan is not None and plan.stage == 'applied' else 'chosen')


def validate_queue(state, queue):
    for control in queue:
        if type(control) in CONTROLS: validate_control(state, control)
    for root in state.resurrection_summon_history:
        actual = [x for x in queue if type(x) in CONTROLS and x.root_id == root.id]
        plan = root.attacks
        expected = []
        if plan is not None and plan.status == 'active':
            if plan.stage == 'ready': expected = [ContinueResurrectionAttacks(root.id)]
            else:
                if plan.stage == 'chosen' and plan.attack is not None:
                    expected.append(ApplyResurrectionAttack(root.id, plan.index))
                expected.append(FinishResurrectionAttack(root.id, plan.index))
        if actual != expected:
            raise ValueError('Resurrection group lost/duplicated/reordered its owed attack controls')
        if plan is not None and plan.window_id is not None and plan.status == 'active':
            from .interrupts import ResolveAttack
            from .resolver import CombatDamage
            from .character_attacks import record as attack_record
            row = attack_record(state, plan.window_id)
            if row.terminal is None:
                work = next((x for x in queue if type(x) is ResolveAttack and x.window_id == plan.window_id or
                    type(x) is CombatDamage and x.attack_window_id == plan.window_id), None)
                # During DamageBatch reactions native character-attack validation owns the remaining tail.
                if work is not None and queue.index(work) > queue.index(expected[-1]):
                    raise ValueError('Resurrection group advanced ahead of its native combat work')


def from_dict(value):
    from .serialization import _row
    row = _row(value, ResurrectionAttacks)
    row['members'] = tuple(allocation_from_dict(x) for x in row['members'])
    if row['attack'] is not None:
        attack = _row(row['attack'], ForceAttack)
        for name in ('attacker_id', 'defender_id'):
            attack[name] = BoardPresenceReference(**_row(attack[name], BoardPresenceReference))
        row['attack'] = ForceAttack(**attack)
    return ResurrectionAttacks(**row)


def validate_events(game, children, closed, current):
    from .resurrection_summons import from_dict as root_from_dict, ResurrectionBatch, validate_record
    latest = {}
    for event in game._events:
        if event.kind == 'resurrection_batch_finished':
            root = root_from_dict(ResurrectionBatch, json.loads(dict(event.data)['root']))
            if root.attacks is not None:
                if root.attacks != initial(root, children):
                    raise ValueError('Resurrection attack acceptance changed the complete original group')
                latest[root.id] = root
        if event.kind != 'resurrection_attacks_progress': continue
        data = dict(event.data)
        if set(data) != {'resurrection_batch_id', 'phase', 'root'}:
            raise ValueError('Complete original resurrection attack progress receipt required')
        root = root_from_dict(ResurrectionBatch, json.loads(data['root']))
        validate_record(game._state, game.registry, root, closed=True, children=children)
        old = latest.get(root.id)
        if (old is None or data['resurrection_batch_id'] != root.id or replace(root, attacks=old.attacks) != old or
                (event.source_id, event.player_id) != (root.spec.cause.source.entity_id, root.spec.player_id) or
                event.action < root.action or old.attacks.status != 'active'):
            raise ValueError('Resurrection attack progress lost its original completed batch')
        a, b, phase = old.attacks, root.attacks, data['phase']
        if phase == 'chosen':
            valid = a.stage == 'ready' and b.stage == 'chosen' and replace(b, stage='ready', attack=None) == a
        elif phase == 'applied':
            valid = a.stage == 'chosen' and a.attack is not None and b.stage == 'applied' and replace(b, stage='chosen', window_id=None) == a
        elif phase == 'step_finished':
            index = a.index + 1
            valid = a.stage == ('applied' if a.attack is not None else 'chosen') and b == ResurrectionAttacks(
                a.members, index, status='completed' if index == len(a.members) else 'active')
        elif phase == 'interrupted': valid = b == replace(a, status='interrupted')
        else: valid = False
        if not valid: raise ValueError('Resurrection attack cropped/replayed/changed an original step')
        latest[root.id] = root
    for root in current.values():
        if root.attacks is not None and latest.get(root.id) != root:
            raise ValueError('Resurrection group differs from its complete original progress receipts')
    for identity, root in closed.items():
        if identity not in current and root.attacks is not None and latest[identity].attacks.status == 'active':
            raise ValueError('Retired resurrection group lost its owed attack completion')


def register(mechanics):
    mechanics.register_payload_type(ResurrectionAttacks)
    mechanics.register(ContinueResurrectionAttacks, continue_attacks)
    mechanics.register(ApplyResurrectionAttack, apply_attack)
    mechanics.register(FinishResurrectionAttack, finish_attack)
