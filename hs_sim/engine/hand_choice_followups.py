"""Private original hand offers followed by a same-turn physical hand play.

R-Map uses completed card_played, the original hand residence, and ExpireTurn.
These are explicit internal policies pending CN calibration, not a full pool.
"""
from dataclasses import dataclass, replace
from random import Random

from .effects import AddToHand, ChoiceOption, Effect, RequestChoice, _integer, _source
from .errors import ResolutionError
from .model import CardClass, ChoicePurpose, ChoiceResult, PendingChoice, Zone, validate_end_turn_rng
from .pools import (DiscoverFromPool, GenerationPolicy, PoolMember, generation_candidates,
                    resolve_candidates, sample_candidates)
from .zones import (CardReference, ChooseFromZone, CopyCard, MoveCard, choose_from_zone,
                    reference_entity, zone_candidates)


def validate_request(request):
    if type(request) not in (DiscoverFromPool, ChooseFromZone):
        raise ValueError('Hand followup requires a pool or own-deck hand discovery')
    request.__post_init__()
    _integer(request.source_id, 'hand discovery source', 1)
    if type(request) is DiscoverFromPool:
        if (request.destination != 'hand' or request.discoveries != 1 or request.delivery != 'after_each'
                or request.cause is not None or request.cost is not None or request.expires_turn is not None
                or request.spell_repeat is not None or request.minion_grant is not None
                or request.temporary_until_turn is not None or request.gift_copy_to_hand
                or request.shuffle_unselected_into_deck or request.keep_all_corpse_cost is not None):
            raise ValueError('Hand followup requires one plain hand delivery')
    elif (request.zone != Zone.DECK or request.owner_id != request.player_id
          or request.operation not in ('copy_base', 'copy_current', 'take', 'draw')):
        raise ValueError('Hand followup zone discovery requires an explicit own-deck hand operation')


@dataclass(frozen=True)
class DiscoverForPlayFollowup(Effect):
    request: DiscoverFromPool | ChooseFromZone
    def __post_init__(self): validate_request(self.request)


@dataclass(frozen=True)
class HandFollowupOption:
    id: str
    card_id: str
    card: CardReference | None = None
    def __post_init__(self):
        for name in ('id', 'card_id'):
            if type(getattr(self, name)) is not str or not getattr(self, name):
                raise ValueError('Original hand option identity required')
        if self.card is not None:
            if type(self.card) is not CardReference: raise ValueError('Typed original deck option required')
            self.card.__post_init__()
            if self.card.zone != Zone.DECK or self.card.card_id != self.card_id:
                raise ValueError('Original deck option and printed card disagree')


@dataclass(frozen=True)
class HandChoiceFollowup:
    id: int
    request: DiscoverFromPool | ChooseFromZone
    turn: int
    owner_turn_id: int
    action: int
    source_card_id: str
    offers: tuple[HandFollowupOption, ...]
    available_pool: tuple[PoolMember, ...]
    available_cards: tuple[CardReference, ...]
    hero_class: CardClass | None
    rng_before: tuple
    rng_after: tuple
    status: str = 'offered'
    initial_choice: PendingChoice | None = None
    initial_result: ChoiceResult | None = None
    initial_entity_id: int | None = None
    hand_entry_id: int | None = None
    initial_delivery_pending: bool = False
    trigger_play_id: int | None = None
    reward_choice: PendingChoice | None = None
    reward_result: ChoiceResult | None = None
    reward_entity_id: int | None = None
    reward_delivery_pending: bool = False

    def __post_init__(self):
        validate_request(self.request)
        for name in ('id', 'turn', 'owner_turn_id'): _integer(getattr(self, name), name, 1)
        _integer(self.action, 'followup action', 0)
        if type(self.source_card_id) is not str or not self.source_card_id:
            raise ValueError('Original discovery source face required')
        if self.status not in ('offered', 'initial_delivery', 'armed', 'reward_queued', 'reward_offered',
                               'reward_delivery', 'completed', 'empty', 'exhausted', 'not_hand', 'lost', 'expired', 'ended'):
            raise ValueError('Unknown hand followup phase')
        for name, kind in (('offers', HandFollowupOption), ('available_pool', PoolMember), ('available_cards', CardReference)):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(v) is not kind for v in values):
                raise ValueError('Complete typed hand offer inventory required')
            for value in values: value.__post_init__()
        if len({o.id for o in self.offers}) != len(self.offers): raise ValueError('Duplicate hand option identity')
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Original typed discovery class required')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        for name in ('initial_entity_id', 'hand_entry_id', 'trigger_play_id', 'reward_entity_id'):
            _source(getattr(self, name))
        for name in ('initial_delivery_pending', 'reward_delivery_pending'):
            if type(getattr(self, name)) is not bool: raise ValueError('Hand delivery phase must be boolean')
        for phase in ('initial', 'reward'):
            choice, result = getattr(self, phase+'_choice'), getattr(self, phase+'_result')
            if choice is not None:
                if type(choice) is not PendingChoice: raise ValueError('Original hand choice required')
                choice.__post_init__()
            if result is not None:
                if type(result) is not ChoiceResult or result.choice != choice:
                    raise ValueError('Hand selection lost its original choice')
                result.__post_init__()
                if len(result.selected_ids) != 1: raise ValueError('Hand offer selects exactly one option')


