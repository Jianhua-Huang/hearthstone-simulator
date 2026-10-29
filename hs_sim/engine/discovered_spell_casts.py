"""One plain spell discovery followed by an affordable automatic copy.

The original selection and completed physical delivery remain authoritative.
The producer reuses normal quotes, stored copy material and automatic CASTs.
"""
from dataclasses import dataclass, replace
import json

from .effects import Effect, _integer
from .model import CardType, CostQuoteFact, GeneratedCostQuoteFact, Zone
from .pools import PoolQuery

QUERY = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current')
QUEUED = 'discovered_spell_copy_queued'
CHECKED = 'discovered_spell_copy_checked'


def validate_spec(spec):
    from .pools import DiscoverFromPool
    if type(spec.source_id) is not int or spec.source_id < 1:
        raise ValueError('Affordable discovery requires its original spell source')
    plain = DiscoverFromPool(spec.player_id, 'constructed.cards', QUERY,
        source_id=spec.source_id, prompt=spec.prompt)
    if replace(spec, cast_affordable_copy=False) != plain:
        raise ValueError('Affordable copy requires one ordinary current-class spell discovery')


@dataclass(frozen=True)
class CastAffordableDiscoveredSpell(Effect):
    selection: object
    cast_id: int
    accepted_event: int

    def __post_init__(self):
        from .discovery import ResolvePoolDiscovery
        if type(self.selection) is not ResolvePoolDiscovery:
            raise ValueError('Affordable copy requires its complete original selection')
        self.selection.__post_init__()
        spec = self.selection.batch.spec
        validate_spec(spec)
        if not spec.cast_affordable_copy or self.selection.choice_result is None:
            raise ValueError('Affordable copy requires a committed original choice')
        _integer(self.cast_id, 'original discovery CAST', 1)
        _integer(self.accepted_event, 'original copy acceptance', 1)

    @property
    def source_id(self): return self.selection.batch.spec.source_id

    @property
    def player_id(self): return self.selection.batch.spec.player_id

    def validate_in_state(self, state, registry, events=None):
        from .card_discoveries import require_original_result
        from .spell_casts import cast_record
        self.__post_init__()
        row = require_original_result(state, self.selection.choice_result)
        parent = cast_record(state, self.cast_id)
        if ((parent.source_id, parent.player_id) != (self.source_id, self.player_id) or
                parent.failure is not None or not parent.payload_started or
                not parent.recorded_event < row.selection_event < self.accepted_event or
                registry.card(self.selection.selection.card_id).kind != CardType.SPELL):
            raise ValueError('Affordable copy borrowed another original CAST or selection window')
        if events is not None:
            from .hero_health_history import effective_events
            events = effective_events(events)
            accepted = [e for e in events if e.sequence == self.accepted_event and e.kind == QUEUED]
            if (len(accepted) != 1 or (accepted[0].source_id, accepted[0].player_id) !=
                    (self.source_id, self.player_id) or any(e.kind == 'spell_cast_finished' and
                    dict(e.data).get('cast_id') == self.cast_id and e.sequence <= self.accepted_event for e in events)):
                raise ValueError('Affordable copy lost its actual original active CAST acceptance')


