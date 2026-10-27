"""Native remaining-ability doubling uses ordinary removable unit attachments.

Each marker identifies one completed native skill, rather than a numeric label.
Current copies retain markers and consumed skills; ordinary resets remove both.
"""
from dataclasses import dataclass,fields

from .effects import Effect
from .errors import ResolutionError
from .model import CardType,Enchantment,Event,Keyword,TriggerSpec,_int,_name
from .sacrifice import MinionReference,live_minion,reference_value

PREFIX='native_minion_ability_power.'


@dataclass(frozen=True)
class MinionAbilityPowerProfile:
    id:str
    card_id:str
    after_behavior_id:str
    base_values:tuple[tuple[str,int],...]


def validate_profile(registry,profile):
    if type(profile)is not MinionAbilityPowerProfile:raise ValueError('Typed native ability power profile required')
    for key in('id','card_id','after_behavior_id'):_name(getattr(profile,key),'native ability power '+key)
    if ':'in profile.id:raise ValueError('Native ability power profile cannot contain a marker separator')
    if type(profile.base_values)is not tuple or len(profile.base_values)!=3:
        raise ValueError('Native ability power requires three complete Titan values')
    for row in profile.base_values:
        if type(row)is not tuple or len(row)!=2:raise ValueError('Native ability values require immutable identity/value pairs')
        _name(row[0],'native ability value identity');_int(row[1],'native ability printed value',1)
        if ':'in row[0]:raise ValueError('Native ability identity cannot contain a marker separator')
    card=registry.card(profile.card_id)
    ids=tuple(key for key,_ in profile.base_values)
    if (len(set(ids))!=3 or card.kind!=CardType.MINION or Keyword.TITAN not in card.keywords or
            tuple(a.id for a in card.activated_abilities)!=ids or
            sum(t==TriggerSpec('minion_ability_used',profile.after_behavior_id)for t in card.triggers)!=1):
        raise ValueError('Native ability power lost its complete original Titan and completion trigger')
    registry.behavior(profile.after_behavior_id)


def marker(enchantment):
    label=enchantment.label
    if type(label)is not str or not label.startswith(PREFIX):return None
    parts=label[len(PREFIX):].split(':')
    if len(parts)!=2 or not all(parts):raise ValueError('Native ability marker lost its profile or completed skill')
    return tuple(parts)


def validate_marker_shape(enchantment):
    key=marker(enchantment)
    if key is None:return
    for part in key:_name(part,'native ability marker identity')
    if enchantment.source_id is None:raise ValueError('Native ability marker requires its original physical source')
    for field in fields(enchantment):
        if field.name not in('id','source_id','label')and getattr(enchantment,field.name)!=field.default:
            raise ValueError('Native ability unit marker cannot mix stats, cost, expiry or silence retention')


def validate_carrier(registry,card_id,kind,enchantments):
    seen=set()
    for enchantment in enchantments:
        key=marker(enchantment)
        if key is None:continue
        validate_marker_shape(enchantment)
        pid,skill=key;profile=registry.minion_ability_power_profiles.get(pid)
        if (profile is None or kind!=CardType.MINION or card_id!=profile.card_id or
                skill not in dict(profile.base_values)or key in seen):
            raise ValueError('Native ability marker borrowed an unknown profile, card or completed skill')
        seen.add(key)
    if len(seen)>2:raise ValueError('Three finite Titan skills have at most two remaining-ability doublings')


def profile_for(registry,entity):
    rows=[p for p in registry.minion_ability_power_profiles.values()if p.card_id==entity.card_id]
    if len(rows)>1:raise ValueError('Native ability power requires one independent source declaration')
    return rows[0]if rows else None


def value(registry,entity,skill_id):
    validate_carrier(registry,entity.card_id,entity.kind,entity.enchantments)
    profile=profile_for(registry,entity)
    if profile is None or skill_id not in dict(profile.base_values):
        raise ValueError('Native ability value has no original declared skill')
    count=sum(marker(e)is not None for e in entity.enchantments)
    return dict(profile.base_values)[skill_id]*(2**count)


def public_value(registry,entity,ability):
    if ability.consumed or profile_for(registry,entity)is None:return None
    return value(registry,entity,ability.activation.id)


@dataclass(frozen=True)
class DoubleRemainingMinionAbilities(Effect):
    profile_id:str
    source:MinionReference
    completion:Event

    def __post_init__(self):
        _name(self.profile_id,'native ability power profile');reference_value(self.source)
        event=self.completion
        # The body can change control before completion. Its original actor and
        # this physical carrier's completion-time controller are distinct facts.
        if (type(event)is not Event or event.kind!='minion_ability_used' or
                event.source_id!=self.source.entity_id or type(event.player_id)is not int or event.player_id not in(1,2)):
            raise ValueError('Native ability doubling requires its actual original completion event')


def double(r,effect):
    effect.__post_init__();profile=r.registry.minion_ability_power_profiles.get(effect.profile_id)
    event=effect.completion;skill=dict(event.data).get('ability_id')
    if (profile is None or effect.source.card_id!=profile.card_id or skill not in dict(profile.base_values)or
            dict(event.data).get('ability_card_id')!=skill or event.sequence>len(r.game._events)or
            event.sequence<1 or r.game._events[event.sequence-1]!=event):
        raise ResolutionError('Native ability doubling lost its original source, skill or published completion')
    source=live_minion(r.state,effect.source)
    if source is None:
        r.stale(effect,effect.source.entity_id);return ()
    validate_carrier(r.registry,source.card_id,source.kind,source.enchantments)
    abilities=[a for a in source.abilities if a.kind=='activated']
    if not any(not a.consumed for a in abilities):return ()
    if not any(a.activation.id==skill and a.consumed for a in abilities):
        raise ResolutionError('Native ability doubling requires the consumed original skill')
    key=(profile.id,skill)
    if any(marker(e)==key for e in source.enchantments):
        raise ResolutionError('Native ability completion cannot install its doubling twice')
    from .lifecycle import attachment_id
    source.enchantments.append(Enchantment(attachment_id(r.state),source_id=effect.source.entity_id,
        label=PREFIX+profile.id+':'+skill))
    r.emit('minion_ability_power_doubled',source_id=source.id,target_id=source.id,
        player_id=source.controller,amount=2,ability_card_id=skill)
    return ()


def validate_game(game):
    registry,state=game.registry,game._state
    for entity in state.entities.values():
        validate_carrier(registry,entity.card_id,entity.kind,entity.enchantments)
        marked=[marker(e)for e in entity.enchantments if marker(e)is not None]
        if marked and entity.zone.value=='board':
            consumed={a.activation.id for a in entity.abilities if a.kind=='activated'and a.consumed}
            if any(skill not in consumed for _,skill in marked):
                raise ValueError('Native ability power cannot precede consumption of its original skill')
    for death in state.death_history:
        validate_carrier(registry,death.card_id,registry.card(death.card_id).kind,death.enchantments)


def register(mechanics):mechanics.register(DoubleRemainingMinionAbilities,double)
