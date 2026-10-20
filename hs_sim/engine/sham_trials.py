"""Native two-component trial spells; ordinary choices, CASTs and owner clocks."""
from dataclasses import asdict, dataclass, replace
import base64
import binascii
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import AddToHand, ChoiceOption, Effect, RequestChoice, _integer, _player
from .model import CardType, PlayerEffect, PlayerEffectSpec, _name

PREFIX = 'sham-trial:'
VERSION = 'sham-trial-v1'
ROOT = 'sham_trial_craft_started'
OFFER = 'sham_trial_offered'
PICK = 'sham_trial_selected'
CREATED = 'sham_trial_created'
INSTALLED = 'sham_trial_installed'
START = 'sham_trial_started'
STEP = 'sham_trial_component'
END = 'sham_trial_finished'


@dataclass(frozen=True)
class TrialComponent:
    card_id: str
    behavior_id: str
    script_index: int

    def __post_init__(self):
        _name(self.card_id, 'trial component'); _name(self.behavior_id, 'trial component body')
        _integer(self.script_index, 'original trial component index', 1)


@dataclass(frozen=True)
class TrialTier:
    template_card_id: str
    choice_card_id: str
    owner_starts: int

    def __post_init__(self):
        _name(self.template_card_id, 'trial template'); _name(self.choice_card_id, 'trial length choice')
        _integer(self.owner_starts, 'trial owner-start count', 0)


@dataclass(frozen=True)
class ShamTrialProfile:
    source_card_id: str
    components: tuple[TrialComponent, ...]
    tiers: tuple[TrialTier, ...]
    cast_behavior_id: str
    expire_behavior_id: str

    @property
    def component_ids(self): return tuple(c.card_id for c in self.components)


def validate_profile(registry, profile):
    if (type(profile) is not ShamTrialProfile or type(profile.components) is not tuple or
            type(profile.tiers) is not tuple or len(profile.components) != 9 or len(profile.tiers) != 3 or
            any(type(c) is not TrialComponent for c in profile.components) or
            any(type(t) is not TrialTier for t in profile.tiers) or
            tuple(c.script_index for c in profile.components) != tuple(range(1, 10)) or
            len(set(profile.component_ids)) != 9):
        raise ValueError('A sham trial requires all nine original ordered components and three lengths')
    source = registry._cards[profile.source_card_id]
    if source.kind != CardType.MINION or source.battlecry is None:
        raise ValueError('Trial manufacture requires its actual Battlecry source')
    registry.behavior(profile.cast_behavior_id); registry.behavior(profile.expire_behavior_id)
    for component in profile.components:
        component.__post_init__()
        registry.behavior(component.behavior_id)
        card = registry._cards[component.card_id]
        if card.kind != CardType.SPELL or not card.choice_only or card.on_play is not None:
            raise ValueError('Trial components must remain nonphysical original effect choices')
    if len({t.template_card_id for t in profile.tiers}) != 3 or len({t.choice_card_id for t in profile.tiers}) != 3:
        raise ValueError('Trial lengths cannot alias templates or choices')
    for tier, cost, turns in zip(profile.tiers, (0, 4, 7), (4, 1, 0)):
        tier.__post_init__()
        card, choice = registry._cards[tier.template_card_id], registry._cards[tier.choice_card_id]
        if (card.kind != CardType.SPELL or card.manual_playable or card.choice_only or card.cost != cost or
                choice.kind != CardType.SPELL or not choice.choice_only or choice.cost != cost or
                choice.on_play is not None or tier.owner_starts != turns):
            raise ValueError('Trial length changed its original cost or owner-start clock')


