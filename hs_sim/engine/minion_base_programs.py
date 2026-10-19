"""Persistent minion bases below ordinary modifiers; not a repeating stat aura."""
from dataclasses import asdict,dataclass
import json

from .effects import SetStats,_integer
from .model import CardType,Enchantment,MinionBaseStatsOrigin,PlayerEffectSpec,Zone

ACCEPTED='minion_base_program_accepted'
LIVE=(Zone.HAND,Zone.DECK,Zone.PLAY,Zone.BOARD)


@dataclass(frozen=True)
class MinionBaseStatsProfile:
    program_id:str
    card_id:str
    attack:int
    health:int

    def __post_init__(self):
        from .model import _name
        _name(self.program_id,'minion base program');_name(self.card_id,'minion base source')
        _integer(self.attack,'minion base Attack',0);_integer(self.health,'minion base Health',1)


def validate_profile(registry,profile):
    if type(profile)is not MinionBaseStatsProfile:raise ValueError('Typed minion base profile required')
    profile.__post_init__()
    if registry.card(profile.card_id).kind!=CardType.SPELL or registry.player_effect(profile.program_id)!=PlayerEffectSpec(profile.program_id,profile.card_id):
        raise ValueError('Minion bases require their own independent persistent spell program')


def profiles(registry):return getattr(registry,'minion_base_stats_profiles',{})
def eligible(entity):return entity.kind==CardType.MINION and entity.zone in LIVE and not entity.starship_building


def origin(player_id,instance,profile):
    return MinionBaseStatsOrigin(profile.program_id,player_id,instance.id,instance.source_id,
        instance.source_card_id,instance.created_turn,instance.entered_order,profile.attack,profile.health)


def latest(state,registry,player_id):
    declared=profiles(registry)
    return next(((e,declared[e.spec_id])for e in reversed(state.players[player_id].player_effects)
        if e.spec_id in declared),None)


def apply_to_entity(state,registry,entity):
    if not profiles(registry)or not eligible(entity):return
    current=latest(state,registry,entity.controller)
    if current is None:return
    instance,profile=current;stamp=origin(entity.controller,instance,profile)
    if any(e.minion_base_stats==stamp for e in entity.enchantments):return
    from .lifecycle import attachment_id,refresh_entity
    entity.enchantments.append(Enchantment(attachment_id(state),source_id=instance.source_id,
        remove_on_silence=False,label='minion_base_stats',minion_base_stats=stamp))
    refresh_entity(entity)


def synchronize(state,registry):
    if not profiles(registry)or not any(latest(state,registry,p)for p in(1,2)):return
    for entity in state.entities.values():apply_to_entity(state,registry,entity)


def packed(stamp):return json.dumps(asdict(stamp),sort_keys=True,separators=(',',':'))


def install(r,player_id,instance):
    profile=profiles(r.registry).get(instance.spec_id)
    if profile is None:return
    source=r.state.entities[instance.source_id]
    if (source.card_id,source.kind,source.controller,instance.source_card_id)!=(profile.card_id,CardType.SPELL,player_id,profile.card_id):
        raise ValueError('Minion base program lost its actual controlled spell source')
    stamp=origin(player_id,instance,profile)
    r.emit(ACCEPTED,source_id=source.id,player_id=player_id,origin=packed(stamp),turn=r.state.turn,_capture=False)
    targets=tuple(e for e in r.state.entities.values()if e.controller==player_id and eligible(e))
    reset=tuple((e,(e.attack,e.health,e.max_health))for e in targets
        if e.zone==Zone.BOARD and e.active and e.health>0 and not e.doomed)
    for entity in targets:apply_to_entity(r.state,r.registry,entity)
    # Only the existing board gets the original one-time reset and healing.
    # Future explicit 1/1 copy operands remain ordinary later modifiers.
    from .resolver import _set_stats_on_entity
    for entity,old in reset:
        _set_stats_on_entity(r,SetStats(entity.id,profile.attack,profile.health,source.id),entity,original_stats=old)


def validate_origin(state,registry,stamp):
    if type(stamp)is not MinionBaseStatsOrigin:raise ValueError('Typed original minion base required')
    stamp.__post_init__();profile=profiles(registry).get(stamp.program_id)
    if (profile is None or (stamp.source_card_id,stamp.attack,stamp.health)!=(profile.card_id,profile.attack,profile.health)or
            stamp.source_id not in state.entities or stamp.instance_id>=state.next_attachment_id or
            stamp.entered_order>=state.next_order or stamp.created_turn>state.turn):
        raise ValueError('Minion base changed its original declaration or allocation')


def validate_shape(state,registry):
    for entity in state.entities.values():
        stamps=[e.minion_base_stats for e in entity.enchantments if e.minion_base_stats is not None]
        if stamps and entity.kind!=CardType.MINION:raise ValueError('Only minions carry minion bases')
        if len(set(stamps))!=len(stamps):raise ValueError('Duplicate physical minion base layer')
        for stamp in stamps:validate_origin(state,registry,stamp)


def validate_boundary(game):
    from .hero_health_history import effective_events
    validate_shape(game._state,game.registry);accepted={}
    for event in effective_events(game._events):
        if event.kind!=ACCEPTED:continue
        from .serialization import _row
        stamp=MinionBaseStatsOrigin(**_row(json.loads(dict(event.data)['origin']),MinionBaseStatsOrigin))
        validate_origin(game._state,game.registry,stamp)
        if (event.source_id,event.player_id,dict(event.data)['turn'])!=(stamp.source_id,stamp.player_id,stamp.created_turn)or stamp in accepted:
            raise ValueError('Minion base program changed its original acceptance')
        accepted[stamp]=event.sequence
    for player in game._state.players.values():
        for instance in player.player_effects:
            profile=profiles(game.registry).get(instance.spec_id)
            if profile is not None and origin(player.id,instance,profile)not in accepted:
                raise ValueError('Persistent minion base lost its original acceptance')
    for entity in game._state.entities.values():
        for enchantment in entity.enchantments:
            if enchantment.minion_base_stats is not None and enchantment.minion_base_stats not in accepted:
                raise ValueError('Minion base borrowed an unaccepted program')
