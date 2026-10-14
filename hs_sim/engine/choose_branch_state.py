"""Physical preselection and explicit branch inheritance; no payment or RNG.

A saved preference is distinct from an accepted root's frozen branch. Current
copies inherit it, base/reset recipes clear it, and compatible Rewind faces
rebind it. Ordinary history roots still choose anew unless their source opts in.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _source
from .errors import ResolutionError
from .model import CardType, ChooseBranchSelection, HeroPowerReference, Zone
from .zones import CardReference


def validate_selection(registry, value, *, card_id=None):
    if type(value) is not ChooseBranchSelection:
        raise ValueError('Physical preselection requires ChooseBranchSelection')
    value.__post_init__()
    if card_id is not None and value.card_id != card_id:
        raise ValueError('Physical preselection borrowed another card face')
    return validate_selection_for_card(registry.card(value.card_id), value)


def validate_selection_for_card(card, value):
    if type(value) is not ChooseBranchSelection:
        raise ValueError('Physical preselection requires ChooseBranchSelection')
    value.__post_init__()
    if value.card_id != card.id:
        raise ValueError('Physical preselection borrowed another card face')
    from .choose_one import branch
    if card.choose_one is None:
        raise ValueError('Physical preselection requires a Choose One card')
    branch(card, value.branch_id)
    allowed = (('power_manual', 'power_effect') if card.kind == CardType.HERO_POWER else
               ('hand', 'physical') if card.kind == CardType.MINION else
               ('hand', 'cast_effect', 'cast_draw', 'cast_history'))
    if any(origin not in allowed for origin in value.origins):
        raise ValueError('Preselected origin cannot activate this physical card kind')
    return value


def transfer_map(registry, source_card_id, card_id, mapping=None):
    """Complete explicit old-branch mapping; combined keeps its distinct role."""
    old, new = registry.card(source_card_id), registry.card(card_id)
    if old.kind != new.kind or old.choose_one is None or new.choose_one is None:
        raise ValueError('Branch transfer requires two Choose One cards of the same kind')
    original = tuple(b.id for b in (*old.choose_one.branches, old.choose_one.combined))
    mapping = tuple((s,s) for s in original) if mapping is None else mapping
    from .card_creation import validate_branch_transfer
    validate_branch_transfer('inherit', None, mapping)
    if tuple(a for a,b in mapping) != original:
        raise ValueError('Branch transfer requires the complete ordered original declaration')
    normal = {b.id for b in new.choose_one.branches}
    if any(b not in normal for a,b in mapping[:-1]) or mapping[-1][1] != new.choose_one.combined.id:
        raise ValueError('Branch transfer changed an ordinary/combined branch role')
    return dict(mapping)


def transfer_choose_branch(registry, selection, card_id, branch_map=None):
    """Freeze a declared recipe onto a new face without copying other state."""
    if selection is None:
        if branch_map is not None: raise ValueError('An unbound mapping has no original branch declaration')
        return None
    validate_selection(registry, selection)
    mapped = transfer_map(registry, selection.card_id, card_id, branch_map)
    return validate_selection(registry, replace(selection, card_id=card_id, branch_id=mapped[selection.branch_id]))


def capture_power_choose_branch(state, registry, record_id, *,
        origins=('power_manual', 'power_effect'), combination='override'):
    """Freeze one actual accepted activation, independently of current recipe."""
    from .hero_powers import power_record
    record = power_record(state, record_id)
    card = registry.card(record.card_id)
    if card.kind != CardType.HERO_POWER:
        raise ValueError('Accepted branch requires an actual hero power activation')
    # Invalid authority is still an error for an ordinary, unbranched power.
    value = ChooseBranchSelection(card.id, record.branch_id or '__unbranched__', origins, combination)
    if any(origin not in ('power_manual', 'power_effect') for origin in value.origins):
        raise ValueError('Accepted power branch requires a hero power origin')
    if card.choose_one is None:
        if record.branch_id is not None: raise ValueError('Unbranched power fabricated a choice')
        return None
    return validate_selection(registry, value)


def selection_from_dict(value):
    from .serialization import _list, _row
    row = _row(value, ChooseBranchSelection)
    row['origins'] = tuple(_list(row['origins'], 'preselected origins'))
    return ChooseBranchSelection(**row)


def options(definition, combined, origin, selection=None):
    """Pure complete branch policy, also used to replay compact receipts."""
    spec = definition.choose_one
    if spec is None:
        if selection is not None: raise ValueError('A non-Choose One card has a saved branch')
        return (None,)
    normal = (spec.combined.id,) if combined else tuple(b.id for b in spec.branches)
    if selection is None:
        return normal
    selection.__post_init__()
    if selection.card_id != definition.id:
        raise ValueError('Preselection belongs to another physical face')
    from .choose_one import branch
    branch(definition, selection.branch_id)
    if origin not in selection.origins:
        return normal
    if combined and selection.branch_id != spec.combined.id:
        return normal if selection.combination == 'override' else ()
    return (selection.branch_id,)


def for_entity(entity):
    return None if entity is None else entity.choose_branch


def rebind_face(entity, registry, card_id):
    """Compatible Rewind faces preserve preference; arbitrary transforms reset."""
    value = entity.choose_branch
    if value is None: return
    old, new = registry.card(value.card_id), registry.card(card_id)
    if old.choose_one != new.choose_one or old.kind != new.kind:
        raise ValueError('Saved branch cannot be rebound to an unrelated face')
    entity.choose_branch = replace(value, card_id=card_id)


def validate_boundary(game):
    for entity in game._state.entities.values():
        if entity.choose_branch is not None:
            validate_selection(game.registry, entity.choose_branch, card_id=entity.card_id)
            if entity.kind != game.registry.card(entity.card_id).kind:
                raise ValueError('Preselection carrier lost its physical kind')


@dataclass(frozen=True)
class SetChooseBranch(Effect):
    """Set/clear a saved choice on one captured hand/deck card or installed power."""
    card: CardReference | HeroPowerReference
    branch_id: str | None
    origins: tuple[str, ...] = ('hand',)
    combination: str = 'override'
    source_id: int | None = None

    def __post_init__(self):
        if type(self.card) not in (CardReference, HeroPowerReference):
            raise ValueError('Preselection requires a captured physical card or power reference')
        self.card.__post_init__(); _source(self.source_id)
        # Clear requests have the same strict declaration shape as set requests.
        ChooseBranchSelection(self.card.card_id, self.branch_id or '__clear__', self.origins, self.combination)
        if self.branch_id is not None and (type(self.branch_id) is not str or not self.branch_id.strip()):
            raise ValueError('Preselection branch must be a nonempty string or None')


def set_branch(r, effect):
    from .zones import reference_entity, source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    value = None if effect.branch_id is None else validate_selection(r.registry,
        ChooseBranchSelection(effect.card.card_id, effect.branch_id, effect.origins, effect.combination))
    if type(effect.card) is CardReference:
        entity = reference_entity(r, effect.card)
    else:
        from .hero_powers import selected_power
        from types import SimpleNamespace
        entity = selected_power(r, SimpleNamespace(power=effect.card, player_id=effect.card.player_id))
    if entity is None: return
    entity.choose_branch = value
    r.emit('choose_branch_changed', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller)


def history_selection(state, registry, child, policy, *, origin='physical'):
    """Bind each actual generated child to its own committed occurrence."""
    if policy == 'current': return None
    if policy != 'inherit': raise ValueError('Unknown historical branch inheritance policy')
    if not 1 <= child.occurrence_id <= len(state.play_history):
        raise ValueError('Inherited branch lost its actual historical hand root')
    record = state.play_history[child.occurrence_id - 1]
    if (record.card_id, record.kind) != (child.card_id, child.kind):
        raise ValueError('Inherited branch borrowed another historical physical face')
    if registry.card(record.card_id).choose_one is None:
        if record.branch_id is not None: raise ValueError('Unbranched history fabricated a choice')
        return None
    return validate_selection(registry, ChooseBranchSelection(record.card_id, record.branch_id, (origin,)))


def register(mechanics):
    mechanics.register_payload_type(ChooseBranchSelection)
    mechanics.register(SetChooseBranch, set_branch)
