"""Hidden-zone operations and private choices over physical cards.

Movement keeps entity identity; copies allocate new entities and attachments.
Captured physical targets include zone/controller/definition guards so later
reactions cannot pull a departed card back or operate on a different face.
"""
from .hand_capacity import hand_capacity
from .card_creation import (CardSpellRepeatGrant, CreatedMinionGrant, CreatedMinionStats, validate_minion_stats, validate_declaration,
    validate_branch_declaration, validate_minion_grant)
from dataclasses import dataclass, replace

from .construction import integer, name
from .effects import AddToHand, ChoiceOption, Draw, Effect, RequestChoice, _player, _source, validate_generated_cost
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import copy_attachments, reset_to_definition
from .model import CardClass, CardType, CostSpec, ChooseBranchSelection, DeathRecord, Entity, SummonStats, Zone, validate_summon_stats, CardPreview, ChoiceResult
from .sacrifice import MinionReference, live_minion
from .pools import PoolQuery, matches_metadata
from .card_conditions import has_battlecry
from .copy_materials import CopyEntryMaterial,CapturedCardCopyMaterial,validate_captured_card_copy
from .played_minion_copies import PlayedMinionCopyMaterial
from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .discard_history import DiscardRecord, validate_base_copy as validate_discard_base_copy


CARD_ZONES = (Zone.HAND, Zone.DECK)
HAND_TYPES = (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO)


def card_zone(zone):
    if type(zone) is not Zone or zone not in CARD_ZONES:
        raise ValueError('Expected hand or deck zone')


def position_value(position):
    if type(position) is int:
        integer(position, 'insertion position', 0)
    elif type(position) is not str or position not in ('top', 'bottom', 'random'):
        raise ValueError('Position must be top, bottom, random or a nonnegative index')


def insertion_index(r, position, size):
    position_value(position)
    if type(position) is int:
        if position > size:
            raise ResolutionError('Insertion position exceeds destination length')
        return position
    return 0 if position == 'top' else size if position == 'bottom' else r.game._rng.randrange(size + 1)


def source_exists(r, source_id):
    if source_id is not None and source_id not in r.state.entities:
        raise ResolutionError('Zone operation source does not exist')


@dataclass(frozen=True)
class FillHandWithCard(Effect):
    """Accept the current free slots once, then use ordinary card delivery."""
    player_id: int
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); name(self.card_id,'hand fill card'); _source(self.source_id)


def fill_hand_with_card(r, effect):
    effect.__post_init__(); source_exists(r,effect.source_id)
    definition=r.registry.card(effect.card_id)
    if definition.kind not in HAND_TYPES or not definition.hand_playable:
        raise ResolutionError('Hand refill requires a complete physical hand card')
    player=r.player(effect.player_id)
    count=max(0,hand_capacity(player,r.rules)-len(player.hand))
    if count>r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Hand refill exceeds resolution budget')
    return tuple(AddToHand(player.id,effect.card_id,effect.source_id)for _ in range(count))


@dataclass(frozen=True)
class FillHandWithDeckCopies(Effect):
    """Quote free slots once; each current physical deck copy uses CopyMatching."""
    player_id: int
    owner_id: int
    source_id: int
    cost: CostSpec | None = None

    def __post_init__(self):
        _player(self.player_id);_player(self.owner_id);_source(self.source_id)
        if self.source_id is None:raise ValueError('Deck-copy fill requires its original source')
        validate_generated_cost(self.cost,None)


def validate_copy_cost(r, cost, mode, candidates):
    if cost is None:return
    from types import SimpleNamespace
    from .costs import validate_cost_targets
    validate_cost_targets(r.state,SimpleNamespace(cost=cost,expires_turn=None),
        tuple((r.registry.card(ref.card_id),r.state.entities[ref.entity_id]if mode=='current'else None)
            for ref in candidates))


