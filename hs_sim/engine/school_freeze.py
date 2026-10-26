"""Native entry Freeze held until a real controller Fire-cast completion.

The immutable profile identifies a real printed trigger. One removable printed
ability uses the existing consumed bit as its entry gate; ordinary Freeze,
Unfreeze, copy materials and source life cycles stay authoritative.
"""
from dataclasses import dataclass, fields, replace

from .model import AbilityInstance, CardType, SpellSchool, TriggerSpec, Zone, _name

KIND = 'school_freeze'


@dataclass(frozen=True)
class SchoolFreezeProfile:
    card_id: str
    behavior_id: str
    school: SpellSchool = SpellSchool.FIRE

    def __post_init__(self):
        _name(self.card_id, 'native school Freeze card')
        _name(self.behavior_id, 'native school Freeze body')
        if (self.card_id.startswith(('crafted:', 'assemble:')) or
                type(self.school) is not SpellSchool or self.school != SpellSchool.FIRE):
            raise ValueError('Unreviewed native school Freeze declaration')


def validate_profile(registry, profile):
    if type(profile) is not SchoolFreezeProfile:
        raise ValueError('Expected complete native school Freeze profile')
    profile.__post_init__(); card = registry.card(profile.card_id)
    if (card.kind != CardType.MINION or card.choice_only or card.starship_for or
            card.triggers.count(TriggerSpec('spell_cast_finished', profile.behavior_id)) != 1):
        raise ValueError('School Freeze requires its original physical minion trigger')
    registry.behavior(profile.behavior_id)


def declarations(registry, card_id, components=None):
    from .crafted_faces import PREFIX, recipe_from_id
    if card_id.startswith(PREFIX):
        recipe = recipe_from_id(card_id)
        if components is not None and components != recipe.parts:
            raise ValueError('School Freeze lost its original physical composition')
        ids = recipe.parts
    else:
        ids = (card_id,)
    profiles = tuple(registry.school_freeze_profiles[cid] for cid in ids if cid in registry.school_freeze_profiles)
    if profiles and card_id.startswith(PREFIX): registry.card(card_id)
    return profiles


def validate_carrier(registry, card_id, kind, abilities, components=(), *, silenced=False, source_id=None):
    rows = tuple(a for a in abilities if a.kind == KIND)
    profiles = declarations(registry, card_id, components)
    if not rows and not profiles: return
    if kind != CardType.MINION or len(profiles) != 1 or len(rows) > 1:
        raise ValueError('Unreviewed native school Freeze carrier or duplicate donor')
    profile, = profiles; validate_profile(registry, profile)
    if not silenced and len(rows) != 1:
        raise ValueError('Native school Freeze lost its printed entry gate')
    for row in rows:
        row.__post_init__()
        expected = AbilityInstance(row.id, KIND, source_id=source_id, origin='printed',
            behavior_id=profile.behavior_id, consumed=row.consumed)
        if row != expected:
            changed = ','.join(f.name for f in fields(row) if getattr(row,f.name) != getattr(expected,f.name))
            raise ValueError('School Freeze borrowed a foreign native body or material: '+changed)


def validate_entity(registry, entity):
    validate_carrier(registry, entity.card_id, entity.kind, entity.abilities, entity.components,
        silenced=entity.silenced, source_id=entity.id)
    if (entity.zone == Zone.BOARD and entity.active and entity.health > 0 and not entity.doomed
            and locked(entity) and not entity.frozen):
        raise ValueError('Active native school Freeze lost its ordinary frozen state')


def locked(entity):
    return any(a.kind == KIND and not a.consumed for a in entity.abilities)


def release(entity):
    entity.abilities = [replace(a, consumed=True) if a.kind == KIND and not a.consumed else a
        for a in entity.abilities]


def initialize(state, registry, entity, *, fresh=False):
    if entity.zone != Zone.BOARD or entity.kind != CardType.MINION: return
    if fresh:
        entity.abilities = [replace(a, consumed=False) if a.kind == KIND else a for a in entity.abilities]
    if not entity.active or entity.health <= 0 or entity.doomed or not locked(entity): return
    from .combat import can_be_frozen, freeze_deadline
    if not can_be_frozen(entity):
        release(entity)
    elif not entity.frozen:
        entity.frozen_until_owner_turn = freeze_deadline(state, entity, registry=registry)


def synchronize(resolver):
    if not resolver.registry.school_freeze_profiles: return
    for player in resolver.state.players.values():
        for eid in player.board:
            entity = resolver.state.entities[eid]
            if locked(entity): initialize(resolver.state, resolver.registry, entity)


def after_cast(context, registry, behavior_id):
    from .effects import Unfreeze
    from .spell_casts import cast_record
    event = context.event
    if event is None or event.kind != 'spell_cast_finished':
        raise ValueError('School Freeze requires its real successful cast notification')
    cast = cast_record(context.state, dict(event.data)['cast_id'])
    if ((cast.source_id, cast.player_id, cast.target_id) !=
            (event.source_id, event.player_id, event.target_id) or not cast.completed or
            not cast.payload_started or cast.failure is not None or cast.interrupted):
        raise ValueError('School Freeze lost its original successful cast')
    source = context.source
    profiles = declarations(registry, source.card_id, source.components)
    profile = next((p for p in profiles if p.behavior_id == behavior_id), None)
    if profile is None:
        raise ValueError('School Freeze body lost its original declaration')
    if (cast.player_id != context.player_id or registry.card(cast.card_id).spell_school != profile.school
            or source.zone != Zone.BOARD or not source.active or source.health <= 0 or source.doomed):
        return ()
    return (Unfreeze(source.id),)
