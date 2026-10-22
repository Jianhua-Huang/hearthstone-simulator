"""Original spell discovery into a real weapon template with native spell text."""
from dataclasses import dataclass,replace

from .effects import AddToHand,Effect
from .model import CardType,Zone
from .pools import DiscoverFromPool,PoolQuery

QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')


def validate_spec(spec):
    if type(spec)is not DiscoverFromPool or type(spec.spell_weapon_card_id)is not str or not spec.spell_weapon_card_id:
        raise ValueError('Spell weapon requires its explicit native weapon template')
    plain=DiscoverFromPool(spec.player_id,spec.pool_id,QUERY,source_id=spec.source_id,prompt=spec.prompt)
    if spec.source_id is None or replace(spec,spell_weapon_card_id=None)!=plain:
        raise ValueError('Spell weapon supports one plain current-class collectible spell discovery')


def validate_declaration(registry,spec):
    from .carved_spells import profile_for
    validate_spec(spec)
    if not profile_for(registry,spec.spell_weapon_card_id).weapon_attack:
        raise ValueError('Weapon discovery requires its registered native attack-spell template')


@dataclass(frozen=True)
class DeliverDiscoveredSpellWeapon(Effect):
    discovery:object

    def __post_init__(self):
        from .discovery import ResolvePoolDiscovery
        if type(self.discovery)is not ResolvePoolDiscovery:raise ValueError('Weapon discovery lost its actual original selection')
        self.discovery.__post_init__();validate_spec(self.discovery.batch.spec)
        if self.discovery.choice_result is None:raise ValueError('Weapon discovery has no committed original choice')

    @property
    def result(self):return self.discovery.choice_result
    @property
    def player_id(self):return self.discovery.batch.spec.player_id
    @property
    def source_id(self):return self.discovery.batch.spec.source_id
    @property
    def card_id(self):return self.discovery.selection.card_id
    @property
    def weapon_card_id(self):return self.discovery.batch.spec.spell_weapon_card_id


def validate_original(state,registry,context,effect):
    from .discovery import validate_selection
    from .card_discoveries import require_original_result
    from .carved_spells import profile_for,validate_spell
    effect.__post_init__();validate_selection(registry,context,effect.discovery)
    require_original_result(state,effect.result)
    profile=profile_for(registry,effect.weapon_card_id)
    if not profile.weapon_attack:raise ValueError('Selected weapon requires its native attack-spell profile')
    validate_spell(registry,effect.weapon_card_id,effect.card_id)


def deliver(r,effect):
    from .discovery_delivery import MaterializeDiscoveredCard
    validate_original(r.state,r.registry,r.game._generation_context,effect)
    return (MaterializeDiscoveredCard(effect.result,effect),)


def materialize(r,effect):
    from .opening import create_hand_card
    validate_original(r.state,r.registry,r.game._generation_context,effect)
    # The real template, native spell and cost settle before public hand events.
    return create_hand_card(r,AddToHand(effect.player_id,effect.weapon_card_id,
        effect.source_id,carved_spell_id=effect.card_id))


def validate_completion(state,registry,completion):
    effect=completion.recipe
    if type(effect)is not DeliverDiscoveredSpellWeapon:return
    from .carved_spells import profile_for,weapon_material
    effect.__post_init__()
    if effect.result!=completion.result or not profile_for(registry,effect.weapon_card_id).weapon_attack:
        raise ValueError('Weapon discovery borrowed another original choice or native template')
    fact=completion.recipient
    if fact is None or (fact.card_id,fact.kind,fact.owner,fact.controller)!=(
            effect.weapon_card_id,CardType.WEAPON,effect.player_id,effect.player_id)or fact.zone not in(Zone.HAND,Zone.GRAVEYARD):
        raise ValueError('Weapon discovery changed its actual original hand delivery or burn')
    entity=state.entities.get(fact.entity_id)
    if entity is not None and entity.card_id==fact.card_id and entity.zone_epoch==fact.zone_epoch:
        value=weapon_material(entity)
        if value is None or value[1]!=effect.card_id:raise ValueError('Original discovered weapon changed its selected spell')


def cast_after_attack(context,registry):
    from .carved_spells import validate_ability
    from .character_attacks import completed_attack
    from .spell_casts import CastSpell
    # Ordinary BehaviorCall already retains its accepted detached source state.
    # Read that native trigger, not the player's later current weapon slot.
    values=[a for a in context.source.abilities if a.kind=='trigger'and a.event=='attack_finished'
        and a.carved_spell_id is not None]
    if len(values)!=1:
        raise ValueError('Native weapon attack lost its accepted original spell trigger')
    ability=values[0]
    validate_ability(registry,ability);row=completed_attack(context)
    if (row is None or row.source_kind!=CardType.HERO or row.declaration.player_id!=context.player_id or
            row.combat is None or row.combat.weapon_id!=context.source_id):return ()
    return (CastSpell(context.player_id,ability.carved_spell_id,context.source_id),)


def register(mechanics):mechanics.register(DeliverDiscoveredSpellWeapon,deliver)
