"""A real minion's frozen spell text, ordinary targets and ordinary spell CAST."""
from dataclasses import dataclass, replace
from functools import lru_cache

from .effects import AddToHand, Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, SpellManaBudgetLink, SpellSchool, TargetMode, _name
from .registry import UnsupportedDefinitionError


@dataclass(frozen=True)
class CarvedSpellProfile:
    card_id: str
    source_card_id: str
    school: SpellSchool | None = None
    teaching: bool = False

    def __post_init__(self):
        _name(self.card_id,'carved carrier');_name(self.source_card_id,'carved source')
        if self.school is not None and type(self.school) is not SpellSchool:
            raise ValueError('Carved spell school requires its original enum')
        if type(self.teaching)is not bool or self.teaching and self.school is not None:
            raise ValueError('Native student teaching requires its explicit any-school profile')


def validate_profile(registry,profile):
    if type(profile) is not CarvedSpellProfile:raise ValueError('Expected a native carved spell profile')
    profile.__post_init__();card=registry.card(profile.card_id);source=registry.card(profile.source_card_id)
    if (card.kind!=CardType.MINION or card.metadata is None or card.metadata.collectible or card.battlecry is None or
            source.kind!=CardType.MINION or source.battlecry is None):
        raise ValueError('Carved spell requires its real noncollectible minion and original creator Battlecry')


def profile_for(registry,card_id):
    profile=registry.carved_spell_profiles.get(card_id)
    if profile is None:raise UnsupportedDefinitionError('Unregistered carved spell carrier: '+card_id)
    return profile


def spell_target_definition(registry,carrier,spell_id):
    from .choose_one import effective
    from .targeting import target_spec
    spell=registry.card(spell_id)
    if spell.kind!=CardType.SPELL or not spell.hand_playable or spell.choice_only or spell.target_condition is not None:
        raise UnsupportedDefinitionError('Unsupported original carved spell face or conditional target contract')
    variants=(spell,) if spell.choose_one is None else tuple(effective(spell,b.id)
        for b in (*spell.choose_one.branches,spell.choose_one.combined))
    targets=[]
    for variant in variants:
        spec=target_spec(variant)
        if spec is not None and (spec,variant.target_rule) not in targets:targets.append((spec,variant.target_rule))
    if len(targets)>1:
        raise UnsupportedDefinitionError('Carved spell has incompatible branch target domains')
    spec,rule=targets[0] if targets else (None,'any_entity')
    # A targeted Battlecry minion can still be played when no target exists.
    if spec is not None:spec=replace(spec,mode=TargetMode.IF_AVAILABLE)
    return replace(carrier,requires_target=False,targeting=spec,target_rule=rule,target_condition=None)


def validate_spell(registry,card_id,spell_id):
    profile=profile_for(registry,card_id);spell=registry.card(spell_id)
    if profile.school is not None and spell.spell_school!=profile.school:
        raise ValueError('Carved spell differs from its original school profile')
    spell_target_definition(registry,registry.card(card_id),spell_id)


def validate_ability(registry,ability):
    if ability.carved_spell_id is None:return
    ability.__post_init__();profile=profile_for(registry,ability.battlecry_card_id)
    if ability.kind!='battlecry' or ability.behavior_id!=registry.card(profile.card_id).battlecry:
        raise ValueError('Carved value lost its exact native Battlecry declaration')
    validate_spell(registry,profile.card_id,ability.carved_spell_id)


def validate_payload(registry,payload):
    if payload.carved_spell_id is None:return
    profile=profile_for(registry,payload.card_id)
    if payload.behavior_id!=registry.card(profile.card_id).battlecry:
        raise ValueError('Carved payload borrowed a different original body')
    validate_spell(registry,payload.card_id,payload.carved_spell_id)


def target_definition(registry,source,definition):
    if source.card_id!=definition.id:return definition
    values=[a for a in active_abilities(source,'battlecry') if a.carved_spell_id is not None]
    if not values:return definition
    if len(values)!=1:raise UnsupportedDefinitionError('Carved physical carrier requires one original spell body')
    validate_ability(registry,values[0])
    return spell_target_definition(registry,definition,values[0].carved_spell_id)


def validate_creation(registry,effect):
    spell_id=getattr(effect,'carved_spell_id',None)
    if spell_id is None:return
    if (type(effect) is not AddToHand or effect.source_id is None or effect.cost is not None or
            effect.expires_turn is not None or effect.spell_repeat is not None or effect.choose_branch is not None or
            effect.minion_grant is not None or effect.minion_stats is not None or effect.spell_damage or
            effect.combined_shatter or effect.revealed_to):
        raise ValueError('Carved creation requires a plain source-bound native hand minion')
    validate_spell(registry,effect.card_id,spell_id)


