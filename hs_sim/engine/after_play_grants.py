"""Timed physical hand attachments executed after the original whole hand play."""
from dataclasses import dataclass

from .effects import Effect, _behavior, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id, active_abilities
from .model import AbilityInstance, CardType, Zone
from .zones import CardReference, HAND_TYPES


@dataclass(frozen=True)
class GrantAfterPlay(Effect):
    card: CardReference
    behavior_id: str
    source_id: int

    def __post_init__(self):
        if type(self.card) is not CardReference or self.card.zone != Zone.HAND:
            raise ValueError('After-play grant requires an original hand reference')
        self.card.__post_init__(); _behavior(self.behavior_id)
        _integer(self.source_id, 'after-play source', 1)


@dataclass(frozen=True)
class GrantRandomAfterPlay(Effect):
    player_id: int
    behavior_id: str
    source_id: int
    tribes_any: tuple[str, ...] = ()

    def __post_init__(self):
        _player(self.player_id); _behavior(self.behavior_id)
        _integer(self.source_id, 'after-play source', 1)
        from .model import TribeChangeSpec
        if self.tribes_any: TribeChangeSpec('set',self.tribes_any).__post_init__()
        elif type(self.tribes_any) is not tuple: raise ValueError('Expected immutable recipient tribes')


@dataclass(frozen=True)
class RunAfterPlay(Effect):
    play_id: int
    ability_id: int

    def __post_init__(self):
        _integer(self.play_id, 'after-play original play', 1)
        _integer(self.ability_id, 'after-play original attachment', 1)


def install(state, entity, behavior_id, source_id):
    ability=AbilityInstance(attachment_id(state),'after_play',source_id=source_id,
        behavior_id=behavior_id,expires_turn=state.turn)
    ability.__post_init__();entity.abilities.append(ability)
    return ability


def grant(r,effect):
    effect.__post_init__();r.registry.behavior(effect.behavior_id)
    from .zones import source_exists
    source_exists(r,effect.source_id)
    ref=effect.card;entity=r.state.entities.get(ref.entity_id)
    if entity is None or entity.zone!=Zone.HAND or CardReference.capture(entity)!=ref:
        r.emit('zone_target_skipped',target_id=ref.entity_id,reason='after_play_hand_departed')
        return
    if entity.kind not in HAND_TYPES or not r.registry.card(entity.card_id).hand_playable:
        raise ResolutionError('After-play grants require a physical hand-playable card')
    ability=install(r.state,entity,effect.behavior_id,effect.source_id)
    r.emit('ability_granted',target_id=entity.id,source_id=effect.source_id,
        ability_id=ability.id,ability_kind='after_play')


def grant_random(r,effect):
    effect.__post_init__();r.registry.behavior(effect.behavior_id)
    from .zones import source_exists
    from .costs import quote_cost
    from .tribes import has_any_tribe
    source_exists(r,effect.source_id);player=r.player(effect.player_id)
    candidates=[]
    for eid in player.hand:
        entity=r.state.entities[eid];definition=r.registry.card(entity.card_id)
        if not definition.hand_playable or not definition.manual_playable:continue
        if effect.tribes_any and (entity.kind!=CardType.MINION or not has_any_tribe(
                r.registry,entity,effect.tribes_any)):continue
        # Native "playable" is a price filter, not a target/board/requirement search.
        # Precise alternate-resource qualification remains an M6 policy.
        if quote_cost(r.state,r.registry,entity).amount<=player.mana:candidates.append(entity)
    if not candidates:return
    entity=r.game._rng.choice(candidates)
    return (GrantAfterPlay(CardReference.capture(entity),effect.behavior_id,effect.source_id),)


def capture(entity):return active_abilities(entity,'after_play')


def validate_record(state,registry,record):
    if type(record.after_play) is not tuple or len({a.id for a in record.after_play})!=len(record.after_play):
        raise ValueError('After-play acceptance requires its complete unique attachment tuple')
    for ability in record.after_play:
        ability.__post_init__()
        if (ability.kind!='after_play' or ability.id>=state.next_attachment_id or
                ability.source_id not in state.entities or ability.expires_turn!=record.turn):
            raise ValueError('After-play acceptance changed its original attachment or turn')
        registry.behavior(ability.behavior_id)


def completed(record):return tuple(RunAfterPlay(record.id,a.id)for a in record.after_play)


def accepted_ability(state,registry,effect):
    effect.__post_init__()
    from .play_history import play_record
    record=play_record(state,effect.play_id);validate_record(state,registry,record)
    ability=next((a for a in record.after_play if a.id==effect.ability_id),None)
    if ability is None:raise ValueError('After-play execution borrowed another acceptance attachment')
    return record,ability


def run(r,effect):
    record,ability=accepted_ability(r.state,r.registry,effect)
    if not record.completed or record.interrupted:
        raise ResolutionError('After-play execution requires its completed original physical play')
    return (r.call(ability.behavior_id,record.source_id,record.player_id,
        record.target_id,play=record),)


def register(mechanics):
    mechanics.register(GrantAfterPlay,grant)
    mechanics.register(GrantRandomAfterPlay,grant_random)
    mechanics.register(RunAfterPlay,run)
