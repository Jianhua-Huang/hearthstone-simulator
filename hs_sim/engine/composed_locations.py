"""Finite native location recipes, ordinary choices, and resumable use bodies."""
from dataclasses import asdict, dataclass, fields, replace
import base64
import binascii
import json
from random import Random

from .allocation_facts import allocation_from_dict, validate_allocation
from .effects import AddToHand, ChoiceOption, Effect, RequestChoice, _integer, _player
from .model import BoardPresenceReference, CardType, ChoicePurpose, Event, TargetSpec, Zone, _name
from .summon_quantities import SummonCause

PREFIX = 'custom-location:'
VERSION = 'composed-location-v1'
ROOT = 'location_craft_started'
OFFER = 'location_craft_offered'
PICK = 'location_craft_selected'
CREATED = 'location_craft_created'
USE = 'composed_location_started'
STEP = 'composed_location_component'
END = 'composed_location_finished'


@dataclass(frozen=True)
class LocationComponent:
    card_id: str
    behavior_id: str
    timing: str = 'use'
    targeting: TargetSpec | None = None
    requires_board_space: bool = False
    after: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocationRecipeProfile:
    source_card_id: str
    template_card_id: str
    components: tuple[LocationComponent, ...]
    use_behavior_id: str

    @property
    def component_ids(self):
        return tuple(c.card_id for c in self.components)


def validate_profile(registry, profile):
    if (type(profile) is not LocationRecipeProfile or type(profile.components) is not tuple or
            len(profile.components) not in (6, 7) or any(type(c) is not LocationComponent for c in profile.components) or
            len(set(profile.component_ids)) != len(profile.components)):
        raise ValueError('Location recipe requires its complete finite native component domain')
    source = registry._cards[profile.source_card_id]
    template = registry._cards[profile.template_card_id]
    if source.kind != CardType.MINION or source.battlecry is None:
        raise ValueError('Location craft requires its declared physical Battlecry source')
    if (template.kind != CardType.LOCATION or template.manual_playable or template.choice_only or
            template.metadata is None or template.metadata.collectible is not False or template.durability <= 0):
        raise ValueError('Location craft requires an uninitialized original physical template')
    registry.behavior(profile.use_behavior_id)
    for component in profile.components:
        _name(component.card_id, 'location component'); registry.behavior(component.behavior_id)
        card = registry._cards[component.card_id]
        if (card.kind != CardType.SPELL or not card.choice_only or card.on_play is not None or
                component.timing not in ('use', 'deathrattle') or type(component.requires_board_space) is not bool or
                type(component.after) is not tuple or len(set(component.after)) != len(component.after) or
                any(c not in profile.component_ids or c == component.card_id for c in component.after)):
            raise ValueError('Invalid native location component or execution dependency')
        if component.targeting is not None:
            if type(component.targeting) is not TargetSpec or component.timing != 'use':
                raise ValueError('Only an active location component declares a target')
            component.targeting.__post_init__()
        if component.timing == 'deathrattle' and (component.after or component.requires_board_space):
            raise ValueError('Location Deathrattle cannot borrow active-use requirements')
    if sum(c.timing == 'deathrattle' for c in profile.components) > 1:
        raise ValueError('This native location family has one Deathrattle component')


@dataclass(frozen=True)
class LocationRecipe:
    template_card_id: str
    first_card_id: str
    second_card_id: str

    def __post_init__(self):
        for value in (self.template_card_id, *self.parts):
            _name(value, 'location recipe identity')
            if value.startswith((PREFIX, 'potion:', 'crafted:', 'assemble:')):
                raise ValueError('Recursive location ingredients are unsupported')
        if len(set((self.template_card_id, *self.parts))) != 3:
            raise ValueError('A location recipe needs two distinct original components')

    @property
    def parts(self):
        return (self.first_card_id, self.second_card_id)

    @property
    def card_id(self):
        self.__post_init__()
        raw = json.dumps([VERSION, self.template_card_id, *self.parts], separators=(',', ':')).encode('utf-8')
        return PREFIX + base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def recipe_from_id(card_id):
    if type(card_id) is not str or not card_id.startswith(PREFIX) or len(card_id) > 2048:
        raise ValueError('Expected a bounded canonical location recipe')
    token = card_id[len(PREFIX):]
    try:
        values = json.loads(base64.b64decode(token + '=' * ((-len(token)) % 4), altchars=b'-_', validate=True).decode('utf-8'))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError('Invalid location recipe encoding') from exc
    if type(values) is not list or len(values) != 4 or values[0] != VERSION:
        raise ValueError('Unknown location recipe version or fields')
    recipe = LocationRecipe(*values[1:])
    if recipe.card_id != card_id:
        raise ValueError('Noncanonical location recipe')
    return recipe


