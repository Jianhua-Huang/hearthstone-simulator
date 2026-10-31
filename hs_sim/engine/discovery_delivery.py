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
    from .hand_exchange_discovery import SelectHandExchange
    from .zones import AddToDeck, CopyCard, MoveCard, DiscardCard
    from .temporary_cards import CreateTemporaryCard
    from .discovery_destinations import DeliverDiscoveredSpell
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer
    from .sideboards import _TakeSideboardCard
    from .spell_weapons import DeliverDiscoveredSpellWeapon
    from .hero_power_discovery import InstallDiscoveredHeroPower
    from .spell_casts import CastSpell, CastStoredSpell
    from .discovery_cost_swaps import DeliverCostSwappedSpell
    return (SelectHandExchange, DeliverCostSwappedSpell, AddToHand, AddToDeck, CopyCard, MoveCard, DiscardCard, CreateTemporaryCard,DeliverDiscoveredSpell,CopyOpponentDeckOffer,_TakeSideboardCard,DeliverDiscoveredSpellWeapon,InstallDiscoveredHeroPower,CastStoredSpell,CastSpell)


def recipe_face(request):
    from .copy_materials import CapturedCardCopyMaterial
    material = getattr(request, 'card', None)
    if type(material) is CapturedCardCopyMaterial:
        return material.origin.card_id
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
    from .hand_exchange_discovery import validate_recipe as validate_hand_recipe
    validate_hand_recipe(result,request)
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer,validate_recipe as validate_copy_recipe
    if type(request)is CopyOpponentDeckOffer:validate_copy_recipe(result,request)
    from .sideboards import _TakeSideboardCard, validate_discovery_recipe
    if type(request) is _TakeSideboardCard:validate_discovery_recipe(result,request)
    from .hero_power_discovery import validate_recipe as validate_skill_recipe
    validate_skill_recipe(result, request)
    from .spell_casts import CastSpell, CastStoredSpell
    if type(request) is CastSpell and (request.target_id is not None or request.targeting != 'random' or
            request.choices != 'random' or request.branch_id is not None or request.target_preference is not None or
            request.mana_budget is not None or request.target_ids):
        raise ValueError('Discovered generated CAST requires its plain original Secret recipe')
    if type(request) is CastStoredSpell and (request.card.zone != Zone.DECK or
            request.card.player_id != result.choice.player_id or request.target_id is not None or
            request.targeting != 'random' or request.choices != 'random' or request.branch_id is not None or
            request.target_preference is not None or request.target_ids):
        raise ValueError('Discovered direct CAST requires its plain original own-deck spell')


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
    work = FinishCardDiscovery(DiscoveryCompletion(result, None if entity is None else SourceAllocationFact.capture(r.state, entity), recipe,
        event_cursor=event_cursor))
    return queue(r, work)


