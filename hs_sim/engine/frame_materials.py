"""Reuse unchanged captured states only within a single action transaction.

This is an internal codec optimization, never a cache for external snapshots.
Every returned state/wire has independent mutable storage. Full graph guards
cover mutations, scalar types, ordering and native schemas; unknown structures
keep the original validation and conversion path.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields
from enum import Enum, EnumMeta
from types import FunctionType

from .registry_identity import _engine_kind, _reader, _same_values
from .runtime_copy import _ordinary_record


_current = ContextVar('action_frame_materials', default=None)
_ATOMIC = (str, int, float, bool, bytes, type(None))


class GraphGuard:
    """No equality callbacks, hashes, or unchecked mutable descendants."""
    MAX_NODES = 20000

    @classmethod
    def capture(cls, root):
        guard = cls()
        guard.root = root
        guard.dicts, guard.lists, guard.sets, guard.records = [], [], [], []
        guard.schemas, guard.enums = {}, {}
        pending, seen = [root], set()
        while pending:
            value = pending.pop()
            kind = type(value)
            if kind in _ATOMIC:
                continue
            if type(kind) is EnumMeta and _engine_kind(kind):
                if (kind.__getattribute__ is not object.__getattribute__
                        or kind.__deepcopy__ is not Enum.__deepcopy__
                        or '__deepcopy__' in vars(value)):
                    return None
                guard.enums[kind] = kind.__deepcopy__
                continue
            if id(value) in seen:
                continue
            seen.add(id(value))
            if len(seen) > cls.MAX_NODES:
                return None
            if kind is dict:
                items = tuple(value.items())
                guard.dicts.append((value, items))
                pending.extend(k for k, v in items)
                pending.extend(v for k, v in items)
            elif kind is list:
                items = tuple(value)
                guard.lists.append((value, items))
                pending.extend(items)
            elif kind is set:
                items = frozenset(id(v) for v in value)
                guard.sets.append((value, items))
                pending.extend(value)
            elif kind in (tuple, frozenset):
                pending.extend(value)
            elif type(kind) is type and (kind in guard.schemas or _ordinary_record(kind)):
                if kind not in guard.schemas:
                    declared = fields(kind)
                    names = tuple(f.name for f in declared)
                    post = getattr(kind, '__post_init__', None)
                    if post is not None and (type(post) is not FunctionType or post.__module__ != kind.__module__):
                        return None
                    if type(kind.__init__) is not FunctionType or kind.__init__.__module__ != kind.__module__:
                        return None
                    guard.schemas[kind] = (declared, names, post, kind.__init__,
                                           kind.__dataclass_params__.frozen, _reader(names))
                schema = guard.schemas[kind]
                if set(vars(value)) != set(schema[1]):
                    return None
                items = schema[-1](value)
                guard.records.append((value, kind, tuple(vars(value)), items))
                pending.extend(items)
            else:
                return None
        return guard

    def matches(self, root):
        if root is not self.root:
            return False
        try:
            for kind, copy in self.enums.items():
                if (not _engine_kind(kind) or kind.__getattribute__ is not object.__getattribute__
                        or kind.__deepcopy__ is not copy):
                    return False
            for kind, (declared, names, post, init, frozen, read) in self.schemas.items():
                current = fields(kind)
                if (not _ordinary_record(kind) or kind.__init__ is not init
                        or getattr(kind, '__post_init__', None) is not post
                        or kind.__dataclass_params__.frozen is not frozen
                        or not _same_values(current, declared)
                        or not _same_values(tuple(f.name for f in current), names)):
                    return False
            for obj, items in self.dicts:
                if (len(obj) != len(items) or
                        any(k is not ok or v is not ov for (k, v), (ok, ov) in zip(obj.items(), items))):
                    return False
            if any(not _same_values(obj, items) for obj, items in self.lists):
                return False
            if any(frozenset(id(v) for v in obj) != items for obj, items in self.sets):
                return False
            return all(type(obj) is kind and _same_values(tuple(vars(obj)), keys)
                       and _same_values(self.schemas[kind][-1](obj), items)
                       for obj, kind, keys, items in self.records)
        except (AttributeError, TypeError, RuntimeError):
            return False

    def detached(self):
        """Copy an already checked native graph and record its guard together."""
        guard = GraphGuard.capture(None)
        guard.schemas, guard.enums = self.schemas, self.enums
        memo = {}

        def copy(value):
            kind = type(value)
            if kind in _ATOMIC or kind in self.enums:
                return value
            identity = id(value)
            if identity in memo:
                return memo[identity]
            if kind is dict:
                result = {}
                memo[identity] = result
                for key, child in value.items():
                    copied = copy(child)
                    result[copy(key)] = copied
                guard.dicts.append((result, tuple(result.items())))
            elif kind is list:
                result = []
                memo[identity] = result
                result.extend(copy(child) for child in value)
                guard.lists.append((result, tuple(result)))
            elif kind is tuple:
                children = [copy(child) for child in value]
                if identity in memo:
                    return memo[identity]
                result = tuple(children)
            elif kind in (set, frozenset):
                result = kind(copy(child) for child in value)
                if kind is set:
                    guard.sets.append((result, frozenset(id(v) for v in result)))
            else:
                result = object.__new__(kind)
                memo[identity] = result
                result.__dict__.update((name, copy(child)) for name, child in vars(value).items())
                guard.records.append((result, kind, tuple(vars(result)), self.schemas[kind][-1](result)))
            memo[identity] = result
            return result

        guard.root = copy(self.root)
        return guard


def _copy_wire(value, guard):
    if type(value) is dict:
        result = {k: _copy_wire(v, guard) for k, v in value.items()}
        guard.dicts.append((result, tuple(result.items())))
        return result
    if type(value) is list:
        result = [_copy_wire(v, guard) for v in value]
        guard.lists.append((result, tuple(result)))
        return result
    return value


class FrameMaterials:
    MAX_STATES = 64
    MAX_WIRES = 128

    def __init__(self, registry, *, deferred=False):
        self.registry = registry
        self.active = not deferred
        self.inventory = None
        self.enabled = None  # Check lazily: actions without frames pay no scan.
        self.states, self.wires = {}, {}

    def available(self):
        if self.enabled is None:
            from .registry import Registry
            self.enabled = (type(self.registry) is Registry and self.registry._frozen
                            and self.registry._identity_unchanged())
            if self.enabled:
                self.inventory = self.registry._identity_guard
        return self.enabled

    def disable(self):
        self.enabled = False
        self.states.clear()
        self.wires.clear()

    def encode_state(self, state, validate, encode):
        entry = self.states.get(id(state)) if self.available() else None
        if (entry is not None and entry[0].matches(state)
                and entry[1]['validate'] is validate and entry[1]['encode'] is encode):
            material = entry[1]
        else:
            validate(state, self.registry)
            wire = encode(state)
            if not self.enabled or len(self.states) >= self.MAX_STATES:
                return wire
            guard = GraphGuard.capture(state)
            if guard is None:
                return wire
            material = {'wire': wire, 'validate': validate, 'encode': encode, 'decoded': None}
            self.states[id(state)] = (guard, material)
        # Record the newly allocated wire containers as we copy them, avoiding
        # a second traversal just to build the mutation guard.
        guard = GraphGuard.capture(None)
        result = _copy_wire(material['wire'], guard)
        guard.root = result
        if len(self.wires) < self.MAX_WIRES:
            if len(guard.dicts) + len(guard.lists) <= GraphGuard.MAX_NODES:
                self.wires[id(result)] = (guard, material)
        return result

    def decode_state(self, wire, decode, validate):
        entry = self.wires.get(id(wire)) if self.available() else None
        material = (entry[1] if entry is not None and entry[0].matches(wire)
                    and entry[1]['validate'] is validate else None)
        saved = material['decoded'] if material is not None else None
        guard = None
        if saved is not None and saved[1] is decode and saved[0].matches(saved[0].root):
            guard = saved[0].detached()
            result = guard.root
        else:
            result = decode(wire)
            validate(result, self.registry)
        if material is not None and len(self.states) < self.MAX_STATES:
            guard = guard if guard is not None else GraphGuard.capture(result)
            if guard is not None:
                if saved is None or not saved[0].matches(saved[0].root):
                    material['decoded'] = (guard, decode)
                self.states[id(result)] = (guard, material)
        return result


@contextmanager
def action_frame_materials(registry, *, deferred=False):
    cache = FrameMaterials(registry, deferred=deferred)
    token = _current.set(cache)
    try:
        yield
        if cache.inventory is not None and (registry._identity_guard is not cache.inventory
                                            or not cache.inventory.matches(registry)):
            raise ValueError('Registry changed during action frame validation')
    finally:
        _current.reset(token)


def begin_choice_materials(registry, *, audit=False):
    cache = _current.get()
    if cache is not None and cache.registry is registry:
        cache.active = True
        if audit:
            cache.available()


def materials_for(registry, kind=None):
    cache = _current.get()
    if cache is None or cache.registry is not registry:
        return None
    # A foreign payload may execute arbitrary constructors/validation hooks.
    # Do not carry validated materials through that extension boundary.
    if kind is not None and not _engine_kind(kind):
        cache.disable()
    return cache if cache.active and cache.enabled is not False else None
