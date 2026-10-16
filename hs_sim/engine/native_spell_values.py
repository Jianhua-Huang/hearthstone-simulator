"""Generated native base damage: immutable source value, physical copy, actual CAST."""
from dataclasses import dataclass,replace
from .effects import AddToHand,Effect,_integer,_player
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance,CardType,SpellBaseDamageValue,_name


@dataclass(frozen=True)
class SpellBaseDamageProfile:
    card_id:str
    source_card_id:str
    def __post_init__(self):
        _name(self.card_id,'native damage spell');_name(self.source_card_id,'native damage death declaration')


def validate_profile(registry,profile):
    if type(profile)is not SpellBaseDamageProfile:raise ValueError('Expected native base damage profile')
    profile.__post_init__();card=registry.card(profile.card_id);source=registry.card(profile.source_card_id)
    if card.kind!=CardType.SPELL or not card.hand_playable or card.on_play is None or source.kind!=CardType.MINION or source.deathrattle is None:
        raise ValueError('Native base damage requires a real spell and original minion Deathrattle')


def validate_ability(state,registry,ability):
    ability.__post_init__()
    if ability.kind!='spell_base_value':raise ValueError('Expected native physical spell value')
    value=ability.spell_base_value;profile=registry.spell_value_profiles.get(value.card_id)
    if profile is None:raise ValueError('Native spell value lost its complete registered declaration')
    validate_profile(registry,profile)
    if not 1<=value.deathrattle_id<=len(state.deathrattle_history):raise ValueError('Native spell value borrowed an unknown Deathrattle')
    row=state.deathrattle_history[value.deathrattle_id-1];capture=row.capture
    if row.id!=value.deathrattle_id or capture.carrier_id!=ability.source_id or capture.kind!=CardType.MINION or row.execution_order is None or value.amount!=row.source_attack:
        raise ValueError('Native spell value differs from its actual original Deathrattle Attack')
    if capture.ability.behavior_id!=registry.card(profile.source_card_id).deathrattle:
        raise ValueError('Native spell value borrowed an unrelated source body')


def validate_carrier(state,registry,card_id,kind,abilities):
    rows=tuple(a for a in abilities if a.kind=='spell_base_value')
    if not rows:return
    if kind!=CardType.SPELL or len(rows)!=1 or rows[0].spell_base_value.card_id!=card_id:
        raise ValueError('Native base value requires its single original spell carrier')
    validate_ability(state,registry,rows[0])


def install(state,registry,entity,value):
    if type(value)is not SpellBaseDamageValue:raise ValueError('Expected complete generated spell value')
    value.__post_init__();row=state.deathrattle_history[value.deathrattle_id-1]if value.deathrattle_id<=len(state.deathrattle_history)else None
    if row is None:raise ValueError('Native generation lost its actual source Deathrattle')
    ability=AbilityInstance(attachment_id(state),'spell_base_value',source_id=row.capture.carrier_id,spell_base_value=value)
    validate_ability(state,registry,ability)
    if entity.kind!=CardType.SPELL or entity.card_id!=value.card_id or any(a.kind=='spell_base_value'for a in entity.abilities):
        raise ValueError('Native spell value cannot be installed on a foreign or already bound carrier')
    entity.abilities.append(ability)


@dataclass(frozen=True)
class CreateDeathrattleSpell(Effect):
    player_id:int
    card_id:str
    deathrattle_id:int
    def __post_init__(self):
        _player(self.player_id);_name(self.card_id,'generated native spell');_integer(self.deathrattle_id,'original generation Deathrattle',1)


def create(r,request):
    request.__post_init__()
    if request.deathrattle_id>len(r.state.deathrattle_history):raise ResolutionError('Native spell creation has no actual source Deathrattle')
    row=r.state.deathrattle_history[request.deathrattle_id-1]
    if row.source_attack is None:raise ResolutionError('Native spell generation requires its actually started body')
    value=SpellBaseDamageValue(request.card_id,row.source_attack,row.id)
    from .opening import create_hand_card
    create_hand_card(r,AddToHand(request.player_id,request.card_id,row.capture.carrier_id),native_spell_value=value)
    return()


def capture(r,record):
    rows=tuple(a for a in r.state.entities[record.source_id].abilities if a.kind=='spell_base_value')
    required=record.card_id in r.registry.spell_value_profiles
    if not required and not rows:return record
    if len(rows)!=1 or rows[0].spell_base_value.card_id!=record.card_id:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Native generated spell lacks its bound original base damage: '+record.card_id)
    validate_ability(r.state,r.registry,rows[0])
    record=replace(record,native_spell_value=rows[0]);r.state.cast_history[record.id-1]=record
    return record


def validate_record(state,registry,record,live,owners):
    ability=record.native_spell_value;required=record.card_id in registry.spell_value_profiles
    if ability is None:
        if required and record.payload_started and record.failure is None:raise ValueError('Accepted native spell lost its original frozen value')
        return
    validate_ability(state,registry,ability)
    if not required or ability.spell_base_value.card_id!=record.card_id or ability.id>=state.next_attachment_id:
        raise ValueError('Native cast value lost its original face or allocation')
    if ability.id in live and live[ability.id]!=('ability',record.source_id,ability):raise ValueError('Native cast value borrowed another physical attachment')
    if ability.id in owners and owners[ability.id]!=record.source_id:raise ValueError('Native cast value migrated across physical spells')
    owners[ability.id]=record.source_id


def public_value(entity):
    rows=tuple(a for a in entity.abilities if a.kind=='spell_base_value')
    return None if not rows else rows[0].spell_base_value.amount


def inherit_play(r,entity,original_state,play_id):
    """One exact selected hand occurrence, including a countered original card."""
    if entity.card_id not in r.registry.spell_value_profiles:return
    from .play_history import play_record
    original=play_record(original_state,play_id)
    if original.card_id!=entity.card_id or original.kind!=CardType.SPELL:
        raise ValueError('Native replay value borrowed a different selected hand occurrence')
    values=tuple(c.native_spell_value for c in original_state.cast_history
        if c.play_id==original.id and c.card_id==original.card_id and c.native_spell_value is not None)
    if not values:
        source=original_state.entities[original.source_id]
        values=tuple(a for a in source.abilities if a.kind=='spell_base_value'and a.spell_base_value.card_id==original.card_id)
    if not values or any(a.spell_base_value!=values[0].spell_base_value for a in values):
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Selected native spell occurrence lacks recoverable original parameters')
    for ability in values:validate_ability(original_state,r.registry,ability)
    install(r.state,r.registry,entity,values[0].spell_base_value)


def register(mechanics):mechanics.register(CreateDeathrattleSpell,create)