def checked_recipe(registry, card_id):
    recipe = recipe_from_id(card_id)
    profile = registry._composed_location_profiles[recipe.template_card_id]
    if any(c not in profile.component_ids for c in recipe.parts):
        raise ValueError('Location recipe borrowed an ineligible or unimplemented component')
    return recipe, profile


def use_components(recipe, profile):
    chosen = [next(c for c in profile.components if c.card_id == cid) for cid in recipe.parts]
    active = [c for c in chosen if c.timing == 'use']
    if len(active) == 2:
        if active[0].card_id in active[1].after and active[1].card_id in active[0].after:
            raise ValueError('Cyclic native location execution dependency')
        if active[1].card_id in active[0].after:
            active.reverse()
    return tuple(active)


def resolve_face(registry, card_id):
    from .registry import UnsupportedDefinitionError
    try:
        recipe, profile = checked_recipe(registry, card_id)
        chosen = [c for c in profile.components if c.card_id in recipe.parts]
        targets = [c.targeting for c in chosen if c.targeting is not None]
        deaths = [c.behavior_id for c in chosen if c.timing == 'deathrattle']
        if len(targets) > 1 or len(deaths) > 1:
            raise ValueError('Unreviewed native location target or Deathrattle domains')
        use_components(recipe, profile)
        face = replace(registry._cards[recipe.template_card_id], id=card_id, manual_playable=True,
            on_use=profile.use_behavior_id, targeting=targets[0] if targets else None,
            deathrattle=deaths[0] if deaths else None,
            requires_board_space=any(c.requires_board_space for c in chosen))
        registry._validate_card(face)
        return face
    except (ValueError, TypeError, KeyError) as exc:
        raise UnsupportedDefinitionError('Unsupported native location recipe: ' + str(exc)) from exc


def public_recipe(card_id):
    if not card_id.startswith(PREFIX):
        return None
    recipe = recipe_from_id(card_id)
    return dict(template_card_id=recipe.template_card_id, parts=list(recipe.parts))


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def effective(game, kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events) if e.kind == kind)


@dataclass(frozen=True)
class CraftLocation(Effect):
    player_id: int
    source_id: int
    source_card_id: str

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'craft source', 1)
        _name(self.source_card_id, 'native craft declaration')


@dataclass(frozen=True)
class OfferLocation(Effect):
    root_id: int
    template_card_id: str | None = None
    first_card_id: str | None = None

    def __post_init__(self):
        _integer(self.root_id, 'craft root', 1)
        for value in (self.template_card_id, self.first_card_id):
            if value is not None: _name(value, 'craft phase material')
        if self.first_card_id is not None and self.template_card_id is None:
            raise ValueError('Second component requires its original cost choice')


@dataclass(frozen=True)
class SelectLocationOption(Effect):
    offer_id: int
    card_id: str

    def __post_init__(self):
        _integer(self.offer_id, 'craft offer', 1); _name(self.card_id, 'craft selection')


@dataclass(frozen=True)
class DeliverLocation(Effect):
    root_id: int
    recipe_id: str

    def __post_init__(self):
        _integer(self.root_id, 'craft root', 1); recipe_from_id(self.recipe_id)


def event_by_id(game, ident, kind):
    if type(ident) is not int or not 0 < ident <= len(game._events):
        raise ValueError('Missing original location event')
    event = game._events[ident - 1]
    if event.kind != kind or event not in effective(game, kind):
        raise ValueError('Location work borrowed a rolled-back or foreign event')
    return event