def fill_hand_with_deck_copies(r, effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    candidates=zone_candidates(r,effect.owner_id,Zone.DECK,PoolQuery(),effect.player_id,effect.source_id)
    validate_copy_cost(r,effect.cost,'current',candidates)
    player=r.player(effect.player_id)
    count=max(0,hand_capacity(player,r.rules)-len(player.hand))
    if count>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Deck-copy fill exceeds resolution budget')
    if not count or not candidates:return ()
    return(CopyMatching(player.id,effect.owner_id,Zone.DECK,count=count,
        source_id=effect.source_id,cost=effect.cost),)


@dataclass(frozen=True)
class AddToDeck(Effect):
    player_id: int
    card_id: str
    position: str | int = 'random'
    source_id: int | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None

    spell_repeat: CardSpellRepeatGrant | None = None
    choose_branch: ChooseBranchSelection | None = None
    minion_grant: CreatedMinionGrant | None = None
    minion_stats: CreatedMinionStats | None = None

    def __post_init__(self):
        validate_minion_grant(self.minion_grant)
        validate_minion_stats(self.minion_stats)
        validate_declaration(self.spell_repeat)
        validate_branch_declaration(self.choose_branch, self.card_id)
        _player(self.player_id); name(self.card_id, 'card ID'); _source(self.source_id)
        position_value(self.position)
        validate_generated_cost(self.cost, self.expires_turn)


@dataclass(frozen=True)
class CardReference:
    entity_id: int
    player_id: int
    zone: Zone
    card_id: str
    zone_epoch: int

    def __post_init__(self):
        integer(self.entity_id, 'entity ID'); _player(self.player_id)
        card_zone(self.zone); name(self.card_id, 'card ID')
        integer(self.zone_epoch, 'zone epoch', 0)

    @classmethod
    def capture(cls, entity):
        return cls(entity.id, entity.controller, entity.zone, entity.card_id, entity.zone_epoch)


def reference_entity(r, reference):
    r.registry.card(reference.card_id)
    entity = r.state.entities.get(reference.entity_id)
    if entity is None or (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) != (
            reference.player_id, reference.zone, reference.card_id, reference.zone_epoch):
        r.emit('zone_target_skipped', target_id=reference.entity_id, reason='captured_card_departed')
        return None
    return entity


def reference_value(reference):
    if type(reference) is not CardReference:
        raise ValueError('Expected a captured CardReference')
    reference.__post_init__()


@dataclass(frozen=True)
class SetAsideCardReference:
    """Explicit original custody; not a normal hidden-zone query/copy target."""
    entity_id: int
    player_id: int
    card_id: str
    zone_epoch: int
    zone: Zone = Zone.SETASIDE

    def __post_init__(self):
        integer(self.entity_id,'stored custody entity');_player(self.player_id)
        name(self.card_id,'stored custody card');integer(self.zone_epoch,'stored custody epoch',0)
        if type(self.zone) is not Zone or self.zone != Zone.SETASIDE:
            raise ValueError('Custody reference requires its actual set-aside zone')


@dataclass(frozen=True)
class MoveCard(Effect):
    card: CardReference | SetAsideCardReference
    player_id: int
    destination: Zone
    position: str | int = 'bottom'
    draw: bool = False
    reset: bool = False
    source_id: int | None = None

    def __post_init__(self):
        if type(self.card) is SetAsideCardReference:
            self.card.__post_init__()
            if self.destination != Zone.HAND or self.draw or self.reset:
                raise ValueError('Original custody supports only physical non-draw hand return')
        else: reference_value(self.card)
        _player(self.player_id); card_zone(self.destination)
        position_value(self.position); _source(self.source_id)
        if type(self.draw) is not bool or type(self.reset) is not bool:
            raise ValueError('Move flags must be boolean')
        if self.destination == Zone.HAND and self.position != 'bottom':
            raise ValueError('Move to hand appends; use ReorderZone for hand order')
        if self.draw and (self.card.zone != Zone.DECK or self.destination != Zone.HAND):
            raise ValueError('A physical draw moves an original deck card to the recipient hand')


@dataclass(frozen=True)
class CopyCard(Effect):
    card: CardReference | CopyEntryMaterial | MinionReference | CapturedCardCopyMaterial | DeathRecord | DiscardRecord | PlayedMinionCopyMaterial
    player_id: int
    destination: Zone = Zone.HAND
    mode: str = 'current'
    position: str | int = 'random'
    source_id: int | None = None
    stats: SummonStats | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None
    cast_when_drawn: bool = False

    def __post_init__(self):
        if type(self.cast_when_drawn) is not bool:
            raise ValueError('Copied draw-cast declaration must be boolean')
        if self.cast_when_drawn and (type(self.card) is not CapturedCardCopyMaterial or
                self.card.origin.kind != CardType.SPELL or self.card.origin.zone != Zone.DECK or
                self.card.origin.controller != self.player_id or self.mode != 'current' or
                self.destination != Zone.DECK or self.position != 'random' or self.source_id is None):
            raise ValueError('Draw-cast copies require original current own-deck spell material and random insertion')
        if type(self.card) is PlayedMinionCopyMaterial:
            self.card.__post_init__()
            if self.mode != 'base': raise ValueError('Played minion history permits only its printed base copy')
        elif type(self.card)is DiscardRecord:
            self.card.__post_init__()
            if self.mode!='base':raise ValueError('Discard occurrence copies require the original printed recipe')
        elif type(self.card)is DeathRecord:
            self.card.__post_init__()
            if self.mode!='base' or self.card.zone!=Zone.BOARD:raise ValueError('Death copies require their original printed board-minion recipe')
        elif type(self.card)is CapturedCardCopyMaterial:
            self.card.__post_init__()
            if self.card.origin.zone in(Zone.GRAVEYARD,Zone.BOARD)and self.mode!='base':
                raise ValueError('Spent/board captured copies require the printed base recipe')
        elif type(self.card)is CopyEntryMaterial:
            self.card.__post_init__()
            if (self.card.profile!='discard_copy' or self.player_id!=self.card.discard.player_id or
                    self.destination!=Zone.HAND or self.mode!='current' or self.position!='random' or
                    self.source_id is not None and self.source_id!=self.card.origin.entity_id or
                    self.stats is not None or self.cost is not None or self.expires_turn is not None):
                raise ValueError('Discard copies require original current material and own hand append')
        elif type(self.card) is MinionReference:
            self.card.__post_init__()
        else:
            reference_value(self.card)
        _player(self.player_id); card_zone(self.destination)
        position_value(self.position); _source(self.source_id)
        validate_summon_stats(self.stats)
        validate_generated_cost(self.cost, self.expires_turn)
        if self.mode not in ('base', 'current'):
            raise ValueError('Copy mode must be base or current')
        if self.destination == Zone.HAND and self.position != 'random':
            raise ValueError('Hand copies append; insertion position applies only to deck copies')


@dataclass(frozen=True)
class DestroyStoredCard(Effect):
    """Destroy the captured physical hand/deck card, independently of discard."""
    card: CardReference
    source_id: int | None = None
    reveal: bool = True
    on_destroy: tuple[Effect, ...] = ()

    def __post_init__(self):
        reference_value(self.card); _source(self.source_id)
        if type(self.reveal) is not bool:
            raise ValueError('Stored destruction requires a boolean reveal policy')
        if type(self.on_destroy) is not tuple or any(not isinstance(e, Effect) for e in self.on_destroy):
            raise ValueError('Destruction continuation must be an immutable tuple of effects')


@dataclass(frozen=True)
class DestroyDeckCard(Effect):
    card: CardReference
    source_id: int | None = None
    reveal: bool = True
    on_destroy: tuple[Effect, ...] = ()

    def __post_init__(self):
        reference_value(self.card); _source(self.source_id)
        if self.card.zone != Zone.DECK or type(self.reveal) is not bool:
            raise ValueError('Deck destruction requires a deck reference and boolean reveal policy')
        if type(self.on_destroy) is not tuple or any(not isinstance(e, Effect) for e in self.on_destroy):
            raise ValueError('Destruction continuation must be an immutable tuple of effects')


@dataclass(frozen=True)
class DestroyDeckBatch(Effect):
    """Remove all captured deck targets before publishing any destruction."""
    cards: tuple[CardReference, ...]
    source_id: int | None = None
    reveal: bool = True

    def __post_init__(self):
        _source(self.source_id)
        if type(self.cards) is not tuple or type(self.reveal) is not bool:
            raise ValueError('Deck destruction batch requires an immutable list and boolean reveal policy')
        for card in self.cards:
            reference_value(card)
            if card.zone != Zone.DECK:
                raise ValueError('Deck destruction batch requires deck references')
        if len({card.entity_id for card in self.cards}) != len(self.cards):
            raise ValueError('A deck destruction batch cannot repeat a physical target')


@dataclass(frozen=True)
class CardDestructionRecord:
    """One successful original occurrence, derived from its immutable event."""
    card: CardReference | SourceAllocationFact
    owner_id: int
    kind: CardType
    source_id: int | None
    sequence: int
    turn: int
    action: int
    reveal: bool
    profile: str = 'explicit'
    recipient_id: int | None = None

    def __post_init__(self):
        _player(self.owner_id); _source(self.source_id)
        name(self.profile, 'destruction profile')
        if self.profile == 'explicit':
            reference_value(self.card)
            if self.recipient_id is not None:
                raise ValueError('Explicit destruction uses its captured controller')
        else:
            if type(self.card) is not SourceAllocationFact:
                raise ValueError('Overflow requires its original physical allocation')
            self.card.__post_init__(); _player(self.recipient_id)
            zones={'stored_overflow':(Zone.HAND,Zone.DECK),'created_overflow':(Zone.GRAVEYARD,),
                'deck_overflow':(Zone.HAND,Zone.DECK,Zone.SETASIDE),
                'setaside_overflow':(Zone.SETASIDE,),'graveyard_delivery_overflow':(Zone.GRAVEYARD,)}
            if (self.profile not in zones or self.card.zone not in zones[self.profile] or
                    self.owner_id != self.card.owner or self.kind != self.card.kind):
                raise ValueError('Overflow profile disagrees with its original card')
            if self.profile == 'created_overflow' and (self.card.zone_epoch != 0 or
                    self.card.entity_id != self.card.next_entity_id-1):
                raise ValueError('Created overflow requires its original newborn allocation')
        if type(self.kind) is not CardType or self.kind not in HAND_TYPES:
            raise ValueError('Stored destruction requires a physical hand-card type')
        integer(self.sequence, 'destruction event sequence'); integer(self.turn, 'destruction turn')
        integer(self.action, 'destruction action', 0)
        if type(self.reveal) is not bool:
            raise ValueError('Destruction reveal policy must be boolean')

    @property
    def player_id(self):
        return self.card.player_id if self.profile == 'explicit' else self.recipient_id

    @property
    def after_epoch(self):
        return self.card.zone_epoch + (0 if self.profile == 'created_overflow' else 1)


def destruction_result(event):
    if event is not None and event.kind == 'card_burned' and 'burn_destruction' in dict(event.data):
        payload=dict(event.data)['burn_destruction']
        if type(payload) is not tuple or any(type(row) is not tuple or len(row)!=2 for row in payload):
            raise ValueError('Overflow requires immutable original receipt fields')
        values=dict(payload)
        if len(values)!=len(payload) or set(values)!={'profile','original','recipient_id','turn'}:
            raise ValueError('Overflow requires its complete original receipt')
        original=allocation_from_payload(values['original'])
        if original is None or type(event.amount) is not int or event.amount != 0:
            raise ValueError('Overflow lost its original card or notification amount')
        row=CardDestructionRecord(original,original.owner,original.kind,event.source_id,event.sequence,
            values['turn'],event.action,True,values['profile'],values['recipient_id'])
        if type(event.target_id) is not int or type(event.player_id) is not int or (
                event.target_id,event.player_id)!=(original.entity_id,row.player_id):
            raise ValueError('Overflow notification changed its physical card/recipient')
        return row
    if event is None or event.kind not in ('card_destroyed_in_hand', 'card_destroyed_in_deck'):
        return None
    data = dict(event.data)
    if (len(event.data) != 6 or set(data) != {'card_id','original_card','owner_id','card_kind','turn','reveal'} or
            type(event.amount) is not int or event.amount != 0):
        raise ValueError('Stored destruction requires its complete original receipt')
    values = data['original_card']
    if type(values) not in (tuple, list) or len(values) != 5 or type(values[2]) is not str:
        raise ValueError('Stored destruction lost its original captured card')
    card = CardReference(values[0], values[1], Zone(values[2]), values[3], values[4])
    expected = 'card_destroyed_in_' + card.zone.value
    if (event.kind != expected or type(data['card_kind']) is not str or
            type(event.target_id) is not int or type(event.player_id) is not int or
            (event.target_id,event.player_id,data['card_id']) != (card.entity_id,card.player_id,card.card_id)):
        raise ValueError('Stored destruction event disagrees with its original card')
    return CardDestructionRecord(card,data['owner_id'],CardType(data['card_kind']),event.source_id,
        event.sequence,data['turn'],event.action,data['reveal'])


def validate_destroyed_definition(card):
    if card.on_destroyed is None:
        return
    name(card.on_destroyed, 'native destroyed behavior')
    if not card.hand_playable or card.starship_for:
        raise ValueError('Native destroyed body requires a physical non-composite hand card')


def validate_destroyed_carrier(registry, card_id, kind, abilities, components=()):
    bodies = tuple(a for a in abilities if a.kind == 'on_destroyed')
    if not bodies:
        return
    card = registry.card(card_id); validate_destroyed_definition(card)
    if (card.on_destroyed is None or card.kind != kind or components or len(bodies) != 1):
        raise ValueError('Destroyed carrier lost its unique native body')
    bodies[0].__post_init__()
    if bodies[0].behavior_id != card.on_destroyed:
        raise ValueError('Destroyed body differs from its current native declaration')


def validate_destroyed_context(context, registry):
    from .model import AbilityInstance
    if type(context.trigger) is not AbilityInstance or context.trigger.kind != 'on_destroyed':
        return
    row = destruction_result(context.event)
    if row is None:
        raise ValueError('Native destroyed acceptance lost its original successful event')
    integer(context.source_id, 'native destroyed source'); _player(context.player_id)
    if (context.source_id != row.card.entity_id or context.player_id != row.player_id or
            context.target_id is not None or type(context.rewind_attempt) is not int or context.rewind_attempt != 0 or
            (context.state.turn,context.state.action_number) != (row.turn,row.action) or
            any(getattr(context,key) is not None for key in ('death','choice','player_effect','window','play','cast',
                'draw','power','battlecry','combo','deathrattle','power_payload','end_turn','physical','discard'))):
        raise ValueError('Native destroyed body requires its independent original acceptance')
    entity = context.state.entities.get(row.card.entity_id)
    if (entity is None or (entity.owner,entity.controller,entity.card_id,entity.kind,entity.zone,entity.zone_epoch) !=
            (row.owner_id,row.player_id,row.card.card_id,row.kind,Zone.GRAVEYARD,row.after_epoch)):
        raise ValueError('Native destroyed body lost its original after-destruction carrier')
    if row.profile != 'explicit':
        validate_allocation(context.state,registry,row.card)
    validate_destroyed_carrier(registry,entity.card_id,entity.kind,entity.abilities,entity.components)
    if (context.trigger not in entity.abilities or
            context.trigger.behavior_id != registry.card(entity.card_id).on_destroyed):
        raise ValueError('Native destroyed body borrowed another declaration')
    if row.source_id is not None and row.source_id not in context.state.entities:
        raise ValueError('Native destroyed event borrowed an unknown source')


def validate_destroyed_call(call, registry):
    validate_destroyed_context(call.context, registry)
    if (call.context.trigger is not None and call.context.trigger.kind == 'on_destroyed' and
            call.behavior_id != call.context.trigger.behavior_id):
        raise ValueError('Native destroyed call substituted another body')


def capture_destroyed_body(r, event):
    from copy import deepcopy
    from .lifecycle import active_abilities
    from .registry import RuleContext
    from .resolver import BehaviorCall
    row = destruction_result(event)
    entity = r.state.entities[row.card.entity_id]
    if r.registry.card(entity.card_id).stored_deathrattle:
        from .stored_deathrattles import capture_group
        return capture_group(r,event)
    validate_destroyed_carrier(r.registry,entity.card_id,entity.kind,entity.abilities,entity.components)
    bodies = active_abilities(entity,'on_destroyed')
    if not bodies:
        return ()
    call = BehaviorCall(bodies[0].behavior_id,RuleContext(deepcopy(r.state),entity.id,entity.controller,
        event=deepcopy(event),trigger=deepcopy(bodies[0])))
    validate_destroyed_call(call,r.registry)
    return (call,)


def validate_stored_destruction_events(state, registry, events):
    from .deck_capacity import validate_events
    validate_events(state, registry, events)
    from .hero_health_history import effective_events
    seen=set()
    for event in effective_events(events):
        row = destruction_result(event)
        if row is None:
            continue
        entity = state.entities.get(row.card.entity_id)
        if (registry.card(row.card.card_id).kind != row.kind or entity is None or
                entity.owner != row.owner_id or entity.zone_epoch < row.after_epoch or
                row.turn > state.turn or row.action > state.action_number or
                row.source_id is not None and row.source_id not in state.entities):
            raise ValueError('Stored destruction borrowed unknown or future original material')
        if row.profile != 'explicit':
            validate_allocation(state,registry,row.card)
        key=(row.card.entity_id,row.after_epoch)
        if key in seen:
            raise ValueError('A physical retirement cannot publish destruction twice')
        seen.add(key)


def emit_burn(r, entity, *, profile, original=None, source_id=None, player_id=None, **data):
    """The existing overflow producers supply their actual before-allocation."""
    from .deck_capacity import room
    if original is None:
        if profile != 'created_overflow':
            raise ResolutionError('Non-created overflow requires its actual previous allocation')
        original=SourceAllocationFact.capture(r.state,entity)
    recipient=entity.controller if player_id is None else player_id
    row=CardDestructionRecord(original,original.owner,original.kind,source_id,len(r.game._events)+1,
        r.state.turn,r.state.action_number,True,profile,recipient)
    validate_allocation(r.state,r.registry,original)
    if ((entity.id,entity.owner,entity.controller,entity.card_id,entity.kind,entity.zone,entity.zone_epoch)!=
            (original.entity_id,row.owner_id,recipient,original.card_id,row.kind,Zone.GRAVEYARD,row.after_epoch) or
            (bool(room(r.state,recipient)) if profile=='deck_overflow' else
             len(r.player(recipient).hand)<hand_capacity(r.player(recipient),r.rules)) or 'burn_destruction' in data):
        raise ResolutionError('Overflow requires its completed failed full-zone delivery')
    return r.emit('card_burned',source_id=source_id,target_id=entity.id,player_id=recipient,
        burn_destruction=(('profile',profile),('original',original.payload()),('recipient_id',recipient),('turn',r.state.turn)),**data)


@dataclass(frozen=True)
class DiscardCard(Effect):
    card: CardReference
    source_id: int | None = None
    reveal: bool = True
    on_success: tuple[Effect,...] = ()

    def __post_init__(self):
        reference_value(self.card); _source(self.source_id)
        if self.card.zone != Zone.HAND or type(self.reveal) is not bool:
            raise ValueError('Discard requires a hand card and boolean reveal policy')
        success_value(self.on_success)


def success_value(effects):
    if type(effects)is not tuple or any(not isinstance(e,Effect)for e in effects):raise ValueError('Discard success requires immutable typed effects')
    for effect in effects:
        validate=getattr(effect,'__post_init__',None)
        if validate is not None:validate()


@dataclass(frozen=True)
class ShuffleDeck(Effect):
    player_id: int

    def __post_init__(self):
        _player(self.player_id)


@dataclass(frozen=True)
class ReorderZone(Effect):
    player_id: int
    zone: Zone
    entity_ids: tuple[int, ...]

    def __post_init__(self):
        _player(self.player_id); card_zone(self.zone)
        if type(self.entity_ids) is not tuple or len(set(self.entity_ids)) != len(self.entity_ids):
            raise ValueError('Reordering requires a unique immutable ID sequence')
        for entity_id in self.entity_ids:
            integer(entity_id, 'ordered entity ID')


@dataclass(frozen=True)
class PutMatchingDeckMinionOnTop(Effect):
    """One physical random recipient shares top placement and stored growth."""
    player_id: int
    card_ids: tuple[str, ...]
    source_id: int
    attack: int = 0
    health: int = 0

    def __post_init__(self):
        from .pools import ids
        _player(self.player_id); integer(self.source_id, 'deck placement source', 1)
        ids(self.card_ids, 'positive top-deck identities', unique=True)
        if not self.card_ids: raise ValueError('Top placement requires explicit matching identities')
        integer(self.attack, 'top-deck attack growth', 0)
        integer(self.health, 'top-deck health growth', 0)

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Top placement has an unknown original source')
        for cid in self.card_ids:
            if registry.card(cid).kind!=CardType.MINION:
                raise ValueError('Top placement identities must be complete minions')


def put_matching_deck_minion_on_top(r, effect):
    from .hand_upgrades import BuffStoredCard
    effect.validate_in_state(r.state,r.registry)
    deck=r.player(effect.player_id).deck
    candidates=tuple(CardReference.capture(r.state.entities[i]) for i in deck
        if r.state.entities[i].kind==CardType.MINION and r.state.entities[i].card_id in effect.card_ids)
    if not candidates:return ()
    selected=r.game._rng.choice(candidates)
    order=(selected.entity_id, *(i for i in deck if i!=selected.entity_id))
    return (ReorderZone(effect.player_id,Zone.DECK,order),
        BuffStoredCard(selected,effect.attack,effect.health,effect.source_id))


def filter_value(query):
    if type(query) is not PoolQuery:
        raise ValueError('Expected PoolQuery')
    query.__post_init__()


@dataclass(frozen=True)
class DrawMatching(Effect):
    player_id: int
    query: PoolQuery
    empty_deck: str
    count: int = 1
    selection: str = 'random'
    source_id: int | None = None
    owner_id: int | None = None
    card_ids: tuple[str, ...] = ()
    on_empty: tuple[Effect, ...] = ()

    def __post_init__(self):
        _player(self.player_id); filter_value(self.query); _source(self.source_id)
        integer(self.count, 'draw count', 0)
        if self.owner_id is not None: _player(self.owner_id)
        from .pools import ids
        ids(self.card_ids, 'positive physical draw card IDs', unique=True)
        success_value(self.on_empty)
        if self.on_empty and (self.count != 1 or self.empty_deck != 'skip'):
            raise ValueError('Empty matching-draw fallback requires one skip-on-empty attempt')
        if self.selection not in ('random', 'first', 'highest_cost', 'lowest_cost') or self.empty_deck not in ('skip', 'fatigue'):
            raise ValueError('Draw requires explicit empty-deck and selection policies')


@dataclass(frozen=True)
class DrawMinionWithAttack(Effect):
    """Draw one physical minion matching its current stored Attack; empty skips."""
    player_id: int
    attack: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); integer(self.attack, 'draw minion Attack', 0); _source(self.source_id)


