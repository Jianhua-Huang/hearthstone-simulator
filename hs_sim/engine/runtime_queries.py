"""Synchronous native query scope; never caches live rules or game outcomes."""
from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar('native_rule_queries', default=None)


@contextmanager
def query_materials(game):
    from .registry import Registry
    from .assembly_materials import candidate_materials
    registry = game.registry
    native = (type(registry) is Registry and registry._frozen and
              registry._identity_guard is not None)
    previous = _current.get()
    audit = getattr(game, 'runtime_audits', True) or not native
    if previous is not None and previous[0] is registry:
        audit = audit or previous[1]
        if audit == previous[1]:
            yield
            return
    token = _current.set((registry, audit, {}))
    try:
        with candidate_materials(registry, audit=audit):
            yield
    finally:
        _current.reset(token)


def audit_query_inputs(registry):
    """Standalone callers and explicit validators retain full input audits."""
    active = _current.get()
    return active is None or active[0] is not registry or active[1]


def decode_immutable_payload(value, decode):
    """Reuse a strict pure decoder during one native release operation only.

    Keys retain the actual input, never equality/hash aliases (True versus 1).
    Only ordinary immutable wire tuples qualify. No live state, failed decode,
    external object or mutable container is memoized; debug decodes normally.
    The decoder's returned native frozen record is private and read only.
    """
    active = _current.get()
    if active is None or active[1]:
        return decode(value)
    cache = active[2]
    key = (decode, id(value))
    entry = cache.get(key)
    if entry is not None:
        return entry[1]
    result = decode(value)
    if len(cache) < 1024 and _immutable_wire(value):
        cache[key] = (value, result)
    return result


def _immutable_wire(value):
    kind = type(value)
    return kind in (str, int, bool, type(None)) or (
        kind is tuple and all(_immutable_wire(child) for child in value))
