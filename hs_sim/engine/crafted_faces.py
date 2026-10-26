"""Immutable complete minion compositions; source candidate pools are separate."""
import base64
import binascii
import json
from dataclasses import dataclass,fields,replace

from .model import CardDefinition,CardType,_name

PREFIX='crafted:'
VERSION='crafted-minion-v1'
NATIVE_DORMANT_ENTRY='crafted_dormant_entry'
TUPLES=('triggers','auras','cost_auras','keyword_auras','battlecry_repeats','deathrattle_repeats',
    'combo_repeats','spell_repeats','health_loss_replacements','health_loss_floors','summon_quantities',
    'weapon_wear_policies','health_rules','activated_abilities','limited_triggers','hero_power_repeats',
    'end_turn_repeats','intrinsic_costs','attack_policies','stat_relations','timed_keywords')
PART_FIELDS=frozenset(('id','name','kind','cost','attack','health','metadata','keywords','on_play',
    'battlecry','deathrattle','combo','requires_target','target_rule','targeting','spell_damage',
    'spell_damage_schools','cleave','dormant_turns','native_condition','minion_death_cost','native_deathrattle','hand_progress',*TUPLES))


@dataclass(frozen=True)
class CraftedMinionBlueprint:
    template_card_id:str
    first_tribe:str
    second_tribe:str

    def __post_init__(self):
        for key in('template_card_id','first_tribe','second_tribe'):_name(getattr(self,key),'crafted '+key)
        if self.template_card_id.startswith((PREFIX,'assemble:')):raise ValueError('Crafting requires a static original template')


@dataclass(frozen=True)
class CraftedMinionRecipe:
    template_card_id:str
    first_card_id:str
    second_card_id:str

    def __post_init__(self):
        for key in('template_card_id','first_card_id','second_card_id'):
            value=getattr(self,key);_name(value,'crafted '+key)
            if value.startswith((PREFIX,'assemble:')):raise ValueError('Recursive crafted ingredients are unsupported')
        if self.template_card_id in(self.first_card_id,self.second_card_id):
            raise ValueError('An uninitialized creation cannot be its own ingredient')

    @property
    def parts(self):return(self.first_card_id,self.second_card_id)

    @property
    def card_id(self):
        self.__post_init__()
        data=[VERSION,self.template_card_id,self.first_card_id,self.second_card_id]
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf8')
        return PREFIX+base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def recipe_from_id(card_id):
    if type(card_id)is not str or not card_id.startswith(PREFIX)or len(card_id)>4096:
        raise ValueError('Expected a bounded canonical crafted identity')
    token=card_id[len(PREFIX):]
    try:
        raw=base64.b64decode(token+'='*((-len(token))%4),altchars=b'-_',validate=True)
        data=json.loads(raw.decode('utf8'))
    except(ValueError,UnicodeError,binascii.Error)as exc:raise ValueError('Invalid crafted recipe encoding')from exc
    if type(data)is not list or len(data)!=4 or data[0]!=VERSION:raise ValueError('Unknown crafted recipe version or fields')
    recipe=CraftedMinionRecipe(*data[1:]);recipe.__post_init__()
    if recipe.card_id!=card_id:raise ValueError('Noncanonical crafted recipe')
    return recipe


def validate_blueprint(registry,blueprint):
    if type(blueprint)is not CraftedMinionBlueprint:raise ValueError('Typed native crafting blueprint required')
    blueprint.__post_init__();template=registry._cards.get(blueprint.template_card_id)
    if template is None or template.kind!=CardType.MINION or template.metadata is None or template.metadata.collectible is not False:
        raise ValueError('Crafting requires its original noncollectible physical minion template')
    default=CardDefinition(template.id,template.name,template.kind)
    if any(getattr(template,f.name)!=getattr(default,f.name)for f in fields(template)
            if f.name not in('id','name','kind','cost','attack','health','metadata')):
        raise ValueError('Crafting cannot discard native text from its original template')
    if not all(tribe in template.metadata.tribes for tribe in(blueprint.first_tribe,blueprint.second_tribe)):
        raise ValueError('Crafting blueprint differs from its full original minion types')


