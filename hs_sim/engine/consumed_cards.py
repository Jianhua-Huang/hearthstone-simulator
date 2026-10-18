"""Real hand absorption/deck consumption and source-bound granted Deathrattles.

Original material is retained for attribution and future calibration. Current
native output policy generates base cards; consumption is neither discard nor
death. Every granted payload refers to one immutable physical removal.
"""
from dataclasses import dataclass
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .copy_materials import CapturedCardCopyMaterial, from_dict as copy_from_dict, validate_captured_card_copy
from .effects import Buff, Effect, GrantDeathrattle, _behavior, _integer, _player
from .model import CardType, Zone, validate_end_turn_rng
from .sacrifice import MinionReference, reference_value, same_instance
from .zones import CardReference, CopyCard

EVENT = 'native_card_consumed'


@dataclass(frozen=True)
class ConsumptionProfile:
    card_id: str
    kind: str

    def __post_init__(self):
        _behavior(self.card_id)
        if self.kind not in ('hand_spell', 'deck_minion', 'opponent_hand'):
            raise ValueError('Unknown native consumption profile')


def validate_profile(registry, profile):
    if type(profile) is not ConsumptionProfile:
        raise ValueError('Native consumption requires a registered finite profile')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if card.kind != CardType.MINION or card.deathrattle is None:
        raise ValueError('Native consumption requires its printed minion Deathrattle')
    registry.behavior(card.deathrattle)


@dataclass(frozen=True)
class ConsumedCardRecord:
    id: int
    profile_id: str
    source: SourceAllocationFact
    card: CapturedCardCopyMaterial
    after_epoch: int
    ability_id: int
    turn: int
    action: int
    event_sequence: int
    attack_gain: int = 0
    health_gain: int = 0
    candidates: tuple[CardReference, ...] = ()
    rng_before: tuple | None = None
    rng_after: tuple | None = None

    def __post_init__(self):
        for name in ('id', 'ability_id', 'turn', 'event_sequence'):
            _integer(getattr(self, name), 'native consumption ' + name, 1)
        for name in ('after_epoch', 'action', 'attack_gain', 'health_gain'):
            _integer(getattr(self, name), 'native consumption ' + name, 0)
        _behavior(self.profile_id)
        if type(self.source) is not SourceAllocationFact or type(self.card) is not CapturedCardCopyMaterial:
            raise ValueError('Consumption requires complete source and original card material')
        self.source.__post_init__()
        self.card.__post_init__()
        origin = self.card.origin
        if (self.source.kind != CardType.MINION or self.source.zone != Zone.BOARD
                or origin.zone not in (Zone.HAND, Zone.DECK) or origin.entity_id == self.source.entity_id
                or self.after_epoch != origin.zone_epoch + 1):
            raise ValueError('Consumption changed its original physical source or removal')
        if type(self.candidates) is not tuple or any(type(ref) is not CardReference for ref in self.candidates):
            raise ValueError('Consumption candidates require their complete frozen references')
        for ref in self.candidates:
            ref.__post_init__()
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError('Consumption duplicated a physical candidate')


def record(state, identity):
    _integer(identity, 'consumed card identity', 1)
    if identity > len(state.consumed_card_history):
        raise ValueError('Native payload lost its original consumed card')
    result = state.consumed_card_history[identity - 1]
    if type(result) is not ConsumedCardRecord or result.id != identity:
        raise ValueError('Consumption history changed its original order')
    return result


def validate_payload(state, registry, ability):
    if ability.consumed_card_id is None:
        return
    row = record(state, ability.consumed_card_id)
    profile = registry.consumption_profiles[row.profile_id]
    if (ability.kind != 'deathrattle' or ability.origin != 'granted'
            or ability.id < row.ability_id or ability.deathrattle_card_id != profile.card_id
            or ability.behavior_id != registry.card(profile.card_id).deathrattle):
        raise ValueError('Consumed payload differs from its original granted Deathrattle')


