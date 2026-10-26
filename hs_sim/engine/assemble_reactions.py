"""Reviewed ordinary reaction subjects use the existing captured trigger calls."""
from dataclasses import asdict, dataclass, replace
import base64
import binascii
import hashlib
import json

from .errors import ResolutionError
from .model import CardType, TriggerSpec, LimitedTriggerSpec, _name

REACTION_PREFIX = 'assemble.reaction:'
# Actual ordinary and native finite-trigger roots in the pinned CN37 inventory.
# Syntax does not install their conditions, bodies or source declarations.
REACTION_TIMINGS = frozenset(('attack_declared', 'attack_finished', 'card_committed', 'card_drawn',
    'card_played', 'damage_dealt', 'hand_card_entered', 'health_resolved', 'hero_power_used',
    'mana_spent', 'mana_consumed', 'minion_died', 'minion_summoned', 'shield_lost', 'spell_cast_finished', 'spell_cast_started',
    'stealth_lost', 'turn_started'))
LATE_REACTION_PREFIX = 'assemble.reaction_late:'


@dataclass(frozen=True)
class AssembleReactionSource:
    card_id: str
    event: str
    original_behavior_id: str
    condition_id: str

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        for field in ('card_id', 'original_behavior_id', 'condition_id'):
            _name(getattr(self, field), 'assembled reaction ' + field)
        if (self.event not in REACTION_TIMINGS or
                self.original_behavior_id.startswith(TIMING_PREFIXES)):
            raise ValueError('Assembled reaction needs its reviewed ordinary native subject')


@dataclass(frozen=True)
class AssembleWeaponReactionSource:
    """A complete weapon may lend its reviewed owner-hero attack prefix."""
    card_id: str
    original_behavior_id: str
    condition_id: str
    definition_sha256: str
    event: str = 'attack_finished'
    source_kind: CardType = CardType.WEAPON

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        for field in ('card_id', 'original_behavior_id', 'condition_id'):
            _name(getattr(self, field), 'weapon assembled reaction '+field)
        if (self.event != 'attack_finished' or self.source_kind is not CardType.WEAPON or
                self.original_behavior_id.startswith(TIMING_PREFIXES) or
                type(self.definition_sha256) is not str or len(self.definition_sha256) != 64 or
                any(c not in '0123456789abcdef' for c in self.definition_sha256)):
            raise ValueError('Weapon reaction requires its complete original completed-attack source')


@dataclass(frozen=True)
class AssembleNativeReactionSource:
    card_id: str
    events: tuple[str, ...]
    original_behavior_id: str
    condition_id: str
    limited: LimitedTriggerSpec | None = None

    @property
    def event(self): return self.events[0]

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        for field in ('card_id', 'original_behavior_id', 'condition_id'):
            _name(getattr(self, field), 'native assembled reaction '+field)
        if (type(self.events) is not tuple or not self.events or
                len(set(self.events)) != len(self.events) or
                any(e not in REACTION_TIMINGS for e in self.events) or
                self.original_behavior_id.startswith(TIMING_PREFIXES)):
            raise ValueError('Native reaction requires its complete ordered original events')
        if self.limited is None:
            if len(self.events) < 2:
                raise ValueError('One ordinary event uses the original reaction declaration')
        else:
            if type(self.limited) is not LimitedTriggerSpec:
                raise ValueError('Native reaction requires a complete limited trigger')
            self.limited.__post_init__()
            if (self.events != (self.limited.event,) or self.limited.keyword is not None or
                    self.limited.end_turn is not None or self.limited.reset != 'turn' or
                    self.limited.uses != 1 or self.limited.behavior_id != self.original_behavior_id or
                    self.limited.condition_id != self.condition_id):
                raise ValueError('Native finite reaction requires its original once-per-turn subject')


def source_events(profile):
    return profile.events if type(profile) is AssembleNativeReactionSource else (profile.event,)


