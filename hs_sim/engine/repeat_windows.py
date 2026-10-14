"""Existing durable family acceptance windows, separate from ordinary event views.

This inventory does not decide chronology; each family compares its complete
original accepted markers and prefix before trusting a foreign window.
"""

def original_acceptance_windows(work):
    """Return existing family acceptance contexts, never an extra body view."""
    from .battlecry_repeats import FinishBattlecryAcceptance
    from .combo_acceptance import FinishComboAcceptance
    from .spell_acceptance import FinishSpellAcceptance
    from .deathrattles import InvokeDeathrattle, FinishDeathrattleBatch
    from .power_payloads import InvokeHeroPowerPayload
    from .end_turns import InvokeEndTurn, FinishEndTurnBatch, CheckActiveEndTurn
    from .limited_triggers import CheckLimitedTrigger
    from .hero_powers import CheckHeroPowerTrigger, FinishHeroPower
    if type(work) is FinishSpellAcceptance:
        return ((work.submission, 'spell_submission', work.play_id), *(
            ((work.resolution, 'spell_payload', work.play_id),) if work.resolution is not None else ()))
    if type(work) is FinishBattlecryAcceptance:
        return ((work.context, 'battlecry_activation', work.context.play.id),)
    if type(work) is FinishComboAcceptance:
        return ((work.context, 'combo_policy', work.receipt_id),)
    if type(work) in (InvokeDeathrattle, FinishDeathrattleBatch):
        return ((work.context, 'deathrattle', work.context.deathrattle.group_id),)
    if type(work) is InvokeHeroPowerPayload:
        return ((work.context, 'power_payload', work.context.power_payload.batch_id),)
    if type(work) is FinishHeroPower:
        return ((work.context, 'power', work.record_id),)
    if type(work) is InvokeEndTurn:
        return ((work.acceptance, 'end_turn', work.acceptance.end_turn.batch_id),)
    if type(work) is CheckActiveEndTurn:
        return ((work.acceptance, 'end_turn', work.acceptance.end_turn.batch_id),)
    if type(work) is CheckLimitedTrigger and work.end_turn_context is not None:
        return ((work.end_turn_context, 'end_turn', work.end_turn_context.end_turn.batch_id),)
    if type(work) is CheckHeroPowerTrigger and work.context.end_turn is not None:
        return ((work.context, 'end_turn', work.context.end_turn.batch_id),)
    if type(work) is FinishEndTurnBatch:
        return ((work.context, 'end_turn', work.batch.id),)
    return ()