@dataclass(frozen=True)
class ResolveHandFollowupChoice(Effect):
    followup_id: int
    phase: str
    option_id: str
    result: ChoiceResult | None = None
    def __post_init__(self):
        _integer(self.followup_id, 'hand followup ID', 1)
        if self.phase not in ('initial', 'reward') or type(self.option_id) is not str or not self.option_id:
            raise ValueError('Original hand choice branch required')
        if self.result is not None:
            if type(self.result) is not ChoiceResult: raise ValueError('Typed hand selection result required')
            self.result.__post_init__()


@dataclass(frozen=True)
class RequestHandFollowupReward(Effect):
    followup_id: int
    def __post_init__(self): _integer(self.followup_id, 'hand followup ID', 1)


@dataclass(frozen=True)
class FinishHandFollowupDelivery(Effect):
    followup_id: int
    phase: str
    def __post_init__(self):
        _integer(self.followup_id, 'hand followup ID', 1)
        if self.phase not in ('initial', 'reward'): raise ValueError('Unknown hand delivery phase')


def record(state, identity):
    _integer(identity, 'hand followup ID', 1)
    if identity > len(state.hand_choice_followups): raise ValueError('Unknown hand followup')
    return state.hand_choice_followups[identity-1]


def update(state, root, **changes):
    value = replace(root, **changes); state.hand_choice_followups[root.id-1] = value; return value


def selected(root, phase='initial'):
    result = getattr(root, phase+'_result')
    return None if result is None else next(o for o in root.offers if o.id == result.selected_ids[0])


def phase_options(root, phase):
    picked = selected(root)
    return root.offers if phase == 'initial' else tuple(o for o in root.offers if o.id != picked.id)


def request_choice(root, phase, registry):
    return RequestChoice(root.request.player_id, tuple(ChoiceOption(o.id, registry.card(o.card_id).name,
        (ResolveHandFollowupChoice(root.id, phase, o.id),), card_id=o.card_id)
        for o in phase_options(root, phase)), root.request.source_id,
        prompt=root.request.prompt,
        purpose=ChoicePurpose.CARD_DISCOVERY if phase == 'initial' else ChoicePurpose.EFFECT)


def sample_zone(request, cards, rng):
    groups = {}
    if request.distinct == 'card':
        for c in cards: groups.setdefault(c.card_id, []).append(c)
        cards = tuple(groups[k][0] for k in sorted(groups))
    count = len(cards) if request.sample_size is None else min(len(cards), request.sample_size)
    offered = cards if request.sample_size is None else tuple(rng.sample(cards, count))
    return tuple(rng.choice(groups[c.card_id]) for c in offered) if request.distinct == 'card' and request.operation == 'copy_current' else offered