@dataclass(frozen=True)
class ShamTrialRecipe:
    template_card_id: str
    first_card_id: str
    second_card_id: str

    def __post_init__(self):
        for value in (self.template_card_id, *self.parts):
            _name(value, 'trial recipe identity')
            if value.startswith(PREFIX): raise ValueError('Recursive trial recipes are unsupported')
        if len(set((self.template_card_id, *self.parts))) != 3:
            raise ValueError('Trial requires two distinct original effects')

    @property
    def parts(self): return (self.first_card_id, self.second_card_id)

    @property
    def card_id(self):
        self.__post_init__()
        body = json.dumps([VERSION, self.template_card_id, *self.parts], separators=(',', ':')).encode('utf8')
        return PREFIX + base64.urlsafe_b64encode(body).decode('ascii').rstrip('=')


def recipe_from_id(card_id):
    if type(card_id) is not str or not card_id.startswith(PREFIX) or len(card_id) > 2048:
        raise ValueError('Expected bounded immutable trial identity')
    token = card_id[len(PREFIX):]
    try:
        row = json.loads(base64.b64decode(token + '=' * ((-len(token)) % 4), altchars=b'-_', validate=True).decode('utf8'))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError('Malformed trial identity') from exc
    if type(row) is not list or len(row) != 4 or row[0] != VERSION:
        raise ValueError('Unknown trial identity version or fields')
    recipe = ShamTrialRecipe(*row[1:])
    if recipe.card_id != card_id: raise ValueError('Noncanonical trial identity')
    return recipe


def checked_recipe(registry, card_id):
    recipe = recipe_from_id(card_id)
    matches = [(p, t) for p in registry._sham_trial_profiles.values() for t in p.tiers
               if t.template_card_id == recipe.template_card_id]
    if len(matches) != 1: raise ValueError('Trial recipe requires its one original profile and length')
    profile, tier = matches[0]
    indices = tuple(profile.component_ids.index(c) for c in recipe.parts)
    if indices != tuple(sorted(indices)): raise ValueError('Trial recipe changed native component order')
    return recipe, profile, tier


def resolve_face(registry, card_id):
    from .registry import UnsupportedDefinitionError
    try:
        recipe, profile, tier = checked_recipe(registry, card_id)
        template = registry._cards[recipe.template_card_id]
        face = replace(template, id=card_id, manual_playable=True,
            on_play=profile.cast_behavior_id if tier.owner_starts == 0 else None,
            ongoing_effect_id=card_id if tier.owner_starts else None)
        registry._validate_card(face)
        return face
    except (ValueError, KeyError, TypeError) as exc:
        raise UnsupportedDefinitionError('Unsupported sham trial: ' + str(exc)) from exc


def resolve_program(registry, spec_id):
    recipe, profile, tier = checked_recipe(registry, spec_id)
    if not tier.owner_starts: raise ValueError('An immediate trial cannot own a countdown')
    spec = PlayerEffectSpec(spec_id, recipe.card_id, kind='objective', duration=tier.owner_starts,
        tick_event='turn_started', on_expire=profile.expire_behavior_id)
    spec.__post_init__()
    return spec


def public_recipe(card_id):
    if not card_id.startswith(PREFIX): return None
    recipe = recipe_from_id(card_id)
    return dict(template_card_id=recipe.template_card_id, parts=list(recipe.parts))


def pack(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def encode(game, value):
    from .continuations import FrameCodec
    return pack(FrameCodec(game.mechanics, game.registry).encode(value))


def decode(game, value):
    from .continuations import FrameCodec
    return FrameCodec(game.mechanics, game.registry).decode(json.loads(value))


def events(game, kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events) if e.kind == kind)


def original(game, ident, kind):
    rows = [e for e in events(game, kind) if e.sequence == ident]
    if len(rows) != 1: raise ValueError('Trial work lost its original effective event')
    return rows[0]


@dataclass(frozen=True)
class CraftShamTrial(Effect):
    player_id: int
    source_id: int
    profile_card_id: str

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'trial source', 1); _name(self.profile_card_id, 'trial profile')


