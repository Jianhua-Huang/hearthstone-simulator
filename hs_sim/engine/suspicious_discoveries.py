"""Finite altered Discover faces with original identities and shared delivery."""
from dataclasses import asdict, dataclass, replace
import json
from random import Random
from types import SimpleNamespace

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import AddToHand, ChoiceOption, Effect, RequestChoice, _integer, _player
from .model import (BoardPresenceReference, CardClass, CardPreview, CardType, ChoicePurpose,
    ChoiceResult, CostSpec, Enchantment, TribeChangeSpec, Zone, _name)
from .pools import PoolMember, PoolQuery, generation_candidates, resolve_candidates, sample_candidates

OFFERED = 'suspicious_discovery_offered'
DELIVERED = 'suspicious_discovery_delivered'
FINISHED = 'suspicious_discovery_finished'
KINDS = ('cost', 'attack', 'health', 'tribe', 'name')
PROMPT = '发现一张随从牌'
VERSION = 'watfin-local-v1'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current')


@dataclass(frozen=True)
class SuspiciousDiscoveryProfile:
    source_card_id: str
    names: tuple[tuple[str, str], ...]
    tribes: tuple[str, ...]
    version: str = VERSION

    def __post_init__(self):
        _name(self.source_card_id, 'suspicious source')
        if self.version != VERSION or type(self.names) is not tuple or not self.names or type(self.tribes) is not tuple or not self.tribes:
            raise ValueError('Suspicious discovery needs its complete versioned name and tribe domains')
        ids = []
        for row in self.names:
            if type(row) is not tuple or len(row) != 2: raise ValueError('Name domain requires exact original identity/name pairs')
            _name(row[0], 'name donor'); _name(row[1], 'visible name')
            if len(row[1]) > 256: raise ValueError('Name donor is too long')
            ids.append(row[0])
        if len(ids) != len(set(ids)) or self.tribes != tuple(sorted(set(self.tribes))) or 'all' in self.tribes:
            raise ValueError('Duplicate names or invalid native tribe domain')
        TribeChangeSpec('add', self.tribes).__post_init__()


def validate_profile(registry, profile):
    if type(profile) is not SuspiciousDiscoveryProfile: raise ValueError('Typed suspicious profile required')
    profile.__post_init__()
    face = registry.card(profile.source_card_id)
    if face.kind != CardType.MINION or face.battlecry is None:
        raise ValueError('Suspicious discovery requires its declared native Battlecry minion')


@dataclass(frozen=True)
class SuspiciousMutation:
    kind: str = 'none'
    value: str | None = None

    def __post_init__(self):
        if self.kind not in ('none', *KINDS): raise ValueError('Unknown native suspicious modification')
        if self.kind in ('tribe', 'name'):
            _name(self.value, 'suspicious modification value')
        elif self.value is not None: raise ValueError('Numeric modification cannot borrow an identity value')


def validate_mutation(registry, profile_id, mutation):
    if type(mutation) is not SuspiciousMutation: raise ValueError('Typed native modification required')
    mutation.__post_init__()
    profile = registry._suspicious_discovery_profiles[profile_id]
    if mutation.kind == 'tribe' and mutation.value not in profile.tribes:
        raise ValueError('Suspicious modification borrowed an unknown tribe')
    if mutation.kind == 'name' and mutation.value not in dict(profile.names):
        raise ValueError('Suspicious modification borrowed an unknown name donor')
    return profile


@dataclass(frozen=True)
class DiscoverSuspiciousMinion(Effect):
    player_id: int
    source: SourceAllocationFact
    presence: BoardPresenceReference | None
    profile_card_id: str
    pool_id: str = 'constructed.minions'

    def __post_init__(self):
        _player(self.player_id); _name(self.profile_card_id, 'suspicious profile')
        if type(self.source) is not SourceAllocationFact: raise ValueError('Original physical discovery source required')
        self.source.__post_init__()
        if self.pool_id != 'constructed.minions': raise ValueError('Native suspicious discovery uses the ordinary minion pool')
        if self.presence is not None:
            if type(self.presence) is not BoardPresenceReference: raise ValueError('Original board residence required')
            self.presence.__post_init__()
            if self.presence.entity_id != self.source.entity_id: raise ValueError('Discovery reward borrowed another source')
        if (self.presence is not None) != (self.source.kind == CardType.MINION and self.source.zone == Zone.BOARD):
            raise ValueError('Discovery reward lost its original minion residence')

    @property
    def source_id(self): return self.source.entity_id

    @property
    def query(self): return QUERY


