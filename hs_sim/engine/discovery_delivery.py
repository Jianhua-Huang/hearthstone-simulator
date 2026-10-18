"""Original discovery recipients at existing physical producers.

Rule callbacks consume the semantic event's immutable allocation. The private
queue log is only a boundary consistency witness, never a recipient search.
"""
from dataclasses import dataclass, fields, is_dataclass
import json

from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .effects import AddToHand, Effect, ModifyCost, _integer, _source
from .model import ChoiceResult, CostSpec, Event, GameState, Zone
from .card_discoveries import PURPOSES, require_original_result

QUEUED = 'card_discovery_delivery_queued'
COMPLETED = 'card_discovered'


def recipe_types():
    from .zones import AddToDeck, CopyCard, MoveCard, DiscardCard
    from .temporary_cards import CreateTemporaryCard
    from .discovery_destinations import DeliverDiscoveredSpell
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer
    return (AddToHand, AddToDeck, CopyCard, MoveCard, DiscardCard, CreateTemporaryCard,DeliverDiscoveredSpell,CopyOpponentDeckOffer)


def recipe_face(request):
    return request.card_id if hasattr(request, 'card_id') else request.card.card_id


def validate_result(result):
    if type(result) is not ChoiceResult:
        raise ValueError('Discovery delivery requires its complete actual choice')
    result.__post_init__()
    if result.choice.purpose not in PURPOSES or len(result.selected) != 1:
        raise ValueError('Discovery delivery requires one genuine card selection')


def validate_recipe(result, request):
    validate_result(result)
    if request is None:
        return
    if type(request) not in recipe_types():
        raise ValueError('Unsupported original discovery materialization recipe')
    request.__post_init__()
    if (recipe_face(request) != result.selected[0].card_id or
            request.source_id != result.choice.source_id):
        raise ValueError('Discovery recipe borrowed another selected face or source')
    from .zones import MoveCard, DiscardCard
    if type(request) not in (MoveCard, DiscardCard) and request.player_id != result.choice.player_id:
        raise ValueError('Discovery recipe borrowed another original recipient player')
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer,validate_recipe as validate_copy_recipe
    if type(request)is CopyOpponentDeckOffer:validate_copy_recipe(result,request)


@dataclass(frozen=True)
class DiscoveryCompletion:
    result: ChoiceResult
    recipient: SourceAllocationFact | None
    recipe: Effect | None = None
    summon_root_id: int | None = None
    event_cursor: int | None = None

    def __post_init__(self):
        validate_recipe(self.result, self.recipe)
        if self.event_cursor is not None:
            _integer(self.event_cursor, 'original materialization event cursor', 0)
        if self.recipe is not None and self.event_cursor is None:
            raise ValueError('Physical discovery requires its original synchronous operation window')
        if self.summon_root_id is not None:
            _integer(self.summon_root_id, 'original discovery summon root', 1)
            if self.recipe is not None:
                raise ValueError('Discovery cannot claim physical and summon producers together')
        if self.recipient is not None:
            if type(self.recipient) is not SourceAllocationFact:
                raise ValueError('Discovery recipient requires its actual immutable allocation')
            self.recipient.__post_init__()
            if self.recipe is None and self.summon_root_id is None:
                raise ValueError('A selection-only discovery cannot invent a physical recipient')


@dataclass(frozen=True)
class MaterializeDiscoveredCard(Effect):
    result: ChoiceResult
    recipe: Effect | None

    def __post_init__(self):
        validate_recipe(self.result, self.recipe)


@dataclass(frozen=True)
class FinishCardDiscovery(Effect):
    completion: DiscoveryCompletion

    def __post_init__(self):
        if type(self.completion) is not DiscoveryCompletion:
            raise ValueError('Discovery completion requires its original typed receipt')
        self.completion.__post_init__()


@dataclass(frozen=True)
class PublishDiscoveredSummon(Effect):
    result: ChoiceResult
    root_id: int

    def __post_init__(self):
        validate_result(self.result)
        _integer(self.root_id, 'original selected summon root', 1)