def root_request(game, root_id):
    event = event_by_id(game, root_id, ROOT)
    data = json.loads(dict(event.data)['request'])
    request = CraftLocation(**data)
    if (event.source_id, event.player_id) != (request.source_id, request.player_id):
        raise ValueError('Location craft changed its original actor')
    return request


def phase_candidates(registry, request, template, first):
    profiles = registry._composed_location_profiles
    if template is None:
        return tuple(p.template_card_id for p in sorted(profiles.values(), key=lambda p: registry.card(p.template_card_id).cost)
            if p.source_card_id == request.source_card_id)
    profile = profiles[template]
    if profile.source_card_id != request.source_card_id or first is not None and first not in profile.component_ids:
        raise ValueError('Location craft lost its original tier or first component')
    return tuple(cid for cid in profile.component_ids if cid != first)


def choice_options(registry, offer_id, offered):
    return tuple(ChoiceOption(cid, registry.card(cid).name,
        (SelectLocationOption(offer_id, cid),), card_id=cid) for cid in offered)


def start_craft(r, effect):
    candidates = phase_candidates(r.registry, effect, None, None)
    if len(candidates) != 3:
        raise ValueError('Native location craft requires all three reviewed cost choices')
    from .allocation_facts import SourceAllocationFact
    source = SourceAllocationFact.capture(r.state, r.state.entities[effect.source_id])
    event = r.emit(ROOT, source_id=effect.source_id, player_id=effect.player_id,
        request=pack(asdict(effect)), source=pack(asdict(source)), _capture=False)
    return (OfferLocation(event.sequence),)


def offer_location(r, effect):
    request = root_request(r.game, effect.root_id)
    candidates = phase_candidates(r.registry, request, effect.template_card_id, effect.first_card_id)
    before = r.game._rng.getstate()
    offered = candidates if effect.template_card_id is None else tuple(r.game._rng.sample(candidates, 3))
    event = r.emit(OFFER, source_id=request.source_id, player_id=request.player_id,
        root_id=effect.root_id, template=effect.template_card_id, first=effect.first_card_id,
        candidates=candidates, offered=offered, rng_before=before, rng_after=r.game._rng.getstate(), _capture=False)
    return (RequestChoice(request.player_id, choice_options(r.registry, event.sequence, offered), request.source_id,
        prompt='选择地标费用' if effect.template_card_id is None else '选择地标效果'),)


def selection_event(game, offer, request, card_id):
    from .card_discoveries import SELECTION_EVENTS
    from .hero_health_history import effective_events
    rows = [e for e in effective_events(game._events) if e.sequence > offer.sequence and e.kind in SELECTION_EVENTS and
        (e.source_id, e.player_id, dict(e.data).get('option_ids')) == (request.source_id, request.player_id, (card_id,))]
    if not rows:
        raise ValueError('Location craft lost its actual manual or automatic selection')
    return rows[-1]


def select_option(r, effect):
    offer = event_by_id(r.game, effect.offer_id, OFFER); data = dict(offer.data)
    request = root_request(r.game, data['root_id'])
    if effect.card_id not in data['offered'] or any(dict(e.data)['offer_id'] == effect.offer_id for e in effective(r.game, PICK)):
        raise ValueError('Location craft duplicated or substituted a chosen option')
    selected = selection_event(r.game, offer, request, effect.card_id)
    r.emit(PICK, source_id=request.source_id, player_id=request.player_id, root_id=data['root_id'],
        offer_id=effect.offer_id, card_id=effect.card_id, selection_sequence=selected.sequence, _capture=False)
    if data['template'] is None:
        return (OfferLocation(data['root_id'], effect.card_id),)
    if data['first'] is None:
        return (OfferLocation(data['root_id'], data['template'], effect.card_id),)
    return (DeliverLocation(data['root_id'], LocationRecipe(data['template'], data['first'], effect.card_id).card_id),)