@dataclass(frozen=True)
class DestroyDeckMatching(Effect):
    player_id: int
    query: PoolQuery = PoolQuery()
    count: int = 1
    selection: str = 'random'
    source_id: int | None = None
    reveal: bool = True

    def __post_init__(self):
        _player(self.player_id); filter_value(self.query); _source(self.source_id)
        integer(self.count, 'deck destruction count', 0)
        if self.selection not in ('random', 'first') or type(self.reveal) is not bool:
            raise ValueError('Invalid deck destruction selection or reveal policy')


@dataclass(frozen=True)
class DiscardMatching(Effect):
    player_id: int
    query: PoolQuery = PoolQuery()
    count: int = 1
    selection: str = 'random'
    source_id: int | None = None
    reveal: bool = True
    on_success: tuple[Effect,...] = ()

    def __post_init__(self):
        success_value(self.on_success)
        _player(self.player_id); filter_value(self.query); _source(self.source_id)
        integer(self.count, 'discard count', 0)
        if self.selection not in ('random', 'first', 'highest_cost', 'lowest_cost') or type(self.reveal) is not bool:
            raise ValueError('Invalid discard selection or reveal policy')


@dataclass(frozen=True)
class ChooseFromZone(Effect):
    player_id: int
    owner_id: int
    zone: Zone
    query: PoolQuery = PoolQuery()
    operation: str = 'copy_base'
    sample_size: int | None = 3
    distinct: str = 'card'
    source_id: int | None = None
    prompt: str = '选择一张牌'
    discovery: bool = False
    cost: CostSpec | None = None
    destroy_unchosen: bool = False

    def __post_init__(self):
        _player(self.player_id); _player(self.owner_id); card_zone(self.zone)
        validate_generated_cost(self.cost, None)
        if type(self.destroy_unchosen) is not bool:
            raise ValueError('Unchosen deck destruction requires an explicit boolean')
        if (self.cost is not None or self.destroy_unchosen) and (
                self.operation != 'take' or self.zone != Zone.DECK or self.owner_id != self.player_id or
                self.distinct != 'entity' or self.discovery is not True):
            raise ValueError('Enriched physical deck discovery requires own-deck take with actual card discovery')
        filter_value(self.query); _source(self.source_id); name(self.prompt, 'choice prompt')
        if type(self.discovery) is not bool:
            raise ValueError('Zone discovery requires explicit genuine-card intent')
        if self.operation not in ('copy_base', 'copy_current', 'take', 'draw', 'discard', 'top', 'bottom'):
            raise ValueError('Unsupported zone choice operation')
        if self.sample_size is not None:
            integer(self.sample_size, 'zone choice sample size')
        if self.distinct not in ('card', 'entity') or (self.distinct == 'card' and self.operation not in ('copy_base', 'copy_current')):
            raise ValueError('Only copy choices may collapse physical copies')
        if self.operation == 'draw' and (self.zone != Zone.DECK or self.player_id != self.owner_id):
            raise ValueError('Draw choice requires the choosing player\'s deck')
        if self.operation == 'discard' and self.zone != Zone.HAND:
            raise ValueError('Discard choice requires hand cards')
        if self.operation in ('top', 'bottom') and self.zone != Zone.DECK:
            raise ValueError('Reposition choice requires deck cards')


