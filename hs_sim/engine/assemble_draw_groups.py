"""Selected text rewards retain the native pair of physical draw attempts."""
from dataclasses import dataclass, replace

from .errors import ResolutionError
from .model import BoardPresenceReference, CardType, Zone, _name
from .physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup


@dataclass(frozen=True)
class AssembleDrawGroupSource:
    card_id: str
    original_battlecry_id: str
    qualifier: str
    original_reward_behavior_id: str | None = None

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        _name(self.card_id, 'draw-group assembly source')
        _name(self.original_battlecry_id, 'original draw-group Battlecry')
        if (self.card_id.startswith('assemble:') or
                self.original_battlecry_id.startswith(TIMING_PREFIXES) or
                self.qualifier not in ('each_non_minion', 'both_minions')):
            raise ValueError('Draw-group prefix requires its actual native qualifier')
        if self.qualifier == 'each_non_minion':
            _name(self.original_reward_behavior_id, 'original per-draw reward')
        elif self.original_reward_behavior_id is not None:
            raise ValueError('Native Charge is an original whole-group reward')


def validate_source(registry, source, *, require_template=False):
    if type(source) is not AssembleDrawGroupSource:
        raise ValueError('Expected AssembleDrawGroupSource')
    source.__post_init__()
    original = registry._cards.get(source.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            original.battlecry != source.original_battlecry_id or original.requires_target or
            original.targeting is not None or original.target_rule != 'any_entity'):
        raise ValueError('Draw-group prefix changed its complete original Battlecry')
    registry.behavior(source.original_battlecry_id)
    if source.original_reward_behavior_id is not None:
        registry.behavior(source.original_reward_behavior_id)
    template = registry._assemble_templates.get(source.card_id)
    if require_template and template is None:
        raise ValueError('Draw-group source requires its complete original template')
    if template is not None:
        validate_prefix(template, source)


def validate_prefix(template, source):
    if (template.prefix.timing != 'battlecry' or template.prefix.condition_id is not None or
            template.prefix.before_behavior_id != source.original_battlecry_id or
            template.original_battlecry_id != source.original_battlecry_id):
        raise ValueError('Draw-group template changed its actual native prefix')


def native_battlecry(registry, template, suffix):
    source = registry._assemble_draw_group_sources.get(template.card_id)
    if source is None:
        if any(p.original_battlecry_id == template.prefix.before_behavior_id
                for p in registry._assemble_draw_group_sources.values()):
            raise ValueError('Draw-group prefix cannot borrow another source declaration')
        return None
    validate_source(registry, source)
    validate_prefix(template, source)
    return source.original_battlecry_id if suffix == template.suffix else None


def selected_request(registry, context, before_id, body_id):
    matches = [p for p in registry._assemble_draw_group_sources.values()
        if p.original_battlecry_id == before_id]
    if not matches:
        return None
    from .assemble_faces import recipe_from_id, before_behavior_id
    source, = matches
    validate_source(registry, source, require_template=True)
    try:
        recipe = recipe_from_id(context.source.card_id)
        prefix_id = recipe.secondary_card_id if recipe.half == 'top' else recipe.primary_card_id
        face = registry.card(context.source.card_id)
        if prefix_id != source.card_id or face.battlecry != before_behavior_id(before_id, body_id):
            raise ValueError('Wrong selected prefix or complete immutable face')
    except ValueError as exc:
        raise ResolutionError('Draw prefix requires its original assembled Battlecry') from exc
    planned = registry.behavior(before_id)(context)
    if (type(planned) is not tuple or len(planned) != 1 or type(planned[0]) is not DrawPhysicalGroup or
            (planned[0].player_id, planned[0].source_id) != (context.player_id, context.source_id) or
            planned[0].slots != (DrawGroupSlot(),)*2 or planned[0].kindred_pair):
        raise ResolutionError('Draw prefix changed its complete native pair of attempts')
    request = planned[0]
    if source.qualifier == 'each_non_minion':
        expected = DrawGroupReward('non_minion_followup', behavior_id=source.original_reward_behavior_id)
    else:
        expected = (DrawGroupReward('source_charge_if_both_minions',
            source=BoardPresenceReference.capture(context.state, context.source_id))
            if context.source.kind == CardType.MINION and context.source.zone == Zone.BOARD
            else DrawGroupReward())
    if request.reward != expected:
        raise ResolutionError('Draw prefix changed its original complete reward policy')
    residence = (BoardPresenceReference.capture(context.state, context.source_id)
        if context.source.kind == CardType.MINION and context.source.zone == Zone.BOARD else None)
    reward = DrawGroupReward('qualified_non_minion_followup' if source.qualifier == 'each_non_minion'
        else 'qualified_both_minions_followup', source=residence, behavior_id=body_id,
        target_id=context.target_id)
    return (replace(request, reward=reward),)


def validate_sources(registry):
    seen = set()
    for cid, source in registry._assemble_draw_group_sources.items():
        validate_source(registry, source, require_template=True)
        if cid != source.card_id or source.original_battlecry_id in seen:
            raise ValueError('Duplicate or renamed native draw-group prefix')
        seen.add(source.original_battlecry_id)