def subject_specs(profile, behavior_id=None):
    if type(profile) is AssembleNativeReactionSource and profile.limited is not None:
        return dict(triggers=(), limited_triggers=(profile.limited if behavior_id is None else
            replace(profile.limited, behavior_id=behavior_id),))
    return dict(triggers=tuple(TriggerSpec(event, profile.original_behavior_id if behavior_id is None
        else reaction_behavior_id(event, profile.condition_id, behavior_id)) for event in source_events(profile)),
        limited_triggers=())


def validate_weapon_source(registry, profile, *, require_projection=False):
    from .serialization import canonical_hash
    if type(profile) is not AssembleWeaponReactionSource:
        raise ValueError('Expected a complete native weapon reaction source')
    profile.__post_init__()
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.WEAPON or
            canonical_hash(asdict(original)) != profile.definition_sha256 or
            original.triggers != subject_specs(profile)['triggers'] or original.limited_triggers):
        raise ValueError('Weapon reaction bridge differs from its complete original weapon')
    registry.behavior(profile.original_behavior_id)
    registry.trigger_condition(profile.condition_id)
    if require_projection:
        projection = registry._assemble_projections.get(profile.card_id)
        if projection is None:
            raise ValueError('Weapon reaction bridge requires its actual reviewed projection')
        from .assemble_faces import validate_projection
        validate_projection(registry, projection)


def validate_weapon_projection(registry, projection):
    from .assemble_faces import AssemblePrefix, AssembleProjection
    if type(projection) is not AssembleProjection or projection.source_kind is not CardType.WEAPON:
        raise ValueError('Reaction prefix requires its actual native minion source')
    profile = registry._assemble_reaction_sources.get(projection.card_id)
    if (type(profile) is not AssembleWeaponReactionSource or profile.card_id != projection.card_id or
            projection.definition_sha256 != profile.definition_sha256 or
            projection.prefix != AssemblePrefix(profile.event, condition_id=profile.condition_id)):
        raise ValueError('Reaction prefix requires its actual native minion source or reviewed weapon bridge')
    validate_weapon_source(registry, profile)


def validate_source(registry, profile, *, require_template=False):
    if type(profile) is AssembleWeaponReactionSource:
        return validate_weapon_source(registry, profile, require_projection=require_template)
    if type(profile) not in (AssembleReactionSource, AssembleNativeReactionSource):
        raise ValueError('Expected a complete assembly reaction source')
    profile.__post_init__()
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.MINION or
            original.triggers != subject_specs(profile)['triggers'] or
            original.limited_triggers != subject_specs(profile)['limited_triggers']):
        raise ValueError('Reaction bridge differs from the complete original ordinary trigger')
    registry.behavior(profile.original_behavior_id)
    registry.trigger_condition(profile.condition_id)
    if require_template:
        template = registry._assemble_templates.get(profile.card_id)
        if (template is None or template.prefix.timing != profile.event or
                template.prefix.condition_id != profile.condition_id):
            raise ValueError('Reaction bridge requires its actual reviewed prefix')


def original_trigger(registry, template):
    return original_subject(registry, template)['triggers']


def original_subject(registry, template):
    profile = registry._assemble_reaction_sources.get(template.card_id)
    if profile is None:
        raise ValueError('Reaction prefix lacks its complete native source bridge')
    validate_source(registry, profile)
    if (template.prefix.timing, template.prefix.condition_id) != (profile.event, profile.condition_id):
        raise ValueError('Reaction template changed its actual event or original guard')
    return subject_specs(profile)


def native_subject(registry, template, suffix):
    profile = registry._assemble_reaction_sources.get(template.card_id)
    if type(profile) is not AssembleNativeReactionSource:
        return None
    validate_source(registry, profile)
    if (template.prefix.timing, template.prefix.condition_id) != (profile.event, profile.condition_id):
        raise ValueError('Native reaction changed its complete prefix')
    if suffix == template.suffix:
        return subject_specs(profile)
    if any(event not in suffix.allowed_timings or event in suffix.pending_timings
            for event in source_events(profile)):
        raise ValueError('Native reaction body has an explicitly unreviewed event context')
    if profile.limited is not None:
        return subject_specs(profile, reaction_behavior_id(profile.event, profile.condition_id, suffix.behavior_id))
    return subject_specs(profile, suffix.behavior_id)