@dataclass(frozen=True)
class DeckTakeOffer:
    card: CardReference
    face: CardPreview

    def __post_init__(self):
        reference_value(self.card)
        if self.card.zone != Zone.DECK or type(self.face) is not CardPreview:
            raise ValueError('Deck discovery requires its original stored card and preview')
        self.face.__post_init__()


@dataclass(frozen=True)
class SelectDeckTake(Effect):
    request: ChooseFromZone
    offered: tuple[DeckTakeOffer, ...]
    index: int
    result: ChoiceResult | None = None

    def __post_init__(self):
        if type(self.request) is not ChooseFromZone:
            raise ValueError('Deck selection requires its actual original zone request')
        self.request.__post_init__()
        if self.request.cost is None and not self.request.destroy_unchosen:
            raise ValueError('Plain zone choices retain their original delivery')
        if type(self.offered) is not tuple or not self.offered or any(type(x) is not DeckTakeOffer for x in self.offered):
            raise ValueError('Deck selection requires its complete ordered original offers')
        for offer in self.offered:
            offer.__post_init__()
            if offer.card.player_id != self.request.player_id:
                raise ValueError('Deck selection borrowed another original owner')
        if len({x.card.entity_id for x in self.offered}) != len(self.offered):
            raise ValueError('Deck discovery repeated a physical offered card')
        integer(self.index, 'selected deck offer', 0)
        if self.index >= len(self.offered):raise ValueError('Selected deck offer is outside its original inventory')
        if self.result is not None:
            if type(self.result) is not ChoiceResult:raise ValueError('Deck selection requires its actual result')
            self.result.__post_init__()


@dataclass(frozen=True)
class CopyMatching(Effect):
    """Automatically copy a physical hand/deck candidate through CopyCard."""
    player_id: int
    owner_id: int
    zone: Zone
    query: PoolQuery = PoolQuery()
    mode: str = 'current'
    count: int = 1
    selection: str = 'random'
    source_id: int | None = None
    cost: CostSpec | None = None

    def __post_init__(self):
        _player(self.player_id); _player(self.owner_id); card_zone(self.zone)
        filter_value(self.query); _source(self.source_id)
        validate_generated_cost(self.cost,None)
        integer(self.count, 'copy count', 0)
        if self.mode not in ('current', 'base') or self.selection not in ('random', 'lowest_cost'):
            raise ValueError('Unreviewed automatic zone copy policy')
        if self.selection == 'lowest_cost' and self.zone != Zone.HAND:
            raise ValueError('Lowest current price copy requires a hand')


@dataclass(frozen=True)
class CopyDeckSpellAtCurrentCost(Effect):
    """Copy one own physical deck spell from its current quoted cost tier."""
    player_id: int
    current_cost: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        integer(self.current_cost, 'current deck spell cost', 0)
        integer(self.source_id, 'current deck spell copy source', 1)


