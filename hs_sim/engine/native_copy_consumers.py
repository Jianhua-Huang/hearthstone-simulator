"""Finite physical-copy consumers; existing zone, transform and entry executors own writes."""
from copy import deepcopy
from dataclasses import dataclass, replace

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .errors import ResolutionError
from .model import CardType, SummonStats, Zone
from .sacrifice import MinionReference, live_minion
from .summon_quantities import SummonCause, validate_cause
from .zones import CardReference, reference_entity


def minion_cause(cause):
    if type(cause) is not SummonCause or cause.origin != 'card_effect' or cause.source.kind != CardType.MINION:
        raise ValueError('Native minion copy requires its original typed minion cause')
    cause.__post_init__()


@dataclass(frozen=True)
class TransformIntoDeckDemon(Effect):
    target: MinionReference
    cause: SummonCause

    def __post_init__(self):
        if type(self.target) is not MinionReference:
            raise ValueError('Deck Demon transform requires its original board recipient')
        self.target.__post_init__(); minion_cause(self.cause)
        a = self.cause.source
        if (a.entity_id, a.controller, a.card_id, a.zone_epoch, a.entered_order, a.zone) != (
                self.target.entity_id, self.target.player_id, self.target.card_id,
                self.target.zone_epoch, self.target.entered_order, Zone.BOARD) or self.cause.player_id != a.controller:
            raise ValueError('Deck Demon transform changed its original self/actor')

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_cause(state, registry, self.cause)


def transform_deck_demon(r, effect):
    from .pools import PoolQuery
    from .tribes import has_any_tribe
    from .zones import zone_candidates
    from .resolver import transform_minion
    effect.validate_in_state(r.state, r.registry)
    target = live_minion(r.state, effect.target)
    if target is None: return ()
    candidates = tuple(ref for ref in zone_candidates(r, effect.cause.player_id, Zone.DECK,
        PoolQuery(kinds=(CardType.MINION,)), effect.cause.player_id, effect.target.entity_id)
        if has_any_tribe(r.registry, r.state.entities[ref.entity_id], ('DEMON',)))
    if not candidates: return ()
    # Selection and material capture share this handler, before the first notification.
    source = deepcopy(r.state.entities[r.game._rng.choice(candidates).entity_id])
    return transform_minion(r, target, r.registry.card(source.card_id), source_id=effect.target.entity_id,
        copy_material=source, stats=SummonStats(6, 6))


@dataclass(frozen=True)
class CopyMinionToThreeZones(Effect):
    target: MinionReference
    cause: SummonCause

    def __post_init__(self):
        if type(self.target) is not MinionReference:
            raise ValueError('Three-zone copy requires its original friendly minion')
        self.target.__post_init__(); minion_cause(self.cause)
        if self.target.player_id != self.cause.player_id:
            raise ValueError('Three-zone copy requires its original friendly recipient')

    def validate_in_state(self, state, registry):
        self.__post_init__(); validate_cause(state, registry, self.cause)


def copy_three_zones(r, effect):
    from .copy_materials import CapturedCardCopyMaterial, CopyEntryMaterial
    from .zones import CopyCard
    from .summon_quantities import SummonByCard
    effect.validate_in_state(r.state, r.registry)
    target = live_minion(r.state, effect.target)
    if target is None: return ()
    stored = CapturedCardCopyMaterial.capture(r.state, target)
    # This existing remembered recipe is deliberately valid after earlier copy notifications.
    board = CopyEntryMaterial.capture(r.state, target, 'remembered_copy', 'current',
        registry=r.registry, player_id=effect.cause.player_id)
    player, source = effect.cause.player_id, effect.cause.source.entity_id
    return (CopyCard(stored, player, Zone.HAND, source_id=source),
        CopyCard(stored, player, Zone.DECK, source_id=source),
        SummonByCard(player, (board,), effect.cause))


@dataclass(frozen=True)
class TransformHeldPlayedMinion(Effect):
    target: CardReference
    source_ability_id: int
    play_id: int

    def __post_init__(self):
        if type(self.target) is not CardReference or self.target.zone != Zone.HAND:
            raise ValueError('Held play mimic requires its original hand residence')
        self.target.__post_init__()
        _integer(self.source_ability_id, 'original held mimic ability', 1)
        _integer(self.play_id, 'original mimicked play', 1)

    def validate_in_state(self, state, registry):
        from .play_history import play_record
        self.__post_init__(); row = play_record(state, self.play_id)
        if (row.player_id != self.target.player_id or row.kind != CardType.MINION or
                not row.completed or row.countered or row.interrupted):
            raise ValueError('Held mimic requires an actual successful own minion play')
        from .model import HandProgressCandidate
        candidate = HandProgressCandidate(self.target.entity_id, self.source_ability_id, self.target.player_id)
        if candidate not in row.native_hand_candidates:
            raise ValueError('Held mimic was absent from the original submitted hand')
        return row


