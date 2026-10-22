"""Reviewed ordinary reaction subjects use the existing captured trigger calls."""
from dataclasses import dataclass
import base64
import binascii
import json

from .errors import ResolutionError
from .model import CardType, TriggerSpec, _name

REACTION_PREFIX = 'assemble.reaction:'
REACTION_TIMINGS = frozenset(('card_played',))


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


def validate_source(registry, profile, *, require_template=False):
    if type(profile) is not AssembleReactionSource:
        raise ValueError('Expected AssembleReactionSource')
    profile.__post_init__()
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.MINION or
            original.triggers != (TriggerSpec(profile.event, profile.original_behavior_id),)):
        raise ValueError('Reaction bridge differs from the complete original ordinary trigger')
    registry.behavior(profile.original_behavior_id)
    registry.trigger_condition(profile.condition_id)
    if require_template:
        template = registry._assemble_templates.get(profile.card_id)
        if (template is None or template.prefix.timing != profile.event or
                template.prefix.condition_id != profile.condition_id):
            raise ValueError('Reaction bridge requires its actual reviewed prefix')


def original_trigger(registry, template):
    profile = registry._assemble_reaction_sources.get(template.card_id)
    if profile is None:
        raise ValueError('Reaction prefix lacks its complete native source bridge')
    validate_source(registry, profile)
    if (template.prefix.timing, template.prefix.condition_id) != (profile.event, profile.condition_id):
        raise ValueError('Reaction template changed its actual event or original guard')
    return (TriggerSpec(profile.event, profile.original_behavior_id),)


def validate_sources(registry):
    for cid, profile in registry._assemble_reaction_sources.items():
        if cid != profile.card_id:
            raise ValueError('Reaction source identity changed')
        validate_source(registry, profile, require_template=True)


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
                (t.prefix.timing, t.prefix.condition_id) == (row['event'], row['condition_id']) for t in templates):
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
            recipe_from_id(context.source.card_id)
            face = registry.card(context.source.card_id)
        except ValueError as exc:
            raise ResolutionError('Reaction requires its actual immutable assembled source') from exc
        if (context.source.kind != CardType.MINION or context.source.controller != context.player_id or
                face.triggers != (TriggerSpec(row['event'], behavior_id),)):
            raise ResolutionError('Reaction differs from its captured source declaration')
        result = predicate(context)
        if type(result) is not bool:
            raise ResolutionError('Reaction condition requires an explicit boolean')
        return body(context) if result else ()
    return run
