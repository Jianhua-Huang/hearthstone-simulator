"""One actual source budget partitioned before recipient protection/settlement."""
from dataclasses import dataclass
from .effects import Damage, Effect, _integer
from .errors import ResolutionError
from .health_rules import prepare_health
from .model import CardType, DamageKind, HealthLayer
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class DamageExcessToHero(Effect):
    minion: MinionReference
    amount: int
    source_id: int
    on_result: str | None = None
    kind: DamageKind = DamageKind.SPELL

    def __post_init__(self):
        reference_value(self.minion)
        _integer(self.amount, 'partition base damage', 0)
        _integer(self.source_id, 'partition source', 1)
        if type(self.kind) is not DamageKind or self.kind not in (DamageKind.SPELL, DamageKind.EFFECT):
            raise ValueError('Partition supports its actual spell or location effect source')
        Damage(self.minion.entity_id, self.amount, self.source_id, self.kind,
               on_result=self.on_result).__post_init__()


def prepare_partition(state, registry, request, rules):
    request.__post_init__()
    source = state.entities.get(request.source_id)
    source_kind = CardType.SPELL if request.kind == DamageKind.SPELL else CardType.LOCATION
    if source is None or registry.card(source.card_id).kind != source_kind:
        raise ResolutionError('Damage partition requires its actual allocated spell or location source')
    definition = registry.card(request.minion.card_id)
    if definition.kind != CardType.MINION or definition.interactable is not None:
        raise ResolutionError('Damage partition requires an ordinary original minion')
    if request.on_result is not None: registry.behavior(request.on_result)
    target = live_minion(state, request.minion)
    if target is None: return (), ()
    source_rules = tuple(row for row in rules if row[3].layer == HealthLayer.SOURCE)
    target_rules = tuple(row for row in rules if row[3].layer == HealthLayer.TARGET)
    original = Damage(target.id, request.amount, request.source_id, request.kind)
    budget = prepare_health(state, registry, original, rules=source_rules)
    first = min(budget.amount, target.health)
    remaining = budget.amount - first
    hero = state.players[target.controller].hero_id
    instructions = (Damage(target.id, first, request.source_id, request.kind, on_result=request.on_result),)
    if remaining:
        instructions += (Damage(hero, remaining, request.source_id, request.kind, on_result=request.on_result),)
    packets = tuple(prepare_health(state, registry, instruction, rules=target_rules,
                                  partition_source=budget) for instruction in instructions)
    return instructions, packets


def resolve(r, request):
    from .resolver import settle_health_batch
    return settle_health_batch(r, (), partition_request=request)


def register(mechanics):
    mechanics.register(DamageExcessToHero, resolve)