def validate_record(state, registry, row):
    row.__post_init__()
    profile = registry.consumption_profiles[row.profile_id]
    validate_profile(registry, profile)
    validate_allocation(state, registry, row.source)
    validate_captured_card_copy(state, registry, row.card)
    origin = row.card.origin
    if (row.turn > state.turn or row.action > state.action_number or row.ability_id >= state.next_attachment_id
            or state.entities[origin.entity_id].zone_epoch < row.after_epoch):
        raise ValueError('Consumption has a future source, attachment or removal')
    expected_zone = Zone.DECK if profile.kind == 'deck_minion' else Zone.HAND
    expected_kind = {'hand_spell': CardType.SPELL, 'deck_minion': CardType.MINION}.get(profile.kind)
    expected_player = 3-row.source.controller if profile.kind == 'opponent_hand' else row.source.controller
    if (origin.zone != expected_zone or origin.controller != expected_player
            or expected_kind is not None and origin.kind != expected_kind):
        raise ValueError('Consumption does not match its declared original card kind')
    for ability in row.card.local.abilities:
        if ability.consumed_card_id is not None:
            if ability.consumed_card_id >= row.id:
                raise ValueError('Consumed material cannot refer to its own or future payload')
            validate_payload(state, registry, ability)
    if profile.kind == 'hand_spell':
        if row.candidates or row.rng_before is not None or row.rng_after is not None or row.attack_gain or row.health_gain:
            raise ValueError('Targeted absorption cannot invent a random draw or minion stats')
    else:
        validate_end_turn_rng(row.rng_before)
        validate_end_turn_rng(row.rng_after)
        if not row.candidates:
            raise ValueError('Random consumption requires its original nonempty candidates')
        for ref in row.candidates:
            if (ref.zone != expected_zone or ref.player_id != expected_player
                    or expected_kind is not None and registry.card(ref.card_id).kind != expected_kind
                    or ref.entity_id not in state.entities or ref.zone_epoch > state.entities[ref.entity_id].zone_epoch):
                raise ValueError('Random consumption has an unknown or invalid original candidate')
        if profile.kind == 'opponent_hand' and (row.attack_gain or row.health_gain):
            raise ValueError('Opponent hand consumption cannot invent stat gains')
        rng = Random()
        rng.setstate(row.rng_before)
        selected = rng.choice(row.candidates)
        if (selected.entity_id, selected.card_id, selected.zone_epoch) != (
                origin.entity_id, origin.card_id, origin.zone_epoch) or rng.getstate() != row.rng_after:
            raise ValueError('Consumption differs from its original random selection')


def validate_state(state, registry):
    if type(state.consumed_card_history) is not list:
        raise ValueError('Consumption history requires an ordered list')
    seen = set()
    previous = (0, 0, 0)
    for index, row in enumerate(state.consumed_card_history, 1):
        if type(row) is not ConsumedCardRecord or row.id != index:
            raise ValueError('Consumption history lost its complete ordinal inventory')
        validate_record(state, registry, row)
        key = row.card.origin.entity_id, row.card.origin.zone_epoch
        chronology = row.turn, row.action, row.event_sequence
        if key in seen or chronology < previous:
            raise ValueError('Consumption duplicated or reordered an original physical removal')
        seen.add(key)
        previous = chronology


@dataclass(frozen=True)
class ConsumeHandSpell(Effect):
    source: MinionReference
    card: CardReference
    profile_id: str

    def __post_init__(self):
        reference_value(self.source)
        if type(self.card) is not CardReference or self.card.zone != Zone.HAND:
            raise ValueError('Absorption requires its original hand card')
        self.card.__post_init__()
        _behavior(self.profile_id)


@dataclass(frozen=True)
class ConsumeDeckMinion(Effect):
    source: MinionReference
    profile_id: str

    def __post_init__(self):
        reference_value(self.source)
        _behavior(self.profile_id)


@dataclass(frozen=True)
class ResolveConsumedDeathrattle(Effect):
    deathrattle_id: int

    def __post_init__(self):
        _integer(self.deathrattle_id, 'consumed payload invocation', 1)


@dataclass(frozen=True)
class ConsumeOpponentHand(Effect):
    """The actual two-card native Battlecry, followed by ordinary dormancy."""
    source: MinionReference
    profile_id: str

    def __post_init__(self):
        reference_value(self.source)
        _behavior(self.profile_id)


def consume(r, effect):
    effect.__post_init__()
    profile = r.registry.consumption_profiles[effect.profile_id]
    validate_profile(r.registry, profile)
    source = same_instance(r.state, effect.source)
    if source is None or not source.active or source.health <= 0 or source.doomed:
        return ()
    candidates, before, after = (), None, None
    if type(effect) is ConsumeHandSpell:
        if profile.kind != 'hand_spell':
            raise ValueError('Hand absorption borrowed another native profile')
        from .zones import reference_entity
        target = reference_entity(r, effect.card)
        if target is None:
            return ()
        if target.kind != CardType.SPELL or target.controller != source.controller:
            raise ValueError('Absorption requires a friendly physical spell')
    else:
        if profile.kind != 'deck_minion':
            raise ValueError('Deck consumption borrowed another native profile')
        candidates = tuple(CardReference.capture(r.state.entities[i]) for i in r.player(source.controller).deck
                           if r.registry.card(r.state.entities[i].card_id).kind == CardType.MINION)
        if not candidates:
            return ()
        before = r.game._rng.getstate()
        selected = r.game._rng.choice(candidates)
        after = r.game._rng.getstate()
        target = r.state.entities[selected.entity_id]
    _capture_consumption(r, source, profile, target, candidates, before, after)
    return ()