@dataclass(frozen=True)
class MaterializeDiscoveredResurrection(Effect):
    result: ChoiceResult
    request: Effect

    def __post_init__(self):
        from .summon_sources import ResurrectMinion
        validate_result(self.result)
        if type(self.request) is not ResurrectMinion:
            raise ValueError('Selected resurrection requires its original typed request')
        self.request.__post_init__()
        if (self.request.player_id, self.request.source_id) != (self.result.choice.player_id, self.result.choice.source_id):
            raise ValueError('Selected resurrection borrowed another actor/source')


@dataclass(frozen=True)
class DiscountDiscoveredCard(Effect):
    event: Event
    source_id: int
    amount: int = 1

    def __post_init__(self):
        if type(self.event) is not Event or self.event.kind != COMPLETED:
            raise ValueError('Discovered discount requires its original semantic event')
        _integer(self.source_id, 'discovered discount source', 1)
        _integer(self.amount, 'discovered discount amount', 1)


CONTROL = (FinishCardDiscovery, PublishDiscoveredSummon)


def work_result(work):
    return work.completion.result if type(work) is FinishCardDiscovery else work.result


def queue(r, work):
    result = work_result(work)
    require_original_result(r.state, result)
    from .continuations import FrameCodec
    r.emit(QUEUED, source_id=result.choice.source_id, player_id=result.choice.player_id,
        choice_id=result.choice.id, work=json.dumps(FrameCodec(r.game.mechanics, r.registry).encode(work),
            ensure_ascii=False, sort_keys=True, separators=(',', ':')), _capture=False)
    return work


def finish_for_entity(r, result, entity, recipe, event_cursor=None):
    work = FinishCardDiscovery(DiscoveryCompletion(result, SourceAllocationFact.capture(r.state, entity), recipe,
        event_cursor=event_cursor))
    return queue(r, work)


def materialize(r, effect):
    effect.__post_init__(); require_original_result(r.state, effect.result)
    cursor = len(r.game._events)
    request = effect.recipe; entity = None; work = ()
    from .discovery_destinations import DeliverDiscoveredSpell,materialize as materialize_destination
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer,materialize as materialize_copy
    from .zones import AddToDeck, CopyCard, MoveCard, DiscardCard
    from .temporary_cards import CreateTemporaryCard
    if type(request) is AddToHand:
        from .opening import create_hand_card
        entity = create_hand_card(r, request)
    elif type(request) is AddToDeck:
        from .zones import create_deck_card
        entity = create_deck_card(r, request)
    elif type(request) is CopyCard:
        from .zones import copy_physical_card
        entity = copy_physical_card(r, request)
    elif type(request) is MoveCard:
        from .zones import move_card, move_physical_card, reference_entity
        if request.draw:
            entity = reference_entity(r, request.card)
            work = move_card(r, request) or ()
        else:
            entity = move_physical_card(r, request)
    elif type(request) is DiscardCard:
        from .zones import reference_entity, discard_card
        entity = reference_entity(r, request.card)
        work = discard_card(r, request) or ()
    elif type(request) is CreateTemporaryCard:
        from .temporary_cards import materialize_temporary_card
        entity = materialize_temporary_card(r, request)
    elif type(request)is DeliverDiscoveredSpell:
        entity=materialize_destination(r,request)
    elif type(request)is CopyOpponentDeckOffer:
        entity=materialize_copy(r,request)
    return (*work, finish_for_entity(r, effect.result, entity, request, cursor))


def summon_completion(state, registry, work, *, closed=False):
    work.__post_init__(); require_original_result(state, work.result)
    from .summon_quantities import record
    root = record(state, work.root_id)
    choice = work.result.choice
    if (root.request.player_id != choice.player_id or root.request.cause.source.entity_id != choice.source_id or
            len(root.request.materials) != 1 or root.request.materials[0].card_id != work.result.selected[0].card_id):
        raise ValueError('Discovery summon borrowed another original selected entry')
    if not closed and root.status not in ('completed', 'skipped'):
        raise ValueError('Discovery notification preceded complete original entry work')
    recipient = root.deliveries[0].entity if root.deliveries else None
    return DiscoveryCompletion(work.result, recipient, summon_root_id=root.id)