def deliver(r, effect):
    from .allocation_facts import SourceAllocationFact
    from .opening import create_hand_card, announce_hand_card
    request = root_request(r.game, effect.root_id)
    if any(dict(e.data)['root_id'] == effect.root_id for e in effective(r.game, CREATED)):
        raise ValueError('A location craft can create only one original reward')
    checked_recipe(r.registry, effect.recipe_id)
    delivery = AddToHand(request.player_id, effect.recipe_id, source_id=request.source_id)
    entity = create_hand_card(r, delivery, defer_publication=True)
    r.emit(CREATED, source_id=request.source_id, target_id=entity.id, player_id=request.player_id,
        root_id=effect.root_id, recipe_id=effect.recipe_id,
        material=pack(asdict(SourceAllocationFact.capture(r.state, entity))), _capture=False)
    announce_hand_card(r, delivery, entity)
    return ()


def cause_from_json(value):
    data = json.loads(value)
    return SummonCause(allocation_from_dict(data.pop('source')), **data)


def target_from_json(value):
    data = json.loads(value)
    return None if data is None else BoardPresenceReference(**data)


@dataclass(frozen=True)
class BeginLocationUse(Effect):
    cause: SummonCause
    target: BoardPresenceReference | None = None

    def __post_init__(self):
        if type(self.cause) is not SummonCause:
            raise ValueError('Composed location use requires its original card cause')
        self.cause.__post_init__()
        if self.cause.source.kind != CardType.LOCATION or self.cause.source.zone != Zone.BOARD or self.cause.origin != 'card_effect':
            raise ValueError('Composed location body requires an actual accepted location use')
        if self.target is not None:
            if type(self.target) is not BoardPresenceReference: raise ValueError('Typed original copy target required')
            self.target.__post_init__()


@dataclass(frozen=True)
class ContinueLocationUse(Effect):
    use_id: int
    index: int = 0

    def __post_init__(self):
        _integer(self.use_id, 'location use', 1); _integer(self.index, 'component cursor', 0)
        if self.index > 2: raise ValueError('A composed location has at most two active components')


def use_material(event):
    data = dict(event.data)
    cause = cause_from_json(data['cause']); target = target_from_json(data['target'])
    BeginLocationUse(cause, target).__post_init__()
    return cause, target


def component_context(context, registry):
    if type(context.event) is not Event or context.event.kind != STEP:
        raise ValueError('Location component requires its original private use cursor')
    cause, target = use_material(context.event)
    if (context.source_id, context.player_id) != (cause.source.entity_id, cause.player_id):
        raise ValueError('Location component borrowed another original actor')
    validate_allocation(context.state, registry, cause.source)
    recipe, profile = checked_recipe(registry, cause.source.card_id)
    ordered = use_components(recipe, profile); data = dict(context.event.data)
    index = data['index']
    if type(index) is not int or not 0 <= index < len(ordered) or data['component'] != ordered[index].card_id:
        raise ValueError('Location component changed its accepted recipe cursor')
    return cause, target


def begin_use(r, effect):
    cause = effect.cause; checked_recipe(r.registry, cause.source.card_id)
    target_id = None if effect.target is None else effect.target.entity_id
    activations = [e for e in r.game._events if e.kind == 'location_activated' and
        (e.source_id, e.player_id, e.target_id, dict(e.data).get('composed_turn'), e.action) ==
        (cause.source.entity_id, cause.player_id, target_id, cause.turn, cause.action) and
        dict(e.data).get('composed_recipe') == cause.source.card_id and dict(e.data).get('composed_body') is True]
    if len(activations) != 1:
        raise ValueError('Composed location lost its actual original activation')
    event = r.emit(USE, source_id=cause.source.entity_id, player_id=cause.player_id, target_id=target_id,
        cause=pack(asdict(cause)), target=pack(None if effect.target is None else asdict(effect.target)),
        activation_id=activations[0].sequence, _capture=False)
    return (ContinueLocationUse(event.sequence),)


