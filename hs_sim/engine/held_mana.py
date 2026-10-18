"""Original mana debits while continuously holding a physical card.

Payments reuse CostUseReceipt, explicit consumption reuses ManaConsumptionRecord.
Both atomic writers precede notifications. Hand plays freeze their prepayment
condition; later current entities cannot rewrite historical Battlecries.
"""
from dataclasses import replace
from .errors import ResolutionError
from .model import HeldManaProgress, PaymentType


def ability(entity):
    return next((a for a in entity.abilities if a.kind == 'hand_progress' and
                 a.hand_progress.kind == 'mana_spent'), None)


def reset_entry(entity):
    a = ability(entity)
    if a is not None:
        entity.abilities[entity.abilities.index(a)] = replace(a, progress_value=0, progress_completions=0,
                                                            progress_keys=(), progress_units=(), consumed=False)


def capture(state, entity):
    a = ability(entity)
    return None if a is None else HeldManaProgress(a.hand_progress, a.progress_keys, a.progress_units,
                                                  len(state.cost_use_history)+1, len(state.mana_consumption_history)+1)


def note(state, player_id, key, amount, *, exclude_id=None):
    if amount <= 0: return
    from .hand_progress import advance_value
    from .lifecycle import refresh_entity
    for identity in state.players[player_id].hand:
        if identity == exclude_id: continue
        entity = state.entities[identity]; a = ability(entity)
        if a is None or a.consumed: continue
        if key in a.progress_keys: raise ValueError('Duplicate atomic held mana debit')
        entity.abilities[entity.abilities.index(a)] = advance_value(a, key, amount)
        refresh_entity(entity)


def note_payment(state, receipt, *, exclude_source=False):
    if receipt.origin == 'payment' and receipt.payment == PaymentType.MANA:
        note(state, receipt.player_id, f'payment:{receipt.id}', receipt.amount,
             exclude_id=receipt.source_id if exclude_source else None)


def note_consumption(state, receipt):
    note(state, receipt.player_id, f'consumption:{receipt.id}', receipt.actual)


def satisfied(context):
    from .play_history import play_record
    from .battlecries import battlecry_record
    record = context.battlecry; historical = False
    while record is not None and record.origin == 'history':
        historical = True
        original = battlecry_record(context.state, record.history_id)
        if original.id >= record.id: raise ResolutionError('Cyclic held mana Battlecry history')
        record = original
    play = context.play
    if record is not None:
        if record.origin == 'hand': play = play_record(context.state, record.play_id)
        elif record.origin == 'played_history': play = play_record(context.state, record.history_play_id)
        elif historical: raise ResolutionError('Historical effect Battlecry has no original held mana condition')
        else: play = None
    if play is not None:
        if play.held_mana is None: raise ResolutionError('Played Battlecry lost its original held mana facts')
        return play.held_mana.completed
    a = ability(context.source)
    if a is None: raise ResolutionError('Effect Battlecry carrier has no held mana declaration')
    return a.consumed


def validate_progress(state, registry, progress, play=None):
    if type(progress) is not HeldManaProgress: raise ValueError('Expected original held mana condition')
    progress.__post_init__(); registry.validate_hand_progress(progress.spec)
    if (progress.before_payment_id > len(state.cost_use_history)+1 or
            progress.before_consumption_id > len(state.mana_consumption_history)+1):
        raise ValueError('Held mana cursor exceeds original debit history')
    if play is not None and progress.spec != registry.card(play.card_id).hand_progress:
        raise ValueError('Played held mana declaration differs from original card')
    accepted = 0
    for key, units in zip(progress.keys, progress.units):
        kind, number = key.split(':'); identity = int(number)
        if kind == 'payment':
            row = state.cost_use_history[identity-1]
            if row.origin != 'payment' or row.payment != PaymentType.MANA:
                raise ValueError('Held mana borrowed a non-mana or unpaid cost use')
            amount = row.amount
        else:
            row = state.mana_consumption_history[identity-1]; amount = row.actual
        if units != min(amount, progress.spec.goal-accepted) or units <= 0:
            raise ValueError('Held mana units differ from actual original debit')
        if play is not None and (row.turn > play.turn or row.action > play.action):
            raise ValueError('Held mana debit postdates original hand play')
        accepted += units


def validate_ability(state, registry, a):
    if a.hand_progress.kind != 'mana_spent': return
    progress = HeldManaProgress(a.hand_progress, a.progress_keys, a.progress_units,
                                len(state.cost_use_history)+1, len(state.mana_consumption_history)+1)
    validate_progress(state, registry, progress)
    if (a.progress_value != sum(progress.units) or a.progress_completions != int(progress.completed) or
            a.consumed != progress.completed):
        raise ValueError('Held mana progress differs from its actual debit witnesses')