def validate_sources(registry):
    for cid, profile in registry._assemble_reaction_sources.items():
        if cid != profile.card_id:
            raise ValueError('Reaction source identity changed')
        validate_source(registry, profile, require_template=True)
    for condition_id, profile in registry._assemble_reaction_continuations.items():
        if condition_id != profile.condition_id:
            raise ValueError('Reaction continuation identity changed')
        validate_continuation(registry, profile)


def reaction_behavior_id(event, condition_id, behavior_id):
    from .assemble_faces import TIMING_PREFIXES
    if event not in REACTION_TIMINGS:
        raise ValueError('Unsupported ordinary assembly reaction event')
    _name(condition_id, 'assembled reaction condition')
    _name(behavior_id, 'assembled reaction body')
    if behavior_id.startswith(TIMING_PREFIXES):
        raise ValueError('Reaction body cannot recursively wrap a timing gate')
    row = dict(event=event, condition_id=condition_id, behavior_id=behavior_id)
    token = base64.urlsafe_b64encode(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).decode().rstrip('=')
    result = REACTION_PREFIX + token
    if len(result) > 8192:
        raise ValueError('Reaction identity exceeds its bounded size')
    return result


def reaction_behavior(registry, behavior_id):
    from .registry import UnsupportedDefinitionError
    try:
        if not behavior_id.startswith(REACTION_PREFIX) or len(behavior_id) > 8192:
            raise ValueError('Invalid reaction identity')
        token = behavior_id[len(REACTION_PREFIX):]
        row = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True).decode())
        if (type(row) is not dict or set(row) != {'event', 'condition_id', 'behavior_id'} or
                reaction_behavior_id(**row) != behavior_id):
            raise ValueError('Noncanonical reaction identity')
        templates = (*registry._assemble_templates.values(), *registry._assemble_projections.values())
        if not any(t.card_id in registry._assemble_reaction_sources and
                row['event'] in source_events(registry._assemble_reaction_sources[t.card_id]) and
                t.prefix.condition_id == row['condition_id'] for t in templates):
            raise ValueError('Unreviewed reaction subject or condition')
        if not any(t.suffix.behavior_id == row['behavior_id'] and
                row['event'] in t.suffix.allowed_timings and row['event'] not in t.suffix.pending_timings for t in templates):
            raise ValueError('Unreviewed reaction body context')
        predicate = registry.trigger_condition(row['condition_id'])
        body = registry.behavior(row['behavior_id'])
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise UnsupportedDefinitionError('Unsupported assembled reaction: ' + str(exc)) from exc

    def run(context):
        from .assemble_faces import recipe_from_id
        if context.event is None or context.event.kind != row['event']:
            raise ResolutionError('Reaction requires its original captured event')
        try:
            source_kind = CardType.MINION
            source_card_id = context.source.card_id
            from .assembled_powers import PREFIX as POWER_PREFIX, power_recipe_from_id
            if source_card_id.startswith(POWER_PREFIX):
                # The ordinary face resolver checks the full template, both
                # source roles and keyword policy before lending its trigger.
                registry.card(source_card_id)
                source_card_id = power_recipe_from_id(source_card_id).minion_card_id
                source_kind = CardType.HERO_POWER
            recipe = recipe_from_id(source_card_id)
            face = registry.card(context.source.card_id)
            prefix_id = recipe.secondary_card_id if recipe.half == 'top' else recipe.primary_card_id
            profile = registry._assemble_reaction_sources[prefix_id]
            if row['condition_id'] != profile.condition_id or row['event'] not in source_events(profile):
                raise ValueError('Reaction borrowed another native prefix')
            expected = (subject_specs(profile, behavior_id) if
                type(profile) is AssembleNativeReactionSource and profile.limited is not None else
                subject_specs(profile, row['behavior_id']))
        except (ValueError, KeyError) as exc:
            raise ResolutionError('Reaction requires its actual immutable assembled source') from exc
        if (context.source.kind != source_kind or context.source.controller != context.player_id or
                face.triggers != expected['triggers'] or face.limited_triggers != expected['limited_triggers']):
            raise ResolutionError('Reaction differs from its captured source declaration')
        if type(profile) is AssembleNativeReactionSource and profile.limited is not None:
            trigger = context.trigger
            if (trigger is None or trigger.kind != 'limited_trigger' or
                    trigger.limited_trigger != expected['limited_triggers'][0] or
                    trigger not in context.source.abilities or trigger.uses_remaining >= trigger.limited_trigger.uses):
                raise ResolutionError('Native finite reaction requires its actually consumed original budget')
        result = predicate(context)
        if type(result) is not bool:
            raise ResolutionError('Reaction condition requires an explicit boolean')
        if not result:
            return ()
        if row['condition_id'] in registry._assemble_reaction_continuations:
            return defer_attack(context, row)
        return body(context)
    return run


