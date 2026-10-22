"""Reviewed minion play halves retain native Outcast and Kindred execution."""
from collections.abc import Mapping
from dataclasses import dataclass

from .model import CardType, KindredProfile, Keyword, _name


@dataclass(frozen=True)
class AssembleOnPlaySource:
    card_id: str
    original_behavior_id: str
    condition_id: str
    kind: str

    def __post_init__(self):
        for value in (self.card_id, self.original_behavior_id, self.condition_id):
            _name(value, 'assembly native minion play source')
        if self.card_id.startswith('assemble:') or self.kind not in ('outcast', 'kindred'):
            raise ValueError('Assembly minion play requires a static actual Outcast or Kindred source')


@dataclass(frozen=True)
class AssembleOnPlayDeathSource:
    card_id: str
    original_behavior_id: str
    condition_id: str
    kind: str
    original_deathrattle_id: str
    body_behavior_id: str
    original_kindred_active_id: str | None = None
    prefix_deathrattle_id: str | None = None

    def __post_init__(self):
        AssembleOnPlaySource(self.card_id, self.original_behavior_id, self.condition_id, self.kind)
        for value in (self.original_deathrattle_id, self.body_behavior_id):
            _name(value, 'assembly actual play/death body')
        for value in (self.original_kindred_active_id, self.prefix_deathrattle_id):
            if value is not None:
                _name(value, 'assembly original play/death material')
        if (self.kind == 'kindred') != (self.original_kindred_active_id is not None):
            raise ValueError('Assembly play/death source lost its original Kindred active identity')


def source_profile(registry, card_id):
    return (registry._assemble_on_play_sources.get(card_id) or
        registry._assemble_on_play_death_sources.get(card_id))


def validate_source(registry, profile):
    if type(profile) is not AssembleOnPlaySource:
        raise ValueError('Invalid assembly minion play declaration')
    profile.__post_init__()
    validate_native_source(registry, profile)


def validate_native_source(registry, profile):
    original = registry._cards.get(profile.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            original.on_play != profile.original_behavior_id):
        raise ValueError('Assembly minion play changed its exact original native entry')
    registry.behavior(profile.original_behavior_id)
    registry.trigger_condition(profile.condition_id)
    native = registry._kindred_profiles.get(profile.card_id)
    if profile.kind == 'outcast':
        if Keyword.OUTCAST not in original.keywords or native is not None:
            raise ValueError('Assembly Outcast source lost its original printed declaration')
    elif (native is None or native.mode != 'body' or native.wrapper != original.on_play or
            native.active is None or native.prepare is not None or native.inactive is not None):
        raise ValueError('Assembly Kindred requires its complete original independent active component')


def validate_death_source(registry, profile):
    if type(profile) is not AssembleOnPlayDeathSource:
        raise ValueError('Invalid assembly actual play/death source')
    profile.__post_init__()
    validate_native_source(registry, profile)
    original = registry._cards[profile.card_id]
    if original.deathrattle != profile.original_deathrattle_id:
        raise ValueError('Assembly play/death source changed its exact original Deathrattle')
    for key in (profile.original_deathrattle_id, profile.body_behavior_id):
        registry.behavior(key)
    if profile.kind == 'kindred' and registry._kindred_profiles[profile.card_id].active != profile.original_kindred_active_id:
        raise ValueError('Assembly play/death source changed its original Kindred component')
    if profile.prefix_deathrattle_id is not None and profile.prefix_deathrattle_id != original.deathrattle:
        raise ValueError('Assembly independent prefix Deathrattle must retain its complete original body')


def original_on_play(registry, template):
    profile = source_profile(registry, template.card_id)
    if profile is None:
        raise ValueError('Assembly minion play requires its original source declaration')
    dual = type(profile) is AssembleOnPlayDeathSource
    (validate_death_source if dual else validate_source)(registry, profile)
    timing = ('on_play_prefix_deathrattle' if profile.prefix_deathrattle_id else
        'on_play_deathrattle') if dual else 'on_play'
    if template.prefix.timing != timing or template.prefix.condition_id != profile.condition_id:
        raise ValueError('Assembly minion play lost its exact prefix and condition')
    if dual and template.suffix.behavior_id != profile.body_behavior_id:
        raise ValueError('Assembly play/death source changed its reviewed independent body')
    if (not dual and profile.kind == 'kindred' and
            registry._kindred_profiles[profile.card_id].active != template.suffix.behavior_id):
        raise ValueError('Assembly Kindred changed its original complete active component')
    return profile.original_behavior_id


