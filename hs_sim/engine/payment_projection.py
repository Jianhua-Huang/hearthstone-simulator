"""Pure, staged cost settlement projection and global finite-use facts.

This does not execute events, trigger conditions, handlers or checkpoints.
Quote truth and Rewind provenance belong to the separate cost acceptance proof.
"""
from copy import deepcopy
from .runtime_copy import deepcopy as copy_native
from dataclasses import dataclass, fields, replace
from .errors import ResolutionError
from .model import CostUseReceipt, PaymentType, Resource


@dataclass(frozen=True)
class PaymentWrite:
    collection: str
    identity: int | None
    name: str
    before: object
    after: object


@dataclass(frozen=True)
class PaymentEvent:
    kind: str
    data: tuple


@dataclass(frozen=True)
class PaymentPlan:
    resource_writes: tuple[PaymentWrite, ...]
    health_events: tuple[PaymentEvent, ...]
    hero_health_data: tuple = ()
    corpse_spend_id: int | None = None


@dataclass(frozen=True)
class PaymentCapture:
    event: PaymentEvent
    state: object


@dataclass(frozen=True)
class PaymentProjection:
    resource_state: object
    captures: tuple[PaymentCapture, ...]
    final_state: object


def payment_plan(state, quote):
    from .costs import payment_error
    if reason := payment_error(state, quote):
        raise ResolutionError(f'{reason} at payment')
    player = state.players[quote.player_id]
    source = state.entities.get(quote.entity_id)
    if source is None:
        raise ResolutionError('Payment quote has no physical source')
    hero = state.entities[player.hero_id]
    writes, events = [], []
    hero_health_data = ()
    corpse_spend_id = None

    def write(collection, identity, name, before, after):
        if before != after:
            writes.append(PaymentWrite(collection, identity, name, deepcopy(before), deepcopy(after)))

    if quote.payment == PaymentType.MANA:
        from .resources import project_mana_spend
        result = project_mana_spend(player, quote.amount)
        for name in ('temporary_mana', 'mana_spent', 'mana'):
            write('player', player.id, name, getattr(player, name), getattr(result, name))
    elif quote.payment in (PaymentType.HEALTH,PaymentType.OPPONENT_HEALTH):
        from .health_loss import replacement_for, project_loss
        from .model import HealthLossKind
        opponent = quote.payment==PaymentType.OPPONENT_HEALTH
        if opponent:
            hero=state.entities[state.players[3-player.id].hero_id]
        # Eligibility is taken before the original armor debit, as before.
        replacement = replacement_for(state, hero.id, HealthLossKind.PAYMENT)
        armor = 0 if opponent else min(hero.armor, quote.amount)
        armored = deepcopy(hero); armored.armor -= armor
        result = project_loss(state, armored, quote.amount - armor,
                              HealthLossKind.PAYMENT, source.id, replacement)
        from .hero_health_history import prepare_change, snapshot as hero_health_snapshot, event_data
        before_health, after_health = hero_health_snapshot(hero), hero_health_snapshot(result.target)
        health_row = prepare_change(state, before_health, after_health, f'{quote.payment.value}_spent')
        hero_health_data = tuple(sorted(event_data(before_health, after_health, health_row).items()))
        if health_row is not None:
            write('state', None, 'hero_health_change_history', state.hero_health_change_history,
                  [*state.hero_health_change_history, health_row])
            write('state', None, 'next_hero_health_change_id', state.next_hero_health_change_id,
                  state.next_hero_health_change_id + 1)
        for field in fields(type(hero)):
            write('entity', hero.id, field.name, getattr(hero, field.name), getattr(result.target, field.name))
        write('state', None, 'next_attachment_id', state.next_attachment_id, result.next_attachment_id)
        events.extend(PaymentEvent(kind, tuple(sorted(data.items()))) for kind, data in result.events)
    elif quote.payment == PaymentType.ARMOR:
        write('entity', hero.id, 'armor', hero.armor, hero.armor - quote.amount)
    else:
        after = dict(player.resources); after[Resource.CORPSES] -= quote.amount
        write('player', player.id, 'resources', player.resources, after)
        from .resources import prepare_corpse_spend
        corpse_row = prepare_corpse_spend(state, player.id, player.resources[Resource.CORPSES], quote.amount, 'payment', source.id)
        write('state', None, 'corpse_spend_history', state.corpse_spend_history, [*state.corpse_spend_history, corpse_row])
        corpse_spend_id = corpse_row.id
    return PaymentPlan(tuple(writes), tuple(events), hero_health_data, corpse_spend_id)


