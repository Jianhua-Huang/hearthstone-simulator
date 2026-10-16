"""Original spell target references across random-selection reactions."""
from dataclasses import dataclass
from .effects import Damage, Destroy, Effect, Silence, _integer
from .errors import ResolutionError
from .model import BoardPresenceReference, CardType, DamageKind, Zone
from .sacrifice import MinionReference, live_minion, reference_value


def reference_id(reference):
    if type(reference) is int:
        _integer(reference, 'original hero', 1)
        return reference
    reference_value(reference)
    return reference.entity_id


def operation_value(operation, amount):
    if operation not in ('damage', 'destroy', 'silence_destroy'):
        raise ValueError('Unsupported captured spell operation')
    _integer(amount, 'captured spell amount', 0)
    if operation in ('destroy','silence_destroy') and amount != 0:
        raise ValueError('Destruction has no damage amount')


@dataclass(frozen=True)
class DamageResidentSpellTarget(Effect):
    """A paid spell's original minion, following face/control but never reentry."""
    target: BoardPresenceReference
    source_id: int
    amount: int

    def __post_init__(self):
        if type(self.target) is not BoardPresenceReference:
            raise ValueError('Resident spell target requires its original physical presence')
        self.target.__post_init__()
        _integer(self.source_id, 'resident SPELL source', 1)
        _integer(self.amount, 'resident SPELL amount', 0)

    def validate_in_state(self, state):
        self.__post_init__()
        target = state.entities.get(self.target.entity_id)
        source = state.entities.get(self.source_id)
        if target is None or source is None or source.kind != CardType.SPELL:
            raise ValueError('Resident spell target/source was never allocated')
        if self.target.presence_id >= state.next_order:
            raise ValueError('Resident spell target borrowed an unallocated future presence')


def damage_resident(r, request):
    from .board_presence import resolve_board_presence
    request.validate_in_state(r.state)
    target = resolve_board_presence(r.state, request.target)
    if target is None or not target.active or target.doomed or target.health <= 0:
        r.stale(request, request.target.entity_id)
        return ()
    return (Damage(target.id, request.amount, request.source_id, DamageKind.SPELL),)


@dataclass(frozen=True)
class ApplyResidentSpellTarget(Effect):
    """Silence and destruction of one original board residence, in two steps."""
    target: BoardPresenceReference
    source_id: int
    operation: str = 'silence_destroy'

    def __post_init__(self):
        if type(self.target)is not BoardPresenceReference:
            raise ValueError('Resident destruction requires its original board presence')
        self.target.__post_init__()
        _integer(self.source_id,'resident destruction SPELL source',1)
        if self.operation not in('silence_destroy','destroy'):
            raise ValueError('Unsupported resident destruction step')

    def validate_in_state(self,state):
        self.__post_init__()
        target=state.entities.get(self.target.entity_id);source=state.entities.get(self.source_id)
        if target is None or source is None or source.kind!=CardType.SPELL:
            raise ValueError('Resident destruction target/source was never allocated')
        if self.target.presence_id>=state.next_order:
            raise ValueError('Resident destruction borrowed a future board presence')


def apply_resident(r,request):
    from .board_presence import resolve_board_presence
    request.validate_in_state(r.state)
    target=resolve_board_presence(r.state,request.target)
    if target is None or not target.active or target.doomed or target.health<=0:
        r.stale(request,request.target.entity_id)
        return ()
    if request.operation=='silence_destroy':
        return(Silence(target.id),ApplyResidentSpellTarget(request.target,request.source_id,'destroy'))
    from .resolver import destroy
    return destroy(r,Destroy(target.id,request.source_id))


@dataclass(frozen=True)
class ApplySpellTarget(Effect):
    target: MinionReference | int
    source_id: int
    operation: str
    amount: int = 0

    def __post_init__(self):
        reference_id(self.target)
        _integer(self.source_id, 'captured SPELL source', 1)
        operation_value(self.operation, self.amount)
        if self.operation in ('destroy','silence_destroy') and type(self.target) is not MinionReference:
            raise ValueError('Captured destruction requires an ordinary minion')


@dataclass(frozen=True)
class RandomSpellTarget(Effect):
    candidates: tuple[MinionReference | int, ...]
    source_id: int
    operation: str
    amount: int = 0

    def __post_init__(self):
        _integer(self.source_id, 'random SPELL source', 1)
        operation_value(self.operation, self.amount)
        if type(self.candidates) is not tuple:
            raise ValueError('Spell candidates require immutable original references')
        for ref in self.candidates:
            ApplySpellTarget(ref, self.source_id, self.operation, self.amount).__post_init__()
        if len({reference_id(ref) for ref in self.candidates}) != len(self.candidates):
            raise ValueError('A physical spell candidate has one weight')


def eligible(r, reference):
    if type(reference) is MinionReference:
        card = r.registry.card(reference.card_id)
        if card.kind != CardType.MINION or card.interactable is not None:
            raise ResolutionError('Spell reference requires an original ordinary minion')
        return live_minion(r.state, reference)
    entity = r.state.entities.get(reference)
    if entity is not None and entity.kind != CardType.HERO:
        raise ResolutionError('Integer spell target must be a physical hero')
    return entity if entity is not None and entity.zone == Zone.HERO and entity.active and (
        entity.health > 0 and not entity.doomed and r.player(entity.controller).hero_id == entity.id) else None


def validate_source(r, request):
    request.__post_init__()
    source = r.state.entities.get(request.source_id)
    if source is None or r.registry.card(source.card_id).kind != CardType.SPELL:
        raise ResolutionError('Captured spell delivery requires its actual allocated SPELL')


def deliver(r, request):
    validate_source(r, request)
    entity = eligible(r, request.target)
    if entity is None:
        r.stale(request, reference_id(request.target))
        return ()
    if request.operation=='silence_destroy':
        from .board_presence import capture_board_presence
        return(ApplyResidentSpellTarget(capture_board_presence(r.state,entity.id),request.source_id),)
    if request.operation == 'destroy':
        from .resolver import destroy
        return destroy(r, Destroy(entity.id, request.source_id))
    from .resolver import settle_health_batch
    return settle_health_batch(r, (Damage(entity.id, request.amount, request.source_id, DamageKind.SPELL),))


def choose(r, request):
    validate_source(r, request)
    candidates = tuple(sorted((ref for ref in request.candidates if eligible(r, ref) is not None),key=reference_id))
    if not candidates:
        r.emit('random_choice_skipped', source_id=request.source_id, reason='no_candidates')
        return ()
    selected = candidates[0] if len(candidates) == 1 else r.game._rng.choice(candidates)
    resident=None
    if request.operation=='silence_destroy':
        from .board_presence import capture_board_presence
        resident=capture_board_presence(r.state,reference_id(selected))
    if len(candidates) > 1:
        r.emit('random_choice', source_id=request.source_id, target_id=reference_id(selected),
               candidates=tuple(reference_id(ref) for ref in candidates))
    if resident is not None:return(ApplyResidentSpellTarget(resident,request.source_id),)
    return (ApplySpellTarget(selected, request.source_id, request.operation, request.amount),)


def register(mechanics):
    mechanics.register(ApplyResidentSpellTarget,apply_resident)
    mechanics.register(DamageResidentSpellTarget, damage_resident)
    mechanics.register(ApplySpellTarget, deliver)
    mechanics.register(RandomSpellTarget, choose)
