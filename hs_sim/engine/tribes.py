"""Physical minion tribe changes with shared attachment and reference lifetimes.

Printed card metadata and current entity identity are deliberately separate.
An all-tribe state can retain explicit exclusions without inventing a finite
tribe universe from the currently implemented card sample.
"""
from dataclasses import dataclass, fields, is_dataclass

from .effects import Effect, _source, _integer
from .model import CardType, Enchantment, GameState, TribeChangeSpec, _tribe_changes, _name, validate_minion_subtypes
from .sacrifice import MinionReference
from .zones import CardReference


@dataclass(frozen=True)
class TribeState:
    members: tuple[str, ...]
    excluded: tuple[str, ...] = ()

    def __post_init__(self):
        for values in (self.members, self.excluded):
            if (type(values) is not tuple or any(type(t) is not str for t in values)
                    or values != tuple(sorted(set(values)))):
                raise ValueError('Effective tribe sets require canonical immutable unique strings')
            for value in values:
                _name(value, 'effective tribe')
        if 'all' in self.members and self.members != ('all',):
            raise ValueError('All tribes cannot carry redundant individual members')
        if self.excluded and self.members != ('all',) or 'all' in self.excluded:
            raise ValueError('Only an all-tribe state can retain individual exclusions')

    def matches_any(self, tribes):
        TribeChangeSpec('set', tribes).__post_init__()
        if not tribes:
            return True
        return any((t == 'all' and self.members == ('all',) and not self.excluded)
                   or t in self.members and t != 'all'
                   or t != 'all' and self.members == ('all',) and t not in self.excluded for t in tribes)


def normalized(tribes):
    return TribeState(('all',) if 'all' in tribes else tuple(sorted(tribes)))


def apply_change(current, spec):
    if type(spec) is not TribeChangeSpec:
        raise ValueError('Tribe evaluation requires a typed change')
    spec.__post_init__()
    values = set(spec.tribes)
    if spec.operation == 'set':
        return normalized(spec.tribes)
    if 'all' in values:
        return TribeState(('all',)) if spec.operation == 'add' else TribeState(())
    if current is None:
        # Partial positive information cannot certify the complete unknown set.
        return None
    if current.members == ('all',):
        excluded = set(current.excluded)
        excluded = excluded - values if spec.operation == 'add' else excluded | values
        return TribeState(('all',), tuple(sorted(excluded)))
    members = set(current.members)
    members = members | values if spec.operation == 'add' else members - values
    return TribeState(tuple(sorted(members)))


def tribe_changes(entity):
    changes = tuple(c for c in entity.enchantments if c.tribe_change is not None)
    _tribe_changes(changes)
    return changes


def tribe_state_for(registry, card_id, changes=(), *, basis='current'):
    if type(basis) is not str or basis not in ('printed', 'current'):
        raise ValueError('Tribe queries require explicit printed or current basis')
    card = registry.card(card_id)
    _tribe_changes(changes)
    if changes and card.kind != CardType.MINION:
        raise ValueError('Tribe changes require a minion face')
    if basis == 'current' and card.kind != CardType.MINION:
        return TribeState(())
    metadata = card.metadata
    current = None if metadata is None or metadata.tribes is None else normalized(metadata.tribes)
    if basis == 'current':
        for change in changes:
            current = apply_change(current, change.tribe_change)
    return current


def tribe_state(registry, entity, *, basis='current'):
    return tribe_state_for(registry, entity.card_id, tribe_changes(entity), basis=basis)


def has_any_tribe(registry, entity, tribes, *, basis='current'):
    TribeChangeSpec('set', tribes).__post_init__()
    if not tribes:
        return True
    current = tribe_state(registry, entity, basis=basis)
    if current is None:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Unknown ' + basis + ' tribe set: ' + entity.card_id)
    return current.matches_any(tribes)


def has_any_subtype(registry, entity, subtypes):
    """Read current printed face membership, independently of tribe attachments."""
    validate_minion_subtypes(subtypes)
    if not subtypes:
        return True
    definition = registry.card(entity.card_id)
    if definition.kind != CardType.MINION:
        return False
    metadata = definition.metadata
    if metadata is None or metadata.subtypes is None:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Unknown printed minion subtypes: ' + entity.card_id)
    return bool(set(subtypes).intersection(metadata.subtypes))


@dataclass(frozen=True)
class ChangeMinionTribes(Effect):
    target: CardReference | MinionReference
    spec: TribeChangeSpec
    source_id: int | None = None
    expires_turn: int | None = None
    remove_on_silence: bool = True

    def __post_init__(self):
        from .cross_zone import reference_value
        reference_value(self.target)
        if type(self.spec) is not TribeChangeSpec:
            raise ValueError('ChangeMinionTribes requires TribeChangeSpec')
        self.spec.__post_init__()
        _source(self.source_id)
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'tribe change expiry', 1)
        if type(self.remove_on_silence) is not bool:
            raise ValueError('Tribe silence policy requires an exact bool')


def validate_request(state, registry, effect):
    effect.__post_init__()
    if registry.card(effect.target.card_id).kind != CardType.MINION:
        raise ValueError('Tribe change captured reference requires a minion definition')
    if effect.target.entity_id not in state.entities or effect.source_id is not None and effect.source_id not in state.entities:
        raise ValueError('Tribe change references an unknown physical target or source')


def change(r, effect):
    from .cross_zone import current_target
    from .lifecycle import attachment_id
    from .resolver import validate_attachment_source
    validate_request(r.state, r.registry, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    target = current_target(r, effect.target)
    if target is None:
        if type(effect.target) is MinionReference:
            r.stale(effect, effect.target.entity_id)
        return ()
    attachment = Enchantment(attachment_id(r.state), source_id=effect.source_id,
        expires_turn=effect.expires_turn, remove_on_silence=effect.remove_on_silence,
        label='tribes', tribe_change=effect.spec)
    target.enchantments.append(attachment)
    r.refresh_auras()
    r.emit('tribes_changed', source_id=effect.source_id, target_id=target.id,
           enchantment_id=attachment.id, operation=effect.spec.operation)
    return ()


def validate_frame_references(state, registry, value):
    """Captured work binds to its own original state; stale known refs may skip."""
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Tribe work exceeds codec depth')
        if type(item) is ChangeMinionTribes:
            validate_request(scope, registry, item)
            return
        if type(item) is RuleContext:
            for field in fields(item):
                if field.name != 'state':
                    visit(getattr(item, field.name), item.state, depth + 1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            visit(item.work, item.state, depth + 1)
            return
        if type(item) is GameState:
            return
        if isinstance(item, (tuple, list)):
            for child in item:
                visit(child, scope, depth + 1)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child, scope, depth + 1)
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item):
                visit(getattr(item, field.name), scope, depth + 1)
    visit(value, state, 0)


def register(mechanics):
    mechanics.register_payload_type(TribeState)
    mechanics.register(ChangeMinionTribes, change)