def apply_resource_writes(state, writes):
    for write in writes:
        target = state if write.collection == 'state' else (
            state.players[write.identity] if write.collection == 'player' else state.entities[write.identity])
        if getattr(target, write.name) != write.before:
            raise ValueError('Payment resource projection no longer matches its original state')
        setattr(target, write.name, deepcopy(write.after))


def consume_quoted_modifiers(state, quote, *, origin, exclude_held_source=False):
    from .costs import consume_modifiers
    player = state.players[quote.player_id]
    source = state.entities[quote.entity_id]
    applied = tuple(sorted((m for m in player.cost_modifiers if m.id in quote.modifier_ids), key=lambda m:m.id))
    receipt = CostUseReceipt(len(state.cost_use_history) + 1, player.id, source.id, source.card_id,
        state.turn, state.action_number, origin, quote.amount, quote.payment,
        quote.modifier_ids, applied, quote.consumable_ids, current_deck=quote.current_deck,
        permanent_mana=quote.permanent_mana,kindred_sources=quote.kindred_sources)
    # Same formula and position as before. No event/checkpoint at this append.
    consume_modifiers(player, quote.consumable_ids)
    if quote.kindred_sources:
        actual=tuple(x for x in player.player_effects if x.id in{x.id for x in quote.kindred_sources})
        if tuple(sorted(actual,key=lambda x:x.id))!=quote.kindred_sources:
            raise ValueError('Payment lost its complete original Kindred source instances')
        used={x.id for x in quote.kindred_sources}
        player.player_effects=[x for x in player.player_effects if x.id not in used]
    state.cost_use_history.append(receipt)
    from .held_mana import note_payment
    note_payment(state,receipt,exclude_source=exclude_held_source)
    return receipt


def project_payment(before, quote, *, registry=None, cause_reason=None, cause_source=None, cause_target_id=None):
    return _project_payment(before, quote, registry=registry, cause_reason=cause_reason,
        cause_source=cause_source, cause_target_id=cause_target_id, capture_stages=True)


def _validation_working_state(before, registry):
    """Local payment-check workspace; never a public detached state.

    Payment/normalization can write either player's accounts and any entity.
    Copy those complete inventories. The only in-place state-list writes are
    the cost-use append and subsequent commit_play append; resource writes
    replace other state fields with detached values. Remaining histories are
    read only by these synchronous core helpers, with no behavior callbacks.
    """
    from .model import Entity, GameState, PlayerState
    from .registry import Registry
    if (type(before) is not GameState or registry is not None and type(registry) is not Registry
            or type(before.players) is not dict or type(before.entities) is not dict
            or any(type(p) is not PlayerState for p in before.players.values())
            or any(type(e) is not Entity for e in before.entities.values())
            or type(before.cost_use_history) is not list or type(before.play_history) is not list):
        return deepcopy(before)
    players, entities = copy_native((before.players, before.entities))
    return replace(before, players=players, entities=entities,
                   cost_use_history=list(before.cost_use_history),
                   play_history=list(before.play_history))


def _project_payment(before, quote, *, registry=None, cause_reason=None, cause_source=None,
                     cause_target_id=None, capture_stages, _validation_only=False):
    """Use the same writes/normalization with optional detached stage records."""
    from .event_normalization import normalize_event_state
    from .resources import corpse_spend_data
    work = (_validation_working_state(before, registry)
            if _validation_only and not capture_stages else deepcopy(before))
    plan = payment_plan(work, quote)
    apply_resource_writes(work, plan.resource_writes)
    resource_state = deepcopy(work) if capture_stages else None
    captures = []
    for event in plan.health_events:
        normalize_event_state(work, cause_reason if cause_reason is not None else event.kind,
            registry=registry,
            cause_source=cause_source, cause_target_id=cause_target_id,remaining_mana_payment_source=quote.entity_id)
        if capture_stages:
            captures.append(PaymentCapture(event, deepcopy(work)))
    consume_quoted_modifiers(work, quote, origin='payment', exclude_held_source=True)
    event = PaymentEvent(f'{quote.payment.value}_spent', tuple(sorted(dict(source_id=quote.entity_id,
        player_id=quote.player_id, amount=quote.amount, modifier_ids=quote.modifier_ids,
        consumed_ids=quote.consumable_ids, **dict(plan.hero_health_data),
        **corpse_spend_data(work, plan.corpse_spend_id)).items())))
    normalize_event_state(work, cause_reason if cause_reason is not None else event.kind,
        registry=registry,
        cause_source=cause_source, cause_target_id=cause_target_id,remaining_mana_payment_source=quote.entity_id)
    if capture_stages:
        captures.append(PaymentCapture(event, deepcopy(work)))
        return PaymentProjection(resource_state, tuple(captures), deepcopy(work))
    # A validation-only workspace must stay inside the synchronous comparison.
    # All other callers retain the original fully detached working copy.
    return work