def copy_deck_spell_at_current_cost(r, effect):
    from .costs import quote_unselected_cost
    effect.__post_init__()
    candidates = zone_candidates(r, effect.player_id, Zone.DECK,
        PoolQuery(kinds=(CardType.SPELL,)), effect.player_id, effect.source_id)
    candidates = tuple(c for c in candidates if quote_unselected_cost(
        r.state, r.registry, r.state.entities[c.entity_id]).amount == effect.current_cost)
    if not candidates:
        return ()
    validate_copy_cost(r, None, 'current', candidates)
    return (CopyCard(r.game._rng.choice(candidates), effect.player_id,
        mode='current', source_id=effect.source_id),)


@dataclass(frozen=True)
class CopyLowestCostMinion(Effect):
    """Copy an own physical hand minion by current tribes and current price."""
    player_id: int
    tribes_any: tuple[str, ...]
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id);_source(self.source_id)
        PoolQuery(tribes_any=self.tribes_any).__post_init__()


def copy_lowest_cost_minion(r, effect):
    from .costs import quote_unselected_cost
    from .tribes import has_any_tribe
    effect.__post_init__();source_exists(r,effect.source_id)
    candidates=tuple(r.state.entities[eid] for eid in r.player(effect.player_id).hand
        if r.state.entities[eid].kind==CardType.MINION and
        has_any_tribe(r.registry,r.state.entities[eid],effect.tribes_any))
    if not candidates:return ()
    prices=tuple(quote_unselected_cost(r.state,r.registry,e).amount for e in candidates)
    lowest=min(prices);tied=tuple(e for e,price in zip(candidates,prices) if price==lowest)
    selected=tied[0] if len(tied)==1 else r.game._rng.choice(tied)
    return (CopyCard(CardReference.capture(selected),effect.player_id,mode='current',source_id=effect.source_id),)


def add_to_deck(r, effect):
    create_deck_card(r, effect)


def create_deck_card(r, effect):
    """Materialize once through the ordinary creator and return its actual body.

    Internal delivery callers may immediately capture a physical reference. The
    registered AddToDeck handler still returns no interpreter continuation.
    """
    player = r.player(effect.player_id); source_exists(r, effect.source_id)
    if not r.registry.card(effect.card_id).hand_playable:
        raise ResolutionError('Unsupported generated deck card type')
    from .costs import attach_cost, validate_creation_cost
    validate_creation_cost(r.state, effect, (r.registry.card(effect.card_id),))
    from .card_creation import validate_creation, install
    validate_creation(r.state, effect, (r.registry.card(effect.card_id),))
    from .deck_capacity import admits, failure
    if not admits(r.state, player.id):
        failure(r, player.id, effect.card_id, effect.source_id)
        return None
    position = insertion_index(r, effect.position, len(player.deck))
    entity = r.create_entity(player.id, effect.card_id, Zone.DECK, position)
    if effect.cost is not None:
        attach_cost(r.state, entity, effect.cost, effect.source_id, effect.expires_turn)
    install(r.state, entity, effect, resolver=r)
    r.emit('card_created', target_id=entity.id, source_id=effect.source_id, player_id=player.id)
    r.emit('card_added_to_deck', target_id=entity.id, source_id=effect.source_id, player_id=player.id, position=position,
        _deck_insertion_mode=effect.position if type(effect.position)is str else 'index')
    return entity


def move_card(r, effect):
    if effect.draw:
        from .draw_casts import draw_one
        return draw_one(r,effect.player_id,card=effect.card,source_id=effect.source_id,reset=effect.reset)
    # The physical helper exposes its actual recipient to internal callers;
    # an Entity is never interpreter work returned by this effect handler.
    move_physical_card(r,effect)


def move_physical_card(r, effect, *, draw_id=None, deathrattle_memory=None):
    """Move the original physical card, returning its actual body or no-op None.

    Draw orchestration remains in draw_one; this is its existing movement step.
    """
    source_exists(r, effect.source_id)
    entity = reference_entity(r, effect.card)
    if entity is None:
        return
    player = r.player(effect.player_id)
    if (effect.reset and entity.zone == Zone.HAND and effect.destination == Zone.HAND and
            player.id != entity.controller and any(a.kind == 'defining_hand_source' for a in entity.abilities)):
        raise ResolutionError('Resetting a transferred defining hand source requires an explicit lifecycle policy')
    if effect.destination == Zone.HAND and entity.zone == Zone.HAND and entity.controller == player.id:
        return  # Already occupies its hand slot; cannot burn by moving to itself.
    destination = effect.destination
    from .deck_capacity import admits, failure
    deck_overflow = destination == Zone.DECK and not admits(r.state, player.id, entity)
    if deck_overflow:
        destination = Zone.GRAVEYARD
    if destination == Zone.HAND and len(player.hand) >= hand_capacity(player, r.rules):
        destination = Zone.GRAVEYARD
    previous_zone = entity.zone
    previous_controller = entity.controller
    original=SourceAllocationFact.capture(r.state,entity) if destination==Zone.GRAVEYARD else None
    if destination == Zone.DECK:
        from .prepare import enter_deck
        enter_deck(entity)
    old = getattr(r.player(entity.controller), entity.zone.value)
    old.remove(entity.id)
    entity.controller, entity.zone = player.id, destination
    entity.zone_epoch += 1
    from .lifecycle import renew_hand_progress
    renew_hand_progress(r.state, entity, previous_zone=previous_zone,
        hand_transfer=previous_zone == Zone.HAND and destination == Zone.HAND and previous_controller != player.id)
    if effect.reset and not deck_overflow:
        reset_to_definition(r.state, entity, r.registry.card(entity.card_id), r.registry,
                            preserve_jade=True, preserve_cthun=previous_controller == player.id,preserve_weapon_spell=True)
        if previous_controller != player.id:
            from .cthun import initialize_instance as initialize_cthun
            initialize_cthun(r.state, r.registry, entity)
    if destination == Zone.DECK:
        r.game._information.conceal(entity.id)
        position = insertion_index(r, effect.position, len(player.deck))
        player.deck.insert(position, entity.id)
        event = 'card_moved_to_deck'
    else:
        getattr(player, destination.value).append(entity.id)
        event = 'card_burned' if destination == Zone.GRAVEYARD else 'card_drawn' if effect.draw else 'card_moved_to_hand'
    if destination == Zone.HAND:
        from .hand_history import enter_hand
        enter_hand(r.state, entity, previous_zone, 'draw' if effect.draw else 'move', source_id=effect.source_id)
        if deathrattle_memory is not None:
            if not effect.draw or draw_id is None:raise ResolutionError('Deathrattle linkage requires an actual physical draw')
            from .deathrattle_memory import remember_draw
            remember_draw(r,deathrattle_memory,draw_id,entity)
    data = {'draw_id': draw_id} if draw_id is not None else {}
    if destination == Zone.DECK:
        data['_deck_insertion_mode']=('reorder' if previous_zone==Zone.DECK and previous_controller==player.id else effect.position if type(effect.position)is str else 'index')
    if destination==Zone.GRAVEYARD:
        if deck_overflow:
            failure(r,player.id,entity.card_id,effect.source_id,original=original)
        emit_burn(r,entity,profile='deck_overflow' if deck_overflow else 'setaside_overflow' if previous_zone==Zone.SETASIDE else 'stored_overflow',original=original,source_id=effect.source_id,player_id=player.id,**data)
    else:
        r.emit(event, source_id=effect.source_id, target_id=entity.id, player_id=player.id, **data)
        if destination == Zone.HAND:
            from .hand_history import publish as publish_hand_entry
            publish_hand_entry(r, entity.hand_entry_id)
    return entity


def copy_card(r, effect):
    copy_physical_card(r, effect)