def install(registry,entity,spell_id):
    if spell_id is None:return
    validate_spell(registry,entity.card_id,spell_id)
    rows=[(i,a) for i,a in enumerate(entity.abilities) if a.kind=='battlecry' and a.battlecry_card_id==entity.card_id]
    if len(rows)!=1:raise ResolutionError('Carved creation lost its one original native body')
    i,ability=rows[0];entity.abilities[i]=replace(ability,carved_spell_id=spell_id)


@dataclass(frozen=True)
class CreateCarvedTreants(Effect):
    player_id: int
    card_id: str
    pool_id: str
    source_id: int

    def __post_init__(self):
        _player(self.player_id);_name(self.card_id,'carved Treant');_name(self.pool_id,'original Nature pool')
        _source(self.source_id)
        if self.source_id is None:raise ValueError('Carved Treants require their actual original creator')


def create_treants(r,effect):
    from .spell_mana_budget import candidates
    from .pools import sample_candidates
    effect.__post_init__();profile=profile_for(r.registry,effect.card_id)
    if profile.school is not SpellSchool.NATURE:raise ValueError('Three-Treant budget requires its real Nature profile')
    if effect.source_id not in r.state.entities:raise ResolutionError('Original carved creator is absent')
    link=SpellManaBudgetLink(effect.pool_id,SpellSchool.NATURE,12,12,r.state.entities[effect.source_id].card_id)
    rows=candidates(r.registry,r.game._generation_context,link,effect.player_id)
    for row in rows:validate_spell(r.registry,effect.card_id,row.card_id)
    costs={row.card_id:r.registry.pool_card(row.card_id).cost for row in rows}
    @lru_cache(None)
    def feasible(slots,amount):
        if slots==0:return amount==0
        return any(cost<=amount and feasible(slots-1,amount-cost) for cost in set(costs.values()))
    if not feasible(3,12):
        raise UnsupportedDefinitionError('Complete three-spell Nature budget is unavailable in this declared pool')
    remaining=12;selected=[]
    for slots in (2,1,0):
        eligible=tuple(row for row in rows if costs[row.card_id]<=remaining and feasible(slots,remaining-costs[row.card_id]))
        card_id,=sample_candidates(r.game._rng,eligible,1,replacement=True)
        selected.append(card_id);remaining-=costs[card_id]
    if remaining:raise ResolutionError('Original carved plan lost its complete printed-mana amount')
    return tuple(AddToHand(effect.player_id,effect.card_id,effect.source_id,carved_spell_id=cid) for cid in selected)


@dataclass(frozen=True)
class CastCarvedSpell(Effect):
    battlecry_id: int

    def __post_init__(self):_integer(self.battlecry_id,'original carved Battlecry',1)

    def validate_in_state(self,state,registry):
        from .battlecries import battlecry_record
        self.__post_init__();record=battlecry_record(state,self.battlecry_id)
        profile=profile_for(registry,record.payload.card_id)
        if record.payload.behavior_id!=registry.card(profile.card_id).battlecry:
            raise ValueError('Carved work borrowed a different native body')
        validate_payload(registry,record.payload)
        if record.completed or record.interrupted or not record.payload_started:
            raise ValueError('Carved work requires an active accepted original Battlecry')
        return record


def cast_spell(r,effect):
    from .choose_one import automatic_branch,effective
    from .spell_casts import CastSpell
    from .targeting import target_spec
    record=effect.validate_in_state(r.state,r.registry)
    spell_id=record.payload.carved_spell_id
    if spell_id is None:
        r.emit('carved_spell_empty',source_id=record.source_id,player_id=record.player_id)
        return ()
    card=r.registry.card(spell_id)
    branch_id=automatic_branch(r,card,record.player_id,origin='cast_effect')
    target=record.target_id if target_spec(effective(card,branch_id)) is not None else None
    return (CastSpell(record.player_id,spell_id,record.source_id,target_id=target,
        targeting='explicit',choices='random',branch_id=branch_id),)


def validate_boundary(game):
    for entity in game._state.entities.values():
        for ability in entity.abilities:
            if ability.carved_spell_id is not None:validate_ability(game.registry,ability)
    for record in game._state.play_history:
        for payload in record.battlecries:validate_payload(game.registry,payload)
    for record in game._state.battlecry_history:validate_payload(game.registry,record.payload)


def register(mechanics):
    mechanics.register(CreateCarvedTreants,create_treants)
    mechanics.register(CastCarvedSpell,cast_spell)
