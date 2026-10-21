"""Finite source-cost operands for actual ordinary spell payloads."""
from dataclasses import asdict, dataclass, replace

from .model import CardType, CostQuoteFact, _name


@dataclass(frozen=True)
class SpellSourceCostProfile:
    card_id: str
    basis: str = 'submitted_manual_or_automatic_acceptance'

    def __post_init__(self):
        _name(self.card_id, 'source-cost spell')
        if self.basis != 'submitted_manual_or_automatic_acceptance':
            raise ValueError('Unsupported ordinary spell source-cost basis')


def validate_profile(registry, profile):
    if type(profile) is not SpellSourceCostProfile:
        raise ValueError('Typed ordinary spell source-cost profile required')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if (card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None or
            card.choose_one is not None or card.ongoing_effect_id is not None or card.secret is not None or card.quest is not None):
        raise ValueError('Source-cost values require a declared ordinary spell payload')


def capture_hand(registry, play):
    if play.card_id not in registry.spell_source_cost_profiles:
        return None
    validate_profile(registry, registry.spell_source_cost_profiles[play.card_id])
    if play.submitted_cost is None:
        raise ValueError('Source-cost hand spell lost its original submitted quote')
    return play.submitted_cost.quote


def capture_automatic(r, entity, player_id):
    if entity.card_id not in r.registry.spell_source_cost_profiles:
        return None
    validate_profile(r.registry, r.registry.spell_source_cost_profiles[entity.card_id])
    from .costs import capture_cost_input, capture_quote_fact
    # Capture before moving the actual stored carrier or selecting its target.
    # Cross-player casts quote for the real caster, without changing ownership.
    original = replace(capture_cost_input(entity), player_id=player_id)
    return capture_quote_fact(r.state, r.registry, original)


def start_receipt(record):
    if record.source_cost is None:
        return {}
    from .serialization import canonical_hash
    return {'source_cost': canonical_hash(asdict(record.source_cost))}


def validate_record(state, registry, record):
    profile = registry.spell_source_cost_profiles.get(record.card_id)
    if profile is None:
        if record.source_cost is not None:
            raise ValueError('Undeclared spell invented an original source-cost value')
        return
    validate_profile(registry, profile)
    quote = record.source_cost
    if type(quote) is not CostQuoteFact:
        raise ValueError('Declared spell lost its complete original source-cost value')
    quote.__post_init__()
    original = quote.quote_input
    if (quote.profile_id is not None or
            (original.source_id, original.player_id, original.card_id, original.kind) !=
            (record.source_id, record.player_id, record.card_id, CardType.SPELL)):
        raise ValueError('Source-cost quote borrowed another original spell or payer')
    from .repeat_matching import validate_cost_quote_fact
    from .intrinsic_costs import validate_intrinsic_history_prefix
    validate_cost_quote_fact(registry, quote)
    validate_intrinsic_history_prefix(quote.intrinsic, state, registry)
    if record.origin in ('hand', 'repeat'):
        from .play_history import play_record
        play = play_record(state, record.play_id)
        if play.submitted_cost is None or quote != play.submitted_cost.quote:
            raise ValueError('Source-cost value changed its original submitted hand quote')
    elif (quote.intrinsic.boundary.turn, quote.intrinsic.boundary.action) != (record.turn, record.action):
        raise ValueError('Automatic source-cost value changed its original acceptance clock')


def amount(context, registry):
    record = context.cast
    if (record is None or not record.payload_started or record.failure is not None or
            (record.source_id, record.player_id) != (context.source_id, context.player_id)):
        raise ValueError('Source-cost payload requires its actual accepted original CAST')
    validate_record(context.state, registry, record)
    if record.source_cost is None:
        raise ValueError('Source-cost payload requires its declared original cost')
    return record.source_cost.amount