def copy_physical_card(r, effect, *, minion_grant=None, publish=True, notify_hand_entry=True, permanent_stats=None):
    """Shared copy materialization; internal callers may bind the new body."""
    effect.__post_init__()
    if type(publish) is not bool:raise ValueError('Copy publication must be boolean')
    if type(notify_hand_entry) is not bool:raise ValueError('Hand notification deferral must be boolean')
    if permanent_stats is not None:
        from .permanent_minion_stats import validate_value
        validate_value(permanent_stats)
        if (type(effect.card)is not CapturedCardCopyMaterial or effect.card.origin.kind!=CardType.MINION or
                effect.mode!='base' or effect.destination!=Zone.DECK or effect.stats is not None or minion_grant is not None):
            raise ValueError('Permanent printed growth requires an original base minion deck copy')
    source_exists(r, effect.source_id)
    material=effect.card if type(effect.card)is CopyEntryMaterial else None
    if type(effect.card) is PlayedMinionCopyMaterial:
        from .played_minion_copies import original_entity
        source = original_entity(r.state, r.registry, effect.card)
    elif type(effect.card)is CapturedCardCopyMaterial:
        validate_captured_card_copy(r.state,r.registry,effect.card)
        source=effect.card.entity()
    elif type(effect.card)is DiscardRecord:
        row=effect.card;validate_discard_base_copy(r.state,r.registry,row)
        source=Entity(row.entity_id,row.card_id,row.card.owner,row.player_id,Zone.GRAVEYARD,kind=row.kind,
            components=row.components,jade_size=row.jade_size)
    elif type(effect.card)is DeathRecord:
        row=effect.card
        if (next((old for old in r.state.death_history if old.id==row.id),None)!=row or
                r.registry.card(row.card_id).kind!=CardType.MINION):
            raise ResolutionError('Stored death copy lost its original committed minion death')
        source=Entity(row.entity_id,row.card_id,row.owner,row.controller,Zone.GRAVEYARD,kind=CardType.MINION,
            components=row.components,jade_size=row.jade_size)
    elif material is not None:
        effect.__post_init__()
        from .copy_materials import validate_scope,apply
        from .discard_history import validate_material as validate_discard
        validate_scope(r.state,r.registry,material,hand_copy=True)
        validate_discard(r.state,r.registry,material.discard)
        source=None
    elif type(effect.card) is MinionReference:
        r.registry.card(effect.card.card_id)
        source = live_minion(r.state, effect.card)
        if source is None:
            r.emit('zone_target_skipped', target_id=effect.card.entity_id, reason='captured_minion_departed')
            return
    else:
        source=reference_entity(r,effect.card)
        if source is None:return
    definition = r.registry.card(material.card_id if material is not None else source.card_id)
    if minion_grant is not None:
        from .card_creation import validate_minion_grant
        validate_minion_grant(minion_grant)
        if type(effect.card)is not CapturedCardCopyMaterial or definition.kind!=CardType.MINION or effect.mode!='current':
            raise ResolutionError('Copied creation grant requires original current stored-minion material')
    if effect.stats is not None and definition.kind != CardType.MINION:
        raise ResolutionError('Copied initial stats require a minion')
    from .costs import attach_cost, validate_cost_targets
    validate_cost_targets(r.state, effect, ((definition, source if effect.mode == 'current' else None),))
    player = r.player(effect.player_id)
    destination = effect.destination
    from .deck_capacity import admits, failure
    if destination == Zone.DECK and not admits(r.state, player.id):
        failure(r, player.id, definition.id, effect.source_id)
        return None
    if destination == Zone.HAND and len(player.hand) >= hand_capacity(player, r.rules):
        destination = Zone.GRAVEYARD
    position = insertion_index(r, effect.position, len(player.deck)) if destination == Zone.DECK else None
    entity = r.create_entity(player.id, material.card_id if material is not None else source.card_id, destination, position,
                             components=()if material is not None else source.components, hand_entry_source_id=effect.source_id)
    origin_id=material.origin.entity_id if material is not None else source.id
    entity.origin_entity_id = origin_id
    from .held_opponent_copies import copy_origin
    entity.copy_origin = copy_origin(material.origin if material is not None else source)
    from .jade import inherit_printed
    if material is not None:
        apply(r,material,entity)
    else:
        from .permanent_minion_stats import value as permanent_value
        from .infused_battlecries import value as infused_value
        inherit_printed(source, entity, state=r.state, permanent_stats=permanent_value(effect.card),
            infused_damage=infused_value(effect.card))
    if material is None and effect.mode == 'current':
        copy_current_stored_state(r.state,source,entity)
        if type(effect.card) is MinionReference:
            # Stored acquisition preserves local card material, not battlefield injury.
            entity.damage = 0
            from .lifecycle import refresh_entity
            refresh_entity(entity)
    from .lifecycle import apply_summon_stats
    from .native_stat_gains import seed
    if permanent_stats is not None:
        from .permanent_minion_stats import imprint
        imprint(r.state,entity,permanent_stats,effect.source_id)
    seed(r,entity,replace_existing=True)
    apply_summon_stats(r.state, entity, effect.stats)
    if effect.cost is not None:
        attach_cost(r.state, entity, effect.cost, effect.source_id, effect.expires_turn)
    if effect.cast_when_drawn:
        from .draw_cast_grants import install as install_draw_cast
        install_draw_cast(r, entity, effect.source_id)
    if minion_grant is not None:
        from types import SimpleNamespace
        from .card_creation import install
        install(r.state,entity,SimpleNamespace(spell_repeat=None,minion_grant=minion_grant,source_id=effect.source_id),resolver=r)
    if publish:announce_copied_card(r,entity,effect,origin_id,notify_hand_entry=notify_hand_entry)
    return entity


def announce_copied_card(r,entity,effect,origin_id,*,notify_hand_entry=True):
    if type(notify_hand_entry) is not bool:raise ValueError('Hand notification deferral must be boolean')
    player=r.player(effect.player_id);destination=entity.zone
    r.emit('card_created', source_id=effect.source_id, target_id=entity.id, player_id=player.id, copied_from=origin_id, copy_mode=effect.mode)
    event = 'card_added_to_deck' if destination == Zone.DECK else 'card_burned' if destination == Zone.GRAVEYARD else 'card_added_to_hand'
    if destination==Zone.GRAVEYARD:
        emit_burn(r,entity,profile='created_overflow',source_id=effect.source_id,player_id=player.id)
    else:
        extra={'_deck_insertion_mode':effect.position if type(effect.position)is str else 'index'}if destination==Zone.DECK else{}
        r.emit(event, source_id=effect.source_id, target_id=entity.id, player_id=player.id,**extra)
        if destination == Zone.HAND and notify_hand_entry:
            from .hand_history import publish as publish_hand_entry
            publish_hand_entry(r, entity.hand_entry_id)


def copy_current_stored_state(state, source, entity, *, retain_ids=False):
    """Existing stored current-copy recipe, independent of recipient allocation."""
    entity.base_attack, entity.base_health, entity.base_cost = source.base_attack, source.base_health, source.base_cost
    entity.damage, entity.durability, entity.corpse_value = source.damage, source.durability, source.corpse_value
    copy_attachments(state,source,entity,rebind_printed=True,retain_ids=retain_ids)
    entity.galakrond_invocations = source.galakrond_invocations


def destroy_deck_card(r, effect):
    return destroy_stored_card(r, effect)


def destroy_stored_card(r, effect):
    from .continuations import FrameCodec
    effect.__post_init__()
    source_exists(r, effect.source_id)
    codec = FrameCodec(r.game.mechanics, r.registry)
    codec.decode(codec.encode(effect))
    entity = reference_entity(r, effect.card)
    if entity is None:
        return ()
    r.move(entity, Zone.GRAVEYARD)
    publish_stored_destruction(r, effect.card, entity, effect.source_id, effect.reveal)
    return effect.on_destroy


def publish_stored_destruction(r, card, entity, source_id, reveal):
    for viewer in ((1, 2) if reveal else (entity.controller,)):
        r.game._information.players[viewer].remember(entity)
    # This is not a draw, discard, or board death: no death record, corpse,
    # deathrattle, reborn or Starship contribution is created.
    event = r.emit('card_destroyed_in_' + card.zone.value, source_id=source_id, target_id=entity.id,
           player_id=entity.controller, card_id=entity.card_id,
           original_card=(card.entity_id,card.player_id,card.zone.value,card.card_id,card.zone_epoch),
           owner_id=entity.owner,card_kind=entity.kind.value,turn=r.state.turn,reveal=reveal)
    own_body = capture_destroyed_body(r,event)
    r._captured.extend(own_body)