@dataclass(frozen=True)
class SuspiciousOffer:
    request: DiscoverSuspiciousMinion
    hero_class: CardClass
    source_card_id: str
    candidates: tuple[tuple[str, int], ...]
    offered: tuple[str, ...]
    marked_index: int | None
    mutation: SuspiciousMutation | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not DiscoverSuspiciousMinion: raise ValueError('Original suspicious request required')
        self.request.__post_init__()
        if type(self.hero_class) is not CardClass or self.hero_class in (CardClass.NEUTRAL, CardClass.DREAM):
            raise ValueError('Original discovery class required')
        _name(self.source_card_id, 'original generation source face')
        if type(self.candidates) is not tuple or type(self.offered) is not tuple or len(self.offered) > 3:
            raise ValueError('Complete immutable suspicious offer required')
        for row in self.candidates:
            if type(row) is not tuple or len(row) != 2: raise ValueError('Complete weighted candidate required')
            PoolMember(*row).__post_init__()
        if len({r[0] for r in self.candidates}) != len(self.candidates) or len(set(self.offered)) != len(self.offered):
            raise ValueError('Suspicious domain or offers duplicated an identity')
        if self.offered:
            _integer(self.marked_index, 'original suspicious slot', 0)
            if self.marked_index >= len(self.offered) or type(self.mutation) is not SuspiciousMutation or self.mutation.kind == 'none':
                raise ValueError('Suspicious offer lost its one original modified slot')
            self.mutation.__post_init__()
        elif self.marked_index is not None or self.mutation is not None:
            raise ValueError('Empty discovery cannot invent a suspicious answer')
        from .model import validate_end_turn_rng
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)


def draw(rng, candidates, profile):
    offered = sample_candidates(rng, candidates, 3, replacement=False)
    if not offered: return (), None, None
    index = rng.randrange(len(offered)); kind = rng.choice(KINDS)
    value = rng.choice(profile.tribes) if kind == 'tribe' else rng.choice(profile.names)[0] if kind == 'name' else None
    return offered, index, SuspiciousMutation(kind, value)


def encode(game, value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(game.mechanics, game.registry).encode(value), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'))


def decode(game, value):
    from .continuations import FrameCodec
    return FrameCodec(game.mechanics, game.registry).decode(json.loads(value))


def events(game, kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events) if e.kind == kind)


def original(game, ident):
    found = [e for e in events(game, OFFERED) if e.sequence == ident]
    if len(found) != 1: raise ValueError('Suspicious choice lost its original accepted window')
    proof = decode(game, dict(found[0].data)['proof'])
    if type(proof) is not SuspiciousOffer: raise ValueError('Typed original suspicious offer required')
    return found[0], proof


def mutation_at(proof, index):
    return proof.mutation if index == proof.marked_index else SuspiciousMutation()


def preview(registry, card_id, profile_id, mutation):
    profile = validate_mutation(registry, profile_id, mutation); card = registry.card(card_id)
    if card.kind != CardType.MINION: raise ValueError('Suspicious offer requires a real minion')
    from .tribes import normalized, apply_change
    current = None
    if mutation.kind == 'tribe':
        if card.metadata is None or card.metadata.tribes is None: raise ValueError('Unknown original offered minion tribes')
        current = apply_change(normalized(card.metadata.tribes), TribeChangeSpec('add', (mutation.value,)))
    return CardPreview(max(0, card.cost - (mutation.kind == 'cost')),
        card.attack + (mutation.kind == 'attack'), card.health + (mutation.kind == 'health'),
        card.health + (mutation.kind == 'health'), 0, tuple(sorted(card.keywords, key=lambda k: k.value)),
        dict(profile.names)[mutation.value] if mutation.kind == 'name' else None,
        None if current is None else current.members, () if current is None else current.excluded)


@dataclass(frozen=True)
class ChooseSuspiciousMinion(Effect):
    offer_id: int
    index: int
    card_id: str
    profile_card_id: str
    mutation: SuspiciousMutation
    result: ChoiceResult | None = None

    def __post_init__(self):
        _integer(self.offer_id, 'original suspicious offer', 1); _integer(self.index, 'original offer slot', 0)
        if self.index >= 3: raise ValueError('Suspicious slot is outside the native three choices')
        _name(self.card_id, 'original selected minion'); _name(self.profile_card_id, 'original native profile')
        if type(self.mutation) is not SuspiciousMutation: raise ValueError('Original modification required')
        self.mutation.__post_init__()
        if self.result is not None:
            if type(self.result) is not ChoiceResult: raise ValueError('Original complete selection required')
            self.result.__post_init__()