@dataclass(frozen=True)
class OfferShamTrial(Effect):
    root_id: int
    chosen: tuple[str, ...] = ()

    def __post_init__(self):
        _integer(self.root_id, 'trial craft root', 1)
        if type(self.chosen) is not tuple or len(self.chosen) > 2 or len(set(self.chosen)) != len(self.chosen):
            raise ValueError('Trial phase needs its two distinct original effect choices')
        for value in self.chosen: _name(value, 'prior trial choice')


@dataclass(frozen=True)
class SelectShamTrial(Effect):
    offer_id: int
    card_id: str

    def __post_init__(self):
        _integer(self.offer_id, 'original trial offer', 1); _name(self.card_id, 'trial option')


@dataclass(frozen=True)
class DeliverShamTrial(Effect):
    root_id: int
    recipe_id: str

    def __post_init__(self):
        _integer(self.root_id, 'trial craft root', 1); recipe_from_id(self.recipe_id)


def root_request(game, root_id):
    event = original(game, root_id, ROOT); request = CraftShamTrial(**json.loads(dict(event.data)['request']))
    if (event.source_id, event.player_id) != (request.source_id, request.player_id):
        raise ValueError('Trial manufacture changed its original actor')
    return request


def candidates(registry, request, chosen):
    profile = registry._sham_trial_profiles[request.profile_card_id]
    if any(cid not in profile.component_ids for cid in chosen): raise ValueError('Trial borrowed another component')
    return tuple(t.choice_card_id for t in profile.tiers) if len(chosen) == 2 else tuple(
        cid for cid in profile.component_ids if cid not in chosen)


def options(registry, offer_id, offered):
    return tuple(ChoiceOption(cid, registry.card(cid).name, (SelectShamTrial(offer_id, cid),), card_id=cid) for cid in offered)


def start_craft(r, effect):
    candidates(r.registry, effect, ())
    source = SourceAllocationFact.capture(r.state, r.state.entities[effect.source_id])
    event = r.emit(ROOT, source_id=effect.source_id, player_id=effect.player_id,
        request=pack(asdict(effect)), source=pack(asdict(source)), _capture=False)
    return (OfferShamTrial(event.sequence),)


def offer(r, effect):
    request = root_request(r.game, effect.root_id); domain = candidates(r.registry, request, effect.chosen)
    before = r.game._rng.getstate()
    offered = domain if len(effect.chosen) == 2 else tuple(r.game._rng.sample(domain, 3))
    event = r.emit(OFFER, source_id=request.source_id, player_id=request.player_id, root_id=effect.root_id,
        chosen=effect.chosen, candidates=domain, offered=offered, rng_before=before,
        rng_after=r.game._rng.getstate(), _capture=False)
    return (RequestChoice(request.player_id, options(r.registry, event.sequence, offered), request.source_id,
        prompt='选择庭审长度' if len(effect.chosen) == 2 else '选择庭审效果'),)


def selected_event(game, offered, request, card_id, *, through=None):
    from .card_discoveries import SELECTION_EVENTS
    from .hero_health_history import effective_events
    rows = [e for e in effective_events(game._events) if e.sequence > offered.sequence and
        (through is None or e.sequence < through) and e.kind in SELECTION_EVENTS and
        (e.source_id, e.player_id, dict(e.data).get('option_ids')) == (request.source_id, request.player_id, (card_id,))]
    if not rows: raise ValueError('Trial lost its actual manual or automatic selected input')
    return rows[-1]


def recipe_for(registry, request, chosen, length):
    profile = registry._sham_trial_profiles[request.profile_card_id]
    tier = next(t for t in profile.tiers if t.choice_card_id == length)
    return ShamTrialRecipe(tier.template_card_id, *sorted(chosen, key=profile.component_ids.index))