def validate_spell_payment_submission(before, quote, prepared_play, submission_state, registry=None):
    # Real PlayFromHand has only action: no work.source_id or work.target_id.
    if (prepared_play.id != len(before.play_history) + 1 or
            (prepared_play.source_id, prepared_play.player_id, prepared_play.action) !=
            (quote.entity_id, quote.player_id, before.action_number)):
        raise ValueError('Payment proof does not belong to this next prepared hand play')
    expected = _project_payment(before, quote, registry=registry, cause_reason='PlayFromHand',
                                capture_stages=False, _validation_only=True)
    # This is comparison of the actual next append, never eligibility querying.
    from .play_history import commit_play
    commit_play(expected, prepared_play)
    if expected != submission_state:
        raise ValueError('Spell submission changed its complete projected payment boundary')


def validate_cost_use_history(state, registry=None):
    from .repeat_provenance import checked_live_attachments
    if type(state.cost_use_history) is not list:
        raise ValueError('Cost use history requires a list')
    catalogue = checked_live_attachments(state)
    expected, owners = {}, {}
    previous_turn = previous_action = 0
    used_kindred=set()
    for index, receipt in enumerate(state.cost_use_history, 1):
        if type(receipt) is not CostUseReceipt: raise ValueError('Invalid cost use receipt')
        receipt.__post_init__()
        if (receipt.id != index or receipt.source_id not in state.entities or
                not previous_turn <= receipt.turn <= state.turn or
                not previous_action <= receipt.action <= state.action_number):
            raise ValueError('Invalid cost use identity/order/source')
        if registry is not None: registry.card(receipt.source_card_id)
        for instance in receipt.kindred_sources:
            if(instance.id>=state.next_attachment_id or instance.id in used_kindred or
                    instance.source_id not in state.entities or instance.created_turn>receipt.turn or
                    any(x.id==instance.id for p in state.players.values()for x in p.player_effects)):
                raise ValueError('Intrinsic Kindred payment borrowed a future, live or reused source')
            used_kindred.add(instance.id)
            if registry is not None:
                from .kindred import validate_sources
                validate_sources(registry,(instance,))
                profile=registry.kindred_profiles.get(receipt.source_card_id)
                if profile is None or profile.mode!='cost':raise ValueError('Kindred payment source has no native cost consumer')
        if receipt.kindred_sources:
            roots=[p for p in state.play_history if(p.source_id,p.player_id,p.turn,p.action)==
                (receipt.source_id,receipt.player_id,receipt.turn,receipt.action)]
            if roots and(len(roots)!=1 or roots[0].submitted_cost is None or
                    roots[0].submitted_cost.quote.intrinsic.kindred_sources!=receipt.kindred_sources):
                raise ValueError('Kindred use differs from the original submitted price sources')
        if any(i >= state.next_attachment_id for i in receipt.modifier_ids):
            raise ValueError('Cost use references a future attachment')
        for modifier in receipt.player_modifiers:
            if modifier.id in expected and (owners[modifier.id] != receipt.player_id or expected[modifier.id] != modifier):
                raise ValueError('Cost use disagrees with the exact global remaining-use clock')
            owners[modifier.id] = receipt.player_id
            if modifier.id not in receipt.consumable_ids:
                expected[modifier.id] = modifier
            elif modifier.uses_remaining == 1:
                expected[modifier.id] = None
            else:
                expected[modifier.id] = replace(modifier, uses_remaining=modifier.uses_remaining - 1)
        previous_turn, previous_action = receipt.turn, receipt.action
    for identity, value in expected.items():
        if identity not in catalogue: continue  # Explicit remove/expiry may end this identity.
        family, owner, current = catalogue[identity]
        if family != 'cost_modifiers' or value is None or owners[identity] != owner or current != value:
            raise ValueError('Live attachment differs from the exact cost use clock or family')


