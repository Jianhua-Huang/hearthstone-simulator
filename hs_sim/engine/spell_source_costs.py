"""Finite source-cost operands for actual ordinary spell payloads."""
from dataclasses import asdict, dataclass, replace

from .model import CardType, CostQuoteFact, SpellSchool, _name


@dataclass(frozen=True)
class SpellSourceCostProfile:
    card_id: str
    basis: str = 'submitted_manual_or_automatic_acceptance'

    def __post_init__(self):
        _name(self.card_id, 'source-cost spell')
        if self.basis != 'submitted_manual_or_automatic_acceptance':
            raise ValueError('Unsupported ordinary spell source-cost basis')


@dataclass(frozen=True)
class SpellSourceCostObserverProfile:
    effect_id: str
    school: SpellSchool | None = SpellSchool.HOLY

    def __post_init__(self):
        _name(self.effect_id, 'spell-cost observing program')
        if self.school is not None and (type(self.school) is not SpellSchool or
                self.school not in (SpellSchool.HOLY, SpellSchool.SHADOW)):
            raise ValueError('Spell-cost observers require Holy, Shadow or the declared all-school scope')


def validate_observer(registry, profile):
    if type(profile) is not SpellSourceCostObserverProfile:
        raise ValueError('Typed original spell-cost observer required')
    profile.__post_init__()
    if profile.effect_id in registry.cards:
        card=registry.card(profile.effect_id)
        if (card.kind!=CardType.MINION or card.choice_only or card.interactable is not None or
                len(card.triggers)!=1 or card.triggers[0].event!='spell_cast_finished' or
                profile.school not in (None,SpellSchool.SHADOW)):
            raise ValueError('Minion spell-cost observation requires its actual single completion trigger')
        return
    spec=registry.player_effect(profile.effect_id)
    if (profile.school!=SpellSchool.HOLY or spec.kind!='aura' or len(spec.triggers)!=1 or spec.triggers[0].event!='spell_cast_finished' or
            registry.card(spec.card_id).spell_school!=SpellSchool.HOLY):
        raise ValueError('Spell-cost observation requires its real native Holy Aura completion trigger')


def requires_quote(registry, card_id):
    profile=registry.spell_source_cost_profiles.get(card_id)
    if profile is not None:
        validate_profile(registry,profile)
        return True
    card=registry.card(card_id)
    return card.kind==CardType.SPELL and (bool(registry.dormant_spell_mana_profiles) or
        any(p.school is None or card.spell_school==p.school for p in registry.spell_source_cost_observers.values()))


def validate_profile(registry, profile):
    if type(profile) is not SpellSourceCostProfile:
        raise ValueError('Typed ordinary spell source-cost profile required')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if (card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None or
            card.choose_one is not None or card.ongoing_effect_id is not None or card.secret is not None or card.quest is not None):
        raise ValueError('Source-cost values require a declared ordinary spell payload')


def capture_hand(registry, play):
    if not requires_quote(registry,play.card_id):
        return None
    if play.submitted_cost is None:
        raise ValueError('Source-cost hand spell lost its original submitted quote')
    return play.submitted_cost.quote


def capture_automatic(r, entity, player_id):
    if not requires_quote(r.registry,entity.card_id):
        return None
    from .costs import capture_cost_input, capture_quote_fact
    # Capture before moving the actual stored carrier or selecting its target.
    # Cross-player casts quote for the real caster, without changing ownership.
    original = replace(capture_cost_input(entity), player_id=player_id)
    from .remaining_mana_numbers import automatic_cost_input
    original = automatic_cost_input(r.state,r.registry,original)
    return capture_quote_fact(r.state, r.registry, original)


def start_receipt(record):
    if record.source_cost is None:
        return {}
    from .serialization import canonical_hash
    return {'source_cost': canonical_hash(asdict(record.source_cost))}


def validate_record(state, registry, record, *, _within_cast_history_check=False):
    if not requires_quote(registry,record.card_id):
        if record.source_cost is not None:
            raise ValueError('Undeclared spell invented an original source-cost value')
        return
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
    validate_intrinsic_history_prefix(quote.intrinsic, state, registry,
                                     _within_cast_history_check=_within_cast_history_check)
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
    if record.card_id not in registry.spell_source_cost_profiles:
        raise ValueError('Source-cost payload requires its declared original cost')
    validate_record(context.state, registry, record)
    if record.source_cost is None:
        raise ValueError('Source-cost payload requires its declared original cost')
    return record.source_cost.amount