def publish_summon(r, effect):
    return finish(r, FinishCardDiscovery(summon_completion(r.state, r.registry, effect)))


def resurrect(r, effect):
    effect.__post_init__(); require_original_result(r.state, effect.result)
    from .summon_sources import resurrect_minion
    from .summon_quantities import FinishCardSummon
    work = tuple(resurrect_minion(r, effect.request))
    roots = [w.root_id for w in work if type(w) is FinishCardSummon]
    if len(roots) != 1:
        raise ValueError('Selected resurrection lost its actual returned original root control')
    notification = queue(r, PublishDiscoveredSummon(effect.result, roots[0]))
    return (*work, notification)


def validate_completion(state, registry, completion, *, closed=False):
    completion.__post_init__(); require_original_result(state, completion.result)
    from .discovery_destinations import validate_completion as validate_destination_completion
    validate_destination_completion(completion,registry)
    from .opponent_deck_gift_copy import validate_completion as validate_copy_completion
    validate_copy_completion(completion,registry)
    if completion.recipient is not None:
        validate_allocation(state, registry, completion.recipient, closed=closed)
    if completion.summon_root_id is not None:
        expected = summon_completion(state, registry,
            PublishDiscoveredSummon(completion.result, completion.summon_root_id), closed=closed)
        if expected != completion:
            raise ValueError('Discovery notification changed its original delivered body')