def start(r, effect):
    req = effect.request; validate_request(req)
    if req.source_id not in r.state.entities: raise ResolutionError('Hand discovery source does not exist')
    from .owner_turns import current_owner_turn
    interval = current_owner_turn(r.state)
    before = r.game._rng.getstate(); pool, cards, hero = (), (), None
    if type(req) is DiscoverFromPool:
        pool = generation_candidates(r, req)
        for member in pool:
            definition = r.registry.card(member.card_id)
            if definition.choice_only or not definition.hand_playable:
                raise ResolutionError('Hand offer contains a nonphysical hand card')
        offered = sample_candidates(r.game._rng, pool, req.count, replacement=False)
        options = tuple(HandFollowupOption(f'generated-{n}', cid) for n, cid in enumerate(offered, 1))
        hero = r.player(req.player_id).hero_class if req.query.class_mode in ('current', 'other') else None
    else:
        cards = zone_candidates(r, req.owner_id, req.zone, req.query, req.player_id, req.source_id)
        # Reuse the original zone producer and replay only its local RNG to bind physical choices.
        work = choose_from_zone(r, req)
        local = Random(); local.setstate(before); offered = sample_zone(req, cards, local)
        if local.getstate() != r.game._rng.getstate(): raise ResolutionError('Zone offer sampling diverged')
        if len(offered) != (len(work[0].options) if work else 0): raise ResolutionError('Zone offer inventory diverged')
        options = tuple(HandFollowupOption(f'zone-{n}', card.card_id, card) for n, card in enumerate(offered, 1))
        for card in cards:
            definition = r.registry.card(card.card_id)
            if definition.choice_only or not definition.hand_playable:
                raise ResolutionError('Hand offer contains a nonphysical hand card')
    root = HandChoiceFollowup(len(r.state.hand_choice_followups)+1, req, r.state.turn, interval.id,
        r.state.action_number, r.state.entities[req.source_id].card_id, options, pool, cards, hero,
        before, r.game._rng.getstate(), status='offered' if options else 'empty')
    r.state.hand_choice_followups.append(root)
    return (request_choice(root, 'initial', r.registry),) if options else ()


def bind_choice(r, choice, options):
    branches = [e for o in options for e in o.effects if type(e) is ResolveHandFollowupChoice]
    if not branches: return
    first = branches[0]; root = record(r.state, first.followup_id)
    expected = request_choice(root, first.phase, r.registry)
    if (tuple(options) != expected.options or (choice.player_id, choice.source_id, choice.prompt,
            choice.min_count, choice.max_count, choice.purpose) !=
            (expected.player_id, expected.source_id, expected.prompt, 1, 1, expected.purpose)):
        raise ResolutionError('Hand choice differs from its original private offer')
    if root.status != ('offered' if first.phase == 'initial' else 'reward_offered'):
        raise ResolutionError('Hand choice has already been consumed')
    update(r.state, root, **{first.phase+'_choice': choice})


