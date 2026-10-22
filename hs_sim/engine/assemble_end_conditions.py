"""Explicit source proof for a gate evaluated in the original end callback view."""
from dataclasses import dataclass

from .model import CardType, _name

NATIVE_END_CONDITION_PREFIX = 'assemble.native_end_condition:'


@dataclass(frozen=True)
class AssembleNativeEndConditionSource:
    card_id: str
    original_behavior_id: str
    condition_id: str

    def __post_init__(self):
        for field in ('card_id', 'original_behavior_id', 'condition_id'):
            _name(getattr(self, field), 'assembly native end condition ' + field)
        if (self.card_id.startswith('assemble:') or
                not self.condition_id.startswith(NATIVE_END_CONDITION_PREFIX) or
                not self.condition_id[len(NATIVE_END_CONDITION_PREFIX):]):
            raise ValueError('Native end condition requires a static source and explicit callback namespace')


def validate_source(registry, source):
    if type(source) is not AssembleNativeEndConditionSource:
        raise ValueError('Invalid native end condition source')
    source.__post_init__()
    original = registry._cards.get(source.card_id)
    if (original is None or original.kind != CardType.MINION or original.choice_only or
            len(original.triggers) != 1 or original.triggers[0].event != 'turn_ended' or
            original.triggers[0].end_turn is None or
            original.triggers[0].behavior_id != source.original_behavior_id):
        raise ValueError('Native end condition changed its complete original trigger')
    registry.behavior(source.original_behavior_id)
    registry.trigger_condition(source.condition_id)


def native_callback_condition(registry, condition_id):
    if not condition_id.startswith(NATIVE_END_CONDITION_PREFIX):
        return False
    source = registry._assemble_native_end_conditions.get(condition_id)
    if source is None:
        raise ValueError('Native end condition requires its reviewed source proof')
    validate_source(registry, source)
    return True


def validate_template(registry, template):
    cid = template.prefix.condition_id
    if cid is None or not native_callback_condition(registry, cid):
        return
    source = registry._assemble_native_end_conditions[cid]
    if (template.card_id != source.card_id or template.prefix.timing != 'end_turn' or
            template.original_end_turn_id != source.original_behavior_id):
        raise ValueError('Native end condition is bound to its actual original ending prefix')


def validate_sources(registry):
    for condition_id, source in registry._assemble_native_end_conditions.items():
        validate_source(registry, source)
        if (condition_id != source.condition_id or source.card_id not in registry._assemble_templates or
                registry._assemble_templates[source.card_id].prefix.condition_id != condition_id):
            raise ValueError('Native end condition requires its actual minion template')
        validate_template(registry, registry._assemble_templates[source.card_id])