def held_binding(registry, target, effect):
    native = next((a for a in target.abilities if a.kind == 'defining_hand_source' and
        a.id == effect.source_ability_id and a.hand_progress.event == 'card_played'), None)
    if native is None: raise ResolutionError('Held mimic lost its original native source')
    registry.validate_defining_hand_binding(target, native)
    if not native.progress_keys: raise ResolutionError('Held mimic lost its actual accepted play witness')
    return native


def transform_held_play(r, effect):
    from .cross_zone import reset_stored_entity, announce_stored_transform
    from .jade import inherit_printed
    from .lifecycle import apply_summon_stats, refresh_entity
    from .costs import attach_cost
    from .model import CostSpec
    effect.validate_in_state(r.state, r.registry)
    target = reference_entity(r, effect.target)
    if target is None: return ()
    native = held_binding(r.registry, target, effect)
    event = r.game._events[int(native.progress_keys[-1].split(':')[1])-1]
    if event.kind != 'card_played' or dict(event.data).get('play_id') != effect.play_id:
        raise ResolutionError('Held mimic borrowed another accepted original play witness')
    row = effect.validate_in_state(r.state, r.registry)
    material = row.minion_copy_material
    definition = r.registry.card(material.source.card_id)
    original = r.registry.card(native.defining_card_id)
    old_card = target.card_id
    reset_stored_entity(r, target, definition, components=material.components)
    inherit_printed(material.entity(), target, state=r.state,
        permanent_stats=material.permanent_stats, infused_damage=material.infused_damage)
    target.abilities = [a for a in target.abilities if a.kind != 'defining_hand_source']
    target.abilities.append(native)
    apply_summon_stats(r.state, target, SummonStats(original.attack, original.health), source_id=target.id)
    attach_cost(r.state, target, CostSpec(set_to=original.cost), target.id)
    refresh_entity(target)
    announce_stored_transform(r, target, old_card, source_id=target.id)
    return ()


@dataclass(frozen=True)
class DeathrattleDeckPartner:
    invocation_id: int
    source: SourceAllocationFact
    deck_ids: tuple[int, ...]

    def __post_init__(self):
        _integer(self.invocation_id, 'original physical-swap Deathrattle', 1)
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Deck swap requires its actual outgoing physical source')
        self.source.__post_init__()
        if self.source.kind != CardType.MINION or self.source.zone not in (Zone.BOARD, Zone.GRAVEYARD, Zone.HAND, Zone.DECK):
            raise ValueError('Deck swap requires its original minion residence')
        if type(self.deck_ids) is not tuple or len(set(self.deck_ids)) != len(self.deck_ids):
            raise ValueError('Deck swap requires its complete ordered physical deck')
        for entity_id in self.deck_ids:
            _integer(entity_id, 'original deck swap inventory', 1)
            if entity_id >= self.source.next_entity_id:
                raise ValueError('Deck swap inventory contains a future physical allocation')


def validate_deck_partner(state, registry, partner):
    from .deathrattles import record
    partner.__post_init__(); validate_allocation(state, registry, partner.source)
    row = record(state, partner.invocation_id)
    if row.execution_order is None or row.interrupted or row.capture.carrier_id != partner.source.entity_id:
        raise ValueError('Deck swap borrowed another actually executed Deathrattle')
    if any(i not in state.entities for i in partner.deck_ids):
        raise ValueError('Deck swap lost its complete original physical deck')
    return row


def validate_deck_recipe(state, registry, request, material):
    partner = material.deck_swap
    if partner is None: return
    row = validate_deck_partner(state, registry, partner)
    if (request.player_id != row.capture.player_id or request.cause.player_id != row.capture.player_id or
            request.cause.source.entity_id != partner.source.entity_id or
            material.reference.player_id != request.player_id or material.reference.zone != Zone.DECK or
            material.reference.entity_id not in partner.deck_ids or request.producer_link is not None):
        raise ValueError('Deck swap changed its original actor, deck or physical partner')


