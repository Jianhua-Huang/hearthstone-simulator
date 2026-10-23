"""Finite post-installation spell-cost query over original CAST history."""
from dataclasses import dataclass

from .model import CardType, Zone, _int, _name


@dataclass(frozen=True)
class DormantSpellManaProfile:
    card_id: str
    goal: int = 5

    def __post_init__(self):
        _name(self.card_id, 'dormant spell-mana source')
        _int(self.goal, 'dormant spell-mana goal', 1)
        if self.goal != 5:
            raise ValueError('Only the reviewed five-Mana dormant source is declared')


def validate_profile(registry, profile):
    if type(profile) is not DormantSpellManaProfile:
        raise ValueError('Typed dormant spell-mana declaration required')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if (card.kind != CardType.MINION or not card.hand_playable or card.choice_only or
            card.dormant_turns is not None or card.permanent_dormancy or
            len(card.dormant_triggers) != 1 or card.dormant_triggers[0].event != 'spell_cast_finished'):
        raise ValueError('Spell-mana awakening requires its declared original dormant carrier')


def completed_mana(context, registry):
    """No duplicate progress counter, payment, or awakening implementation."""
    source = context.source
    profile = registry.dormant_spell_mana_profiles.get(source.card_id)
    if profile is None:
        raise ValueError('Unknown dormant spell-mana carrier')
    validate_profile(registry, profile)
    event = context.event
    if event is None or event.kind != 'spell_cast_finished':
        raise ValueError('Dormant progress requires the original CAST completion')
    from .spell_casts import cast_record
    from .spell_source_costs import validate_record
    current = cast_record(context.state, dict(event.data)['cast_id'])
    if ((current.source_id, current.player_id) != (event.source_id, event.player_id) or
            not current.completed or current.interrupted or current.failure is not None):
        raise ValueError('Dormant progress borrowed another completed spell')
    if (source.zone != Zone.BOARD or source.dormancy is None or
            current.player_id != context.player_id or current.id < source.dormancy.first_cast_id):
        return 0
    validate_record(context.state, registry, current)
    rows = tuple(row for row in context.state.cast_history
        if row.id >= source.dormancy.first_cast_id and row.player_id == context.player_id and
        row.completed and not row.interrupted and row.failure is None)
    if any(row.source_cost is None for row in rows):
        raise ValueError('Dormant progress lost an original accepted spell quote')
    return sum(row.source_cost.amount for row in rows)
