"""Atomic enemy character maximum-health theft to the player's current hero.

Ordinary minion debuffs use the existing Buff lifecycle; permanent hero changes
use the existing maximum-health projection. No damage/healing packet is made.
"""
from dataclasses import dataclass, replace
from .effects import Buff, Effect, _integer, _player
from .errors import ResolutionError
from .health_loss import StealHeroHealth, adjust_max_health, current_living_hero, steal_hero_health
from .model import BoardPresenceReference, CardType, Zone
from .sacrifice import MinionReference, live_minion, reference_value


def reference_id(reference):
    if type(reference) is int:
        _integer(reference, 'physical hero donor', 1)
        return reference
    reference_value(reference)
    return reference.entity_id


@dataclass(frozen=True)
class StealHealthToHero(Effect):
    player_id: int
    donor: MinionReference | int
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        reference_id(self.donor)
        _integer(self.amount, 'stolen maximum health', 0)
        _integer(self.source_id, 'health theft source', 1)


@dataclass(frozen=True)
class RandomStealHealthToHero(Effect):
    player_id: int
    candidates: tuple[MinionReference | int, ...]
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'stolen maximum health', 0)
        _integer(self.source_id, 'health theft source', 1)
        if type(self.candidates) is not tuple:
            raise ValueError('Health theft requires immutable original candidates')
        ids = [reference_id(ref) for ref in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError('Each physical health donor has one random weight')


@dataclass(frozen=True)
class StealHealthToMinion(Effect):
    beneficiary: MinionReference
    donor: MinionReference
    amount: int
    source_id: int

    def __post_init__(self):
        reference_value(self.beneficiary); reference_value(self.donor)
        _integer(self.amount, 'stolen remaining minion health', 0)
        _integer(self.source_id, 'minion health theft source', 1)
        if self.beneficiary.player_id == self.donor.player_id or self.beneficiary.entity_id == self.donor.entity_id:
            raise ValueError('Minion health theft requires original enemy donor and recipient')


@dataclass(frozen=True)
class ChooseHealthForMinion(Effect):
    beneficiary: MinionReference
    amount: int
    count: int
    source_id: int

    def __post_init__(self):
        reference_value(self.beneficiary)
        _integer(self.amount, 'chosen stolen minion health', 0)
        _integer(self.count, 'remaining minion theft choices', 0)
        _integer(self.source_id, 'chosen minion health theft source', 1)


@dataclass(frozen=True)
class StealHealthFromOtherMinions(Effect):
    player_id: int
    beneficiary: BoardPresenceReference
    amount: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        if type(self.beneficiary) is not BoardPresenceReference:
            raise ValueError('Other-minion theft requires its original delivered board residence')
        self.beneficiary.__post_init__()
        _integer(self.amount, 'health stolen from each other minion', 0)
        _integer(self.source_id, 'original stealing minion', 1)
        if self.source_id != self.beneficiary.entity_id:
            raise ValueError('Other-minion theft belongs to the original stealing minion itself')


def eligible(r, player_id, reference):
    if type(reference) is MinionReference:
        card = r.registry.card(reference.card_id)
        if card.kind != CardType.MINION or card.interactable is not None:
            raise ResolutionError('Health donor must be an ordinary original minion')
        target = live_minion(r.state, reference)
    else:
        target = r.state.entities.get(reference)
        if target is not None and target.kind != CardType.HERO:
            raise ResolutionError('Integer health donor must be a physical hero')
        if target is not None and (target.zone != Zone.HERO or not target.active or target.health <= 0
                or target.doomed or r.player(target.controller).hero_id != target.id):
            target = None
    return target if target is not None and target.controller != player_id else None


def validate_source(r, request):
    from .resolver import validate_attachment_source
    request.__post_init__()
    validate_attachment_source(r, request.source_id, None)


def deliver(r, request):
    from .resolver import buff
    validate_source(r, request)
    donor = eligible(r, request.player_id, request.donor)
    recipient = current_living_hero(r, request.player_id)
    if donor is None or recipient is None:
        r.stale(request, reference_id(request.donor)); return ()
    if donor.kind == CardType.HERO:
        return steal_hero_health(r, StealHeroHealth(request.player_id, donor.controller,
                                                  request.amount, request.source_id))
    amount = min(request.amount, max(0, donor.max_health))
    if not amount:
        return ()
    # Commit recipient first without publishing. Buff then commits the donor;
    # its first emitted event already observes both final values. The shared
    # scheduler performs deaths/reactions after this complete effect returns.
    events = adjust_max_health(r, recipient, amount, request.source_id, 'preserve_missing')
    buff(r, Buff(donor.id, health=-amount, source_id=request.source_id))
    for kind, data in events:
        r.emit(kind, **data)
    return ()


def choose(r, request):
    validate_source(r, request)
    candidates = tuple(sorted((ref for ref in request.candidates
                               if eligible(r, request.player_id, ref) is not None), key=reference_id))
    if not candidates or not request.amount:
        r.emit('random_choice_skipped', source_id=request.source_id,
               reason='no_candidates' if not candidates else 'zero_amount')
        return ()
    selected = candidates[0] if len(candidates) == 1 else r.game._rng.choice(candidates)
    if len(candidates) > 1:
        r.emit('random_choice', source_id=request.source_id, target_id=reference_id(selected),
               candidates=tuple(reference_id(ref) for ref in candidates))
    return (StealHealthToHero(request.player_id, selected, request.amount, request.source_id),)


def deliver_to_minion(r, request):
    """Commit both ordinary minion attachments before either notification."""
    from .resolver import _buff_to
    validate_source(r, request)
    beneficiary = live_minion(r.state, request.beneficiary)
    donor = live_minion(r.state, request.donor)
    for ref in (request.beneficiary, request.donor):
        card = r.registry.card(ref.card_id)
        if card.kind != CardType.MINION or card.interactable is not None:
            raise ResolutionError('Minion health transfer requires original ordinary minions')
    if beneficiary is None or donor is None:
        r.stale(request, request.donor.entity_id)
        return ()
    amount = min(request.amount, donor.health)
    if not amount:
        return ()
    debit = _buff_to(r, Buff(donor.id, health=-amount, source_id=request.source_id), donor, notify=False)
    credit = _buff_to(r, Buff(beneficiary.id, health=amount, source_id=request.source_id), beneficiary, notify=False)
    r.refresh_auras()
    for entity, enchantment, delta in ((donor, debit, -amount), (beneficiary, credit, amount)):
        r.emit('stats_changed', source_id=request.source_id, target_id=entity.id,
               enchantment_id=enchantment.id, attack_delta=0, health_delta=delta)
    return ()


def steal_from_other_minions(r, request):
    """Freeze all donor amounts, then commit the complete batch before events."""
    from .board_presence import resolve_board_presence
    from .resolver import _buff_to
    validate_source(r, request)
    beneficiary = resolve_board_presence(r.state, request.beneficiary)
    if (beneficiary is None or not beneficiary.active or beneficiary.health <= 0 or beneficiary.doomed or
            beneficiary.controller != request.player_id):
        r.stale(request, request.beneficiary.entity_id); return ()
    if r.registry.card(beneficiary.card_id).interactable is not None:
        raise ResolutionError('Health thief must be an ordinary current minion')
    donors = []
    for pid in (1, 2):
        for eid in tuple(r.player(pid).board):
            entity = r.state.entities[eid]
            card = r.registry.card(entity.card_id)
            if entity.zone != Zone.BOARD or entity.controller != pid or entity.kind != card.kind:
                raise ResolutionError('Other-minion health inventory differs from its actual board')
            if (entity.id == beneficiary.id or entity.kind != CardType.MINION or not entity.active or
                    entity.health <= 0 or entity.doomed): continue
            if card.interactable is not None:
                raise ResolutionError('Health donor must be an ordinary current minion')
            amount = min(request.amount, entity.health)
            if amount: donors.append((entity, amount))
    if not donors: return ()
    changes = [(entity, _buff_to(r, Buff(entity.id, health=-amount, source_id=request.source_id),
        entity, notify=False), -amount) for entity, amount in donors]
    amount = sum(amount for _, amount in donors)
    changes.append((beneficiary, _buff_to(r, Buff(beneficiary.id, health=amount, source_id=request.source_id),
        beneficiary, notify=False), amount))
    r.refresh_auras()
    for entity, enchantment, delta in changes:
        r.emit('stats_changed', source_id=request.source_id, target_id=entity.id,
            enchantment_id=enchantment.id, attack_delta=0, health_delta=delta)
    return ()


def choose_for_minion(r, request):
    """Each actual choice observes the board after the preceding theft/reactions."""
    from .battlecries import active_battlecry
    from .effects import ChoiceOption, RequestChoice
    from .errors import ResolutionLimitExceeded
    from .model import CardDefinition, TargetSpec
    from .targeting import accepts_target
    validate_source(r, request)
    if request.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Minion theft choices exceed resolution budget')
    beneficiary = live_minion(r.state, request.beneficiary)
    if beneficiary is None or not request.count or not request.amount:
        return ()
    # Use the common ability-target domain. Indirect automatic Battlecries keep
    # their existing random-choice policy and automatic selectable protections.
    definition = CardDefinition('health_theft.target', 'Enemy minion health donor',
        CardType.MINION, health=1, targeting=TargetSpec(zones=(Zone.BOARD,),
            kinds=(CardType.MINION,), relation='enemy'))
    battlecry = active_battlecry(r.state, request.source_id, beneficiary.controller)
    automatic = battlecry is not None and battlecry.choices == 'random'
    candidates = tuple(r.state.entities[eid] for eid in sorted(r.state.entities)
        if accepts_target(r.state, r.registry, beneficiary, definition, eid, automatic=automatic))
    if not candidates:
        return ()
    continuation = (replace(request, count=request.count - 1),) if request.count > 1 else ()
    options = tuple(ChoiceOption('target-' + str(index + 1), r.registry.card(e.card_id).name,
        (StealHealthToMinion(request.beneficiary, MinionReference.capture(e), request.amount, request.source_id),
            *continuation), card_id=e.card_id, entity_id=e.id) for index, e in enumerate(candidates))
    return (RequestChoice(beneficiary.controller, options, request.source_id,
        prompt='Choose an enemy minion to steal Health from',targeting=definition.targeting),)


def register(mechanics):
    mechanics.register(StealHealthToHero, deliver)
    mechanics.register(RandomStealHealthToHero, choose)
    mechanics.register(StealHealthToMinion, deliver_to_minion)
    mechanics.register(ChooseHealthForMinion, choose_for_minion)
    mechanics.register(StealHealthFromOtherMinions, steal_from_other_minions)
