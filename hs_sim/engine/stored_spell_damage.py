"""Local physical-spell bonuses, captured by the shared actual CAST pipeline."""
from dataclasses import dataclass,fields,replace
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .lifecycle import attachment_id,refresh_entity
from .model import AbilityInstance,CardType,Zone
from .pools import PoolQuery
from .zones import reference_entity,reference_value,source_exists,zone_candidates,CardReference


def validate_local_ability(ability):
    if type(ability)is not AbilityInstance:raise ValueError('Local Spell Damage needs a complete ability')
    ability.__post_init__()
    if ability.kind!='spell_damage' or ability.spell_damage<=0 or ability.source_id is None:
        raise ValueError('Local Spell Damage needs its positive original granted source')
    allowed={'id','kind','source_id','spell_damage'}
    if any(getattr(ability,f.name)!=f.default for f in fields(ability)if f.name not in allowed):
        raise ValueError('Local Spell Damage cannot carry native, temporary or unrelated ability state')


@dataclass(frozen=True)
class GrantStoredSpellDamage(Effect):
    card:CardReference
    amount:int
    source_id:int
    def __post_init__(self):
        reference_value(self.card);_integer(self.amount,'local Spell Damage',1);_integer(self.source_id,'local bonus source',1)
    def validate_in_state(self,state):
        self.__post_init__();entity=state.entities.get(self.card.entity_id)
        if entity is None or self.card.zone_epoch>entity.zone_epoch or self.source_id not in state.entities:
            raise ValueError('Local bonus has an unknown source or future physical spell')


def grant(r,effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    entity=reference_entity(r,effect.card)
    if entity is None:return ()
    if entity.kind!=CardType.SPELL or entity.zone not in(Zone.HAND,Zone.DECK):
        raise ResolutionError('Local stored Spell Damage requires an original hand/deck spell')
    ability=AbilityInstance(attachment_id(r.state),'spell_damage',source_id=effect.source_id,spell_damage=effect.amount)
    validate_local_ability(ability);entity.abilities.append(ability);refresh_entity(entity)
    r.emit('stored_spell_damage_granted',source_id=effect.source_id,target_id=entity.id,player_id=entity.controller)
    return ()


@dataclass(frozen=True)
class DrawMatchingSpellDamage(Effect):
    player_id:int
    query:PoolQuery
    source_id:int
    amount:int
    repetitions:int=1
    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'matching spell source',1);_integer(self.amount,'matching spell bonus',1)
        if type(self.repetitions)is not int or self.repetitions not in(1,2):raise ValueError('Matching bonus repeats require the actual max2 Kindred component')
        if type(self.query)is not PoolQuery:raise ValueError('Matching spell draw requires a complete typed query')
        self.query.__post_init__()
        if self.query.kinds!=(CardType.SPELL,):raise ValueError('Local bonus draw requires an explicit spell query')
    def validate_in_state(self,state):
        self.__post_init__()
        if self.source_id not in state.entities:raise ValueError('Matching bonus draw has an unknown source')


def draw(r,effect):
    from .draw_casts import draw_one
    effect.__post_init__();source_exists(r,effect.source_id)
    candidates=zone_candidates(r,effect.player_id,Zone.DECK,effect.query,effect.player_id,effect.source_id)
    if not candidates:return ()
    card=r.game._rng.choice(candidates)
    # One original draw window: enchant before draw_one can accept a drawn cast.
    for _ in range(effect.repetitions):grant(r,GrantStoredSpellDamage(card,effect.amount,effect.source_id))
    return draw_one(r,effect.player_id,card=card,source_id=effect.source_id)


def capture(r,record):
    source=r.state.entities[record.source_id]
    if source.kind!=CardType.SPELL:raise ResolutionError('Local cast bonus requires its original physical spell')
    abilities=tuple(sorted((a for a in source.abilities if a.kind=='spell_damage'and not a.consumed),key=lambda a:a.id))
    for ability in abilities:validate_local_ability(ability)
    if abilities:
        record=replace(record,local_spell_damage=abilities)
        r.state.cast_history[record.id-1]=record
    return record


def validate_record(state,record,live,owners):
    for ability in record.local_spell_damage:
        validate_local_ability(ability)
        if ability.id>=state.next_attachment_id or ability.source_id not in state.entities:
            raise ValueError('Local cast bonus has an unknown source or future attachment')
        if ability.id in live and live[ability.id]!=('ability',record.source_id,ability):
            raise ValueError('Local cast bonus borrowed another physical attachment')
        if ability.id in owners and owners[ability.id]!=record.source_id:
            raise ValueError('Local cast bonus cannot migrate between physical spells')
        owners[ability.id]=record.source_id


def register(mechanics):
    mechanics.register(GrantStoredSpellDamage,grant)
    mechanics.register(DrawMatchingSpellDamage,draw)
