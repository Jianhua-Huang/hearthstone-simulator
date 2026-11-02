"""Detached runtime copies without pickle reconstruction for native records.

This changes copying only: no state, validation result or wire payload is
cached. A memo belongs to one copy, exactly as with copy.deepcopy. Extensions,
container subclasses, slots and custom copy/reduction hooks use deepcopy.
"""
from copy import deepcopy as _deepcopy
from copyreg import dispatch_table
from dataclasses import is_dataclass
from enum import Enum, EnumMeta
from types import ModuleType
import sys


_ATOMIC = frozenset((str, int, float, bool, bytes, type(None)))
_MISSING = object()
_INSTANCE_PROTOCOLS = frozenset(('__deepcopy__', '__reduce__', '__reduce_ex__',
                               '__getstate__', '__setstate__', '__getnewargs__', '__getnewargs_ex__'))


def _ordinary_record(kind):
    if type(kind) is not type or type(kind.__module__) is not str:
        return False
    owner = sys.modules.get(kind.__module__)
    return (type(owner) is ModuleType and kind.__module__.startswith('hs_sim.engine.')
            and vars(owner).get(kind.__name__) is kind and is_dataclass(kind)
            and kind.__new__ is object.__new__
            and kind.__getattribute__ is object.__getattribute__
            and kind.__reduce__ is object.__reduce__
            and kind.__reduce_ex__ is object.__reduce_ex__
            and getattr(kind, '__getstate__', None) is object.__getstate__
            and not any(hasattr(kind, name) for name in
                        ('__deepcopy__', '__setstate__', '__getnewargs__', '__getnewargs_ex__'))
            and not any('__slots__' in vars(base) for base in kind.__mro__)
            and kind not in dispatch_table)


def _copy_kind(kind):
    if (type(kind) is EnumMeta and kind.__getattribute__ is object.__getattribute__
            and getattr(kind, '__deepcopy__', None) is Enum.__deepcopy__):
        return 'enum'
    return 'record' if _ordinary_record(kind) else 'extension'


def deepcopy(value):
    """Copy native runtime graphs; keep Python's fallback and alias semantics."""
    memo = {}
    ordinary = {}

    def copy(item):
        kind = type(item)
        if kind in _ATOMIC:
            return item
        identity = id(item)
        previous = memo.get(identity, _MISSING)
        if previous is not _MISSING:
            return previous
        # Python deepcopy already keeps wholly atomic tuples by identity.
        # RNG states and immutable history fields need no temporary child list.
        if kind is tuple and (not item or all(type(child) in _ATOMIC for child in item)):
            return item
        if kind is dict:
            result = {}
            memo[identity] = result
            for key, child in item.items():
                # deepcopy evaluates the value before the key; extension hooks
                # can observe this order and may refer back to this dictionary.
                copied = child if type(child) in _ATOMIC else copy(child)
                result[key if type(key) in _ATOMIC else copy(key)] = copied
        elif kind is set and not item and kind not in dispatch_table:
            # Empty keyword sets are common on every captured entity. There
            # are no children/hooks to reconstruct, but the new set still
            # participates in the memo so aliases remain local to the copy.
            result = set()
            memo[identity] = result
        elif kind is list:
            result = []
            memo[identity] = result
            result.extend(child if type(child) in _ATOMIC else copy(child) for child in item)
        elif kind is tuple:
            children = [child if type(child) in _ATOMIC else copy(child) for child in item]
            # A tuple may reach itself through a list. The recursive copy has
            # already supplied the canonical tuple in that case.
            if identity in memo:
                return memo[identity]
            result = item if all(a is b for a, b in zip(item, children)) else tuple(children)
        else:
            native = ordinary.get(kind)
            if native is None:
                native = ordinary[kind] = _copy_kind(kind)
            if native == 'enum' and '__deepcopy__' not in vars(item):
                return item
            if native == 'record' and not _INSTANCE_PROTOCOLS.intersection(vars(item)):
                result = object.__new__(kind)
                memo[identity] = result
                result.__dict__.update(copy(vars(item)))
            else:
                # An extension can change a later class's copy hooks. Never
                # retain a native-class decision across extension execution.
                ordinary.clear()
                result = _deepcopy(item, memo)
                ordinary.clear()
        if result is not item:
            memo[identity] = result
            # Match deepcopy's keep-alive convention for temporary objects
            # created by extension hooks sharing this memo.
            memo.setdefault(id(memo), []).append(item)
        return result

    return copy(value)