def destroy_deck_batch(r, effect):
    from .continuations import FrameCodec
    effect.__post_init__(); source_exists(r, effect.source_id)
    if len(effect.cards) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Deck destruction batch exceeds resolution budget')
    codec = FrameCodec(r.game.mechanics, r.registry, origin_state=r.state)
    codec.decode(codec.encode(effect))
    targets = []
    for card in effect.cards:
        entity = reference_entity(r, card)
        if entity is not None:
            targets.append((card, entity))
    # No reactions, native bodies or caller continuations execute between moves.
    for card, entity in targets:
        r.move(entity, Zone.GRAVEYARD)
    for card, entity in targets:
        publish_stored_destruction(r, card, entity, effect.source_id, effect.reveal)
    return ()


def discard_card(r, effect, *, deathrattle_memory=None):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    if deathrattle_memory is not None:
        from .deathrattle_memory import DiscardForDeathrattle
        if type(deathrattle_memory) is not DiscardForDeathrattle:
            raise ResolutionError('Discard linkage requires its exact native request')
        deathrattle_memory.validate_in_state(r.state,r.registry)
        if (effect.card,effect.source_id)!=(deathrattle_memory.card,deathrattle_memory.reference.entity_id):
            raise ResolutionError('Discard linkage borrowed a different original operation')
    entity = reference_entity(r, effect.card)
    if entity is None:
        return
    from .allocation_facts import SourceAllocationFact
    from .permanent_minion_stats import value as permanent_value
    from .infused_battlecries import value as infused_value
    capture=(SourceAllocationFact.capture(r.state,entity),entity.hand_entry_id,
        SourceAllocationFact.capture(r.state,r.state.entities.get(effect.source_id)),effect.reveal,
        entity.components,entity.jade_size,deathrattle_memory,permanent_value(entity),infused_value(entity))
    r.move(entity, Zone.GRAVEYARD)
    viewers = (1, 2) if effect.reveal else (entity.controller,)
    for viewer in viewers:
        r.game._information.players[viewer].remember(entity)
    # No death checkpoint record, corpse increment, battlecry or deathrattle.
    r.emit('card_discarded', source_id=effect.source_id, target_id=entity.id, player_id=entity.controller,
           _discard_commit=capture)
    return effect.on_success


def shuffle_deck(r, effect):
    player = r.player(effect.player_id)
    r.game._rng.shuffle(player.deck)
    for entity_id in player.deck:
        r.game._information.conceal(entity_id)
    r.emit('deck_shuffled', player_id=player.id)


def reorder_zone(r, effect, *, source_id=None):
    zone = getattr(r.player(effect.player_id), effect.zone.value)
    if set(zone) != set(effect.entity_ids) or len(zone) != len(effect.entity_ids):
        raise ResolutionError('Reordering must be a permutation of the current zone')
    zone[:] = effect.entity_ids
    r.emit('deck_reordered' if effect.zone == Zone.DECK else 'hand_reordered', player_id=effect.player_id, source_id=source_id)


def zone_candidates(r, owner_id, zone, query, player_id, source_id=None):
    filter_value(query); card_zone(zone)
    source_exists(r, source_id)
    current_class = None
    if query.class_mode in ('current', 'other'):
        current_class = r.player(player_id).hero_class
        if current_class is None or current_class == CardClass.NEUTRAL:
            raise ResolutionError('Zone query requires a known current playable hero class')
    excluded = set(query.exclude_card_ids)
    if query.exclude_source:
        if source_id is None:
            raise ResolutionError('Zone query source exclusion requires a source')
        excluded.add(r.state.entities[source_id].card_id)
    result = []
    for entity_id in getattr(r.player(owner_id), zone.value):
        entity = r.state.entities[entity_id]
        from .jade import printed_definition
        definition = printed_definition(r.registry, entity)
        if entity.card_id in excluded:
            continue
        if matches_metadata(query, card_id=entity.card_id, kind=definition.kind, cost=definition.cost,
                meta=definition.metadata, spell_school=definition.spell_school,
                keywords=definition.keywords, current_class=current_class,
                printed_battlecry=definition.battlecry is not None,
                current_battlecry=has_battlecry(entity.abilities), printed_attack=definition.attack):
            result.append(CardReference.capture(entity))
    return tuple(result)


def matching_card(r, effect):
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Zone selection count exceeds resolution budget')
    if effect.count == 0:
        return ()
    drawing = type(effect) is DrawMatching
    destroying = type(effect) is DestroyDeckMatching
    zone = Zone.DECK if drawing or destroying else Zone.HAND
    owner = effect.owner_id if drawing and effect.owner_id is not None else effect.player_id
    candidates = zone_candidates(r, owner, zone, effect.query, effect.player_id, effect.source_id)
    if drawing and effect.card_ids:
        for cid in effect.card_ids: r.registry.card(cid)
        candidates = tuple(c for c in candidates if c.card_id in effect.card_ids)
    if not candidates:
        if drawing and effect.on_empty:
            return effect.on_empty
        if drawing and effect.empty_deck == 'fatigue' and not r.player(owner).deck:
            if owner != effect.player_id:
                from .draw_casts import draw_one
                return (*draw_one(r, effect.player_id, source_id=effect.source_id, deck_owner_id=owner),
                    replace(effect, count=effect.count - 1))
            return (Draw(effect.player_id), replace(effect, count=effect.count - 1))
        return ()
    if drawing and effect.selection in ('highest_cost', 'lowest_cost'):
        from .costs import local_cost
        # The card is still in DECK. Prospective hand-only intrinsic/player
        # discounts are not an actual stored deck cost or a payment quote.
        prices = tuple(max(0, local_cost(r.state.entities[c.entity_id])[0]) for c in candidates)
        extreme = (max if effect.selection == 'highest_cost' else min)(prices)
        tied = tuple(c for c, price in zip(candidates, prices) if price == extreme)
        card = tied[0] if len(tied) == 1 else r.game._rng.choice(tied)
    elif type(effect) is DiscardMatching and effect.selection in ('highest_cost', 'lowest_cost'):
        from .costs import quote_unselected_cost
        # Comparison is a pure quote, independent of affordability or payment.
        prices = tuple(quote_unselected_cost(
            r.state, r.registry, r.state.entities[c.entity_id]).amount for c in candidates)
        extreme = (max if effect.selection == 'highest_cost' else min)(prices)
        tied = tuple(c for c, price in zip(candidates, prices) if price == extreme)
        card = tied[0] if len(tied) == 1 else r.game._rng.choice(tied)
    else:
        card = r.game._rng.choice(candidates) if effect.selection == 'random' else candidates[0]
    selected = (MoveCard(card, effect.player_id, Zone.HAND, draw=True, source_id=effect.source_id) if drawing
                else DestroyDeckCard(card, effect.source_id, effect.reveal) if destroying
                else DiscardCard(card, effect.source_id, effect.reveal,effect.on_success))
    # Re-query after each actual move and its reactions, like repeated Draw(1).
    if drawing and effect.on_empty:
        return (selected,)
    return (selected, replace(effect, count=effect.count - 1))