def resolve(r, effect):
    root = record(r.state, effect.followup_id); phase = effect.phase
    if (root.status != ('offered' if phase == 'initial' else 'reward_offered') or effect.result is None
            or effect.result.choice != getattr(root, phase+'_choice') or effect.result.selected_ids != (effect.option_id,)):
        raise ResolutionError('Hand selection lost its original acceptance')
    option = next((o for o in phase_options(root, phase) if o.id == effect.option_id), None)
    if option is None: raise ResolutionError('Hand option is outside its retained offer')
    req = root.request
    operation = 'generate' if type(req) is DiscoverFromPool else req.operation
    if operation in ('generate', 'copy_base'):
        delivery = AddToHand(req.player_id, option.card_id, req.source_id)
        from .opening import add_to_hand
        handler, expected = add_to_hand, r.state.next_entity_id
    else:
        if reference_entity(r, option.card) is None:
            update(r.state, root, status='not_hand' if phase == 'initial' else 'completed', **{phase+'_result': effect.result})
            if phase=='initial':
                from .discovery_delivery import MaterializeDiscoveredCard
                return (MaterializeDiscoveredCard(effect.result,None),)
            return ()
        if operation == 'copy_current':
            delivery = CopyCard(option.card, req.player_id, source_id=req.source_id)
            from .zones import copy_card
            handler, expected = copy_card, r.state.next_entity_id
        else:
            delivery = MoveCard(option.card, req.player_id, Zone.HAND, draw=operation == 'draw', source_id=req.source_id)
            from .zones import move_card
            handler, expected = move_card, option.card.entity_id
    root = update(r.state, root, status=phase+'_delivery', **{phase+'_result': effect.result,
        phase+'_entity_id': expected, phase+'_delivery_pending': True})
    if phase=='initial':
        from .discovery_delivery import finish_for_entity
        delivery_cursor=len(r.game._events)
        work=()
        if type(delivery)is AddToHand:
            from .opening import create_hand_card
            entity=create_hand_card(r,delivery)
        elif type(delivery)is CopyCard:
            from .zones import copy_physical_card
            entity=copy_physical_card(r,delivery)
        elif delivery.draw:
            entity=reference_entity(r,delivery.card)
            work=handler(r,delivery)or()
        else:
            from .zones import move_physical_card
            entity=move_physical_card(r,delivery)
        if entity is not None and entity.id!=expected:
            raise ResolutionError('Map actual output disagrees with its original hand-entry reservation')
        notification=finish_for_entity(r,effect.result,entity,delivery,delivery_cursor)
        return (*work,FinishHandFollowupDelivery(root.id,phase),notification)
    work = handler(r, delivery)
    return (*(() if work is None else work), FinishHandFollowupDelivery(root.id, phase))


def note_delivery(r, event):
    if event.kind not in ('card_added_to_hand', 'card_drawn', 'card_moved_to_hand'): return
    for root in tuple(r.state.hand_choice_followups):
        if (not root.initial_delivery_pending or root.hand_entry_id is not None
                or root.initial_entity_id != event.target_id or root.request.player_id != event.player_id): continue
        entity = r.state.entities[event.target_id]
        if entity.zone == Zone.HAND and entity.controller == root.request.player_id:
            update(r.state, root, hand_entry_id=entity.hand_entry_id, status='armed')


def finish_delivery(r, effect):
    root = record(r.state, effect.followup_id); phase = effect.phase
    if not getattr(root, phase+'_delivery_pending'): raise ResolutionError('Hand delivery already finished')
    changes = {phase+'_delivery_pending': False}
    if phase == 'initial' and root.status == 'initial_delivery': changes['status'] = 'not_hand'
    if phase == 'reward' and root.status == 'reward_delivery': changes['status'] = 'completed'
    update(r.state, root, **changes)


def note_play(r, event):
    if event.kind != 'card_played': return ()
    from .play_history import play_record
    play = play_record(r.state, dict(event.data)['play_id']); work = []
    for root in tuple(r.state.hand_choice_followups):
        if (root.status == 'armed' and root.turn == r.state.turn and play.completed
                and root.owner_turn_id == play.played_face.owner_turn_id
                and (root.request.player_id, root.initial_entity_id, root.hand_entry_id) ==
                    (play.player_id, play.source_id, play.hand_entry_id)):
            update(r.state, root, status='reward_queued', trigger_play_id=play.id)
            work.append(RequestHandFollowupReward(root.id))
    return tuple(work)


def reward(r, effect):
    root = record(r.state, effect.followup_id)
    if root.status != 'reward_queued': raise ResolutionError('Hand followup has already been consumed')
    if not phase_options(root, 'reward'):
        update(r.state, root, status='exhausted'); return ()
    root = update(r.state, root, status='reward_offered')
    return (request_choice(root, 'reward', r.registry),)


def synchronize(r):
    """Observe actual moves through both resolver and physical-zone handlers."""
    for root in tuple(r.state.hand_choice_followups):
        if root.status != 'armed': continue
        entity = r.state.entities[root.initial_entity_id]
        if (entity.zone == Zone.HAND and entity.controller == root.request.player_id
                and entity.hand_entry_id == root.hand_entry_id): continue
        in_play = any(p.source_id == entity.id and p.hand_entry_id == root.hand_entry_id
                      and not p.completed and not p.interrupted for p in r.state.play_history)
        if not in_play: update(r.state, root, status='lost')


