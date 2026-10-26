"""Real hand absorption/deck consumption and source-bound granted Deathrattles.

Original material is retained for attribution and future calibration. Current
native output policy generates base cards; consumption is neither discard nor
death. Every granted payload refers to one immutable physical removal.
"""
from dataclasses import dataclass, replace
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .copy_materials import CapturedCardCopyMaterial, from_dict as copy_from_dict, validate_captured_card_copy
from .effects import Buff, Effect, GrantDeathrattle, GrantKeyword, _behavior, _integer, _player
from .model import CardType, DeathCause, Keyword, Zone, validate_end_turn_rng
from .sacrifice import MinionReference, reference_value, same_instance
from .zones import CardReference, CopyCard

EVENT = 'native_card_consumed'
RETURN_EVENT = 'consumed_weapon_return_claimed'


@dataclass(frozen=True)
class ConsumptionProfile:
    card_id: str
    kind: str

    def __post_init__(self):
        _behavior(self.card_id)
        if self.kind not in ('hand_spell', 'deck_minion', 'opponent_hand', 'fabled_weapon', 'equipped_weapon', 'board_minions'):
            raise ValueError('Unknown native consumption profile')


def validate_profile(registry, profile):
    if type(profile) is not ConsumptionProfile:
        raise ValueError('Native consumption requires a registered finite profile')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if card.kind != CardType.MINION or card.deathrattle is None:
        raise ValueError('Native consumption requires its printed minion Deathrattle')
    registry.behavior(card.deathrattle)
    if profile.kind == 'fabled_weapon':
        fabled_weapon_id(registry, profile)
    if profile.kind == 'board_minions':
        if len(card.colossal) != 1 or card.battlecry is None:
            raise ValueError('Devoured minions require their original single-Maw Colossal Battlecry')
        maw = registry.card(card.colossal[0].card_id)
        if maw.kind != CardType.MINION or maw.deathrattle is None or maw.metadata is None or maw.metadata.collectible is not False:
            raise ValueError('Devoured minions require their original noncollectible Maw')


def fabled_weapon_id(registry, profile):
    """One actual named companion, never an arbitrary minion equipment slot."""
    family = registry.fabled.get(profile.card_id)
    weapons = () if family is None else tuple(cid for cid in family.companion_card_ids
                                              if registry.card(cid).kind == CardType.WEAPON)
    if len(weapons) != 1:
        raise ValueError('Named weapon consumption requires exactly one Fabled weapon companion')
    return weapons[0]


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
    destruction: DeathCause | None = None

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
                or origin.zone not in (Zone.HAND, Zone.DECK, Zone.WEAPON, Zone.BOARD) or origin.entity_id == self.source.entity_id
                or origin.zone == Zone.WEAPON and origin.kind != CardType.WEAPON
                or self.after_epoch != origin.zone_epoch + 1):
            raise ValueError('Consumption changed its original physical source or removal')
        if self.destruction is not None:
            if type(self.destruction) is not DeathCause or origin.zone != Zone.BOARD or origin.kind != CardType.MINION:
                raise ValueError('Devoured minions require their original board destruction material')
            self.destruction.__post_init__()
        elif origin.zone == Zone.BOARD:
            raise ValueError('Board consumption cannot substitute a silent storage removal')
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
    if ability.devour_parent is not None:
        from .devoured_minions import validate_maw_link
        validate_maw_link(state, registry, ability)
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
    pending_devour = (profile.kind == 'board_minions' and state.entities[origin.entity_id].zone == Zone.BOARD
        and state.entities[origin.entity_id].doomed and state.entities[origin.entity_id].death_cause == row.destruction)
    if (row.turn > state.turn or row.action > state.action_number or row.ability_id >= state.next_attachment_id
            or state.entities[origin.entity_id].zone_epoch < row.after_epoch and not pending_devour):
        raise ValueError('Consumption has a future source, attachment or removal')
    expected_zone = (Zone.BOARD if profile.kind == 'board_minions' else Zone.WEAPON if profile.kind == 'equipped_weapon' else origin.zone if profile.kind == 'fabled_weapon' else
                     Zone.DECK if profile.kind == 'deck_minion' else Zone.HAND)
    expected_kind = {'hand_spell': CardType.SPELL, 'deck_minion': CardType.MINION,
                     'equipped_weapon':CardType.WEAPON, 'board_minions':CardType.MINION}.get(profile.kind)
    expected_player = 3-row.source.controller if profile.kind in ('opponent_hand', 'board_minions') else row.source.controller
    if (origin.zone != expected_zone or origin.controller != expected_player
            or expected_kind is not None and origin.kind != expected_kind):
        raise ValueError('Consumption does not match its declared original card kind')
    if profile.kind == 'board_minions':
        from .devoured_minions import validate_destruction
        validate_destruction(state, registry, row)
    elif row.destruction is not None:
        raise ValueError('Stored consumption cannot borrow board destruction material')
    for ability in row.card.local.abilities:
        if ability.consumed_card_id is not None:
            if ability.consumed_card_id >= row.id:
                raise ValueError('Consumed material cannot refer to its own or future payload')
            validate_payload(state, registry, ability)
    if profile.kind in ('fabled_weapon','equipped_weapon'):
        if (origin.kind != CardType.WEAPON or profile.kind=='fabled_weapon' and origin.card_id != fabled_weapon_id(registry, profile)
                or row.candidates or row.rng_before is not None or row.rng_after is not None
                or row.health_gain != row.card.durability):
            raise ValueError('Fabled weapon material changed its named companion, durability or deterministic removal')
    elif profile.kind in ('hand_spell', 'board_minions'):
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