def prefix_deathrattle(registry, template):
    profile = registry._assemble_on_play_death_sources.get(template.card_id)
    if profile is None:
        if template.prefix.timing == 'on_play_prefix_deathrattle':
            raise ValueError('Assembly independent prefix Deathrattle requires its complete original source')
        return None
    original_on_play(registry, template)
    return profile.prefix_deathrattle_id


def validate_sources(registry):
    for cid, profile in (*registry._assemble_on_play_sources.items(), *registry._assemble_on_play_death_sources.items()):
        template = registry._assemble_templates.get(cid)
        if cid != profile.card_id or template is None or cid in registry._assemble_projections:
            raise ValueError('Assembly minion play requires its actual native template')
        original_on_play(registry, template)


def parts(registry, card_id):
    from .assemble_faces import recipe_from_id, text_source
    recipe = recipe_from_id(card_id)
    first = text_source(registry, recipe.primary_card_id, primary=True)
    second = text_source(registry, recipe.secondary_card_id)
    prefix_source = second if recipe.half == 'top' else first
    suffix = second.suffix if recipe.half == 'bottom' else first.suffix
    from .assemble_faces import prefix_timings
    profile = source_profile(registry, prefix_source.card_id)
    if profile is None or 'on_play' not in prefix_timings(prefix_source.prefix):
        raise KeyError(card_id)
    original_on_play(registry, prefix_source)
    return profile, suffix


class KindredCatalog(Mapping):
    """Finite static inventory, with pure lookup of canonical assembled faces."""
    def __init__(self, registry):
        self.registry = registry

    def __iter__(self):
        return iter(self.registry._kindred_profiles)

    def __len__(self):
        return len(self.registry._kindred_profiles)

    def __getitem__(self, card_id):
        if card_id in self.registry._kindred_profiles:
            return self.registry._kindred_profiles[card_id]
        if not isinstance(card_id, str) or not card_id.startswith('assemble:'):
            raise KeyError(card_id)
        face = self.registry.card(card_id)
        profile, suffix = parts(self.registry, card_id)
        if profile.kind != 'kindred':
            raise KeyError(card_id)
        return KindredProfile(card_id, 'body', wrapper=face.on_play, active=suffix.behavior_id)


def accepted_face(context, registry, behavior_id):
    """Require the real paid or generated physical body, never an Invoke guess."""
    from .play_history import play_record
    if context.physical is not None:
        from .whole_card_physical import active_progress, segment_at
        physical = context.physical
        if (physical != active_progress(context.state, context.source_id, context.player_id) or
                physical.source is None or physical.source.entity_id != context.source_id or
                physical.player_id != context.player_id or physical.kind != CardType.MINION or
                physical.phase != 'running' or physical.cursor < 1 or
                segment_at(physical, physical.cursor - 1) != ('on_play', behavior_id)):
            raise ValueError('Assembly minion play lost its original generated physical body')
        card_id = physical.card_id
    else:
        play = context.play
        if (play is None or play != play_record(context.state, play.id) or
                (play.source_id, play.player_id, play.kind) !=
                (context.source_id, context.player_id, CardType.MINION) or
                play.minion_result != 'summoned' or play.countered or play.completed or play.interrupted or
                context.cast is not None or context.battlecry is not None):
            raise ValueError('Assembly minion play requires its actual accepted physical minion play')
        card_id = play.card_id
    face = registry.card(card_id)
    if face.on_play != behavior_id:
        raise ValueError('Assembly minion play body differs from its accepted printed face')
    return face


def run(context, registry, behavior_id, condition_id, predicate, body):
    face = accepted_face(context, registry, behavior_id)
    profile, _ = parts(registry, face.id)
    if profile.condition_id != condition_id:
        raise ValueError('Assembly minion play borrowed another original condition')
    if profile.kind == 'kindred':
        from .kindred import request
        return request(context, face.id)
    result = predicate(context)
    if type(result) is not bool:
        raise ValueError('Assembly Outcast condition requires an explicit boolean')
    return body(context) if result else ()