@dataclass(frozen=True)
class AssembleReactionContinuation:
    card_id: str
    condition_id: str
    late_condition_id: str
    capture: str = 'attack_source_presence'

    def __post_init__(self):
        for field in ('card_id', 'condition_id', 'late_condition_id'):
            _name(getattr(self, field), 'assembled reaction continuation ' + field)
        if self.capture != 'attack_source_presence' or self.condition_id == self.late_condition_id:
            raise ValueError('Reaction continuation requires its reviewed original attack presence')


def validate_continuation(registry, profile):
    if type(profile) is not AssembleReactionContinuation:
        raise ValueError('Expected AssembleReactionContinuation')
    profile.__post_init__()
    sources = [source for source in registry._assemble_reaction_sources.values()
        if source.condition_id == profile.condition_id]
    if (len(sources) != 1 or sources[0].card_id != profile.card_id or
            sources[0].event != 'attack_finished'):
        raise ValueError('Reaction continuation requires its unique real completed-attack source')
    validate_source(registry, sources[0], require_template=True)
    registry.trigger_condition(profile.late_condition_id)


def late_reaction_behavior_id(event, condition_id, behavior_id, material_sha256):
    reaction_behavior_id(event, condition_id, behavior_id)
    if (event != 'attack_finished' or type(material_sha256) is not str or len(material_sha256) != 64 or
            any(char not in '0123456789abcdef' for char in material_sha256)):
        raise ValueError('Deferred reaction requires its exact original attack material digest')
    row = dict(event=event, condition_id=condition_id, behavior_id=behavior_id, material_sha256=material_sha256)
    token = base64.urlsafe_b64encode(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).decode().rstrip('=')
    result = LATE_REACTION_PREFIX + token
    if len(result) > 8192:
        raise ValueError('Deferred reaction identity exceeds its bound')
    return result


def _material_digest(material):
    content = {key:value for key,value in material.items() if key != 'gate_id'}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def defer_attack(context, row):
    from dataclasses import asdict
    from .character_attacks import completed_attack
    from .effects import ChoiceOption, RequestChoice
    attack = completed_attack(context)
    if (attack is None or attack.declaration.attack_source_presence is None or
            attack.declaration.source_id != context.source_id):
        raise ResolutionError('Deferred reaction lost its original physical attacker')
    material = dict(kind='assemble.attack-source.v1',
        source_id=context.source_id, player_id=context.player_id,
        accepted_card_id=context.source.card_id, attack_window_id=attack.declaration.id,
        event_sequence=context.event.sequence, reference=asdict(attack.declaration.attack_source_presence))
    late_id = late_reaction_behavior_id(**row, material_sha256=_material_digest(material))
    material['gate_id'] = late_id
    return (RequestChoice(context.player_id,
        (ChoiceOption(json.dumps(material, sort_keys=True, separators=(',', ':')), 'Original attack'),),
        context.source_id, min_count=0, max_count=0, on_select=late_id),)