def materialize(r, effect):
    effect.__post_init__(); require_original_result(r.state, effect.result)
    cursor = len(r.game._events)
    request = effect.recipe; entity = None; work = ()
    from .hand_exchange_discovery import SelectHandExchange,materialize as materialize_hand_exchange
    if type(request)is SelectHandExchange:
        entity,work=materialize_hand_exchange(r,request)
        completion=finish_for_entity(r,effect.result,entity,request,cursor)
        # Finish the first genuine discovery before accepting the other hand.
        return(completion,*work)if request.request.first is None else(*work,completion)
    from .discovery_destinations import DeliverDiscoveredSpell,materialize as materialize_destination
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer,materialize as materialize_copy
    from .zones import AddToDeck, CopyCard, MoveCard, DiscardCard
    from .temporary_cards import CreateTemporaryCard
    from .sideboards import _TakeSideboardCard, materialize_discovery
    from .spell_weapons import DeliverDiscoveredSpellWeapon,materialize as materialize_weapon
    from .hero_power_discovery import InstallDiscoveredHeroPower, materialize as materialize_skill
    from .spell_casts import CastSpell, CastStoredSpell, cast_stored, materialize_generated_cast
    from .discovery_cost_swaps import DeliverCostSwappedSpell,materialize as materialize_cost_swap
    if type(request)is DeliverCostSwappedSpell:
        entity=materialize_cost_swap(r,request)
    elif type(request) is AddToHand:
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
    elif type(request) is _TakeSideboardCard:
        entity=materialize_discovery(r,request)
    elif type(request)is DeliverDiscoveredSpellWeapon:
        entity=materialize_weapon(r,request)
    elif type(request) is InstallDiscoveredHeroPower:
        entity = materialize_skill(r, effect.result, request)
    elif type(request) is CastStoredSpell:
        from .zones import reference_entity
        entity = reference_entity(r, request.card)
        work = () if entity is None else tuple(cast_stored(r, request))
    elif type(request) is CastSpell:
        if r.registry.card(request.card_id).secret is None:
            raise ValueError('Discovered generated CAST requires an actual Secret definition')
        entity, work = materialize_generated_cast(r, request)
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
    from .discovery_summons import DiscoverySummonEntryLink,record as discovery_record
    link=root.request.producer_link
    if type(link)is DiscoverySummonEntryLink:
        parent=discovery_record(state,link.producer_id)
        if parent.spec.summon_copies==2:
            if link.index!=0 or len(parent.entry_root_ids)!=2 or parent.entry_root_ids[0]!=root.id:
                raise ValueError('Selected-copy discovery lost its two original entry roots')
            if record(state,parent.entry_root_ids[1]).status not in ('completed','skipped'):
                raise ValueError('Discovery notification preceded its second original copy')
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
    from .hand_exchange_discovery import validate_completion as validate_hand_completion
    validate_hand_completion(state,registry,completion)
    from .discovery_cost_swaps import validate_completion as validate_cost_swap_completion
    validate_cost_swap_completion(state,registry,completion)
    from .discovery_destinations import validate_completion as validate_destination_completion
    validate_destination_completion(completion,registry)
    from .opponent_deck_gift_copy import validate_completion as validate_copy_completion
    validate_copy_completion(completion,registry)
    from .spell_weapons import validate_completion as validate_weapon_completion
    validate_weapon_completion(state,registry,completion)
    from .hero_power_discovery import validate_completion as validate_skill_completion
    validate_skill_completion(state, registry, completion)
    from .spell_casts import CastSpell
    if type(completion.recipe) is CastSpell:
        recipe = completion.recipe; fact = completion.recipient
        if (registry.card(recipe.card_id).secret is None or fact is None or
                fact.card_id != recipe.card_id or fact.zone != Zone.GRAVEYARD or
                (fact.owner,fact.controller) != (recipe.player_id,recipe.player_id)):
            raise ValueError('Discovered Secret lost its actual generated CAST allocation')
        casts = [row for row in state.cast_history if row.source_id == fact.entity_id and
            (row.card_id,row.player_id,row.caster_id,row.from_zone,row.origin) ==
            (recipe.card_id,recipe.player_id,recipe.source_id,None,'effect')]
        if len(casts) != 1:
            raise ValueError('Discovered Secret lost its one original generated CAST')
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
    from .discovery_guesses import completed as complete_guess
    complete_guess(r, completion)
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
    if rows[identity - 1].is_control:
        raise ValueError('A refresh control has no discovered recipient')
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
                    from .spell_casts import CastSpell, CastStoredSpell, cast_record
                    from .hand_exchange_discovery import SelectHandExchange,witnesses as hand_exchange_witnesses
                    created = type(completion.recipe) not in (MoveCard, DiscardCard, CastStoredSpell, CastSpell,SelectHandExchange)
                    witnesses = [e for e in window if e.kind == ('card_created' if created else 'card_discarded')]
                    if type(completion.recipe) is MoveCard:
                        witnesses = [e for e in window if e.kind in ('card_moved_to_hand', 'card_moved_to_deck', 'card_drawn', 'card_burned')]
                    witnesses = [e for e in witnesses if e.action == event.action and
                                 e.source_id == completion.recipe.source_id]
                    if type(completion.recipe)is SelectHandExchange:
                        witnesses=hand_exchange_witnesses(completion.recipe,[e for e in window if e.action==event.action])
                        if fact is None and witnesses or fact is not None and len(witnesses)!=1:
                            raise ValueError('Hand discovery lost or invented its actual atomic exchange')
                    from .hero_power_discovery import InstallDiscoveredHeroPower
                    if type(completion.recipe) is InstallDiscoveredHeroPower:
                        witnesses = [e for e in window if e.kind == 'hero_power_replaced' and
                            e.action == event.action and e.player_id == completion.recipe.player_id]
                    cast_recipe = type(completion.recipe) in (CastStoredSpell, CastSpell)
                    if cast_recipe:
                        recipe = completion.recipe
                        physical = type(recipe) is CastStoredSpell
                        cast_source = recipe.card.entity_id if physical else fact.entity_id
                        cast_face = recipe.card.card_id if physical else recipe.card_id
                        from_zone = recipe.card.zone if physical else None
                        witnesses = [e for e in window if e.kind == 'spell_cast_started' and
                            e.action == event.action and e.source_id == cast_source and
                            (cast_record(game._state, dict(e.data)['cast_id']).card_id,
                             cast_record(game._state, dict(e.data)['cast_id']).caster_id,
                             cast_record(game._state, dict(e.data)['cast_id']).from_zone,
                             cast_record(game._state, dict(e.data)['cast_id']).player_id) ==
                            (cast_face, recipe.source_id, from_zone, recipe.player_id)]
                        if fact is not None and len(witnesses) != 1:
                            raise ValueError('Discovered spell lost its original physical CAST acceptance')
                        if fact is None and witnesses:
                            raise ValueError('Discovered spell discarded its original physical recipient')
                    if created and fact is not None and len(witnesses) != 1:
                        raise ValueError('Discovery creation lost its one original synchronous allocation')
                    if fact is not None and not any((e.source_id if cast_recipe else e.target_id) == fact.entity_id for e in witnesses):
                        raise ValueError('Discovery recipient has no actual original physical operation')
                    if fact is None and created and witnesses:
                        raise ValueError('Discovery discarded its actual created recipient')
                    if fact is None and completion.recipe is not None and created:
                        recipient = deck_recipient(completion.recipe)
                        if recipient is not None:
                            from .deck_capacity import FAILED, validate_failure
                            failures = [e for e in window if e.kind == FAILED]
                            from .sacrifice import MinionReference
                            from .zones import CardReference
                            recipe = completion.recipe
                            skipped = (type(recipe) is CopyCard and type(recipe.card) in (CardReference,MinionReference) and
                                any(e.kind == 'zone_target_skipped' and e.action == event.action and
                                    e.target_id == recipe.card.entity_id and dict(e.data).get('reason') in
                                    ('captured_card_departed','captured_minion_departed') for e in window))
                            if skipped:
                                if failures:raise ValueError('Departed discovery cannot also claim a full-deck failure')
                            elif len(failures) != 1:
                                raise ValueError('Empty discovered deck delivery lost its actual full-deck failure')
                            else:
                                failed = failures[0]
                                validate_failure(game._state, game.registry, failed)
                                if ((failed.action,failed.source_id,failed.player_id,failed.target_id,dict(failed.data)['card_id']) !=
                                        (event.action,completion.recipe.source_id,recipient,None,recipe_face(completion.recipe))):
                                    raise ValueError('Empty discovery borrowed another deck failure')
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


def deck_recipient(recipe):
    """Recipient of an existing generated/copy deck recipe, if it has one."""
    from .zones import AddToDeck, CopyCard
    from .discovery_destinations import DeliverDiscoveredSpell
    from .opponent_deck_gift_copy import CopyOpponentDeckOffer
    if type(recipe) is AddToDeck or type(recipe) is CopyCard and recipe.destination == Zone.DECK:
        return recipe.player_id
    if type(recipe) is DeliverDiscoveredSpell and not recipe.keep:
        return 3-recipe.player_id
    if type(recipe) is CopyOpponentDeckOffer:
        from .stored_gift_discovery import gift_by_id
        gift = recipe.offered[recipe.index].gift_id
        if gift is not None and gift_by_id(gift).destination == 'deck_top':
            return recipe.player_id
    return None
