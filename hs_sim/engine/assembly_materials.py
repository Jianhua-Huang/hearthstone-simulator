"""Bounded static materials within one synchronous assembly calculation.

Only immutable templates, derived definitions and recipe identities are reused.
Queries, candidates, weighting, live state and random selection stay uncached.
Debug checks the frozen registry at both boundaries and guards each result.
Release native queries reuse the same read-only materials without those
repeated audits. Mutable registries and extensions use the normal path.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from types import SimpleNamespace
from weakref import ref

from .registry_identity import RegistryInventoryGuard


MAX_REGISTRIES = 4
MAX_MATERIALS = 512
_owners = OrderedDict()
_lock = RLock()
_current = ContextVar('assembly_static_materials', default=None)


@contextmanager
def candidate_materials(registry, *, audit=True):
    from .registry import Registry
    active = _current.get()
    if active is not None and active[0] is registry and (not audit or active[2]):
        yield
        return
    eligible = (type(registry) is Registry and registry._frozen
                and (registry._identity_unchanged() if audit else registry._identity_guard is not None))
    if not eligible:
        token = _current.set(None)
        try:
            yield
        finally:
            _current.reset(token)
        return
    inventory = registry._identity_guard
    identity = id(registry)
    with _lock:
        row = _owners.get(identity)
        if row is None or row[0]() is not registry or row[1] is not inventory:
            row = (ref(registry), inventory, OrderedDict())
            _owners[identity] = row
        _owners.move_to_end(identity)
        while len(_owners) > MAX_REGISTRIES:
            _owners.popitem(last=False)
    token = _current.set((registry, row[2], audit))
    try:
        yield
    finally:
        _current.reset(token)
        if audit and (registry._identity_guard is not inventory or not inventory.matches(registry)):
            with _lock:
                row[2].clear()
            raise ValueError('Registry changed during static assembly enumeration')


def material(registry, key, compute):
    active = _current.get()
    if active is None or active[0] is not registry:
        return compute()
    cache = active[1]
    with _lock:
        entry = cache.get(key)
        if entry is not None and (not active[2] or entry[1].matches(entry[0])):
            cache.move_to_end(key)
            return entry[0].value
        cache.pop(key, None)
    value = compute()  # Errors and unsupported content are never cached.
    root = SimpleNamespace(value=value)
    guard = RegistryInventoryGuard.capture(root)
    if guard is not None:
        with _lock:
            cache[key] = (root, guard)
            cache.move_to_end(key)
            while len(cache) > MAX_MATERIALS:
                cache.popitem(last=False)
    return value