@dataclass(frozen=True)
class FinishSuspiciousDiscovery(Effect):
    offer_id: int

    def __post_init__(self): _integer(self.offer_id, 'original suspicious offer', 1)


def options(registry, ident, proof):
    result = []
    for i, cid in enumerate(proof.offered):
        mutation = mutation_at(proof, i); face = preview(registry, cid, proof.request.profile_card_id, mutation)
        result.append(ChoiceOption(f'card{i + 1}', face.display_name or registry.card(cid).name,
            (ChooseSuspiciousMinion(ident, i, cid, proof.request.profile_card_id, mutation),), card_id=cid, preview=face))
    return tuple(result)


def validate_waiting(game):
    frame = game._frame; choice = game._state.pending_choice
    if frame is None or choice is None or not frame.options:
        raise ValueError('Suspicious discovery requires its actual waiting menu')
    if any(len(o.effects) != 1 or type(o.effects[0]) is not ChooseSuspiciousMinion for o in frame.options):
        raise ValueError('Suspicious discovery cannot mix or substitute original producers')
    first = frame.options[0].effects[0]; _, proof = original(game, first.offer_id)
    if frame.options != options(game.registry, first.offer_id, proof) or frame.on_select is not None or (
            choice.source_id, choice.player_id, choice.purpose, choice.prompt, choice.min_count,
            choice.max_count, choice.repeat_key) != (proof.request.source_id, proof.request.player_id,
            ChoicePurpose.POOL_DISCOVERY, PROMPT, 1, 1, None):
        raise ValueError('Suspicious waiting menu changed its complete original offer')


def validate_proof(game, proof):
    proof.__post_init__(); request = proof.request
    validate_allocation(game._state, game.registry, request.source)
    profile = game.registry._suspicious_discovery_profiles[request.profile_card_id]
    expected = resolve_candidates(game.registry, game._generation_context, request.pool_id, QUERY,
        current_class=proof.hero_class, source_card_id=proof.source_card_id, player_id=request.player_id, exclude_source_by_rule=True)
    if proof.candidates != tuple((m.card_id, m.weight) for m in expected):
        raise ValueError('Suspicious discovery cropped or changed its original complete candidate pool')
    rng = Random(); rng.setstate(proof.rng_before)
    chosen = draw(rng, expected, profile)
    if chosen != (proof.offered, proof.marked_index, proof.mutation) or rng.getstate() != proof.rng_after:
        raise ValueError('Suspicious discovery changed its original random offer or modification')
    for i, cid in enumerate(proof.offered): preview(game.registry, cid, request.profile_card_id, mutation_at(proof, i))
    if request.presence is not None and request.presence.presence_id >= game._state.next_order:
        raise ValueError('Suspicious reward borrowed a future original residence')


def start(r, request):
    validate_allocation(r.state, r.registry, request.source)
    profile = r.registry._suspicious_discovery_profiles[request.profile_card_id]
    candidates = generation_candidates(r, request); before = r.game._rng.getstate()
    offered, marked, mutation = draw(r.game._rng, candidates, profile)
    proof = SuspiciousOffer(request, r.player(request.player_id).hero_class,
        r.state.entities[request.source_id].card_id, tuple((m.card_id, m.weight) for m in candidates),
        offered, marked, mutation, before, r.game._rng.getstate())
    event = r.emit(OFFERED, source_id=request.source_id, player_id=request.player_id, proof=encode(r.game, proof), _capture=False)
    return () if not offered else (RequestChoice(request.player_id, options(r.registry, event.sequence, proof),
        source_id=request.source_id, purpose=ChoicePurpose.POOL_DISCOVERY, prompt=PROMPT),)