def select(r, effect):
    event = original(r.game, effect.offer_id, OFFER); data = dict(event.data); request = root_request(r.game, data['root_id'])
    if effect.card_id not in data['offered'] or any(dict(e.data)['offer_id'] == effect.offer_id for e in events(r.game, PICK)):
        raise ValueError('Trial duplicated or substituted its original chosen option')
    chosen = selected_event(r.game, event, request, effect.card_id)
    r.emit(PICK, source_id=request.source_id, player_id=request.player_id, root_id=data['root_id'],
        offer_id=effect.offer_id, card_id=effect.card_id, selection_sequence=chosen.sequence, _capture=False)
    prior = tuple(data['chosen'])
    return (DeliverShamTrial(data['root_id'], recipe_for(r.registry, request, prior, effect.card_id).card_id),) if len(prior) == 2 else (
        OfferShamTrial(data['root_id'], (*prior, effect.card_id)),)


def deliver(r, effect):
    from .opening import create_hand_card, announce_hand_card
    request = root_request(r.game, effect.root_id); checked_recipe(r.registry, effect.recipe_id)
    if any(dict(e.data)['root_id'] == effect.root_id for e in events(r.game, CREATED)):
        raise ValueError('Trial manufacture duplicated its one physical delivery')
    delivery = AddToHand(request.player_id, effect.recipe_id, request.source_id)
    entity = create_hand_card(r, delivery, defer_publication=True)
    r.emit(CREATED, source_id=request.source_id, target_id=entity.id, player_id=request.player_id,
        root_id=effect.root_id, recipe_id=effect.recipe_id,
        material=pack(asdict(SourceAllocationFact.capture(r.state, entity))), _capture=False)
    announce_hand_card(r, delivery, entity)
    return ()


@dataclass(frozen=True)
class BeginShamTrial(Effect):
    cast_id: int | None = None
    instance: PlayerEffect | None = None
    expiry_sequence: int | None = None

    def __post_init__(self):
        if (self.cast_id is None) == (self.instance is None): raise ValueError('Trial needs one original CAST or expired program')
        if self.cast_id is not None:
            _integer(self.cast_id, 'trial CAST', 1)
            if self.expiry_sequence is not None: raise ValueError('An immediate trial cannot borrow an expiry')
        else:
            if type(self.instance) is not PlayerEffect: raise ValueError('Trial requires its complete original program')
            self.instance.__post_init__(); _integer(self.expiry_sequence, 'trial expiry event', 1)


@dataclass(frozen=True)
class ContinueShamTrial(Effect):
    start_id: int
    index: int = 0

    def __post_init__(self):
        _integer(self.start_id, 'trial execution root', 1); _integer(self.index, 'trial component cursor', 0)
        if self.index > 2: raise ValueError('Trial has only two native components')


def note_install(r, instance):
    if not instance.spec_id.startswith(PREFIX): return
    from .spell_casts import active_cast
    recipe, _, tier = checked_recipe(r.registry, instance.spec_id)
    record = active_cast(r.state, instance.source_id, r.state.entities[instance.source_id].controller)
    if record is None or record.card_id != recipe.card_id or not record.payload_started or not tier.owner_starts:
        raise ValueError('Trial program requires its original actual spell CAST')
    r.emit(INSTALLED, source_id=instance.source_id, player_id=record.player_id, cast_id=record.id,
        instance=encode(r.game, instance), _capture=False)


def installed(game, instance):
    rows = [e for e in events(game, INSTALLED) if decode(game, dict(e.data)['instance']).id == instance.id]
    if len(rows) != 1: raise ValueError('Trial program lost its unique original installation')
    original_instance = decode(game, dict(rows[0].data)['instance'])
    if replace(original_instance, remaining_turns=instance.remaining_turns) != instance:
        raise ValueError('Trial program changed its original recipe, physical source or instance')
    return rows[0]


