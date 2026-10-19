"""A single original hand minion becomes two ordinary current-material copies.

Only selection and the frozen split operands are new. Physical removal, copied
attachments, capacity, acquisitions, reactions and continuations use the usual
stored-card effects. Odd allocation and departure timing remain CN-calibration
policies; this adapter does not certify the complete official rules.
"""
from dataclasses import dataclass

from .copy_materials import CapturedCardCopyMaterial
from .costs import quote_unselected_cost
from .effects import Effect, _player, _source
from .model import CardType, CostSpec, SummonStats
from .zones import CopyCard, source_exists


@dataclass(frozen=True)
class SplitRandomHandMinion(Effect):
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)


def halves(rng, amount, *, minimum=0):
    """Conserve the operand, with an independently allocated odd remainder."""
    low, odd = divmod(amount, 2)
    if low < minimum:
        return minimum, minimum
    first = rng.randrange(2) if odd else 0
    return low + first, low + odd - first


def split(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    candidates = tuple(eid for eid in r.player(effect.player_id).hand
        if r.state.entities[eid].kind == CardType.MINION)
    if not candidates:
        return ()
    original = r.state.entities[r.game._rng.choice(candidates)]
    material = CapturedCardCopyMaterial.capture(r.state, original)
    # A read-only current quote consumes neither a player modifier nor payment.
    # External layers subsequently apply to each ordinary copied hand card.
    cost = halves(r.game._rng, quote_unselected_cost(r.state, r.registry, original).amount)
    attack = halves(r.game._rng, original.attack)
    health = halves(r.game._rng, original.max_health, minimum=1)
    copies = tuple(CopyCard(material, effect.player_id, source_id=effect.source_id,
        stats=SummonStats(attack[i], health[i]), cost=CostSpec(set_to=cost[i])) for i in range(2))
    # Splitting replaces the original. It is neither a discard nor a burned or
    # destroyed stored card, and must not fabricate any of those histories.
    from .temporary_hands import hide
    hide(r, original)
    return copies


def register(mechanics):
    mechanics.register(SplitRandomHandMinion, split)