def validate_part_shape(registry,card):
    if card.kind!=CardType.MINION or card.metadata is None:
        raise ValueError('Crafted ingredient requires its complete physical minion declaration')
    default=CardDefinition(card.id,card.name,card.kind)
    changed=[f.name for f in fields(card)if f.name not in PART_FIELDS and getattr(card,f.name)!=getattr(default,f.name)]
    if changed:raise ValueError('Unreviewed crafted ingredient declarations: '+','.join(changed))
    if card.native_condition is not None and card.native_condition.kind != 'self_damaged':
        raise ValueError('Unreviewed crafted conditional provider domain')
    if card.native_deathrattle is not None and card.native_deathrattle.kind != 'draw_link':
        raise ValueError('Unreviewed crafted native Deathrattle memory domain')
    if card.hand_progress is not None:
        from .model import HandProgressSpec,Zone
        spec=card.hand_progress
        if (spec.on_complete is None or spec.condition_id is None or spec!=HandProgressSpec(
                'event',1,on_complete=spec.on_complete,repeat=True,event='turn_ended',
                condition_id=spec.condition_id,zone=(Zone.HAND,Zone.DECK))):
            raise ValueError('Unreviewed crafted native stored-growth domain')
    registry._validate_card(card)


def native_dormancy(parts):
    values=tuple(p.dormant_turns for p in parts if p.dormant_turns!=0)
    if len(values)>1 or values and(type(values[0])is not int or values[0]<=0):
        raise ValueError('Unreviewed differing or conditional native dormant materials')
    return values[0]if values else 0


def blocks_dormant_entry(entity):
    return entity.dormancy is not None and any(a.kind==NATIVE_DORMANT_ENTRY for a in entity.abilities)


def validate_dormant_carrier(registry,card_id,kind,abilities,components=()):
    rows=tuple(a for a in abilities if a.kind==NATIVE_DORMANT_ENTRY)
    if not card_id.startswith(PREFIX):
        if rows:raise ValueError('Native crafted dormancy requires its original composition')
        return
    recipe=recipe_from_id(card_id)
    turns=native_dormancy(tuple(registry._cards[cid]for cid in recipe.parts))
    if not rows:
        if turns and any(a.kind in('on_play','battlecry','combo')for a in abilities):
            raise ValueError('Native dormant entry bodies lost their printed blocking declaration')
        return
    if (not turns or kind!=CardType.MINION or type(components)is not tuple or
            components!=recipe.parts or len(rows)!=1):
        raise ValueError('Native crafted dormancy differs from its original timed material')
    rows[0].__post_init__()


def native_domains(parts):
    """Check only actual native donor compatibility; do not enumerate recipes."""
    if sum(p.native_deathrattle is not None for p in parts)>1:
        raise ValueError('Unreviewed multiple native Deathrattle memory donors')
    if sum(p.minion_death_cost is not None for p in parts)>1:
        raise ValueError('Unreviewed duplicate native death quantity prices')
    if sum(p.hand_progress is not None for p in parts)>1:
        raise ValueError('Unreviewed multiple native stored-growth donors')
    schools=[p.spell_damage_schools for p in parts if p.spell_damage]
    if schools and any(s!=schools[0]for s in schools):raise ValueError('Crafted spell damage has unreviewed differing school domains')
    targets=[(p.requires_target,p.target_rule,p.targeting)for p in parts if p.requires_target or p.targeting is not None]
    if targets and any(t!=targets[0]for t in targets):raise ValueError('Crafted minion has unreviewed differing native target domains')
    return targets[0]if targets else(False,'any_entity',None)


def native_draw_memory_carrier(registry,card_id,kind,ability,components):
    """A composed body retains its one original printed draw-link declaration."""
    if not card_id.startswith(PREFIX):return False
    memory=ability.deathrattle_memory
    if (kind!=CardType.MINION or memory is None or memory.spec.kind!='draw_link' or
            ability.origin!='printed' or ability.deathrattle_inherited_from is not None or
            ability.deathrattle_copied_from is not None):return False
    recipe=recipe_from_id(card_id)
    if (components!=recipe.parts or ability.deathrattle_card_id not in recipe.parts or
            ability.deathrattle_card_id not in registry.crafted_minion_parts):return False
    donor=registry.card(ability.deathrattle_card_id)
    if donor.native_deathrattle!=memory.spec or donor.deathrattle!=ability.behavior_id:return False
    # Resolve the whole canonical face: both donor approvals, their tribes, the
    # blueprint, and the single-memory domain must still be valid. Memory stays
    # on the original ability, never in a second aggregate field on the face.
    return registry.card(card_id).kind==CardType.MINION


