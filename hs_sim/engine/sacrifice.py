"""Guarded destruction rewards and live physical-neighbor selection.

The normal scheduler owns deaths/reactions; a reward never resurrects its
beneficiary or attaches to a later incarnation that happens to reuse its ID.
"""
from dataclasses import dataclass

from .effects import Buff, Destroy, Effect, GrantDeathrattle, GrantKeyword, GrantSpellDamage, SetStats, Transform, _behavior, _integer, _player, _source
from .errors import ResolutionError
from .model import AbilityInstance, BoardPresenceReference, CardType, DeckSacrificeSpec, Keyword, LimitedTriggerSpec, StatReference, TimedKeywordSpec, Zone


@dataclass(frozen=True)
class MinionReference:
    entity_id: int
    player_id: int
    card_id: str
    zone_epoch: int
    entered_order: int

    def __post_init__(self):
        _integer(self.entity_id, 'minion ID', 1)
        _player(self.player_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Minion reference requires a card ID')
        _integer(self.zone_epoch, 'minion zone epoch', 0)
        _integer(self.entered_order, 'minion entry order', 1)

    @classmethod
    def capture(cls, entity):
        if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
            raise ValueError('Minion references require a board minion')
        return cls(entity.id, entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order)


def reference_value(value):
    if type(value) is not MinionReference:
        raise ValueError('Expected a captured MinionReference')
    value.__post_init__()


def same_instance(state, reference):
    entity = state.entities.get(reference.entity_id)
    if entity is None or (entity.zone, entity.kind, entity.controller, entity.card_id,
            entity.zone_epoch, entity.entered_order) != (Zone.BOARD, CardType.MINION,
            reference.player_id, reference.card_id, reference.zone_epoch, reference.entered_order):
        return None
    return entity


def live_minion(state, reference):
    entity = same_instance(state, reference)
    return entity if entity is not None and entity.active and entity.health > 0 and not entity.doomed else None


def reward_values(effect, *, board_presence=False):
    if board_presence and type(effect.beneficiary) is BoardPresenceReference:
        effect.beneficiary.__post_init__()
    else:
        reference_value(effect.beneficiary)
    _integer(effect.attack, 'reward attack')
    _integer(effect.health, 'reward health', 0)
    _source(effect.source_id)


@dataclass(frozen=True)
class BuffCapturedMinion(Effect):
    beneficiary: MinionReference | BoardPresenceReference
    attack: int = 0
    health: int = 0
    source_id: int | None = None

    def __post_init__(self):
        reward_values(self, board_presence=True)

    def validate_in_state(self, state):
        self.__post_init__()
        if type(self.beneficiary) is BoardPresenceReference:
            validate_reward_presence(state, self.beneficiary)


@dataclass(frozen=True)
class FreezeCapturedMinion(Effect):
    beneficiary: MinionReference
    source_id: int

    def __post_init__(self):
        reference_value(self.beneficiary)
        _integer(self.source_id, 'original freeze source', 1)

    def validate_in_state(self, state):
        self.__post_init__()
        ref = self.beneficiary
        entity = state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
            raise ValueError('Captured freeze borrowed an unknown or future minion allocation')
        if self.source_id not in state.entities:
            raise ValueError('Captured freeze has an unknown original source')


def freeze_captured_minion(r, effect):
    from .effects import Freeze
    from .resolver import freeze_character
    effect.validate_in_state(r.state)
    validate_request(r, effect)
    if live_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    freeze_character(r, Freeze(effect.beneficiary.entity_id, effect.source_id))
    return ()


@dataclass(frozen=True)
class BuffCapturedMinionWithStartTrigger(Effect):
    """Install one numeric grant and its removable one-use turn-start callback."""
    beneficiary: MinionReference
    attack: int
    health: int
    behavior_id: str
    source_id: int
    condition_id: str

    def __post_init__(self):
        reward_values(self)
        _integer(self.source_id, 'numeric/start grant source', 1)
        _behavior(self.behavior_id)
        _behavior(self.condition_id)

    def validate_in_state(self, state):
        self.__post_init__()
        ref = self.beneficiary
        entity = state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
            raise ValueError('Numeric/start grant borrowed an unknown or future minion allocation')
        if self.source_id not in state.entities:
            raise ValueError('Numeric/start grant has an unknown original source')


def buff_captured_minion_with_start_trigger(r, effect):
    from .lifecycle import attachment_id
    from .resolver import buff
    effect.validate_in_state(r.state)
    validate_request(r, effect)
    spec = LimitedTriggerSpec('turn_started', effect.behavior_id, effect.condition_id)
    r.registry.validate_limited_trigger(spec)
    entity = live_minion(r.state, effect.beneficiary)
    if entity is None:
        r.stale(effect, effect.beneficiary.entity_id); return ()
    # No reaction can capture a half-installed grant. Numeric application and
    # its notification still use the ordinary stat executor and health tracking.
    ability = AbilityInstance(attachment_id(r.state), 'limited_trigger', source_id=effect.source_id,
                              limited_trigger=spec, uses_remaining=1)
    entity.abilities.append(ability)
    buff(r, Buff(entity.id, effect.attack, effect.health, effect.source_id))
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)
    return ()