def expire(r, turn):
    for root in tuple(r.state.hand_choice_followups):
        if root.status == 'armed' and root.turn == turn: update(r.state, root, status='expired')


def ended(r):
    for root in tuple(r.state.hand_choice_followups):
        if root.status in ('offered', 'initial_delivery', 'armed', 'reward_queued', 'reward_offered', 'reward_delivery'):
            update(r.state, root, status='ended', initial_delivery_pending=False, reward_delivery_pending=False)


def public_followups(state, registry, entity):
    return [dict(source_card_id=root.source_card_id, expires_turn=root.turn,
        remaining=[dict(card_id=o.card_id, name=registry.card(o.card_id).name) for o in phase_options(root, 'reward')])
        for root in state.hand_choice_followups if root.status == 'armed'
        and (root.request.player_id, root.initial_entity_id, root.hand_entry_id) ==
            (entity.controller, entity.id, entity.hand_entry_id)]


def rows_from_dict(value):
    from .serialization import _row, _list, choice_from_dict, end_turn_rng_from_json
    from .pool_summons import query_from_dict
    from .model import Keyword
    rows = []
    for item in _list(value['hand_choice_followups'], 'hand followup history'):
        row = _row(item, HandChoiceFollowup); raw = row['request']
        cls = DiscoverFromPool if type(raw) is dict and 'pool_id' in raw else ChooseFromZone
        req = _row(raw, cls); req['query'] = query_from_dict(req['query'])
        if cls is DiscoverFromPool:
            policy = _row(req['policy'], GenerationPolicy)
            policy['allowed_special'] = tuple(Keyword(k) for k in _list(policy['allowed_special'], 'generation exceptions'))
            req['policy'] = GenerationPolicy(**policy)
            req['entry_keywords'] = tuple(Keyword(k) for k in _list(req['entry_keywords'], 'original discovery entry keywords'))
        else: req['zone'] = Zone(req['zone'])
        row['request'] = cls(**req)
        def reference(v):
            if v is None: return None
            ref = _row(v, CardReference); ref['zone'] = Zone(ref['zone']); return CardReference(**ref)
        options = []
        for option in _list(row['offers'], 'hand options'):
            opt = _row(option, HandFollowupOption); opt['card'] = reference(opt['card']); options.append(HandFollowupOption(**opt))
        row['offers'] = tuple(options)
        row['available_pool'] = tuple(PoolMember(**_row(v, PoolMember)) for v in _list(row['available_pool'], 'pool inventory'))
        row['available_cards'] = tuple(reference(v) for v in _list(row['available_cards'], 'deck inventory'))
        row['hero_class'] = None if row['hero_class'] is None else CardClass(row['hero_class'])
        for name in ('rng_before', 'rng_after'): row[name] = end_turn_rng_from_json(row[name])
        for phase in ('initial', 'reward'):
            row[phase+'_choice'] = None if row[phase+'_choice'] is None else choice_from_dict(row[phase+'_choice'])
            result = row[phase+'_result']
            if result is not None:
                result = _row(result, ChoiceResult)
                row[phase+'_result'] = ChoiceResult(choice_from_dict(result['choice']), tuple(_list(result['selected_ids'], 'hand selected IDs')))
        rows.append(HandChoiceFollowup(**row))
    value['hand_choice_followups'] = rows