def continue_use(r, effect):
    start = event_by_id(r.game, effect.use_id, USE); cause, target = use_material(start)
    recipe, profile = checked_recipe(r.registry, cause.source.card_id)
    ordered = use_components(recipe, profile)
    steps = [e for e in effective(r.game, STEP) if dict(e.data)['use_id'] == effect.use_id]
    if effect.index != len(steps) or any(dict(e.data)['use_id'] == effect.use_id for e in effective(r.game, END)):
        raise ValueError('Composed location duplicated or skipped an active component')
    if effect.index == len(ordered):
        r.emit(END, source_id=start.source_id, player_id=start.player_id, use_id=effect.use_id, _capture=False)
        return ()
    part = ordered[effect.index]
    event = r.emit(STEP, source_id=start.source_id, player_id=start.player_id, target_id=start.target_id,
        use_id=effect.use_id, index=effect.index, component=part.card_id,
        cause=dict(start.data)['cause'], target=dict(start.data)['target'], _capture=False)
    from .board_presence import resolve_board_presence
    current = None if target is None else resolve_board_presence(r.state, target)
    body = () if part.targeting is not None and current is None else (
        r.call(part.behavior_id, start.source_id, start.player_id,
            None if current is None else current.id, event=event),)
    return (*body, ContinueLocationUse(effect.use_id, effect.index + 1))


def register(mechanics):
    for kind, handler in ((CraftLocation, start_craft), (OfferLocation, offer_location),
            (SelectLocationOption, select_option), (DeliverLocation, deliver),
            (BeginLocationUse, begin_use), (ContinueLocationUse, continue_use)):
        mechanics.register(kind, handler)