def encoded(r, value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(r.game.mechanics, r.registry).encode(value),
        ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def prepare(r, selection):
    from .spell_casts import active_cast
    spec = selection.batch.spec
    parent = active_cast(r.state, spec.source_id, spec.player_id)
    if parent is None:
        raise ValueError('Affordable discovery requires its actual active spell CAST')
    work = CastAffordableDiscoveredSpell(selection, parent.id, len(r.game._events) + 1)
    r.emit(QUEUED, source_id=work.source_id, player_id=work.player_id,
        work=encoded(r, work), _capture=False)
    work.validate_in_state(r.state, r.registry, r.game.events)
    return work


def original(r, work):
    from .card_discoveries import require_original_result
    from .discovery_delivery import DiscoveryCompletion, original_recipient, validate_completion
    from .discovery_offers import offer_for_result
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    work.validate_in_state(r.state, r.registry, r.game.events)
    result = work.selection.choice_result
    row = require_original_result(r.state, result)
    offer = offer_for_result(r.game, result)
    option = next(o for o in offer.options if o.id == result.selected_ids[0])
    if option.effects != (replace(work.selection, choice_result=None),):
        raise ValueError('Affordable copy changed its actual original discovery recipe')
    events = [e for e in effective_events(r.game.events) if e.kind == 'card_discovered' and
        dict(e.data).get('discovery_id') == row.id]
    if len(events) != 1 or events[0].sequence <= work.accepted_event:
        raise ValueError('Affordable copy requires its original completed delivery')
    event = events[0]
    fact = original_recipient(r.state, event)
    completion = FrameCodec(r.game.mechanics, r.registry).decode(json.loads(dict(event.data)['receipt']))
    if type(completion) is not DiscoveryCompletion or completion.result != result or completion.recipient != fact:
        raise ValueError('Affordable copy changed its original actual recipient')
    validate_completion(r.state, r.registry, completion, closed=True)
    return completion


def execute(r, work):
    from .copy_materials import CapturedCardCopyMaterial, validate_captured_card_copy
    from .costs import capture_cost_input, quote_input, capture_generated_quote_fact
    from .discovered_card_copies import same_recipient
    from .held_opponent_copies import copy_origin
    from .spell_casts import CastSpell, automatic
    from .automatic_targets import AutomaticTargetPreference
    from .zones import copy_current_stored_state
    completion = original(r, work)
    fact = completion.recipient
    recipient = None if fact is None else r.state.entities.get(fact.entity_id)
    material = None
    card_id = work.selection.selection.card_id
    if fact is not None and fact.zone == Zone.HAND and same_recipient(fact, recipient):
        material = CapturedCardCopyMaterial.capture(r.state, recipient)
        validate_captured_card_copy(r.state, r.registry, material)
        quote = quote_input(r.state, r.registry, capture_cost_input(recipient))
    else:
        quote = capture_generated_quote_fact(r.state, r.registry, work.player_id, card_id)
    mana = r.player(work.player_id).mana
    child = None
    tail = ()
    if mana >= quote.amount:
        entity = r.create_entity(work.player_id, card_id, Zone.GRAVEYARD,
            components=material.components if material is not None else ())
        if material is not None:
            copy_current_stored_state(r.state, material.entity(), entity)
        if fact is not None:
            entity.origin_entity_id = fact.entity_id
            entity.copy_origin = copy_origin(fact)
        before = len(r.state.cast_history)
        tail = automatic(r, CastSpell(work.player_id, card_id, work.source_id,
            target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE), entity, None)
        if len(r.state.cast_history) != before + 1:
            raise ValueError('Affordable copy lost its one ordinary automatic CAST')
        child = r.state.cast_history[-1].id
    r.emit(CHECKED, source_id=work.source_id, player_id=work.player_id,
        accepted_event=work.accepted_event, cast_id=child, mana=mana,
        quote=encoded(r, quote), material=None if material is None else encoded(r, material), _capture=False)
    return tail


def validate_boundary(game):
    from types import SimpleNamespace
    from .copy_materials import CapturedCardCopyMaterial
    from .costs import capture_cost_input
    from .discovered_card_copies import same_recipient
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    from .discovery_offers import offer_for_result
    from .spell_casts import cast_record
    from .intrinsic_costs import validate_intrinsic_history_prefix
    events = effective_events(game.events)
    queued = [e for e in events if e.kind == QUEUED]
    if not queued: return
    if any(dict(e.data).get('accepted_event') not in {q.sequence for q in queued}
            for e in events if e.kind == CHECKED):
        raise ValueError('Affordable copy completion has no original acceptance')
    codec = FrameCodec(game.mechanics, game.registry, origin_state=game._state, origin_events=game.events)
    # Acceptance witnesses contain old queue copies. Only these two sequences
    # are executable work, so historical proof material cannot count twice.
    pending = ((*game._frame.prefix, *game._frame.continuation)
        if game._frame is not None else ())
    for event in queued:
        work = codec.decode(json.loads(dict(event.data)['work']))
        if type(work) is not CastAffordableDiscoveredSpell or work.accepted_event != event.sequence:
            raise ValueError('Affordable discovery lost its original queued obligation')
        work.validate_in_state(game._state, game.registry, game.events)
        offer = offer_for_result(game, work.selection.choice_result)
        option = next(o for o in offer.options if o.id == work.selection.choice_result.selected_ids[0])
        if option.effects != (replace(work.selection, choice_result=None),):
            raise ValueError('Affordable discovery borrowed a different original offered body')
        done = [e for e in events if e.kind == CHECKED and dict(e.data).get('accepted_event') == event.sequence]
        expected = 0 if done or game._state.status == 'finished' else 1
        if sum(v == work for v in pending) != expected or len(done) > 1:
            raise ValueError('Affordable discovery clipped or duplicated its original follow-up')
        if not done: continue
        proof = done[0]; data = dict(proof.data)
        if proof.sequence <= event.sequence or (proof.source_id, proof.player_id) != (work.source_id, work.player_id):
            raise ValueError('Affordable copy changed its actual completion window')
        quote = codec.decode(json.loads(data['quote']))
        if type(quote) not in (CostQuoteFact, GeneratedCostQuoteFact):
            raise ValueError('Affordable copy lost its full original price quote')
        validate_intrinsic_history_prefix(quote.intrinsic, game._state, game.registry)
        completion = original(SimpleNamespace(state=game._state, registry=game.registry, game=game), work)
        material = None if data['material'] is None else codec.decode(json.loads(data['material']))
        if type(quote) is CostQuoteFact:
            if (type(material) is not CapturedCardCopyMaterial or material.origin.zone != Zone.HAND or
                    not same_recipient(completion.recipient, material.entity()) or
                    quote.quote_input != capture_cost_input(material.entity())):
                raise ValueError('Affordable copy lost its original current hand material and quote')
        elif material is not None or quote.quote_input.initial_cost is not None or quote.quote_input.minimum_cost != 0:
            raise ValueError('Unavailable discovered recipient cannot invent current copy material')
        if (quote.quote_input.card_id, quote.quote_input.player_id) != (work.selection.selection.card_id, work.player_id):
            raise ValueError('Affordable copy borrowed a different price subject')
        _integer(data['mana'], 'remaining discovery Mana', 0)
        if (data['cast_id'] is not None) != (data['mana'] >= quote.amount):
            raise ValueError('Affordable copy changed its original remaining Mana comparison')
        if data['cast_id'] is not None:
            child = cast_record(game._state, data['cast_id'])
            if ((child.card_id, child.caster_id, child.player_id, child.origin, child.from_zone) !=
                    (work.selection.selection.card_id, work.source_id, work.player_id, 'effect', None) or
                    not event.sequence < child.recorded_event < proof.sequence or child.id <= work.cast_id):
                raise ValueError('Affordable copy lost its actual separate automatic CAST')


def register(mechanics):
    mechanics.register(CastAffordableDiscoveredSpell, execute)
