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
    token = _current.set((registry, audit))
    try:
        with candidate_materials(registry, audit=audit):
            yield
    finally:
        _current.reset(token)


def audit_query_inputs(registry):
    """Standalone callers and explicit validators retain full input audits."""
    active = _current.get()
    return active is None or active[0] is not registry or active[1]
