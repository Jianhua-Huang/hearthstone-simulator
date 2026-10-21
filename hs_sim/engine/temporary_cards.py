"""Temporary physical hand cards and printed repeat-this-turn declarations.

R-084 records commit/expiry windows and cross-zone policies awaiting calibration.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass

from .effects import Effect, _player, _source, _integer
from .errors import ResolutionError
from .model import CardType, CostSpec, HandLifetime, HandRepeatSpec, Keyword, Zone
from .zones import CardReference
from .card_creation import CardSpellRepeatGrant, validate_declaration


@dataclass(frozen=True)
class CreateTemporaryCard(Effect):
    player_id: int
    card_id: str
    expires_turn: int
    minimum_cost: int = 0
    source_id: int | None = None
    cost: CostSpec | None = None
    cost_expires_turn: int | None = None
    spell_repeat: CardSpellRepeatGrant | None = None

    def __post_init__(self):
        validate_declaration(self.spell_repeat)
        _player(self.player_id); _source(self.source_id)
        _integer(self.expires_turn, 'expiry turn', 1)
        _integer(self.minimum_cost, 'minimum card cost', 0)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Temporary cards require a definition ID')
        from .effects import validate_generated_cost
        validate_generated_cost(self.cost,self.cost_expires_turn)


def create_temporary_card(r, effect):
    materialize_temporary_card(r, effect)


def materialize_temporary_card(r, effect):
    effect.__post_init__()
    definition=r.registry.card(effect.card_id)
    if not definition.hand_playable:
        raise ResolutionError('Temporary cards must be physical hand cards')
    if effect.spell_repeat is not None and definition.kind != CardType.SPELL:
        raise ResolutionError('Temporary repeated creation requires a spell')
    if effect.expires_turn < r.state.turn:
        raise ResolutionError('Temporary card deadline has already passed')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Temporary card source does not exist')
    from .costs import attach_cost, matches_cost
    if effect.cost_expires_turn is not None and effect.cost_expires_turn < r.state.turn:
        raise ResolutionError('Temporary card cost has expired')
    if effect.cost is not None and not matches_cost(effect.cost,definition):
        raise ResolutionError('Temporary card cost does not match its definition')
    player=r.player(effect.player_id)
    zone=Zone.HAND if len(player.hand)<hand_capacity(player, r.rules) else Zone.GRAVEYARD
    entity=r.create_entity(player.id,definition.id,zone,hand_entry_source_id=effect.source_id)
    entity.origin_entity_id=effect.source_id
    entity.hand_lifetime=HandLifetime(effect.source_id,r.state.turn,effect.expires_turn,effect.minimum_cost)
    if effect.cost is not None:attach_cost(r.state,entity,effect.cost,effect.source_id,effect.cost_expires_turn)
    if effect.spell_repeat is not None:
        from .card_creation import install
        install(r.state,entity,effect)
    r.emit('card_created',source_id=effect.source_id,target_id=entity.id,player_id=player.id)
    if zone==Zone.GRAVEYARD:
        from .zones import emit_burn
        emit_burn(r,entity,profile='created_overflow',source_id=effect.source_id,reason='temporary')
    else:
        r.emit('card_added_to_hand',source_id=effect.source_id,target_id=entity.id,player_id=player.id,reason='temporary')
        from .hand_history import publish as publish_hand_entry
        publish_hand_entry(r, entity.hand_entry_id)
    return entity



@dataclass(frozen=True)
class MakeHandCardTemporary(Effect):
    """Mark an existing captured hand card; absolute global-turn deadline.

    Repeated grants keep the earliest deadline and highest cost floor. This
    closed local policy does not implement owner-turn countdown destruction.
    """
    card: 'CardReference'
    expires_turn: int
    minimum_cost: int = 0
    source_id: int | None = None

    def __post_init__(self):
        from .zones import reference_value
        reference_value(self.card)
        if self.card.zone != Zone.HAND:
            raise ValueError('Temporary grant requires a captured hand card')
        _integer(self.expires_turn, 'temporary grant expiry', 1)
        _integer(self.minimum_cost, 'temporary grant cost floor', 0)
        _source(self.source_id)


def validate_temporary_request(state, registry, effect):
    # Reference validity is separate from current eligibility. Known earlier
    # epochs and faces may be stale; invented entities/epochs are not stale.
    effect.__post_init__()
    if not registry.card(effect.card.card_id).hand_playable:
        raise ValueError('Temporary grant requires a physical card definition')
    entity = state.entities.get(effect.card.entity_id)
    if entity is None:
        raise ValueError('Unknown temporary grant physical card')
    if effect.card.zone_epoch > entity.zone_epoch:
        raise ValueError('Temporary grant references a future zone epoch')
    if effect.source_id is not None and effect.source_id not in state.entities:
        raise ValueError('Unknown temporary grant source')
    if effect.expires_turn < state.turn:
        raise ValueError('Temporary grant deadline has already passed')


def make_hand_card_temporary(r, effect):
    from .zones import reference_entity
    try:
        validate_temporary_request(r.state, r.registry, effect)
    except ValueError as error:
        raise ResolutionError(str(error)) from error
    entity = reference_entity(r, effect.card)
    if entity is None:
        return
    old = entity.hand_lifetime
    if old is None:
        lifetime = HandLifetime(effect.source_id, r.state.turn,
                                effect.expires_turn, effect.minimum_cost)
    else:
        lifetime = HandLifetime(old.source_id, old.created_turn,
                                min(old.expires_turn, effect.expires_turn),
                                max(old.minimum_cost, effect.minimum_cost))
    if lifetime == old:
        return
    entity.hand_lifetime = lifetime
    # Does not generate, draw, acquire, discard or rebuild this physical card.
    r.emit('hand_card_made_temporary', source_id=effect.source_id,
           target_id=entity.id, player_id=entity.controller)


def validate_temporary_frame(game):
    from dataclasses import fields, is_dataclass
    from .model import GameState
    from .pools import DiscoverFromPool,GenerateFromPool
    seen = set()

    def visit(value):
        if type(value) is MakeHandCardTemporary:
            validate_temporary_request(game._state, game.registry, value)
        if type(value)in(DiscoverFromPool,GenerateFromPool)and value.temporary_until_turn is not None:
            value.__post_init__()
            if value.temporary_until_turn!=game._state.turn:
                raise ValueError('Temporary pool frame lost its accepted current-turn deadline')
        if value is None or type(value) is GameState or id(value) in seen:
            return
        if is_dataclass(value) and not isinstance(value, type):
            seen.add(id(value))
            for field in fields(value):
                visit(getattr(value, field.name))
        elif isinstance(value, (tuple, list)):
            seen.add(id(value))
            for item in value:
                visit(item)
    visit(game._frame)


def repeat_spec(entity, definition):
    if Keyword.ECHO in entity.keywords:
        return HandRepeatSpec()
    spec=definition.hand_repeat
    return spec if spec is not None and not spec.echo and not entity.silenced else None


def on_committed(r, record, spec):
    if spec is not None:
        create_temporary_card(r,CreateTemporaryCard(record.player_id,record.card_id,record.turn,
                                                    int(spec.echo),record.source_id))


def expire_temporary_cards(r, turn):
    expired=[]
    for entity in list(r.state.entities.values()):
        life=entity.hand_lifetime
        if life is None or life.expires_turn>turn:
            continue
        entity.hand_lifetime=None
        if entity.zone==Zone.HAND:
            r.move(entity,Zone.GRAVEYARD)
            expired.append((entity.id,entity.controller,life.source_id))
    for entity_id,player_id,source_id in expired:
        # No discard, death or corpse rewards; identity remains owner-private.
        r.emit('card_expired',source_id=source_id,target_id=entity_id,player_id=player_id)
    return bool(expired)


def validate_definitions(registry):
    for definition in registry.cards.values():
        spec=definition.hand_repeat
        if spec is not None:
            if type(spec) is not HandRepeatSpec or definition.kind not in (CardType.MINION,CardType.SPELL) or not definition.hand_playable:
                raise ValueError('Hand repetition requires a physical minion/spell and HandRepeatSpec')
            spec.__post_init__()
        if (Keyword.ECHO in definition.keywords)!=(spec is not None and spec.echo):
            raise ValueError('Echo requires its marker and hand repetition declaration')


def validate_lifetimes(state,registry):
    for entity in state.entities.values():
        life=entity.hand_lifetime
        if life is None:continue
        if type(life) is not HandLifetime:
            raise ValueError('Invalid hand lifetime record')
        life.__post_init__()
        if (not life.created_turn<=state.turn<=life.expires_turn or
                life.source_id is not None and life.source_id not in state.entities or
                not registry.card(entity.card_id).hand_playable):
            raise ValueError('Invalid temporary card chronology, source or kind')


def register(mechanics):
    mechanics.register(CreateTemporaryCard,create_temporary_card)
    mechanics.register(MakeHandCardTemporary,make_hand_card_temporary)
