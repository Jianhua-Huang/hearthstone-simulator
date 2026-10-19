"""One physical board/hand exchange, with ordinary recruit extras and returns."""
from dataclasses import dataclass

from .effects import Effect
from .errors import ResolutionError
from .model import CardType, Zone
from .pools import PoolQuery
from .sacrifice import MinionReference, live_minion, reference_value
from .summon_quantities import SummonCause, validate_cause


def validate_pair(minion, cause):
    reference_value(minion)
    if type(cause) is not SummonCause:
        raise ValueError('Hand swap requires its typed original summon cause')
    cause.__post_init__()
    a = cause.source
    if (a.entity_id, a.controller, a.card_id, a.zone_epoch, a.entered_order,
            a.kind, a.zone, cause.player_id, cause.origin) != (
            minion.entity_id, minion.player_id, minion.card_id, minion.zone_epoch,
            minion.entered_order, CardType.MINION, Zone.BOARD, minion.player_id, 'card_effect'):
        raise ValueError('Hand swap changed its original board source or player')


@dataclass(frozen=True)
class SwapWithOpponentHand(Effect):
    minion: MinionReference
    cause: SummonCause

    def __post_init__(self):
        validate_pair(self.minion, self.cause)

    def validate_in_state(self, state, registry):
        self.__post_init__()
        validate_cause(state, registry, self.cause)
        if registry.card(self.minion.card_id).interactable is not None:
            raise ValueError('Hand swap requires an ordinary playable minion')


def swap_random(r, effect):
    from .colossal import SummonStoredCard, summon_stored
    from .zones import zone_candidates
    effect.validate_in_state(r.state, r.registry)
    body = live_minion(r.state, effect.minion)
    if body is None or len(r.player(body.controller).board) - 1 >= r.rules.max_board:
        return ()
    choices = zone_candidates(r, 3 - body.controller, Zone.HAND,
        PoolQuery(kinds=(CardType.MINION,)), body.controller, body.id)
    if not choices:
        return ()  # No return, no reveal and no random draw without a partner.
    chosen = r.game._rng.choice(choices)
    # Selection and first movement share a handler. Reactions never replace the
    # selected physical partner or fill the reserved slot between the two.
    return summon_stored(r, SummonStoredCard(chosen, body.controller,
        cause=effect.cause, swap_minion=effect.minion))


def validate_material(state, registry, material):
    ref = material.swap_minion
    if ref is None:
        return
    reference_value(ref)
    entity = state.entities.get(ref.entity_id)
    if (entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order
            or registry.card(ref.card_id).kind != CardType.MINION
            or registry.card(ref.card_id).interactable is not None):
        raise ValueError('Hand swap borrowed an unknown or future board incarnation')


def validate_recipe(request, material):
    if material.swap_minion is None:
        return
    validate_pair(material.swap_minion, request.cause)
    if (request.player_id != material.swap_minion.player_id or
            material.reference.player_id != 3 - request.player_id or
            material.reference.zone != Zone.HAND or request.producer_link is not None):
        raise ValueError('Hand swap changed its original opposing hand or entry recipe')


def entry_has_space(r, request, index=0):
    board = r.player(request.player_id).board
    if len(board) < r.rules.max_board:
        return True
    from .recruit_summons import RecruitEntryMaterial
    material = request.materials[0] if len(request.materials) == 1 else None
    return (index == 0 and type(material) is RecruitEntryMaterial and
        material.swap_minion is not None and live_minion(r.state, material.swap_minion) is not None
        and len(board) - 1 < r.rules.max_board)


def return_partner(r, material, player_id):
    """Commit the outgoing original without publishing an intermediate hand."""
    from .hand_history import enter_hand
    from .lifecycle import reset_to_definition
    ref = material.swap_minion
    entity = live_minion(r.state, ref)
    if entity is None or entity.controller != player_id:
        raise ResolutionError('Accepted hand swap lost its original board partner')
    position = r.player(player_id).board.index(entity.id)
    r.move(entity, Zone.HAND, hand_entry_reason=None)
    r.player(player_id).hand.remove(entity.id)
    entity.controller = material.reference.player_id
    r.player(entity.controller).hand.append(entity.id)
    enter_hand(r.state, entity, Zone.BOARD, 'return')
    reset_to_definition(r.state, entity, r.registry.card(entity.card_id), r.registry,
        preserve_jade=True)
    return position


def register(mechanics):
    mechanics.register(SwapWithOpponentHand, swap_random)