def install_mutation(r, entity, profile_id, mutation, source_id):
    """Install the same original recipe before acquisition or offered-card entry."""
    profile = validate_mutation(r.registry, profile_id, mutation)
    if entity.kind != CardType.MINION: raise ValueError('Native modification requires its original minion body')
    from .lifecycle import attachment_id, refresh_entity
    if mutation.kind in ('attack', 'health'):
        from .card_creation import CreatedMinionGrant, install
        install(r.state, entity, SimpleNamespace(source_id=source_id, spell_repeat=None,
            minion_grant=CreatedMinionGrant(**{mutation.kind: 1})), resolver=r)
    elif mutation.kind == 'cost':
        from .costs import attach_cost
        attach_cost(r.state, entity, CostSpec(delta=-1), source_id)
    elif mutation.kind == 'tribe':
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=source_id,
            label='tribes', tribe_change=TribeChangeSpec('add', (mutation.value,))))
    elif mutation.kind == 'name':
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=source_id,
            label='minion_name', display_name=dict(profile.names)[mutation.value]))
    refresh_entity(entity)
    r.refresh_auras()


def validate_selected(game, effect):
    event, proof = original(game, effect.offer_id); expected = options(game.registry, event.sequence, proof)
    if effect.index >= len(expected) or replace(effect, result=None) != expected[effect.index].effects[0]:
        raise ValueError('Suspicious selection changed its original slot, card or intrinsic recipe')
    from .card_discoveries import require_original_result
    row = require_original_result(game._state, effect.result)
    if (effect.result.choice.options != tuple(o.item for o in expected) or
            effect.result.selected_ids != (expected[effect.index].id,) or
            (effect.result.choice.source_id, effect.result.choice.player_id, effect.result.choice.purpose,
             effect.result.choice.prompt, effect.result.choice.min_count, effect.result.choice.max_count) !=
            (proof.request.source_id, proof.request.player_id, ChoicePurpose.POOL_DISCOVERY, PROMPT, 1, 1)):
        raise ValueError('Suspicious discovery lost its complete actual selected input')
    from .discovery_offers import decode_offer
    offer = decode_offer(game, row.original_offer)
    if offer.options != expected or offer.on_select is not None:
        raise ValueError('Suspicious selection lost its complete original producer work')
    return proof, row


def choose(r, effect):
    proof, row = validate_selected(r.game, effect)
    if any(dict(e.data)['offer_id'] == effect.offer_id for e in events(r.game, DELIVERED)):
        raise ValueError('Suspicious selection duplicated its original delivery')
    from .opening import create_hand_card, announce_hand_card
    from .discovery_delivery import finish_for_entity
    delivery = AddToHand(proof.request.player_id, effect.card_id, proof.request.source_id)
    cursor = len(r.game._events); entity = create_hand_card(r, delivery, defer_publication=True)
    install_mutation(r, entity, effect.profile_card_id, effect.mutation, proof.request.source_id)
    r.emit(DELIVERED, source_id=proof.request.source_id, target_id=entity.id, player_id=proof.request.player_id,
        offer_id=effect.offer_id, discovery_id=row.id, selected=encode(r.game, effect),
        material=json.dumps(asdict(SourceAllocationFact.capture(r.state, entity)), sort_keys=True, separators=(',', ':')), _capture=False)
    announce_hand_card(r, delivery, entity)
    finish = finish_for_entity(r, effect.result, entity, delivery, cursor)
    return (finish, FinishSuspiciousDiscovery(effect.offer_id))


def finish(r, effect):
    _, proof = original(r.game, effect.offer_id)
    rows = [e for e in events(r.game, DELIVERED) if dict(e.data)['offer_id'] == effect.offer_id]
    if len(rows) != 1 or any(dict(e.data)['offer_id'] == effect.offer_id for e in events(r.game, FINISHED)):
        raise ValueError('Suspicious reward duplicated or lost its original physical delivery')
    chosen = decode(r.game, dict(rows[0].data)['selected']); current = None
    if chosen.index == proof.marked_index and proof.request.presence is not None:
        from .board_presence import resolve_board_presence
        current = resolve_board_presence(r.state, proof.request.presence)
    if current is not None and current.kind == CardType.MINION and current.active and current.health > 0 and not current.doomed:
        from .sacrifice import BuffCapturedMinion, MinionReference, buff_captured_minion
        buff_captured_minion(r, BuffCapturedMinion(MinionReference.capture(current), attack=1, health=1,
            source_id=proof.request.source_id))
    else: current = None
    r.emit(FINISHED, source_id=proof.request.source_id, target_id=None if current is None else current.id,
        player_id=proof.request.player_id, offer_id=effect.offer_id, rewarded=current is not None, _capture=False)
    return ()