def _capture_consumption(r, source, profile, target, candidates=(), before=None, after=None):
    material = CapturedCardCopyMaterial.capture(r.state, target)
    source_fact = SourceAllocationFact.capture(r.state, source)
    attack, health = (target.attack, target.max_health) if profile.kind == 'deck_minion' else (0, 0)
    # The existing private storage move retires hand identity and live handles.
    from .temporary_hands import hide
    hide(r, target)
    row = ConsumedCardRecord(len(r.state.consumed_card_history) + 1, profile.card_id,
        source_fact, material, target.zone_epoch, r.state.next_attachment_id,
        r.state.turn, r.state.action_number, len(r.game._events) + 1,
        attack, health, candidates, before, after)
    r.state.consumed_card_history.append(row)
    from .resolver import _grant_to, buff
    _grant_to(r, GrantDeathrattle(source.id, r.registry.card(profile.card_id).deathrattle, source.id),
              source, notify=False, grant_card_id=profile.card_id, consumed_card_id=row.id)
    r.emit(EVENT, source_id=source.id, target_id=target.id, player_id=source.controller,
           _capture=False, consumed_id=row.id)
    if attack or health:
        buff(r, Buff(source.id, attack=attack, health=health, source_id=source.id))
    r.emit('ability_granted', target_id=source.id, source_id=source.id,
           ability_id=row.ability_id, ability_kind='deathrattle')
    return row


def consume_opponent_hand(r, effect):
    effect.__post_init__()
    profile = r.registry.consumption_profiles[effect.profile_id]
    validate_profile(r.registry, profile)
    if profile.kind != 'opponent_hand':
        raise ValueError('Opponent hand consumption borrowed another native profile')
    source = same_instance(r.state, effect.source)
    if source is None or source.health <= 0 or source.doomed:
        return ()
    # An already accepted Battlecry may finish while its source is dormant.
    # Each actual invocation keeps its own current hand pool and payloads.
    for _ in range(2):
        candidates = tuple(CardReference.capture(r.state.entities[i])
                           for i in r.player(3-source.controller).hand)
        if not candidates:
            break
        before = r.game._rng.getstate()
        selected = r.game._rng.choice(candidates)
        after = r.game._rng.getstate()
        _capture_consumption(r, source, profile, r.state.entities[selected.entity_id], candidates, before, after)
    from .dormancy import MakeDormant, make_dormant
    make_dormant(r, MakeDormant(source.id, 2, source.id))
    return ()


def resolve(r, effect):
    effect.__post_init__()
    from .deathrattles import record as activation_record
    activation = activation_record(r.state, effect.deathrattle_id)
    if activation.execution_order is None or activation.completed or activation.interrupted:
        raise ValueError('Consumed payload requires its actual running Deathrattle')
    capture = activation.capture
    if capture.ability.consumed_card_id is None:
        return ()
    validate_payload(r.state, r.registry, capture.ability)
    row = record(r.state, capture.ability.consumed_card_id)
    profile = r.registry.consumption_profiles[row.profile_id]
    if profile.kind == 'hand_spell':
        from .spell_casts import CastSpell
        return (CastSpell(capture.player_id, row.card.origin.card_id, capture.carrier_id),)
    if profile.kind == 'opponent_hand':
        return (CopyCard(row.card, row.card.origin.controller, mode='current', source_id=capture.carrier_id),)
    return (CopyCard(row.card, capture.player_id, mode='base', source_id=capture.carrier_id),)


def validate_boundary(game):
    from .hero_health_history import effective_events
    events = tuple(e for e in effective_events(game._events) if e.kind == EVENT)
    rows = game._state.consumed_card_history
    if len(events) != len(rows):
        raise ValueError('Consumption lost its complete actual event inventory')
    for event, row in zip(events, rows):
        if (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount, dict(event.data)) != (
                row.event_sequence, row.action, row.source.entity_id, row.card.origin.entity_id,
                row.source.controller, 0, {'consumed_id': row.id}):
            raise ValueError('Consumption differs from its original physical publication')


def rows_from_dict(value):
    from .serialization import _row, _list, rng_from_json
    from .copy_materials import CopyLocalState
    from .model import HandPreparation
    result = []
    for raw in _list(value['consumed_card_history'], 'native physical consumption history'):
        row = _row(raw, ConsumedCardRecord)
        row['source'] = allocation_from_dict(row['source'])
        material = _row(row['card'], CapturedCardCopyMaterial)
        material['origin'] = allocation_from_dict(material['origin'])
        material['local'] = copy_from_dict(CopyLocalState, material['local'])
        material['components'] = tuple(_list(material['components'], 'consumed original components'))
        if material['preparation'] is not None:
            material['preparation'] = HandPreparation(**_row(material['preparation'], HandPreparation))
        row['card'] = CapturedCardCopyMaterial(**material)
        row['candidates'] = tuple(CardReference(**dict(x, zone=Zone(x['zone']))) for x in row['candidates'])
        for name in ('rng_before', 'rng_after'):
            if row[name] is not None:
                row[name] = rng_from_json(row[name])
        result.append(ConsumedCardRecord(**row))
    value['consumed_card_history'] = result


def register(mechanics):
    mechanics.register(ConsumeHandSpell, consume)
    mechanics.register(ConsumeDeckMinion, consume)
    mechanics.register(ResolveConsumedDeathrattle, resolve)
    mechanics.register(ConsumeOpponentHand, consume_opponent_hand)