@dataclass(frozen=True)
class SetCapturedMinionStats(Effect):
    beneficiary: MinionReference
    attack: int | StatReference | None = None
    health: int | StatReference | None = None
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.beneficiary)
        SetStats(self.beneficiary.entity_id, self.attack, self.health, self.source_id).__post_init__()

    def validate_in_state(self, state):
        self.__post_init__()
        ref = self.beneficiary
        entity = state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
            raise ValueError('Captured stat setter borrowed an unknown or future minion allocation')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Captured stat setter has an unknown original source')


def set_captured_minion_stats(r, effect):
    from .resolver import set_stats
    effect.validate_in_state(r.state)
    validate_request(r, effect)
    if live_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id); return ()
    set_stats(r, SetStats(effect.beneficiary.entity_id, effect.attack, effect.health, effect.source_id))
    return ()


@dataclass(frozen=True)
class TransformCapturedMinion(Effect):
    beneficiary: MinionReference
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.beneficiary)
        Transform(self.beneficiary.entity_id,self.card_id).__post_init__()
        _source(self.source_id)

    def validate_in_state(self,state):
        self.__post_init__();ref=self.beneficiary;entity=state.entities.get(ref.entity_id)
        if entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order:
            raise ValueError('Captured transform borrowed an unknown or future minion allocation')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Captured transform has an unknown original source')


def transform_captured_minion(r,effect):
    from .resolver import transform_minion
    effect.validate_in_state(r.state);validate_request(r,effect)
    definition=r.registry.card(effect.card_id)
    if definition.kind!=CardType.MINION:raise ResolutionError('Captured transform requires a minion definition')
    entity=live_minion(r.state,effect.beneficiary)
    if entity is None:r.stale(effect,effect.beneficiary.entity_id);return ()
    return transform_minion(r,entity,definition,source_id=effect.source_id)


@dataclass(frozen=True)
class GrantCapturedKeyword(Effect):
    beneficiary: MinionReference | BoardPresenceReference
    keyword: Keyword
    source_id: int | None = None
    expires_turn: int | None = None
    duration: TimedKeywordSpec | None = None

    def __post_init__(self):
        if type(self.beneficiary) is BoardPresenceReference:
            self.beneficiary.__post_init__()
        else:
            reference_value(self.beneficiary)
        GrantKeyword(self.beneficiary.entity_id, self.keyword, self.source_id, self.expires_turn, duration=self.duration)

    def validate_in_state(self, state):
        self.__post_init__()
        if type(self.beneficiary) is BoardPresenceReference:
            validate_reward_presence(state, self.beneficiary)