def finish(r, effect):
    effect.__post_init__(); completion = effect.completion
    validate_completion(r.state, r.registry, completion)
    from .continuations import FrameCodec
    original = require_original_result(r.state, completion.result)
    fact = completion.recipient
    r.emit(COMPLETED, source_id=completion.result.choice.source_id,
        target_id=None if fact is None else fact.entity_id, player_id=completion.result.choice.player_id,
        choice_id=completion.result.choice.id, discovery_id=original.id,
        recipient=None if fact is None else fact.payload(),
        receipt=json.dumps(FrameCodec(r.game.mechanics, r.registry).encode(completion),
            ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def original_recipient(state, event):
    if type(event) is not Event or event.kind != COMPLETED:
        raise ValueError('Original discovered recipient requires its actual semantic event')
    data = dict(event.data)
    rows = state.card_discovery_history; identity = data.get('discovery_id')
    if type(identity) is not int or not 1 <= identity <= len(rows):
        raise ValueError('Discovery notification lost its original selection record')
    result = rows[identity - 1].result; fact = allocation_from_payload(data.get('recipient'))
    if ((event.source_id, event.player_id, data.get('choice_id')) !=
            (result.choice.source_id, result.choice.player_id, result.choice.id) or
            event.target_id != (None if fact is None else fact.entity_id)):
        raise ValueError('Discovered recipient borrowed another actual selection')
    return fact


def discount(r, effect):
    effect.__post_init__()
    event = effect.event
    if event.sequence > len(r.game._events) or r.game._events[event.sequence - 1] != event:
        raise ValueError('Discovered discount lost its actual original semantic event')
    fact = original_recipient(r.state, event)
    if fact is None:
        return ()
    entity = r.state.entities.get(fact.entity_id)
    if (entity is None or fact.zone not in (Zone.HAND, Zone.DECK, Zone.BOARD) or
            (entity.card_id, entity.kind, entity.controller, entity.zone, entity.zone_epoch, entity.entered_order) !=
            (fact.card_id, fact.kind, fact.controller, fact.zone, fact.zone_epoch, fact.entered_order)):
        r.stale(effect, fact.entity_id); return ()
    from .costs import modify_cost
    return modify_cost(r, ModifyCost(entity.id, CostSpec(delta=-effect.amount), effect.source_id),
                       allow_dormant=True)


def validate_boundary(game):
    from .opponent_deck_gift_copy import validate_boundary as validate_copy_boundary
    validate_copy_boundary(game)
    from .hero_health_history import effective_events
    from .continuations import FrameCodec
    codec = FrameCodec(game.mechanics, game.registry); pending = {}; finished = set()
    events = effective_events(game._events); effective_sequences = {e.sequence for e in events}
    for event in events:
        if event.kind not in (QUEUED, COMPLETED): continue
        data = dict(event.data); key = data.get('choice_id')
        if event.kind == QUEUED:
            if set(data) != {'choice_id', 'work'} or key in pending or key in finished:
                raise ValueError('Duplicate or incomplete original discovery delivery acceptance')
            work = codec.decode(json.loads(data['work']))
            if type(work) not in CONTROL:
                raise ValueError('Discovery acceptance has another work type')
            result = work_result(work); require_original_result(game._state, result)
            if type(work) is FinishCardDiscovery:
                completion = work.completion
                validate_completion(game._state, game.registry, completion, closed=True)
                if completion.recipe is not None:
                    if completion.event_cursor >= event.sequence:
                        raise ValueError('Discovery materialization has a future operation window')
                    window = [e for e in game._events[completion.event_cursor:event.sequence-1]
                              if e.sequence in effective_sequences]
                    fact = completion.recipient
                    from .zones import CopyCard, MoveCard, DiscardCard
                    created = type(completion.recipe) not in (MoveCard, DiscardCard)
                    witnesses = [e for e in window if e.kind == ('card_created' if created else 'card_discarded')]
                    if type(completion.recipe) is MoveCard:
                        witnesses = [e for e in window if e.kind in ('card_moved_to_hand', 'card_moved_to_deck', 'card_drawn', 'card_burned')]
                    witnesses = [e for e in witnesses if e.action == event.action and
                                 e.source_id == completion.recipe.source_id]
                    if created and fact is not None and len(witnesses) != 1:
                        raise ValueError('Discovery creation lost its one original synchronous allocation')
                    if fact is not None and not any(e.target_id == fact.entity_id for e in witnesses):
                        raise ValueError('Discovery recipient has no actual original physical operation')
                    if fact is None and created and witnesses:
                        raise ValueError('Discovery discarded its actual created recipient')
            if (key, event.source_id, event.player_id) != (result.choice.id, result.choice.source_id, result.choice.player_id):
                raise ValueError('Discovery delivery acceptance changed original actor/source')
            pending[key] = work
        else:
            if set(data) != {'choice_id', 'discovery_id', 'recipient', 'receipt'} or key not in pending:
                raise ValueError('Discovery notification has no original accepted delivery')
            completion = codec.decode(json.loads(data['receipt']))
            if type(completion) is not DiscoveryCompletion:
                raise ValueError('Discovery notification requires complete typed original material')
            validate_completion(game._state, game.registry, completion, closed=True)
            expected = pending.pop(key)
            if type(expected) is PublishDiscoveredSummon:
                expected = FinishCardDiscovery(summon_completion(game._state, game.registry, expected, closed=True))
            if expected.completion != completion or original_recipient(game._state, event) != completion.recipient:
                raise ValueError('Discovery notification changed its accepted original outcome')
            finished.add(key)
    frame = game._frame
    queued = (*frame.prefix, *frame.continuation) if frame else ()
    controls = tuple(w for w in queued if type(w) in CONTROL)
    if frame:
        if any(type(e) in CONTROL for option in frame.options for e in option.effects):
            raise ValueError('Choice cannot inject discovery completion work')
        if controls != tuple(w for w in frame.paid_hand_choice_boundary.work if type(w) in CONTROL):
            raise ValueError('Discovery completion changed its original owed continuation')
    keys = [work_result(w).choice.id for w in controls]
    if len(set(keys)) != len(keys) or any(pending.get(k) != w for k, w in zip(keys, controls)):
        raise ValueError('Queued discovery completion lost its original accepted delivery')
    if game._state.status == 'playing' and set(keys) != set(pending):
        raise ValueError('Discovery delivery lost an owed original completion')


def register(mechanics):
    mechanics.register_payload_type(DiscoveryCompletion)
    mechanics.register(MaterializeDiscoveredCard, materialize)
    mechanics.register(FinishCardDiscovery, finish)
    mechanics.register(PublishDiscoveredSummon, publish_summon)
    mechanics.register(MaterializeDiscoveredResurrection, resurrect)
    mechanics.register(DiscountDiscoveredCard, discount)