def validate_cost_source_history(original, current, registry):
    """Bind an original complete cost inventory through actual later uses.

    All original policies are seeded, including false ones and both players.
    Prices, applicability, current zones and witnesses are never re-queried.
    A source may disappear through removal/expiry, but its allocated identity
    cannot be repurposed or change the complete value in a later receipt.
    """
    from .costs import validated_cost_source_inventory
    from .model import AbilityInstance
    old = validated_cost_source_inventory(original, registry)
    live = validated_cost_source_inventory(current, registry)
    validate_cost_use_history(original, registry)
    validate_cost_use_history(current, registry)
    size = len(original.cost_use_history)
    if (len(current.cost_use_history) < size or
            current.cost_use_history[:size] != original.cost_use_history):
        raise ValueError('Original cost use history prefix was removed or rewritten')
    if current.next_attachment_id < original.next_attachment_id:
        raise ValueError('Cost source allocation moved backwards')
    expected = {identity: (owner, value) for identity, (family, owner, value) in old.items()
                if family == 'cost_modifiers'}
    for receipt in current.cost_use_history[size:]:
        full = {modifier.id: modifier for modifier in receipt.player_modifiers}
        for identity in receipt.modifier_ids:
            entry = old.get(identity)
            if entry is None:
                if identity < original.next_attachment_id:
                    raise ValueError('Later cost use reuses an old missing attachment identity')
                continue
            family, carrier, value = entry
            if family == 'cost_modifiers':
                if identity not in full:
                    raise ValueError('Later quote omitted an original complete player cost source')
            elif family == 'ability' and value.kind == 'cost_aura':
                if identity in full:
                    raise ValueError('Later cost policy borrows an original cost aura identity')
            else:
                raise ValueError('Later cost quote borrows an original foreign attachment identity')
        for modifier in receipt.player_modifiers:
            if modifier.id in expected:
                owner, before = expected[modifier.id]
                if owner != receipt.player_id or before != modifier:
                    raise ValueError('Later cost source changed its original identity or exact use clock')
            elif modifier.id < original.next_attachment_id:
                raise ValueError('Later cost source borrows an original allocated identity')
            if modifier.id not in receipt.consumable_ids:
                after = modifier
            elif modifier.uses_remaining == 1:
                after = None
            else:
                after = replace(modifier, uses_remaining=modifier.uses_remaining - 1)
            expected[modifier.id] = (receipt.player_id, after)
    for identity, (owner, value) in expected.items():
        if identity not in live:
            continue
        family, carrier, present = live[identity]
        if family != 'cost_modifiers' or value is None or carrier != owner or present != value:
            raise ValueError('Current cost source changed its original family or exact use clock')
    for identity, (family, carrier, before) in old.items():
        if family != 'ability' or before.kind != 'cost_aura' or identity not in live:
            continue
        new_family, new_carrier, value = live[identity]
        if (new_family != 'ability' or type(value) is not AbilityInstance or
                new_carrier != carrier or replace(value, consumed=before.consumed) != before or
                before.consumed and not value.consumed):
            raise ValueError('Original cost aura changed its family, declaration or physical carrier')
    for identity, (family, carrier, value) in live.items():
        is_aura = family == 'ability' and value.kind == 'cost_aura'
        if family != 'cost_modifiers' and not is_aura:
            continue
        entry = old.get(identity)
        if entry is None:
            if identity < original.next_attachment_id:
                raise ValueError('Current cost source reuses an old missing attachment identity')
            continue
        old_family, old_carrier, before = entry
        if family != old_family:
            raise ValueError('Current cost source borrows an original foreign attachment family')
        if family == 'cost_modifiers':
            # Complete policy and owner checks were made using the seeded clock.
            if identity not in expected:
                raise ValueError('Current cost policy borrows an original foreign identity')
        elif (type(before) is not AbilityInstance or before.kind != 'cost_aura' or
              carrier != old_carrier or replace(value, consumed=before.consumed) != before or
              before.consumed and not value.consumed):
            raise ValueError('Current cost aura changed its original declaration or physical carrier')