def grant_captured_keyword(r, effect):
    from .resolver import grant_ability, validate_attachment_source
    effect.__post_init__(); validate_request(r, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    if live_reward_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    grant_ability(r, GrantKeyword(effect.beneficiary.entity_id, effect.keyword, effect.source_id, effect.expires_turn,
                                duration=effect.duration))


@dataclass(frozen=True)
class GrantCapturedSpellDamage(Effect):
    beneficiary: MinionReference | BoardPresenceReference
    amount: int
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        if type(self.beneficiary) is BoardPresenceReference:
            self.beneficiary.__post_init__()
        else:
            reference_value(self.beneficiary)
        GrantSpellDamage(self.beneficiary.entity_id, self.amount, self.source_id, self.expires_turn)

    def validate_in_state(self, state):
        self.__post_init__()
        ref = self.beneficiary
        if type(ref) is BoardPresenceReference:
            validate_reward_presence(state, ref)
        else:
            entity = state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
                raise ValueError('Spell Damage grant borrowed an unknown or future minion allocation')
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Spell Damage grant has an unknown original source')


def grant_captured_spell_damage(r, effect):
    from .resolver import grant_ability, validate_attachment_source
    effect.validate_in_state(r.state)
    validate_request(r, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    if live_reward_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    grant_ability(r, GrantSpellDamage(effect.beneficiary.entity_id, effect.amount,
        effect.source_id, effect.expires_turn))


@dataclass(frozen=True)
class RemoveCapturedKeyword(Effect):
    beneficiary: MinionReference
    keyword: Keyword
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.beneficiary)
        _source(self.source_id)
        if type(self.keyword) is not Keyword or self.keyword not in (
                Keyword.TAUNT, Keyword.LIFESTEAL, Keyword.ELUSIVE, Keyword.DIVINE_SHIELD):
            raise ValueError('Selective removal requires a supported ordinary minion keyword')


def remove_captured_keyword(r, effect):
    from .lifecycle import consume_keyword
    effect.__post_init__(); validate_request(r, effect)
    entity = live_minion(r.state, effect.beneficiary)
    if entity is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    if not any(a.kind == 'keyword' and a.keyword == effect.keyword and not a.consumed
               for a in entity.abilities):
        return ()
    consume_keyword(entity, effect.keyword)
    r.emit('keyword_removed', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller, keyword=effect.keyword.value)


@dataclass(frozen=True)
class GrantCapturedDeathrattle(Effect):
    beneficiary: MinionReference
    behavior_id: str
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.beneficiary)
        GrantDeathrattle(self.beneficiary.entity_id, self.behavior_id, self.source_id)


def grant_captured_deathrattle(r, effect):
    from .resolver import grant_ability, validate_attachment_source
    effect.__post_init__(); validate_request(r, effect)
    validate_attachment_source(r, effect.source_id, None)
    r.registry.behavior(effect.behavior_id)
    if live_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    grant_ability(r, GrantDeathrattle(effect.beneficiary.entity_id, effect.behavior_id, effect.source_id))


@dataclass(frozen=True)
class GrantDeckSacrificeAura(Effect):
    target_id: int
    spec: DeckSacrificeSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'deck sacrifice holder', 1); _source(self.source_id)
        if type(self.spec) is not DeckSacrificeSpec:
            raise ValueError('Deck sacrifice aura requires DeckSacrificeSpec')
        self.spec.__post_init__()
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'deck sacrifice expiry', 1)


@dataclass(frozen=True)
class DestroyForBuff(Effect):
    victim: MinionReference
    beneficiary: MinionReference
    attack: int = 0
    health: int = 0
    source_id: int | None = None
    require_live_beneficiary: bool = True

    def __post_init__(self):
        reference_value(self.victim)
        reward_values(self)
        if type(self.require_live_beneficiary) is not bool:
            raise ValueError('Destruction beneficiary policy requires an exact boolean')


@dataclass(frozen=True)
class SacrificeAdjacent(Effect):
    beneficiary: MinionReference
    attack: int = 0
    health: int = 0
    side: str = 'right'
    source_id: int | None = None

    def __post_init__(self):
        reward_values(self)
        if type(self.side) is not str or self.side not in ('left', 'right'):
            raise ValueError('Sacrifice side must be left or right')


@dataclass(frozen=True)
class DestroyCapturedMinion(Effect):
    """Accept destruction of the original victim, then run ordinary continuations."""
    victim: MinionReference | BoardPresenceReference
    source_id: int | None = None
    on_destroy: tuple[Effect, ...] = ()

    def __post_init__(self):
        if type(self.victim) is BoardPresenceReference:
            self.victim.__post_init__()
        else:
            reference_value(self.victim)
        _source(self.source_id)
        if type(self.on_destroy) is not tuple or any(not isinstance(e,Effect) for e in self.on_destroy):
            raise ValueError('Captured destruction requires immutable effect continuations')

    def validate_in_state(self, state):
        self.__post_init__()
        if type(self.victim) is BoardPresenceReference:
            validate_reward_presence(state, self.victim)