def execution(game, work):
    work.__post_init__()
    from .spell_casts import cast_record
    if work.cast_id is not None:
        record = cast_record(game._state, work.cast_id); recipe, profile, tier = checked_recipe(game.registry, record.card_id)
        if tier.owner_starts or not record.payload_started or record.failure is not None:
            raise ValueError('Immediate trial lost its original accepted CAST')
        return recipe, profile, record.source_id, record.player_id, record
    instance = work.instance; installation = installed(game, instance)
    recipe, profile, tier = checked_recipe(game.registry, instance.spec_id)
    expiry = original(game, work.expiry_sequence, 'player_effect_expired'); data = dict(expiry.data)
    if (not tier.owner_starts or instance.remaining_turns != 1 or installation.sequence >= expiry.sequence or
            data.get('effect_key') != instance.spec_id or data.get('remaining_turns') != 0 or
            (expiry.source_id, expiry.player_id) != (instance.source_id, installation.player_id)):
        raise ValueError('Trial lost its actual owner-clock expiry')
    return recipe, profile, instance.source_id, installation.player_id, None


def begin(r, effect):
    recipe, _, source_id, player_id, record = execution(r.game, effect)
    for event in events(r.game, START):
        old = decode(r.game, dict(event.data)['origin'])
        if (effect.cast_id is not None and old.cast_id == effect.cast_id or effect.instance is not None and
                old.instance is not None and old.instance.id == effect.instance.id):
            raise ValueError('Trial duplicated an original CAST or expired program')
    if record is not None and (record.completed or record.interrupted): raise ValueError('Trial CAST is already closed')
    event = r.emit(START, source_id=source_id, player_id=player_id, recipe_id=recipe.card_id,
        origin=encode(r.game, effect), _capture=False)
    return (ContinueShamTrial(event.sequence),)


def continue_trial(r, effect):
    event = original(r.game, effect.start_id, START); data = dict(event.data)
    recipe, profile, source_id, player_id, record = execution(r.game, decode(r.game, data['origin']))
    steps = [e for e in events(r.game, STEP) if dict(e.data)['start_id'] == effect.start_id]
    if len(steps) != effect.index or any(dict(e.data)['start_id'] == effect.start_id for e in events(r.game, END)):
        raise ValueError('Trial changed its unique original component cursor')
    if effect.index == 2:
        r.emit(END, source_id=source_id, player_id=player_id, start_id=effect.start_id, _capture=False)
        return ()
    cid = recipe.parts[effect.index]; component = next(c for c in profile.components if c.card_id == cid)
    r.emit(STEP, source_id=source_id, player_id=player_id, start_id=effect.start_id,
        index=effect.index, component=cid, _capture=False)
    return (r.call(component.behavior_id, source_id, player_id, cast=record,
        player_effect=decode(r.game, data['origin']).instance), ContinueShamTrial(effect.start_id, effect.index + 1))