def deck_partner_from_dict(value):
    if value is None: return None
    from .serialization import _row, _list
    row = _row(value, DeathrattleDeckPartner)
    row['source'] = allocation_from_dict(row['source'])
    row['deck_ids'] = tuple(_list(row['deck_ids'], 'original deck swap inventory'))
    return DeathrattleDeckPartner(**row)


def reserved_deck_slot(state, material, player_id):
    partner = material.deck_swap
    if partner is None: return False
    source = state.entities.get(partner.source.entity_id)
    return source is not None and (source.zone, source.controller, source.zone_epoch) == (
        Zone.BOARD, player_id, partner.source.zone_epoch) and source.id in state.players[player_id].board


def move_deck_pair(r, material, entity, player_id, position):
    """Ordinary writers commit both originals before the first entry notification."""
    partner = material.deck_swap
    validate_deck_partner(r.state, r.registry, partner)
    source = r.state.entities[partner.source.entity_id]
    a = partner.source
    if (source.card_id, source.controller, source.zone, source.zone_epoch) != (
            a.card_id, a.controller, a.zone, a.zone_epoch):
        raise ResolutionError('Accepted deck swap lost its original outgoing residence')
    if source.zone == Zone.DECK and source.controller == player_id:
        # A repeated actual Deathrattle never allocates a second outgoing copy.
        r.move(entity, Zone.BOARD, position)
        return
    slot = partner.deck_ids.index(entity.id)
    if source.zone == Zone.BOARD and source.controller == player_id:
        # Unpublished staging frees the original board slot. The incoming deck
        # move then frees a deck slot even at capacity 99. No false death occurs.
        r.move(source, Zone.SETASIDE)
    r.move(entity, Zone.BOARD, position)
    if source.controller != player_id and source.zone not in (Zone.BOARD, Zone.GRAVEYARD):
        raise ResolutionError('Cross-controller stored outgoing deck swap awaits a supported transfer policy')
    r.move(source, Zone.DECK, slot, **({'controller_id':player_id} if source.controller != player_id else {}))
    from .lifecycle import reset_to_definition
    reset_to_definition(r.state, source, r.registry.card(source.card_id), r.registry, preserve_jade=True)


@dataclass(frozen=True)
class SwapDeathrattleWithDeck(Effect):
    invocation_id: int
    cause: SummonCause

    def __post_init__(self):
        _integer(self.invocation_id, 'original physical-swap invocation', 1); minion_cause(self.cause)

    def validate_in_state(self, state, registry):
        from .deathrattles import record
        self.__post_init__(); validate_cause(state, registry, self.cause)
        row = record(state, self.invocation_id)
        if (row.execution_order is None or row.completed or row.interrupted or
                (row.capture.carrier_id, row.capture.player_id) != (self.cause.source.entity_id, self.cause.player_id)):
            raise ValueError('Deck swap requires its actually running original Deathrattle')
        return row


def swap_deathrattle_deck(r, effect):
    from .zones import zone_candidates
    from .pools import PoolQuery
    from .colossal import SummonStoredCard, summon_stored
    row = effect.validate_in_state(r.state, r.registry)
    source = r.state.entities[effect.cause.source.entity_id]
    player = r.player(effect.cause.player_id)
    own_board = source.zone == Zone.BOARD and source.controller == player.id
    if len(player.board)-int(own_board) >= r.rules.max_board: return ()
    candidates = zone_candidates(r, player.id, Zone.DECK, PoolQuery(kinds=(CardType.MINION,)), player.id, source.id)
    if not candidates: return ()
    partner = DeathrattleDeckPartner(effect.invocation_id, SourceAllocationFact.capture(r.state, source), tuple(player.deck))
    selected = r.game._rng.choice(candidates)
    position = player.board.index(source.id) if own_board else None
    if position is None and row.capture.death_id is not None:
        position = next(d.position for d in r.state.death_history if d.id == row.capture.death_id)
    return summon_stored(r, SummonStoredCard(selected, player.id, position=position,
        cause=effect.cause, deck_swap=partner))


def register(mechanics):
    mechanics.register_payload_type(DeathrattleDeckPartner)
    for typ, handler in ((TransformIntoDeckDemon, transform_deck_demon),
            (CopyMinionToThreeZones, copy_three_zones), (TransformHeldPlayedMinion, transform_held_play),
            (SwapDeathrattleWithDeck, swap_deathrattle_deck)):
        mechanics.register(typ, handler)