def destroy_captured_minion(r, effect):
    from .resolver import destroy
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Captured destruction source does not exist')
    effect.validate_in_state(r.state)
    if type(effect.victim) is MinionReference and r.registry.card(effect.victim.card_id).kind!=CardType.MINION:
        raise ResolutionError('Captured destruction requires an original minion')
    victim=live_reward_minion(r.state,effect.victim)
    if victim is None:
        r.stale(effect,effect.victim.entity_id);return ()
    destroy(r,Destroy(victim.id,effect.source_id))
    return effect.on_destroy


@dataclass(frozen=True)
class CompleteDestructionBuff(Effect):
    victim: MinionReference
    beneficiary: MinionReference
    first_death_id: int
    attack: int = 0
    health: int = 0
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.victim)
        reward_values(self)
        _integer(self.first_death_id, 'destruction death boundary', 1)


def validate_request(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Destruction reward source does not exist')
    for ref in (effect.beneficiary, *((effect.victim,) if hasattr(effect, 'victim') else ())):
        if type(ref) is BoardPresenceReference:
            validate_reward_presence(r.state, ref)
            continue
        if r.registry.card(ref.card_id).kind != CardType.MINION:
            raise ResolutionError('Destruction reward references require minion definitions')


def validate_reward_presence(state, reference):
    reference.__post_init__()
    if reference.entity_id not in state.entities or reference.presence_id >= state.next_order:
        raise ValueError('Captured reward borrowed an unknown or future board residence')


def live_reward_minion(state, reference):
    if type(reference) is not BoardPresenceReference:
        return live_minion(state, reference)
    from .board_presence import resolve_board_presence
    validate_reward_presence(state, reference)
    entity = resolve_board_presence(state, reference)
    return entity if entity is not None and entity.active and entity.health > 0 and not entity.doomed else None


def destroy_for_buff(r, effect):
    from .resolver import destroy
    validate_request(r, effect)
    victim = live_minion(r.state, effect.victim)
    beneficiary = live_minion(r.state, effect.beneficiary)
    if victim is None or effect.require_live_beneficiary and beneficiary is None:
        r.stale(effect, effect.victim.entity_id if victim is None else effect.beneficiary.entity_id)
        return ()
    first_death_id = r.state.next_death_id
    destroy(r, Destroy(victim.id, effect.source_id))
    return (CompleteDestructionBuff(effect.victim, effect.beneficiary, first_death_id,
                                   effect.attack, effect.health, effect.source_id),)


def sacrifice_adjacent(r, effect):
    validate_request(r, effect)
    beneficiary = live_minion(r.state, effect.beneficiary)
    if beneficiary is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    if deck_sacrifice_aura(r, beneficiary) is not None:
        from .pools import PoolQuery
        from .zones import DestroyDeckCard, zone_candidates
        candidates = zone_candidates(r, 3-beneficiary.controller, Zone.DECK,
            PoolQuery(kinds=(CardType.MINION,)), beneficiary.controller, effect.source_id)
        if not candidates:
            return ()  # An active replacement never falls back to a friendly victim.
        card = r.game._rng.choice(candidates)
        return (DestroyDeckCard(card, effect.source_id, on_destroy=(BuffCapturedMinion(
            effect.beneficiary, effect.attack, effect.health, effect.source_id),)),)
    board = r.player(beneficiary.controller).board
    index = board.index(beneficiary.id) + (1 if effect.side == 'right' else -1)
    if not 0 <= index < len(board):
        return ()
    victim = r.state.entities[board[index]]
    # Locations and dormant minions occupy physical space; never search past them.
    if victim.kind != CardType.MINION or not victim.active or victim.doomed or victim.health <= 0:
        return ()
    return destroy_for_buff(r, DestroyForBuff(MinionReference.capture(victim), effect.beneficiary,
                                             effect.attack, effect.health, effect.source_id))


def deck_sacrifice_aura(r, beneficiary):
    """Live controller-local presence; copies do not multiply one replacement."""
    matches = []
    for entity_id in r.player(beneficiary.controller).board:
        source = r.state.entities[entity_id]
        if source.kind != CardType.MINION or not source.active or source.health <= 0 or source.doomed:
            continue
        matches.extend(a for a in source.abilities if a.kind == 'deck_sacrifice' and
                       not a.consumed and beneficiary.card_id in a.deck_sacrifice.card_ids)
    return min(matches, key=lambda a: a.id) if matches else None


def buff_captured_minion(r, effect):
    from .resolver import buff
    validate_request(r, effect)
    if live_reward_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    buff(r, Buff(effect.beneficiary.entity_id, effect.attack, effect.health, effect.source_id))
    return ()


def grant_deck_sacrifice_aura(r, effect):
    from .lifecycle import attachment_id
    from .resolver import validate_attachment_source
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or not entity.active:
        r.stale(effect, effect.target_id)
        return ()
    ability = AbilityInstance(attachment_id(r.state), 'deck_sacrifice', source_id=effect.source_id,
                             deck_sacrifice=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)


def complete_destruction_buff(r, effect):
    from .resolver import buff
    validate_request(r, effect)
    if effect.first_death_id > r.state.next_death_id:
        raise ResolutionError('Destruction reward has a future death boundary')
    dead = any(d.id >= effect.first_death_id and d.entity_id == effect.victim.entity_id and
               d.card_id == effect.victim.card_id and d.controller == effect.victim.player_id
               for d in r.state.death_history)
    victim = same_instance(r.state, effect.victim)
    # Starship launch deliberately defers minion deaths. An accepted destruction
    # still earns its reward there; it must not create an extra death checkpoint.
    deferred = r.death_deferrals > 0 and victim is not None and victim.doomed
    if not (dead or deferred) or live_minion(r.state, effect.beneficiary) is None:
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    buff(r, Buff(effect.beneficiary.entity_id, effect.attack, effect.health, effect.source_id))
    return ()


def register(mechanics):
    mechanics.register_payload_type(MinionReference)
    mechanics.register(DestroyForBuff, destroy_for_buff)
    mechanics.register(DestroyCapturedMinion, destroy_captured_minion)
    mechanics.register(SacrificeAdjacent, sacrifice_adjacent)
    mechanics.register(CompleteDestructionBuff, complete_destruction_buff)
    mechanics.register(BuffCapturedMinion, buff_captured_minion)
    mechanics.register(FreezeCapturedMinion, freeze_captured_minion)
    mechanics.register(BuffCapturedMinionWithStartTrigger, buff_captured_minion_with_start_trigger)
    mechanics.register(SetCapturedMinionStats, set_captured_minion_stats)
    mechanics.register(TransformCapturedMinion, transform_captured_minion)
    mechanics.register(GrantCapturedKeyword, grant_captured_keyword)
    mechanics.register(GrantCapturedSpellDamage, grant_captured_spell_damage)
    mechanics.register(RemoveCapturedKeyword, remove_captured_keyword)
    mechanics.register(GrantCapturedDeathrattle, grant_captured_deathrattle)
    mechanics.register(GrantDeckSacrificeAura, grant_deck_sacrifice_aura)
    mechanics.register(SacrificeFullNamedBoard, sacrifice_full_named_board)


@dataclass(frozen=True)
class SacrificeFullNamedBoard(Effect):
    player_id: int
    required_card_id: str
    reward_card_id: str
    cause: object

    def __post_init__(self):
        from .summon_quantities import SummonCause
        _player(self.player_id);_behavior(self.required_card_id);_behavior(self.reward_card_id)
        if type(self.cause) is not SummonCause or self.cause.player_id!=self.player_id:
            raise ValueError('Whole-board sacrifice requires its original attributed summon cause')
        self.cause.__post_init__()


def sacrifice_full_named_board(r,effect):
    from .effects import DestroyBatch
    from .summon_quantities import SummonByCard,SummonEntryMaterial,validate_cause
    effect.__post_init__();validate_cause(r.state,r.registry,effect.cause)
    if any(r.registry.card(cid).kind!=CardType.MINION for cid in
            (effect.required_card_id,effect.reward_card_id)):
        raise ResolutionError('Whole-board sacrifice requires real named minion definitions')
    board=tuple(r.player(effect.player_id).board)
    if len(board)!=r.rules.max_board:return ()
    if any((e:=r.state.entities[i]).kind!=CardType.MINION or e.card_id!=effect.required_card_id or
            not e.active or e.health<=0 or e.doomed for i in board):return ()
    # One accepted physical group; ordinary destruction, death reactions and
    # capacity determine the later summon. No second sacrifice/death executor.
    return(DestroyBatch(board,effect.cause.source.entity_id),
        SummonByCard(effect.player_id,(SummonEntryMaterial(effect.reward_card_id),),effect.cause))