def validate_game(game):
    from .hero_health_history import effective_events
    from .spell_casts import cast_record
    relevant = [e for e in effective_events(game._events) if e.kind in (ROOT, OFFER, PICK, CREATED, INSTALLED, START, STEP, END)]
    frame = game._frame; queue = () if frame is None else (*frame.prefix, *frame.continuation)
    if not relevant and not any(type(w) in (CraftShamTrial, OfferShamTrial, SelectShamTrial, DeliverShamTrial,
            BeginShamTrial, ContinueShamTrial) for w in queue): return
    roots, offers, runs, installations = {}, {}, {}, {}
    for event in relevant:
        data = dict(event.data)
        if event.kind == ROOT:
            request = root_request(game, event.sequence); source = allocation_from_dict(json.loads(data['source']))
            validate_allocation(game._state, game.registry, source)
            if source.entity_id != request.source_id: raise ValueError('Trial manufacture borrowed another physical source')
            candidates(game.registry, request, ())
            roots[event.sequence] = dict(request=request, chosen=(), active=None, created=False, recipe=None)
        elif event.kind == OFFER:
            root = roots.get(data['root_id'])
            if root is None or root['created'] or root['active'] is not None or tuple(data['chosen']) != root['chosen'] or root['recipe']:
                raise ValueError('Trial duplicated or changed its original phase')
            domain = candidates(game.registry, root['request'], root['chosen']); rng = Random(); rng.setstate(data['rng_before'])
            expected = domain if len(root['chosen']) == 2 else tuple(rng.sample(domain, 3))
            if (tuple(data['candidates']), tuple(data['offered']), data['rng_after']) != (domain, expected, rng.getstate()) or (
                    event.source_id, event.player_id) != (root['request'].source_id, root['request'].player_id):
                raise ValueError('Trial cropped its complete original domain or changed its original draw')
            root['active'] = event.sequence; offers[event.sequence] = dict(event=event, picked=False)
        elif event.kind == PICK:
            row = offers.get(data['offer_id']); root = roots.get(data['root_id'])
            if row is None or root is None or row['picked'] or root['active'] != data['offer_id']:
                raise ValueError('Trial selection borrowed a consumed or foreign phase')
            offered = tuple(dict(row['event'].data)['offered']); request = root['request']
            selected = selected_event(game, row['event'], request, data['card_id'], through=event.sequence)
            if data['card_id'] not in offered or selected.sequence != data['selection_sequence']:
                raise ValueError('Trial changed its actual selected input')
            d = dict(selected.data)
            published = [e for e in effective_events(game._events) if e.kind == 'choice_requested' and dict(e.data).get('choice_id') == d['choice_id']]
            if selected.kind == 'choice_selected' and len(published) != 1:
                raise ValueError('Trial lost its complete original manual menu')
            if published and (published[0].source_id, published[0].player_id, dict(published[0].data)['option_ids']) != (
                    request.source_id, request.player_id, offered): raise ValueError('Trial substituted the original published menu')
            row['picked'] = True; root['active'] = None
            if len(root['chosen']) == 2: root['recipe'] = recipe_for(game.registry, request, root['chosen'], data['card_id']).card_id
            else: root['chosen'] = (*root['chosen'], data['card_id'])
        elif event.kind == CREATED:
            root = roots.get(data['root_id'])
            if root is None or root['created'] or root['active'] is not None or root['recipe'] != data['recipe_id']:
                raise ValueError('Trial delivery changed its complete original manufacture')
            material = allocation_from_dict(json.loads(data['material'])); validate_allocation(game._state, game.registry, material)
            request = root['request']; checked_recipe(game.registry, data['recipe_id'])
            if (material.entity_id, material.card_id, material.kind, material.owner, material.controller,
                    event.source_id, event.player_id) != (event.target_id, root['recipe'], CardType.SPELL,
                    request.player_id, request.player_id, request.source_id, request.player_id):
                raise ValueError('Trial changed its original physical delivery')
            root['created'] = True
        elif event.kind == INSTALLED:
            instance = decode(game, data['instance']); recipe, _, tier = checked_recipe(game.registry, instance.spec_id)
            record = cast_record(game._state, data['cast_id'])
            if (not tier.owner_starts or instance.id in installations or instance.remaining_turns != tier.owner_starts or
                    (instance.source_id, instance.source_card_id, event.source_id, event.player_id) !=
                    (record.source_id, recipe.card_id, record.source_id, record.player_id) or
                    record.card_id != recipe.card_id or not record.payload_started or record.failure is not None):
                raise ValueError('Trial installation changed its original spell or program')
            installations[instance.id] = instance
        elif event.kind == START:
            origin = decode(game, data['origin']); recipe, _, source_id, player_id, _ = execution(game, origin)
            key = ('cast', origin.cast_id) if origin.cast_id is not None else ('program', origin.instance.id)
            if data['recipe_id'] != recipe.card_id or (event.source_id, event.player_id) != (source_id, player_id) or any(r['key'] == key for r in runs.values()):
                raise ValueError('Trial execution duplicated or changed its original acceptance')
            runs[event.sequence] = dict(origin=origin, key=key, recipe=recipe, source=source_id, player=player_id, steps=0, ended=False)
        else:
            run = runs.get(data['start_id'])
            if run is None or run['ended'] or (event.source_id, event.player_id) != (run['source'], run['player']):
                raise ValueError('Trial component borrowed an absent or finished execution')
            if event.kind == STEP:
                if run['steps'] >= 2 or data != dict(start_id=data['start_id'], index=run['steps'], component=run['recipe'].parts[run['steps']]):
                    raise ValueError('Trial changed or skipped its native component order')
                run['steps'] += 1
            else:
                if run['steps'] != 2 or set(data) != {'start_id'}: raise ValueError('Trial finished an incomplete original body')
                run['ended'] = True
    for player in game._state.players.values():
        for instance in player.player_effects:
            if instance.spec_id.startswith(PREFIX):
                event = installed(game, instance)
                if event.player_id != player.id: raise ValueError('Trial program changed its original player')
    for work in queue:
        if type(work) is CraftShamTrial: candidates(game.registry, work, ())
        elif type(work) is OfferShamTrial:
            root = roots.get(work.root_id)
            if root is None or root['created'] or root['active'] is not None or root['recipe'] or work.chosen != root['chosen']:
                raise ValueError('Trial pending offer changed its original phase')
        elif type(work) is SelectShamTrial:
            row = offers.get(work.offer_id)
            if row is None or row['picked'] or work.card_id not in dict(row['event'].data)['offered']:
                raise ValueError('Trial pending selection borrowed a consumed or foreign offer')
        elif type(work) is DeliverShamTrial:
            root = roots.get(work.root_id)
            if root is None or root['created'] or root['recipe'] != work.recipe_id:
                raise ValueError('Trial pending delivery changed its original completed recipe')
        elif type(work) is BeginShamTrial: execution(game, work)
        elif type(work) is ContinueShamTrial:
            run = runs.get(work.start_id)
            if run is None or run['ended'] or work.index != run['steps']: raise ValueError('Trial lost its original next component')
    if game._state.status != 'playing': return
    for ident, root in roots.items():
        if root['created']: continue
        if root['active'] is None:
            expected = DeliverShamTrial(ident, root['recipe']) if root['recipe'] else OfferShamTrial(ident, root['chosen'])
            if queue.count(expected) != 1: raise ValueError('Trial manufacture lost its unique next phase')
        else:
            event = offers[root['active']]['event']; offered = tuple(dict(event.data)['offered']); expected_options = options(game.registry, event.sequence, offered)
            pending = [w for w in queue if type(w) is SelectShamTrial and w.offer_id == event.sequence and w.card_id in offered]
            pending += [w for w in queue if type(w) is RequestChoice and w.options == expected_options and w.on_select is None]
            if frame is not None and frame.options == expected_options and frame.on_select is None:
                q = game._state.pending_choice
                if q is None or (q.source_id, q.player_id, q.min_count, q.max_count, q.prompt) != (
                        root['request'].source_id, root['request'].player_id, 1, 1,
                        '选择庭审长度' if len(root['chosen']) == 2 else '选择庭审效果'):
                    raise ValueError('Trial waiting menu changed its original actor or phase')
                pending.append(frame)
            if len(pending) != 1: raise ValueError('Trial offer lost its unique original continuation')
    for ident, run in runs.items():
        pending = [w for w in queue if type(w) is ContinueShamTrial and w.start_id == ident]
        if pending != ([] if run['ended'] else [ContinueShamTrial(ident, run['steps'])]):
            raise ValueError('Trial execution lost or duplicated its original next component')


def register(mechanics):
    for kind, handler in ((CraftShamTrial, start_craft), (OfferShamTrial, offer), (SelectShamTrial, select),
            (DeliverShamTrial, deliver), (BeginShamTrial, begin), (ContinueShamTrial, continue_trial)):
        mechanics.register(kind, handler)