def validate_game(game):
    relevant = (*events(game, OFFERED), *events(game, DELIVERED), *events(game, FINISHED))
    frame = game._frame; queue = () if frame is None else (*frame.prefix, *frame.continuation)
    if not relevant and not any(type(e) in (DiscoverSuspiciousMinion, ChooseSuspiciousMinion, FinishSuspiciousDiscovery) for e in queue): return
    offers, deliveries, finishes = {}, {}, {}
    for event in sorted(relevant, key=lambda e: e.sequence):
        data = dict(event.data)
        if event.kind == OFFERED:
            proof = decode(game, data['proof'])
            if type(proof) is not SuspiciousOffer: raise ValueError('Original suspicious proof required')
            validate_proof(game, proof)
            if (event.source_id, event.player_id) != (proof.request.source_id, proof.request.player_id):
                raise ValueError('Suspicious offer changed its original actor')
            offers[event.sequence] = proof
        elif event.kind == DELIVERED:
            if data['offer_id'] not in offers or data['offer_id'] in deliveries:
                raise ValueError('Suspicious delivery lost or duplicated its original offer')
            selected = decode(game, data['selected']); proof, row = validate_selected(game, selected)
            material = allocation_from_dict(json.loads(data['material'])); validate_allocation(game._state, game.registry, material)
            if (selected.offer_id, row.id, material.card_id, material.entity_id, material.kind, material.controller,
                    event.source_id, event.player_id) != (data['offer_id'], data['discovery_id'], selected.card_id,
                    event.target_id, CardType.MINION, proof.request.player_id, proof.request.source_id, proof.request.player_id):
                raise ValueError('Suspicious delivery changed its original selected physical recipient')
            deliveries[data['offer_id']] = event
        else:
            ident = data['offer_id']; proof = offers.get(ident)
            if ident not in deliveries or ident in finishes or type(data.get('rewarded')) is not bool or (
                    event.source_id, event.player_id) != (proof.request.source_id, proof.request.player_id):
                raise ValueError('Suspicious reward lost its original delivery and actor')
            selected = decode(game, dict(deliveries[ident].data)['selected'])
            if data['rewarded'] and (selected.index != proof.marked_index or proof.request.presence is None or
                    event.target_id != proof.request.source_id) or not data['rewarded'] and event.target_id is not None:
                raise ValueError('Suspicious reward borrowed an unchosen answer or another body')
            finishes[ident] = event
    for work in queue:
        if type(work) is DiscoverSuspiciousMinion:
            validate_allocation(game._state, game.registry, work.source)
            if work.profile_card_id not in game.registry._suspicious_discovery_profiles: raise ValueError('Unknown pending native discovery profile')
        if type(work) is ChooseSuspiciousMinion and work.result is not None: validate_selected(game, work)
        if type(work) is FinishSuspiciousDiscovery and (work.offer_id not in deliveries or work.offer_id in finishes):
            raise ValueError('Pending suspicious reward lost its unique original delivery')
    if game._state.status != 'playing': return
    for ident, proof in offers.items():
        if not proof.offered or ident in finishes: continue
        if ident in deliveries:
            pending = [w for w in queue if type(w) is FinishSuspiciousDiscovery and w.offer_id == ident]
        else:
            expected = options(game.registry, ident, proof)
            pending = [w for w in queue if type(w) is ChooseSuspiciousMinion and w.offer_id == ident]
            pending += [w for w in queue if type(w) is RequestChoice and w.options == expected and w.on_select is None]
            if frame is not None and frame.options == expected and frame.on_select is None:
                q = game._state.pending_choice
                if q is None or (q.source_id, q.player_id, q.purpose, q.min_count, q.max_count, q.prompt) != (
                        proof.request.source_id, proof.request.player_id, ChoicePurpose.POOL_DISCOVERY, 1, 1, PROMPT):
                    raise ValueError('Waiting suspicious discovery changed its original actor or menu')
                pending.append(frame)
        if len(pending) != 1: raise ValueError('Unfinished suspicious discovery lost its unique original continuation')


def register(mechanics):
    for payload in (SuspiciousMutation, SuspiciousOffer): mechanics.register_payload_type(payload)
    for kind, handler in ((DiscoverSuspiciousMinion, start), (ChooseSuspiciousMinion, choose), (FinishSuspiciousDiscovery, finish)):
        mechanics.register(kind, handler)