def validate_game(game):
    from .hero_health_history import effective_events
    from .card_discoveries import SELECTION_EVENTS
    events = effective_events(game._events)
    frame = game._frame
    queue = () if frame is None else (*frame.prefix, *frame.continuation)
    work_types = (CraftLocation, OfferLocation, SelectLocationOption, DeliverLocation, BeginLocationUse, ContinueLocationUse)
    relevant = [e for e in events if e.kind in (ROOT, OFFER, PICK, CREATED, USE, STEP, END) or
        e.kind == 'location_activated' and 'composed_recipe' in dict(e.data)]
    if not relevant and not any(type(e) in work_types for e in queue):
        return
    registry = game.registry
    roots, offers, uses, activations = {}, {}, {}, {}
    for event in relevant:
        data = dict(event.data)
        if event.kind == ROOT:
            request = root_request(game, event.sequence)
            source = allocation_from_dict(json.loads(data['source']))
            validate_allocation(game._state, registry, source)
            if source.entity_id != request.source_id or len(phase_candidates(registry, request, None, None)) != 3:
                raise ValueError('Location craft lost its complete original source and tiers')
            roots[event.sequence] = dict(request=request, stage=0, template=None, first=None, active=None, created=False)
        elif event.kind == OFFER:
            root = roots.get(data['root_id'])
            if root is None or root['active'] is not None or root['created'] or root['stage'] >= 3:
                raise ValueError('Location craft duplicated or borrowed an offer window')
            request = root['request']
            if (data['template'], data['first']) != (root['template'], root['first']):
                raise ValueError('Location craft changed its accepted prior choices')
            candidates = phase_candidates(registry, request, root['template'], root['first'])
            rng = Random(); rng.setstate(data['rng_before'])
            drawn = candidates if root['template'] is None else tuple(rng.sample(candidates, 3))
            if (tuple(data['candidates']), tuple(data['offered']), data['rng_after']) != (candidates, drawn, rng.getstate()) or (
                    event.source_id, event.player_id) != (request.source_id, request.player_id):
                raise ValueError('Location offer cropped its native domain or changed its original random draw')
            root['active'] = event.sequence
            offers[event.sequence] = dict(root=data['root_id'], event=event, picked=False)
        elif event.kind == PICK:
            row = offers.get(data['offer_id']); root = roots.get(data['root_id'])
            if row is None or root is None or row['root'] != data['root_id'] or row['picked'] or root['active'] != data['offer_id']:
                raise ValueError('Location craft duplicated or borrowed a selection')
            offer = row['event']; offered = dict(offer.data)['offered']; request = root['request']
            cursor = data['selection_sequence']
            if type(cursor) is not int or not offer.sequence < cursor < event.sequence:
                raise ValueError('Location selection lost its actual original input event')
            selected = game._events[cursor - 1]; d = dict(selected.data)
            if (selected not in events or selected.kind not in SELECTION_EVENTS or data['card_id'] not in offered or
                    (selected.source_id, selected.player_id, d.get('option_ids'), d.get('purpose')) !=
                    (request.source_id, request.player_id, (data['card_id'],), ChoicePurpose.EFFECT.value) or
                    (event.source_id, event.player_id) != (request.source_id, request.player_id)):
                raise ValueError('Location craft changed its actual manual or automatic choice')
            published = [e for e in events if e.kind == 'choice_requested' and dict(e.data).get('choice_id') == d['choice_id']]
            if selected.kind == 'choice_selected' and len(published) != 1:
                raise ValueError('Manual location craft lost its actual original offer')
            if published and (published[0].source_id, published[0].player_id, dict(published[0].data)['option_ids']) != (
                    request.source_id, request.player_id, offered):
                raise ValueError('Location craft changed its actual published options')
            row['picked'] = True; root['active'] = None
            if root['stage'] == 0: root['template'] = data['card_id']
            elif root['stage'] == 1: root['first'] = data['card_id']
            else: root['recipe'] = LocationRecipe(root['template'], root['first'], data['card_id']).card_id
            root['stage'] += 1
        elif event.kind == CREATED:
            root = roots.get(data['root_id'])
            if root is None or root['stage'] != 3 or root['active'] is not None or root['created'] or data['recipe_id'] != root['recipe']:
                raise ValueError('Location reward changed its complete original manufacture')
            material = allocation_from_dict(json.loads(data['material']))
            validate_allocation(game._state, registry, material); checked_recipe(registry, data['recipe_id'])
            request = root['request']
            if (material.entity_id, material.card_id, material.kind, material.owner, material.controller) != (
                    event.target_id, root['recipe'], CardType.LOCATION, request.player_id, request.player_id) or (
                    event.source_id, event.player_id) != (request.source_id, request.player_id):
                raise ValueError('Location creation borrowed another original physical delivery')
            root['created'] = True
        elif event.kind == 'location_activated':
            recipe_id = data['composed_recipe']; face = registry.card(recipe_id)
            if (not recipe_id.startswith(PREFIX) or face.kind != CardType.LOCATION or
                    type(data.get('composed_body')) is not bool or type(data.get('composed_turn')) is not int or
                    not 1 <= data['composed_turn'] <= game._state.turn):
                raise ValueError('Location activation lost its original composed face')
            activations[event.sequence] = event
        elif event.kind == USE:
            cause, target = use_material(event); recipe, profile = checked_recipe(registry, cause.source.card_id)
            validate_allocation(game._state, registry, cause.source)
            activation = activations.get(data['activation_id'])
            expected_target = None if target is None else target.entity_id
            if (activation is None or dict(activation.data)['composed_recipe'] != cause.source.card_id or
                    dict(activation.data)['composed_body'] is not True or
                    (activation.source_id, activation.player_id, activation.target_id, dict(activation.data)['composed_turn'], activation.action) !=
                    (cause.source.entity_id, cause.player_id, expected_target, cause.turn, cause.action) or
                    (event.source_id, event.player_id, event.target_id) != (cause.source.entity_id, cause.player_id, expected_target) or
                    any(row['activation'] == activation.sequence for row in uses.values())):
                raise ValueError('Composed use borrowed another original activation or recipe')
            if (registry.card(cause.source.card_id).targeting is not None) != (target is not None):
                raise ValueError('Composed use lost its original directed target')
            if target is not None and (target.entity_id not in game._state.entities or target.presence_id >= game._state.next_order):
                raise ValueError('Composed use borrowed an unknown target residence')
            uses[event.sequence] = dict(start=event, activation=activation.sequence, parts=use_components(recipe, profile), steps=0, ended=False)
        elif event.kind == STEP:
            use = uses.get(data['use_id'])
            if use is None or use['ended'] or use['steps'] >= len(use['parts']):
                raise ValueError('Location component borrowed a missing or finished use')
            start = use['start']; original = dict(start.data); index = use['steps']
            if data != dict(use_id=start.sequence, index=index, component=use['parts'][index].card_id,
                    cause=original['cause'], target=original['target']) or (
                    event.source_id, event.player_id, event.target_id) != (start.source_id, start.player_id, start.target_id):
                raise ValueError('Location use changed or skipped its original ordered component')
            use['steps'] += 1
        elif event.kind == END:
            use = uses.get(data['use_id'])
            if use is None or use['ended'] or use['steps'] != len(use['parts']) or set(data) != {'use_id'} or (
                    event.source_id, event.player_id) != (use['start'].source_id, use['start'].player_id):
                raise ValueError('Location finish lost its complete original use body')
            use['ended'] = True
    for item in queue:
        if type(item) is CraftLocation:
            if item.source_id not in game._state.entities or len(phase_candidates(registry, item, None, None)) != 3:
                raise ValueError('Pending native craft lost its declared source')
        elif type(item) is OfferLocation:
            root = roots.get(item.root_id)
            if root is None or root['created'] or root['active'] is not None or root['stage'] >= 3 or (
                    item.template_card_id, item.first_card_id) != (root['template'], root['first']):
                raise ValueError('Pending native offer lost its original manufacture phase')
        elif type(item) is SelectLocationOption:
            row = offers.get(item.offer_id)
            if row is None or row['picked'] or item.card_id not in dict(row['event'].data)['offered']:
                raise ValueError('Pending native selection lost its original unconsumed offer')
        elif type(item) is DeliverLocation:
            root = roots.get(item.root_id)
            if root is None or root['created'] or root['stage'] != 3 or item.recipe_id != root['recipe']:
                raise ValueError('Pending location delivery lost its original final recipe')
        elif type(item) is ContinueLocationUse:
            use = uses.get(item.use_id)
            if use is None or use['ended'] or item.index != use['steps']:
                raise ValueError('Pending location cursor lost its original unfinished use')
        elif type(item) is BeginLocationUse:
            validate_allocation(game._state, registry, item.cause.source)
            checked_recipe(registry, item.cause.source.card_id)
    if game._state.status != 'playing':
        return
    for ident, root in roots.items():
        if root['created']: continue
        if root['active'] is None:
            expected = [e for e in queue if type(e) is DeliverLocation and e.root_id == ident] if root['stage'] == 3 else [
                e for e in queue if type(e) is OfferLocation and e.root_id == ident]
        else:
            offer = offers[root['active']]['event']; data = dict(offer.data)
            options = choice_options(registry, offer.sequence, data['offered']); request = root['request']
            expected = [e for e in queue if type(e) is SelectLocationOption and e.offer_id == offer.sequence]
            expected += [e for e in queue if type(e) is RequestChoice and e.options == options and
                (e.source_id, e.player_id, e.min_count, e.max_count, e.on_select) == (request.source_id, request.player_id, 1, 1, None)]
            if frame is not None and frame.options == options and frame.on_select is None:
                choice = game._state.pending_choice
                if (choice.source_id, choice.player_id, choice.min_count, choice.max_count, choice.purpose) != (
                        request.source_id, request.player_id, 1, 1, ChoicePurpose.EFFECT):
                    raise ValueError('Waiting location offer changed its original actor or cardinality')
                expected.append(frame)
        if len(expected) != 1:
            raise ValueError('Unfinished location craft lost its unique original continuation')
    for ident, use in uses.items():
        if use['ended']: continue
        if len([e for e in queue if type(e) is ContinueLocationUse and e.use_id == ident]) != 1:
            raise ValueError('Unfinished composed use lost its unique original component cursor')
    for ident, activation in activations.items():
        if not dict(activation.data)['composed_body'] or any(row['activation'] == ident for row in uses.values()):
            continue
        pending = [e for e in queue if type(e) is BeginLocationUse and
            (e.cause.source.entity_id, e.cause.source.card_id, e.cause.action, e.cause.turn) ==
            (activation.source_id, dict(activation.data)['composed_recipe'], activation.action, dict(activation.data)['composed_turn'])]
        pending += [e for e in queue if hasattr(e, 'behavior_id') and hasattr(e, 'context') and
            (e.context.source_id, e.context.player_id, e.context.state.action_number, e.context.state.turn) ==
            (activation.source_id, activation.player_id, activation.action, dict(activation.data)['composed_turn']) and
            e.behavior_id == checked_recipe(registry, dict(activation.data)['composed_recipe'])[1].use_behavior_id]
        if len(pending) != 1:
            raise ValueError('Accepted composed activation lost its original captured body')
