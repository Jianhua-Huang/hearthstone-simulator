"""Constructed bonus effects, separate from Battlegrounds upgrade effects.

The pool and readiness edge policy are versioned with the core rules. See the
M4 bonus-effects contract for evidence boundaries and pending CN calibration.
"""
from dataclasses import dataclass, replace

from .effects import Effect, GrantKeyword, _integer, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import AbilityInstance, CardType, Keyword, Zone
from .zones import CardReference, reference_entity
from .sacrifice import MinionReference


BONUS_EFFECTS = (
    Keyword.TAUNT, Keyword.DIVINE_SHIELD, Keyword.ELUSIVE, Keyword.LIFESTEAL,
    Keyword.POISONOUS, Keyword.REBORN, Keyword.RUSH, Keyword.WINDFURY,
)


def bonus_candidates(state, entity):
    # Readiness means attack timing, independent of current enemy targets. An
    # old minion facing only immune enemies must not gain redundant Rush.
    rush_useful = (entity.controller == state.active_player and entity.attacks_this_turn == 0
                   and entity.summoned_turn == state.turn and Keyword.CHARGE not in entity.keywords)
    return tuple(k for k in BONUS_EFFECTS if k not in entity.keywords
                 and (k != Keyword.RUSH or rush_useful))


@dataclass(frozen=True)
class GrantRandomBonusEffects(Effect):
    target_id: int
    count: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.count, 'bonus count', 0)
        _source(self.source_id)


def grant_random_bonus_effects(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Bonus effect source does not exist')
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Bonus effects exceed resolution budget')
    if not effect.count:
        return ()
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return ()
    if entity.zone != Zone.BOARD or r.registry.card(entity.card_id).kind != CardType.MINION:
        raise ResolutionError('Bonus effects require a minion')
    candidates = bonus_candidates(r.state, entity)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_bonus_effects')
        return ()
    keyword = r.game._rng.choice(candidates)
    # Shared attachments handle silence, expiry, copies and consumed keywords.
    # Reactions resolve before the next pick, whose eligibility is read afresh.
    return (GrantKeyword(entity.id, keyword, effect.source_id), replace(effect, count=effect.count - 1))


def register_bonus_effects(mechanics):
    mechanics.register(GrantRandomBonusEffects, grant_random_bonus_effects)
    mechanics.register(RotatePrintedHandBonuses, rotate_printed_hand_bonuses)
    mechanics.register(StealBonusEffects, steal_bonus_effects)


@dataclass(frozen=True)
class RotatePrintedHandBonuses(Effect):
    """Replace the native pair, preserving independently granted hand keywords."""
    card: CardReference
    source_id: int | None = None

    def __post_init__(self):
        if type(self.card) is not CardReference or self.card.zone != Zone.HAND:raise ValueError('Native bonus rotation requires its original hand card')
        self.card.__post_init__();_source(self.source_id)

    def validate_in_state(self,state):
        self.__post_init__();entity=state.entities.get(self.card.entity_id)
        if entity is None or self.card.zone_epoch>entity.zone_epoch or self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Hand bonus rotation borrowed an unknown or future physical card')


def rotate_printed_hand_bonuses(r,effect):
    from .lifecycle import attachment_id,refresh_entity
    effect.validate_in_state(r.state);card=r.registry.card(effect.card.card_id)
    if card.kind!=CardType.MINION or len(card.keywords)!=2 or any(k not in BONUS_EFFECTS for k in card.keywords):
        raise ResolutionError('Native bonus rotation requires its declared pair of printed Bonus Effects')
    entity=reference_entity(r,effect.card)
    if entity is None:r.stale(effect,effect.card.entity_id);return ()
    originals=tuple(a for a in entity.abilities if a.kind=='keyword'and a.origin=='printed')
    if len(originals)!=2 or any(a.keyword not in BONUS_EFFECTS for a in originals):
        raise ResolutionError('Native bonus rotation lost its complete two printed keyword slots')
    # Hand slots always use the full constructed pool, including Rush. Board
    # readiness filtering belongs only to the existing board grant operation.
    pool=list(BONUS_EFFECTS);chosen=[]
    for _ in range(2):
        selected=r.game._rng.choice(pool);pool.remove(selected);chosen.append(selected)
    entity.abilities=[a for a in entity.abilities if a not in originals]
    entity.abilities.extend(AbilityInstance(attachment_id(r.state),'keyword',source_id=entity.id,
        origin='printed',keyword=keyword)for keyword in chosen)
    refresh_entity(entity)
    r.emit('hand_bonus_rotated',source_id=effect.source_id,target_id=entity.id,player_id=entity.controller)
    return ()


@dataclass(frozen=True)
class StealBonusEffects(Effect):
    """Strip the original victim's local flags, then reward the original source."""
    victim: MinionReference
    beneficiary: MinionReference | None
    source_id: int

    def __post_init__(self):
        from .sacrifice import reference_value
        reference_value(self.victim)
        _integer(self.source_id, 'bonus theft source', 1)
        if self.beneficiary is not None:
            reference_value(self.beneficiary)
            if (self.beneficiary.entity_id != self.source_id or
                    self.beneficiary.entity_id == self.victim.entity_id):
                raise ValueError('Bonus theft must reward its distinct original source')

    def validate_in_state(self, state):
        self.__post_init__()
        if self.source_id not in state.entities:
            raise ValueError('Bonus theft lost its original source')
        for ref in (self.victim, *((self.beneficiary,) if self.beneficiary is not None else ())):
            entity = state.entities.get(ref.entity_id)
            if (entity is None or ref.zone_epoch > entity.zone_epoch or
                    ref.entered_order >= state.next_order):
                raise ValueError('Bonus theft borrowed an unknown or future minion')


def steal_bonus_effects(r, effect):
    from .lifecycle import consume_keyword
    from .sacrifice import BuffCapturedMinion, GrantCapturedKeyword, live_minion
    effect.validate_in_state(r.state)
    for ref in (effect.victim, *((effect.beneficiary,) if effect.beneficiary is not None else ())):
        if r.registry.card(ref.card_id).kind != CardType.MINION:
            raise ResolutionError('Bonus theft requires original minion references')
    victim = live_minion(r.state, effect.victim)
    if victim is None:
        r.stale(effect, effect.victim.entity_id)
        return ()
    # Existing Rush is stolen even when it would not be a useful random roll.
    selected = tuple(keyword for keyword in BONUS_EFFECTS if keyword in victim.keywords)
    if not selected:
        return ()
    removed = tuple(keyword for keyword in selected if any(
        a.kind == 'keyword' and a.keyword == keyword and not a.consumed for a in victim.abilities))
    for keyword in removed:
        consume_keyword(victim, keyword)
    # Continuous providers remain independent. All local removals precede
    # reactions, so subsequent work cannot rescan a later incarnation.
    for keyword in removed:
        r.emit('keyword_removed', source_id=effect.source_id, target_id=victim.id,
               player_id=victim.controller, keyword=keyword.value)
    r.emit('bonus_effects_stolen', source_id=effect.source_id, target_id=victim.id,
           player_id=victim.controller, keywords=[k.value for k in selected], count=len(selected))
    if effect.beneficiary is None:
        return ()
    return (*(GrantCapturedKeyword(effect.beneficiary, keyword, effect.source_id) for keyword in selected),
            BuffCapturedMinion(effect.beneficiary, len(selected), len(selected), effect.source_id))