def draw_minion_with_attack(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    candidates=tuple(CardReference.capture(entity) for eid in r.player(effect.player_id).deck
        for entity in (r.state.entities[eid],) if entity.kind==CardType.MINION and entity.attack==effect.attack)
    if not candidates:return ()
    selected=r.game._rng.choice(candidates)
    return (MoveCard(selected,effect.player_id,Zone.HAND,draw=True,source_id=effect.source_id),)


def sample_zone_choices(r, effect):
    candidates = zone_candidates(r, effect.owner_id, effect.zone, effect.query, effect.player_id, effect.source_id)
    groups = {}
    if effect.distinct == 'card':
        unique = {}
        for card in candidates:
            unique.setdefault(card.card_id, card)
            groups.setdefault(card.card_id, []).append(card)
        # A definition choice does not expose deck order or duplicate counts.
        candidates = tuple(unique[i] for i in sorted(unique))
    count = len(candidates) if effect.sample_size is None else min(len(candidates), effect.sample_size)
    if count > r.rules.max_choice_options:
        raise ResolutionLimitExceeded('Zone choice exceeds offered option limit')
    if count == 0:
        return ()
    offered = candidates if effect.sample_size is None else tuple(r.game._rng.sample(candidates, count))
    if effect.distinct == 'card' and effect.operation == 'copy_current':
        # Choose the physical representative once, after selecting distinct
        # definitions. Duplicate copies cannot inflate an ID's offer weight.
        offered = tuple(r.game._rng.choice(groups[card.card_id]) for card in offered)
    return offered


def deck_take_options(registry, request, offered):
    return tuple(ChoiceOption(f'zone-{index+1}', offer.face.display_name or registry.card(offer.card.card_id).name,
        (SelectDeckTake(request, offered, index),), card_id=offer.card.card_id, preview=offer.face)
        for index, offer in enumerate(offered))


def select_deck_take(r, effect):
    effect.__post_init__()
    from .card_discoveries import require_original_result
    from .discovery_delivery import MaterializeDiscoveredCard
    from .model import ChoicePurpose
    request = effect.request
    source_exists(r, request.source_id)
    if effect.result is None:
        raise ResolutionError('Enriched deck selection requires its actual committed discovery')
    require_original_result(r.state, effect.result)
    choice = effect.result.choice
    if (choice.purpose != ChoicePurpose.CARD_DISCOVERY or
            (choice.player_id, choice.source_id, choice.prompt) != (request.player_id, request.source_id, request.prompt) or
            choice.options != tuple(o.item for o in deck_take_options(r.registry, request, effect.offered)) or
            effect.result.selected_ids != (f'zone-{effect.index+1}',)):
        raise ResolutionError('Deck selection changed its original complete request or offers')
    selected = effect.offered[effect.index].card
    work = (ModifyStoredCost(selected, request.cost, request.source_id),) if request.cost is not None else ()
    work += (MaterializeDiscoveredCard(effect.result,
        MoveCard(selected, request.player_id, Zone.HAND, source_id=request.source_id)),)
    others = tuple(o.card for i, o in enumerate(effect.offered) if i != effect.index)
    if request.destroy_unchosen and others:
        work += (DestroyDeckBatch(others, request.source_id),)
    return work


def validate_deck_take_choice(game):
    choice, frame = game._state.pending_choice, game._frame
    if choice is None or not any(type(e) is SelectDeckTake for o in frame.options for e in o.effects):
        return
    branches = tuple(o.effects[0] for o in frame.options if len(o.effects) == 1 and type(o.effects[0]) is SelectDeckTake)
    if len(branches) != len(frame.options) or not branches:
        raise ValueError('Deck discovery lost an original physical branch')
    first = branches[0]
    first.__post_init__()
    from .model import ChoicePurpose
    if (choice.purpose != ChoicePurpose.CARD_DISCOVERY or choice.min_count != 1 or choice.max_count != 1 or
            choice.repeat_key is not None or frame.on_select is not None or
            (choice.player_id, choice.source_id, choice.prompt) !=
                (first.request.player_id, first.request.source_id, first.request.prompt) or
            frame.options != deck_take_options(game.registry, first.request, first.offered)):
        raise ValueError('Deck discovery disagrees with its original complete offered material')
    for offer in first.offered:
        entity = game._state.entities.get(offer.card.entity_id)
        if entity is None or CardReference.capture(entity) != offer.card or CardPreview.capture(entity, game.registry) != offer.face:
            raise ValueError('Deck discovery no longer matches its actual original physical preview')


def choose_from_zone(r, effect):
    offered=sample_zone_choices(r,effect)
    if not offered:return ()
    if effect.cost is not None or effect.destroy_unchosen:
        from .model import ChoicePurpose
        original = tuple(DeckTakeOffer(card, CardPreview.capture(r.state.entities[card.entity_id], r.registry)) for card in offered)
        return (RequestChoice(effect.player_id, deck_take_options(r.registry, effect, original), source_id=effect.source_id,
            prompt=effect.prompt, purpose=ChoicePurpose.CARD_DISCOVERY),)
    options = []
    for index, card in enumerate(offered, 1):
        if effect.operation == 'copy_base':
            operation = AddToHand(effect.player_id, card.card_id, effect.source_id)
        elif effect.operation == 'copy_current':
            operation = CopyCard(card, effect.player_id, source_id=effect.source_id)
        elif effect.operation == 'discard':
            operation = DiscardCard(card, effect.source_id)
        elif effect.operation in ('top', 'bottom'):
            operation = MoveCard(card, card.player_id, Zone.DECK, position=effect.operation, source_id=effect.source_id)
        else:
            operation = MoveCard(card, effect.player_id, Zone.HAND, draw=effect.operation == 'draw', source_id=effect.source_id)
        if card.zone == Zone.HAND:
            r.game._information.players[effect.player_id].remember(r.state.entities[card.entity_id])
        options.append(ChoiceOption(f'zone-{index}', r.registry.card(card.card_id).name, (operation,),
                                   card_id=card.card_id, entity_id=card.entity_id if card.zone == Zone.HAND else None))
    from .model import ChoicePurpose
    return (RequestChoice(effect.player_id, tuple(options), source_id=effect.source_id, prompt=effect.prompt,
        purpose=ChoicePurpose.CARD_DISCOVERY if effect.discovery else ChoicePurpose.EFFECT),)


def copy_matching(r, effect):
    effect.__post_init__()
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Zone copy count exceeds resolution budget')
    if effect.count == 0:
        return ()
    candidates=zone_candidates(r,effect.owner_id,effect.zone,effect.query,effect.player_id,effect.source_id)
    if not candidates:
        return ()
    if effect.selection == 'lowest_cost':
        from .costs import quote_unselected_cost
        prices=tuple(quote_unselected_cost(r.state,r.registry,r.state.entities[c.entity_id]).amount for c in candidates)
        lowest=min(prices)
        candidates=tuple(c for c,price in zip(candidates,prices) if price==lowest)
    validate_copy_cost(r,effect.cost,effect.mode,candidates)
    # Each physical slot has one weight. Pure current-price ties use the same RNG;
    # a unique cheapest card and an empty pool do not consume it.
    card=candidates[0] if effect.selection=='lowest_cost' and len(candidates)==1 else r.game._rng.choice(candidates)
    return (CopyCard(card,effect.player_id,mode=effect.mode,source_id=effect.source_id,cost=effect.cost),
            replace(effect,count=effect.count-1))


@dataclass(frozen=True)
class ModifyStoredCost(Effect):
    card: CardReference
    spec: object
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        from .model import CostSpec
        reference_value(self.card);_source(self.source_id)
        if type(self.spec)is not CostSpec:raise ValueError('Stored cost requires a typed CostSpec')
        self.spec.__post_init__()
        if self.expires_turn is not None:integer(self.expires_turn,'stored cost expiry')


def modify_stored_cost(r,effect):
    from .effects import ModifyCost
    from .costs import modify_cost
    effect.__post_init__();source_exists(r,effect.source_id)
    entity=reference_entity(r,effect.card)
    if entity is None:return ()
    return modify_cost(r,ModifyCost(entity.id,effect.spec,effect.source_id,effect.expires_turn))


def register_zones(mechanics):
    mechanics.register_payload_type(SetAsideCardReference)
    mechanics.register_payload_type(DeckTakeOffer)
    mechanics.register(SelectDeckTake, select_deck_take)
    mechanics.register_payload_type(CapturedCardCopyMaterial)
    mechanics.register(ModifyStoredCost,modify_stored_cost)
    mechanics.register_payload_type(CardReference)
    mechanics.register_payload_type(CardDestructionRecord)
    mechanics.register(PutMatchingDeckMinionOnTop,put_matching_deck_minion_on_top)
    for kind, handler in ((DestroyStoredCard, destroy_stored_card), (DestroyDeckCard, destroy_deck_card), (DestroyDeckBatch, destroy_deck_batch), (DestroyDeckMatching, matching_card),
                          (AddToDeck, add_to_deck), (FillHandWithCard, fill_hand_with_card),
            (FillHandWithDeckCopies, fill_hand_with_deck_copies), (MoveCard, move_card), (CopyCard, copy_card),
            (DiscardCard, discard_card), (ShuffleDeck, shuffle_deck), (ReorderZone, reorder_zone),
            (DrawMatching, matching_card), (DrawMinionWithAttack, draw_minion_with_attack),
            (DiscardMatching, matching_card), (ChooseFromZone, choose_from_zone),
            (CopyMatching, copy_matching), (CopyDeckSpellAtCurrentCost, copy_deck_spell_at_current_cost),
            (CopyLowestCostMinion, copy_lowest_cost_minion)):
        mechanics.register(kind, handler)
