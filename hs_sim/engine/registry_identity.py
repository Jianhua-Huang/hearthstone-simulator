"""Strict, callback-free change detection for a validated static inventory.

No digest is derived here. Unknown extension values disable reuse, so their
original validation/serialization path remains live. Values are compared by
identity rather than equality (in particular, True cannot impersonate 1).
"""
from dataclasses import fields, is_dataclass
from enum import Enum, EnumMeta
from operator import attrgetter, is_
from types import BuiltinFunctionType, FunctionType, MethodType, ModuleType
import sys

_EXCLUDED=frozenset(('_identity_guard','_fingerprint_cache'))
_ABSENT=object()
_ATOMIC=(str,int,float,bool,bytes,type(None),FunctionType,BuiltinFunctionType,MethodType)
_ATOMIC_IDS=frozenset(id(kind)for kind in _ATOMIC)


def _same_values(current,original):
    return len(current)==len(original) and all(map(is_,current,original))


def _reader(names):
    if not names:return lambda value:()
    get=attrgetter(*names)
    return get if len(names)>1 else lambda value:(get(value),)


def _engine_kind(kind):
    module=kind.__module__
    owner=sys.modules.get(module)if type(module)is str else None
    return (type(owner)is ModuleType and module.startswith('hs_sim.engine.') and
            vars(owner).get(kind.__name__)is kind)


class RegistryInventoryGuard:
    @classmethod
    def capture(cls,registry):
        guard=cls()
        guard.roots=tuple((k,v)for k,v in vars(registry).items()if k not in _EXCLUDED)
        # Instance method overrides are extensions, not static declarations.
        if any(any(type(v)is t for t in (FunctionType,BuiltinFunctionType,MethodType))for k,v in guard.roots):return None
        guard.dicts=[];guard.lists=[];guard.sets=[];guard.records=[];guard.schemas={};guard.enums={}
        pending=[v for k,v in guard.roots];seen=set()
        while pending:
            value=pending.pop();kind=type(value)
            if id(kind)in _ATOMIC_IDS:continue
            if type(kind) is EnumMeta and issubclass(kind,Enum) and _engine_kind(kind):
                guard.enums[id(kind)]=kind
                continue
            if id(value)in seen:continue
            seen.add(id(value))
            if kind is dict:
                items=tuple(value.items());guard.dicts.append((value,items))
                pending.extend(k for k,v in items);pending.extend(v for k,v in items)
            elif kind is list:
                items=tuple(value);guard.lists.append((value,items));pending.extend(items)
            elif kind is set:
                items=tuple(value);guard.sets.append((value,items));pending.extend(items)
            elif kind is tuple or kind is frozenset:pending.extend(value)
            elif type(kind) is type:
                if kind not in guard.schemas:
                    if not(_engine_kind(kind)and is_dataclass(kind)and kind.__dataclass_params__.frozen):return None
                    declared=fields(kind);names=tuple(f.name for f in declared)
                    guard.schemas[kind]=(declared,names,getattr(kind,'__post_init__',None),_reader(names))
                read=guard.schemas[kind][3];items=read(value)
                guard.records.append((value,kind,items));pending.extend(items)
            else:return None
        return guard

    def matches(self,registry):
        try:
            namespace=vars(registry)
            if len(namespace)-sum(k in namespace for k in _EXCLUDED)!=len(self.roots):return False
            if any(namespace.get(k,_ABSENT)is not v for k,v in self.roots):return False
            if any(not _engine_kind(kind)for kind in self.enums.values()):return False
            for kind,(declared,names,post_init,read)in self.schemas.items():
                current=fields(kind)
                if (not _engine_kind(kind)or not kind.__dataclass_params__.frozen or
                        getattr(kind,'__post_init__',None)is not post_init or
                        not _same_values(current,declared)or
                        not _same_values(tuple(f.name for f in current),names)):return False
            for obj,items in self.dicts:
                if len(obj)!=len(items):return False
                if any(k is not old_k or v is not old_v for (k,v),(old_k,old_v)in zip(obj.items(),items)):return False
            for obj,items in self.lists:
                if not _same_values(obj,items):return False
            for obj,items in self.sets:
                if len(obj)!=len(items)or {id(v)for v in obj}!={id(v)for v in items}:return False
            for obj,kind,items in self.records:
                if type(obj)is not kind or not _same_values(self.schemas[kind][3](obj),items):return False
            return True
        except (AttributeError,TypeError,RuntimeError):
            return False