def _late_material(context):
    from .model import BoardPresenceReference
    try:
        choice = context.choice
        if (choice is None or choice.selected_ids or len(choice.choice.options) != 1 or
                choice.choice.min_count != 0 or choice.choice.max_count != 0 or
                (choice.choice.source_id, choice.choice.player_id) != (context.source_id, context.player_id)):
            raise ValueError('Missing automatic reaction material')
        encoded = choice.choice.options[0].id
        if len(encoded) > 32768:
            raise ValueError('Reaction material exceeds its bound')
        material = json.loads(encoded)
        if (type(material) is not dict or set(material) != {'kind', 'gate_id', 'source_id', 'player_id',
                'accepted_card_id', 'attack_window_id', 'event_sequence', 'reference'} or
                material['kind'] != 'assemble.attack-source.v1' or
                json.dumps(material, sort_keys=True, separators=(',', ':')) != encoded or
                (material['source_id'], material['player_id']) != (context.source_id, context.player_id)):
            raise ValueError('Reaction material changed its accepted source')
        if (any(type(material[key]) is not int or material[key] < 1 for key in
                ('source_id', 'player_id', 'attack_window_id', 'event_sequence')) or
                type(material['accepted_card_id']) is not str or not material['accepted_card_id'] or
                len(material['accepted_card_id']) > 8192 or type(material['gate_id']) is not str or
                not material['gate_id'].startswith(LATE_REACTION_PREFIX) or len(material['gate_id']) > 8192):
            raise ValueError('Reaction material requires exact physical identities')
        token = material['gate_id'][len(LATE_REACTION_PREFIX):]
        accepted = json.loads(base64.b64decode(token+'='*(-len(token)%4), altchars=b'-_', validate=True).decode())
        if (late_reaction_behavior_id(**accepted) != material['gate_id'] or
                accepted['material_sha256'] != _material_digest(material)):
            raise ValueError('Reaction material changed its exact accepted capture')
        reference = BoardPresenceReference(**material['reference'])
        attack = next(row for row in context.state.character_attack_history
            if row.declaration.id == material['attack_window_id'])
        if (attack.terminal is None or attack.terminal.status != 'completed' or attack.combat is None or
                attack.terminal.event_cursor+1 != material['event_sequence'] or
                attack.declaration.source_id != context.source_id or
                attack.declaration.attack_source_presence != reference):
            raise ValueError('Reaction material borrowed another completed attack')
        return material, reference
    except (ValueError, TypeError, KeyError, StopIteration, UnicodeError, binascii.Error) as exc:
        raise ResolutionError('Deferred reaction lost its exact original attack material') from exc


def reaction_attack_reference(context):
    """The original physical attacker, including an already invalidated presence."""
    return _late_material(context)[1]


def late_reaction_behavior(registry, behavior_id):
    from .assemble_faces import recipe_from_id
    from .registry import UnsupportedDefinitionError
    try:
        token = behavior_id[len(LATE_REACTION_PREFIX):]
        row = json.loads(base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True).decode())
        if (not behavior_id.startswith(LATE_REACTION_PREFIX) or
                type(row) is not dict or set(row) != {'event', 'condition_id', 'behavior_id', 'material_sha256'} or
                late_reaction_behavior_id(**row) != behavior_id):
            raise ValueError('Noncanonical deferred reaction identity')
        normal_id = reaction_behavior_id(row['event'], row['condition_id'], row['behavior_id'])
        reaction_behavior(registry, normal_id)
        profile = registry._assemble_reaction_continuations[row['condition_id']]
        validate_continuation(registry, profile)
        predicate = registry.trigger_condition(profile.late_condition_id)
        body = registry.behavior(row['behavior_id'])
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise UnsupportedDefinitionError('Unsupported deferred reaction declaration') from exc

    def run(context):
        material, _ = _late_material(context)
        try:
            recipe_from_id(material['accepted_card_id'])
            accepted = registry.card(material['accepted_card_id'])
        except ValueError as exc:
            raise ResolutionError('Deferred reaction lost its accepted assembled face') from exc
        if (material['gate_id'] != behavior_id or
                accepted.triggers != (TriggerSpec(row['event'], normal_id),)):
            raise ResolutionError('Deferred reaction changed its accepted body or source declaration')
        result = predicate(context)
        if type(result) is not bool:
            raise ResolutionError('Deferred reaction condition requires an explicit boolean')
        return body(context) if result else ()
    return run