def validate_shape(state):
    if type(state.hand_choice_followups) is not list: raise ValueError('Typed hand followup history required')
    for identity, root in enumerate(state.hand_choice_followups, 1):
        if type(root) is not HandChoiceFollowup: raise ValueError('Typed hand followup record required')
        root.__post_init__()
        if root.id != identity or root.turn > state.turn or root.action > state.action_number:
            raise ValueError('Hand followup history is not allocated in order')
        if (root.status == 'empty') != (not root.offers):
            raise ValueError('Hand followup empty phase differs from its original offer')
        if root.status == 'offered' and root.initial_result is not None:
            raise ValueError('Original hand offer was already selected')
        if root.status not in ('offered', 'empty', 'ended') and root.initial_result is None:
            raise ValueError('Hand delivery phase has no initial selection')
        if root.reward_choice is not None and root.initial_result is None:
            raise ValueError('Hand reward precedes its initial selection')
        if root.reward_result is not None and root.status not in ('reward_delivery', 'completed', 'ended'):
            raise ValueError('Hand reward result differs from its delivery phase')
        if root.initial_delivery_pending and (root.initial_result is None or root.initial_entity_id is None):
            raise ValueError('Initial hand delivery has no reserved recipient')
        if root.reward_delivery_pending and (root.reward_result is None or root.reward_entity_id is None):
            raise ValueError('Reward hand delivery has no reserved recipient')
        if root.request.source_id not in state.entities or not 1 <= root.owner_turn_id <= len(state.owner_turn_history):
            raise ValueError('Unknown original hand source or turn interval')
        if state.owner_turn_history[root.owner_turn_id-1].turn != root.turn:
            raise ValueError('Hand offer changed its original turn interval')
        for phase in ('initial', 'reward'):
            choice = getattr(root, phase+'_choice'); result = getattr(root, phase+'_result')
            if choice is not None:
                ids = tuple(o.id for o in phase_options(root, phase))
                if tuple(o.id for o in choice.options) != ids or choice.id >= state.next_choice_id:
                    raise ValueError('Hand choice changed its original ordered options')
                if (choice.player_id, choice.source_id, choice.prompt, choice.min_count, choice.max_count, choice.purpose) != (
                        root.request.player_id, root.request.source_id, root.request.prompt, 1, 1,
                        ChoicePurpose.CARD_DISCOVERY if phase == 'initial' else ChoicePurpose.EFFECT):
                    raise ValueError('Hand choice changed its original owner or source')
                if tuple(o.card_id for o in choice.options) != tuple(o.card_id for o in phase_options(root, phase)):
                    raise ValueError('Hand choice changed its original printed options')
            if result is not None and getattr(root, phase+'_entity_id') is not None and getattr(root, phase+'_entity_id') not in state.entities:
                raise ValueError('Unknown delivered hand entity')
        if root.hand_entry_id is not None:
            if root.initial_result is None or not 1 <= root.hand_entry_id <= len(state.hand_entries):
                raise ValueError('Hand followup has no accepted physical hand entry')
            entry = state.hand_entries[root.hand_entry_id-1]
            if (entry.entity_id, entry.player_id, entry.card_id) != (
                    root.initial_entity_id, root.request.player_id, selected(root).card_id):
                raise ValueError('Hand followup changed its delivered physical card')
        if root.trigger_play_id is not None:
            if not 1 <= root.trigger_play_id <= len(state.play_history): raise ValueError('Unknown consumed hand play')
            play = state.play_history[root.trigger_play_id-1]
            if (not play.completed or (play.source_id, play.player_id, play.hand_entry_id,
                    play.played_face.owner_turn_id) != (root.initial_entity_id, root.request.player_id,
                    root.hand_entry_id, root.owner_turn_id)):
                raise ValueError('Hand followup consumption differs from its actual original play')
        if root.status in ('armed', 'lost', 'expired', 'reward_queued', 'reward_offered', 'reward_delivery', 'completed', 'exhausted') and root.hand_entry_id is None:
            raise ValueError('Hand followup phase has no delivered original recipient')
        if root.status in ('reward_queued', 'reward_offered', 'reward_delivery', 'completed', 'exhausted') and root.trigger_play_id is None:
            raise ValueError('Hand reward has no one-shot play acceptance')