@dataclass(frozen=True)
class ConsumeFabledWeapon(Effect):
    """Take the original named weapon from own equipped/hand/deck inventory."""
    source: MinionReference
    profile_id: str

    def __post_init__(self):
        reference_value(self.source)
        _behavior(self.profile_id)


@dataclass(frozen=True)
class ConsumeEquippedWeapon(Effect):
    source: MinionReference
    profile_id: str

    def __post_init__(self):
        reference_value(self.source);_behavior(self.profile_id)


def consume_equipped_weapon(r,effect):
    effect.__post_init__();profile=r.registry.consumption_profiles[effect.profile_id]
    validate_profile(r.registry,profile)
    if profile.kind!='equipped_weapon':
        raise ValueError('Current equipped weapon consumption borrowed another native profile')
    source=same_instance(r.state,effect.source)
    if source is None or not source.active or source.health<=0 or source.doomed:return ()
    identity=r.player(source.controller).weapon_id
    target=r.state.entities.get(identity)
    if target is not None and target.active and target.durability>0 and not target.doomed:
        _capture_consumption(r,source,profile,target)
    return ()


def consume_fabled_weapon(r, effect):
    effect.__post_init__()
    profile = r.registry.consumption_profiles[effect.profile_id]
    validate_profile(r.registry, profile)
    if profile.kind != 'fabled_weapon':
        raise ValueError('Named weapon consumption borrowed another native profile')
    source = same_instance(r.state, effect.source)
    if source is None or not source.active or source.health <= 0 or source.doomed:
        return ()
    player = r.player(source.controller)
    cid = fabled_weapon_id(r.registry, profile)
    # Explicit local priority pending CN calibration. Never draw, destroy or
    # search another player's inventory, even when the named weapon is absent.
    ids = (() if player.weapon_id is None else (player.weapon_id,)) + tuple(player.hand) + tuple(player.deck)
    for eid in ids:
        target = r.state.entities[eid]
        if (target.card_id == cid and target.kind == CardType.WEAPON
                and target.controller == source.controller and not target.doomed
                and (target.zone != Zone.WEAPON or target.durability > 0)):
            _capture_consumption(r, source, profile, target)
            break
    return ()


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
    attack, health = ((target.attack, target.durability) if profile.kind in ('fabled_weapon','equipped_weapon') else
                      (target.attack, target.max_health) if profile.kind == 'deck_minion' else (0, 0))
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
    if profile.kind == 'fabled_weapon':
        from .resolver import _buff_to
        enchantment = _buff_to(r, Buff(source.id, attack, health, source.id), source, notify=False)
        source.enchantments[-1] = replace(enchantment, remove_on_silence=False, label='held_fabled_weapon')
        _grant_to(r, GrantKeyword(source.id, Keyword.WINDFURY, source.id), source, notify=False)
        keyword = source.abilities[-1]
        source.abilities[-1] = replace(keyword, remove_on_silence=False)
        r.refresh_auras()
        # All removal, payload and stat/keyword material precedes public reactions.
        r.emit('stats_changed', source_id=source.id, target_id=source.id,
               enchantment_id=enchantment.id, attack_delta=attack, health_delta=health)
        r.emit('ability_granted', target_id=source.id, source_id=source.id,
               ability_id=keyword.id, ability_kind='keyword')
    elif attack or health:
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
    if profile.kind == 'board_minions':
        raise ValueError('Devoured minions require their original attributed resurrection request')
    if profile.kind=='equipped_weapon':
        first=first_weapon_activation(r.state,capture)
        if (capture.group_id,capture.trigger_index)!=(first.group_id,first.trigger_index):return ()
        if capture.id==first.id:
            carrier=r.state.entities[capture.carrier_id]
            carrier.abilities=[replace(a,consumed=True)if a.id==capture.ability.id else a for a in carrier.abilities]
            r.emit(RETURN_EVENT,source_id=capture.carrier_id,target_id=row.card.origin.entity_id,
                player_id=capture.player_id,consumed_id=row.id,deathrattle_id=capture.id,
                group_id=capture.group_id,trigger_index=capture.trigger_index,ability_id=capture.ability.id)
        from .equipment import EquipWeaponCopy
        return (EquipWeaponCopy(capture.player_id,row.card,capture.carrier_id),)
    if profile.kind == 'hand_spell':
        from .spell_casts import CastSpell
        return (CastSpell(capture.player_id, row.card.origin.card_id, capture.carrier_id),)
    if profile.kind == 'opponent_hand':
        return (CopyCard(row.card, row.card.origin.controller, mode='current', source_id=capture.carrier_id),)
    if profile.kind == 'fabled_weapon':
        return (CopyCard(row.card, capture.player_id, mode='current', source_id=capture.carrier_id),)
    return (CopyCard(row.card, capture.player_id, mode='base', source_id=capture.carrier_id),)