def resolve_face(registry,card_id):
    from .registry import UnsupportedDefinitionError
    try:
        recipe=recipe_from_id(card_id);blueprint=registry._crafted_minion_blueprints[recipe.template_card_id]
        validate_blueprint(registry,blueprint)
        template=registry._cards[recipe.template_card_id]
        parts=tuple(registry._cards[cid]for cid in recipe.parts)
        for part,tribe in zip(parts,(blueprint.first_tribe,blueprint.second_tribe)):
            if part.id not in registry._crafted_minion_parts:
                raise ValueError('Crafted ingredient has no reviewed native donation adapter: '+part.id)
            validate_part_shape(registry,part)
            if not any(t in part.metadata.tribes for t in(tribe,'all')):
                raise ValueError('Crafted ingredient lost its original printed minion type')
        require,rule,target=native_domains(parts)
        tribes=('all',)if any('all'in p.metadata.tribes for p in parts)else template.metadata.tribes
        face=replace(template,id=card_id,cost=sum(p.cost for p in parts),attack=sum(p.attack for p in parts),
            health=sum(p.health for p in parts),keywords=tuple(sorted({k for p in parts for k in p.keywords})),
            cleave=any(p.cleave for p in parts),
            dormant_turns=native_dormancy(parts),
            minion_death_cost=next((p.minion_death_cost for p in parts if p.minion_death_cost is not None),None),
            hand_progress=next((p.hand_progress for p in parts if p.hand_progress is not None),None),
            # This aggregate describes the printed potential. Installation keeps
            # each donor's conditional and unconditional providers separate.
            spell_damage=sum(p.spell_damage for p in parts),spell_damage_schools=tuple(sorted({s for p in parts for s in p.spell_damage_schools})),
            metadata=replace(template.metadata,tribes=tribes),requires_target=require,target_rule=rule,targeting=target,
            **{key:next((getattr(p,key)for p in parts if getattr(p,key)is not None),None)for key in('battlecry','deathrattle','combo')},
            **{key:tuple(value for p in parts for value in getattr(p,key))for key in TUPLES})
        # BC/DR/Combo fields expose the ordinary printed presence/target contract.
        # Every original body is installed separately, retaining donor identity.
        registry._validate_card(face)
        return face
    except(ValueError,TypeError,KeyError)as exc:
        raise UnsupportedDefinitionError('Unsupported crafted minion definition: '+str(exc))from exc


def composition_shape(card,components):
    if card.id.startswith(PREFIX):return type(components)is tuple and components==recipe_from_id(card.id).parts
    return bool(card.starship_for)==bool(components)


def native_death_heal_price(card_id, kind, rules, death_spec):
    """The actual death-count/hero-healed native ingredient price contract."""
    from .model import IntrinsicCostSpec, MinionDeathCostSpec
    if not card_id.startswith(PREFIX):return False
    recipe_from_id(card_id)
    return (kind==CardType.MINION and
        rules==(IntrinsicCostSpec(set_to=0,condition='hero_healed_this_turn',history_profile_id='healing.hero-this-turn-v1'),) and
        death_spec==MinionDeathCostSpec('cost.minion-deaths-both-turn-v1'))


def install(rules_state,entity,definition,registry,components):
    recipe=recipe_from_id(definition.id)
    if components and components!=recipe.parts:raise ValueError('Crafted material changed its original ordered ingredients')
    from .lifecycle import install_printed,refresh_entity,attachment_id
    entity.components=recipe.parts;entity.herald_rank=None
    entity.base_attack,entity.base_health=definition.attack,definition.health
    for index,cid in enumerate(recipe.parts):
        excluded=tuple(a.keyword for a in entity.abilities if a.kind=='keyword')if index else ()
        install_printed(rules_state,entity,registry.card(cid),registry,append=bool(index),exclude_keywords=excluded)
    if definition.dormant_turns:
        from .model import AbilityInstance
        entity.abilities.append(AbilityInstance(attachment_id(rules_state),NATIVE_DORMANT_ENTRY,
            source_id=entity.id,origin='printed'))
    refresh_entity(entity)


def public_recipe(card_id):
    if not card_id.startswith(PREFIX):return None
    recipe=recipe_from_id(card_id)
    return dict(template_card_id=recipe.template_card_id,parts=list(recipe.parts))