def validate_boundary(game):
    state, registry = game._state, game.registry
    validate_shape(state)
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    for work in queue:
        if type(work) is FinishHandFollowupDelivery:
            if not getattr(record(state, work.followup_id), work.phase+'_delivery_pending'):
                raise ValueError('Unaccepted hand delivery finish in continuation')
        elif type(work) is RequestHandFollowupReward:
            if record(state, work.followup_id).status != 'reward_queued':
                raise ValueError('Unaccepted hand reward in continuation')
        elif type(work) is ResolveHandFollowupChoice:
            root = record(state, work.followup_id)
            if (root.status != ('offered' if work.phase == 'initial' else 'reward_offered')
                    or work.result is None or work.result.choice != getattr(root, work.phase+'_choice')
                    or work.result.selected_ids != (work.option_id,)):
                raise ValueError('Unaccepted hand choice branch in continuation')
    for root in state.hand_choice_followups:
        registry.card(root.source_card_id)
        local = Random(); local.setstate(root.rng_before)
        if type(root.request) is DiscoverFromPool:
            req = root.request
            pool = resolve_candidates(registry, game._generation_context, req.pool_id, req.query,
                current_class=root.hero_class, source_card_id=root.source_card_id, policy=req.policy, player_id=req.player_id,
                exclude_source_by_rule=True)
            if pool != root.available_pool or root.available_cards: raise ValueError('Hand offer changed its original pool basis')
            offered = sample_candidates(local, pool, req.count, replacement=False)
            expected = tuple(HandFollowupOption(f'generated-{n}', cid) for n, cid in enumerate(offered, 1))
        else:
            if root.available_pool: raise ValueError('Deck offer cannot carry a generated pool')
            for ref in root.available_cards:
                if ref.entity_id not in state.entities or ref.zone_epoch > state.entities[ref.entity_id].zone_epoch:
                    raise ValueError('Unknown original deck option residence')
            cards = sample_zone(root.request, root.available_cards, local)
            expected = tuple(HandFollowupOption(f'zone-{n}', c.card_id, c) for n, c in enumerate(cards, 1))
        if expected != root.offers or local.getstate() != root.rng_after:
            raise ValueError('Hand offer lost its original ordered random sample')
        for option in root.offers:
            if not registry.card(option.card_id).hand_playable: raise ValueError('Invalid original hand option')
        for phase in ('initial', 'reward'):
            if getattr(root, phase+'_delivery_pending'):
                markers = [x for x in queue if type(x) is FinishHandFollowupDelivery and (x.followup_id, x.phase) == (root.id, phase)]
                if len(markers) != 1: raise ValueError('Hand delivery lost its unique finish marker')
        if root.status == 'reward_queued' and sum(type(x) is RequestHandFollowupReward and x.followup_id == root.id for x in queue) != 1:
            raise ValueError('Consumed hand play lost its original owed reward')
        if root.status in ('offered', 'reward_offered'):
            phase = 'initial' if root.status == 'offered' else 'reward'
            expected_request = request_choice(root, phase, registry)
            choice = getattr(root, phase+'_choice')
            pending = state.pending_choice is not None and state.pending_choice == choice
            queued = any(type(x) is RequestChoice and x == expected_request for x in queue)
            selected_branch = any(type(x) is ResolveHandFollowupChoice and (x.followup_id, x.phase) == (root.id, phase) for x in queue)
            if not (pending or queued or selected_branch): raise ValueError('Hand offer lost its actual waiting or selected branch')
            if pending and (game._frame.options != expected_request.options or game._frame.on_select is not None):
                raise ValueError('Hand choice frame differs from its original offer')
        if root.status == 'armed':
            if root.turn != state.turn: raise ValueError('Expired hand offer remained armed')
            entity = state.entities[root.initial_entity_id]
            resident = (entity.zone, entity.controller, entity.hand_entry_id) == (
                Zone.HAND, root.request.player_id, root.hand_entry_id)
            playing = any(p.source_id == entity.id and p.hand_entry_id == root.hand_entry_id
                and not p.completed and not p.interrupted for p in state.play_history)
            if not (resident or playing): raise ValueError('Armed hand followup lost its actual original residence')


def register(mechanics):
    for cls in (HandFollowupOption, HandChoiceFollowup): mechanics.register_payload_type(cls)
    for cls, handler in ((DiscoverForPlayFollowup, start), (ResolveHandFollowupChoice, resolve),
                         (RequestHandFollowupReward, reward), (FinishHandFollowupDelivery, finish_delivery)):
        mechanics.register(cls, handler)


# Bookkeeping work adds no gameplay checkpoint of its own.
CONTROL = (RequestHandFollowupReward, FinishHandFollowupDelivery)