def first_weapon_activation(state,capture):
    candidates=[row for row in state.deathrattle_history if row.execution_order is not None and
        (row.capture.carrier_id,row.capture.ability.id,row.capture.ability.consumed_card_id)==
        (capture.carrier_id,capture.ability.id,capture.ability.consumed_card_id)]
    if not candidates:raise ValueError('Weapon return lost its actual first invocation')
    return min(candidates,key=lambda row:row.execution_order).capture


def validate_boundary(game):
    from .hero_health_history import effective_events
    effective=tuple(effective_events(game._events))
    events = tuple(e for e in effective if e.kind == EVENT)
    rows = game._state.consumed_card_history
    if len(events) != len(rows):
        raise ValueError('Consumption lost its complete actual event inventory')
    for event, row in zip(events, rows):
        if (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount, dict(event.data)) != (
                row.event_sequence, row.action, row.source.entity_id, row.card.origin.entity_id,
                row.source.controller, 0, {'consumed_id': row.id}):
            raise ValueError('Consumption differs from its original physical publication')
    validate_weapon_returns(game,effective)


def validate_weapon_returns(game,events):
    state=game._state;registry=game.registry;claims={}
    identities={row.id for row in state.consumed_card_history
        if registry.consumption_profiles[row.profile_id].kind=='equipped_weapon'}
    if not identities:return
    firsts={}
    for row in state.deathrattle_history:
        c=row.capture;identity=c.ability.consumed_card_id
        if identity not in identities or row.execution_order is None:continue
        key=(c.carrier_id,c.ability.id,identity)
        if key not in firsts or row.execution_order<firsts[key].execution_order:firsts[key]=row
    for event in events:
        if event.kind!=RETURN_EVENT:continue
        data=dict(event.data)
        if set(data)!={'consumed_id','deathrattle_id','group_id','trigger_index','ability_id'}:
            raise ValueError('Weapon return changed its complete first-activation receipt')
        from .deathrattles import record as activation_record
        capture=activation_record(state,data['deathrattle_id']).capture
        row=record(state,data['consumed_id']);key=(capture.carrier_id,capture.ability.id,row.id)
        if key not in firsts:raise ValueError('Weapon return has no actual first execution')
        first=firsts[key].capture
        if (key in claims or registry.consumption_profiles[row.profile_id].kind!='equipped_weapon' or
                capture.id!=first.id or capture.ability.consumed_card_id!=row.id or
                (data['group_id'],data['trigger_index'],data['ability_id'])!=
                    (capture.group_id,capture.trigger_index,capture.ability.id) or
                (event.source_id,event.target_id,event.player_id,event.amount)!=
                    (capture.carrier_id,row.card.origin.entity_id,capture.player_id,0) or
                event.sequence<=row.event_sequence or event.action<capture.action):
            raise ValueError('Weapon return borrowed another activation, material or first-use receipt')
        claims[key]=event
        carrier=state.entities[capture.carrier_id]
        if any(a.id==capture.ability.id and not a.consumed for a in carrier.abilities):
            raise ValueError('Returned equipped material restored its consumed live payload')
    for key,activation in firsts.items():
        if activation.completed and key not in claims:
            raise ValueError('Completed weapon return lost its original first-use receipt')


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
        if row['destruction'] is not None:
            from .serialization import _death_cause_from_dict
            row['destruction'] = _death_cause_from_dict(row['destruction'])
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
    mechanics.register(ConsumeFabledWeapon, consume_fabled_weapon)
    mechanics.register(ConsumeEquippedWeapon, consume_equipped_weapon)
