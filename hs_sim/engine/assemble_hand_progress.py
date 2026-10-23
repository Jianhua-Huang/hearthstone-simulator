"""Original held-card progress travels with its reviewed assembly prefix."""
from dataclasses import dataclass
from copy import deepcopy

from .model import CardType,HandProgressSpec,Zone,_name


@dataclass(frozen=True)
class AssembleHandProgressSource:
    card_id: str
    native_spec: HandProgressSpec
    original_battlecry_id: str
    condition_id: str
    reward_behavior_id: str

    def __post_init__(self):
        for name in('card_id','original_battlecry_id','condition_id','reward_behavior_id'):
            _name(getattr(self,name),'native held progress '+name)
        if self.card_id.startswith('assemble:')or type(self.native_spec)is not HandProgressSpec:
            raise ValueError('Held progress requires the complete original static declaration')
        self.native_spec.__post_init__()
        if (self.native_spec.kind,self.native_spec.goal,self.native_spec.event,self.native_spec.repeat,
                self.native_spec.upgrade_card_id,self.native_spec.on_progress,self.native_spec.zone)!=(
                'event',1,'spell_cast_accepted',False,None,None,Zone.HAND):
            raise ValueError('Held progress requires its original one-event hand stay')


def validate_source(registry,source,*,require_template=False):
    if type(source)is not AssembleHandProgressSource:raise ValueError('Expected complete original held progress')
    source.__post_init__();original=registry._cards.get(source.card_id)
    if (original is None or original.kind!=CardType.MINION or original.hand_progress!=source.native_spec or
            original.battlecry!=source.original_battlecry_id):
        raise ValueError('Held prefix changed its complete original progress or Battlecry')
    registry.trigger_condition(source.condition_id);registry.trigger_condition(source.native_spec.condition_id)
    registry.behavior(source.original_battlecry_id);registry.behavior(source.reward_behavior_id)
    template=registry._assemble_templates.get(source.card_id)
    if template is None:
        if require_template:raise ValueError('Held progress lacks its original template')
    elif (template.prefix.timing!='battlecry' or template.prefix.condition_id!=source.condition_id or
            template.prefix.before_behavior_id is not None or template.suffix.behavior_id!=source.reward_behavior_id or
            template.original_battlecry_id!=source.original_battlecry_id):
        raise ValueError('Held prefix changed its original condition, body or native bridge')


def prefix_material(registry,template):
    source=registry._assemble_hand_progress_sources.get(template.card_id)
    if source is None:
        original=registry._cards.get(template.card_id)
        if original is not None and original.hand_progress is not None:
            raise ValueError('Held assembly prefix lacks its reviewed complete progress declaration')
        return None
    validate_source(registry,source)
    return source.native_spec


def reviewed_condition(registry,condition_id):
    return condition_id is not None and any(p.condition_id==condition_id
        for p in registry._assemble_hand_progress_sources.values())


def native_battlecry(registry,template,suffix):
    source=registry._assemble_hand_progress_sources.get(template.card_id)
    return source.original_battlecry_id if source is not None and suffix==template.suffix else None


def effective_spec(state,registry,source,definition,spec):
    if spec is None or not definition.id.startswith('assemble:'):return spec
    from .assemble_faces import recipe_from_id
    recipe=recipe_from_id(definition.id)
    prefix_id=recipe.secondary_card_id if recipe.half=='top'else recipe.primary_card_id
    profile=registry._assemble_hand_progress_sources.get(prefix_id)
    if profile is None:return spec
    validate_source(registry,profile,require_template=True)
    from .registry import RuleContext
    result=registry.trigger_condition(profile.condition_id)(RuleContext(deepcopy(state),source.id,source.controller))
    if type(result)is not bool:raise ValueError('Held target condition must return bool')
    return spec if result else None


def validate_sources(registry):
    seen=set()
    for cid,profile in registry._assemble_hand_progress_sources.items():
        validate_source(registry,profile,require_template=True)
        if cid!=profile.card_id or profile.condition_id in seen:raise ValueError('Duplicate original held progress condition')
        seen.add(profile.condition_id)
