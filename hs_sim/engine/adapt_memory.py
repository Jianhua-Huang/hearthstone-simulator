"""Two actual Adapt rounds and their source-independent future-play material.

Choices, attachments, entry, magnetic fusion and summons retain their existing
executors. The generated primary/extra and pre-entry policies require CN calibration.
"""
from dataclasses import dataclass, replace
from types import SimpleNamespace

from .adapt import CHOICE_IDS, PLANT_ID, _effect
from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import Buff, ChoiceOption, Effect, GrantDeathrattle, GrantKeyword, RequestChoice, _behavior, _player
from .errors import ResolutionError
from .model import CardType, Zone
from .sacrifice import (BuffCapturedMinion, GrantCapturedDeathrattle, GrantCapturedKeyword,
                       MinionReference, reference_value)

SPORES = 'adapt.native_living_spores.v1'


def validate_options(registry):
    for cid in CHOICE_IDS:
        card = registry.card(cid)
        if card.kind != CardType.SPELL or not card.choice_only:
            raise ValueError('Remembered Adaptations require all ten actual choice-only faces')
    plant = registry.card(PLANT_ID)
    if (plant.kind, plant.cost, plant.attack, plant.health) != (CardType.MINION, 1, 1, 1):
        raise ValueError('Living Spores requires its complete original 1/1 Plant')
    registry.behavior(SPORES)


@dataclass(frozen=True)
class AdaptAndRemember(Effect):
    player_id: int
    source: SourceAllocationFact
    beneficiary: MinionReference | None
    spec_id: str
    selected: tuple[str, ...] = ()

    def __post_init__(self):
        _player(self.player_id); _behavior(self.spec_id)
        if type(self.source) is not SourceAllocationFact or self.source.kind != CardType.MINION:
            raise ValueError('Remembered Adaptations require their original minion source')
        self.source.__post_init__()
        if (type(self.selected) is not tuple or len(self.selected) > 2 or
                any(type(cid) is not str or cid not in CHOICE_IDS for cid in self.selected)):
            raise ValueError('Remembered Adaptations have exactly two fixed-choice rounds')
        if self.beneficiary is not None:
            reference_value(self.beneficiary)
            ref, fact = self.beneficiary, self.source
            if (fact.zone != Zone.BOARD or (ref.entity_id, ref.player_id, ref.card_id, ref.zone_epoch,
                    ref.entered_order) != (fact.entity_id, fact.controller, fact.card_id, fact.zone_epoch,
                    fact.entered_order)):
                raise ValueError('Adaptation beneficiary differs from its original source residency')


def validate_request(request, registry, state=None):
    request.__post_init__()
    if registry.player_effect(request.spec_id).kind != 'adaptations':
        raise ValueError('Remembered Adaptations require their independent permanent profile')
    validate_options(registry)
    if registry.card(request.source.card_id).kind != CardType.MINION:
        raise ValueError('Adaptation source has another registered kind')
    if state is not None:
        validate_allocation(state, registry, request.source)


def remember_adaptations(context, spec_id):
    """Freeze this Battlecry's source, recipient and actor once, before round one."""
    source = SourceAllocationFact.capture(context.state, context.source)
    beneficiary = (MinionReference.capture(context.source)
                   if context.source.zone == Zone.BOARD else None)
    return AdaptAndRemember(context.player_id, source, beneficiary, spec_id)


def recipe(player_id, source_id, entity, cid):
    effect = _effect(SimpleNamespace(player_id=player_id, source_id=source_id), entity, cid)
    return replace(effect, behavior_id=SPORES) if type(effect) is GrantDeathrattle else effect


def captured_recipe(request, cid):
    ref = request.beneficiary
    if ref is None:
        return ()
    effect = recipe(request.player_id, request.source.entity_id,
                    SimpleNamespace(id=ref.entity_id, controller=ref.player_id), cid)
    if type(effect) is Buff:
        return (BuffCapturedMinion(ref, effect.attack, effect.health, effect.source_id),)
    if type(effect) is GrantKeyword:
        return (GrantCapturedKeyword(ref, effect.keyword, effect.source_id, duration=effect.duration),)
    return (GrantCapturedDeathrattle(ref, effect.behavior_id, effect.source_id),)


def adapt_and_remember(r, request):
    validate_request(request, r.registry, r.state)
    if len(request.selected) == 2:
        from .player_effects import AddPlayerEffect, add
        # One ordinary instance commits the whole ordered program before its
        # added notification; no half-program is active during either round.
        add(r, AddPlayerEffect(request.player_id, request.spec_id, request.source.entity_id),
            adaptations=request.selected, adaptation_source=request.source)
        return ()
    options = tuple(ChoiceOption(cid, r.registry.card(cid).name,
        (*captured_recipe(request, cid), replace(request, selected=(*request.selected, cid))),
        card_id=cid) for cid in CHOICE_IDS)
    return (RequestChoice(request.player_id, options, request.source.entity_id,
                          prompt='选择一项进化', sample_size=3),)


def living_spores(context):
    from .ordered_group_batches import SummonOrderedGroup
    from .ordered_summon_groups import OrderedGroupMember, OrderedSummonGroupSpec
    from .summon_quantities import SummonCause, SummonEntryMaterial
    position = None if context.death is None else context.death.position
    members = tuple(OrderedGroupMember('plant-' + str(i), SummonEntryMaterial(PLANT_ID),
        None if position is None else position + i) for i in range(2))
    return (SummonOrderedGroup(OrderedSummonGroupSpec(context.player_id, SummonCause.capture(context), members)),)


def programs(r, player_id):
    return tuple(e for e in r.player(player_id).player_effects
                 if r.registry.player_effect(e.spec_id).kind == 'adaptations')


def install(r, entity, player_id, instances):
    from .resolver import _buff_to, _grant_to
    validate_options(r.registry)
    for instance in instances:
        instance.__post_init__()
        for cid in instance.adaptations:
            effect = recipe(player_id, instance.source_id, entity, cid)
            if type(effect) is Buff:
                _buff_to(r, effect, entity, notify=False)
            else:
                _grant_to(r, effect, entity, notify=False, pending=entity.zone == Zone.PLAY,
                          grant_card_id=instance.source_card_id)


def install_paid(r, play, entity):
    instances = programs(r, play.player_id)
    if not instances:
        return
    from .play_history import play_record
    if (play != play_record(r.state, play.id) or play.kind != CardType.MINION or
            play.source_id != entity.id or entity.zone != Zone.PLAY or
            entity.controller != play.player_id or entity.card_id != play.card_id or
            play.minion_result is not None or play.submitted_cost is None):
        raise ResolutionError('Remembered Adaptations lost the original accepted paid minion')
    install(r, entity, play.player_id, instances)


def install_generated(r, root, entity):
    instances = programs(r, root.request.player_id)
    if not instances:
        return
    from .replay_entry_material import PhysicalReplayEntryMaterial, validate_scope
    from .summon_quantities import record
    material = root.request.materials[root.selected]
    if (type(material) is not PhysicalReplayEntryMaterial or root != record(r.state, root.id) or
            root.status != 'active' or root.deliveries or entity.zone != Zone.BOARD or
            entity.kind != CardType.MINION or entity.card_id != material.card_id or
            entity.controller != root.request.player_id):
        raise ResolutionError('Remembered Adaptations lost their original generated primary')
    validate_scope(r.state, r.registry, root.request, material)
    install(r, entity, root.request.player_id, instances)


def register(mechanics):
    mechanics.register(AdaptAndRemember, adapt_and_remember)
