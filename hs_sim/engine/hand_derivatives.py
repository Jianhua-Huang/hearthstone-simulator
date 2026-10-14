"""Declared derivative identities for Twinspell, Miniaturize and Gigantify.

R-085 fixes provisional generation windows and cross-mechanism inheritance.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass

from .effects import Effect
from .errors import ResolutionError
from .model import CardType, HandDerivativeSpec, Keyword, Zone, _int


DERIVATIVE_KEYWORDS = frozenset((Keyword.TWINSPELL, Keyword.MINIATURIZE, Keyword.GIGANTIFY))
FORM_STATS = {Keyword.MINI: 1, Keyword.GIGANTIC: 8}


def validate_definitions(registry):
    for root in registry.cards.values():
        specs = root.hand_derivatives
        if (type(specs) is not tuple or any(type(s) is not HandDerivativeSpec for s in specs) or
                len({s.keyword for s in specs}) != len(specs)):
            raise ValueError('Hand derivatives require an immutable tuple with distinct keywords')
        if set(root.keywords) & DERIVATIVE_KEYWORDS != {s.keyword for s in specs}:
            raise ValueError('Derivative keywords require matching declarations')
        for marker, size in FORM_STATS.items():
            if marker in root.keywords and (not root.hand_playable or root.kind != CardType.MINION or
                    (root.cost, root.attack, root.health) != (size, size, size) or specs):
                raise ValueError('Mini/Gigantic forms require their printed size and no derivative generation')
        for spec in specs:
            spec.__post_init__()
            kind = CardType.SPELL if spec.keyword == Keyword.TWINSPELL else CardType.MINION
            target = registry.card(spec.card_id)
            if (not root.hand_playable or root.kind != kind or target.kind != kind or
                    not target.hand_playable or target.id == root.id or target.hand_derivatives or
                    set(target.keywords) & DERIVATIVE_KEYWORDS or root.starship_for or target.starship_for):
                raise ValueError('Derivatives require a distinct terminal physical form of the same kind')
            if spec.keyword == Keyword.TWINSPELL:
                if target.cost != root.cost:
                    raise ValueError('Twinspell derivative must retain the printed cost')
            else:
                marker = Keyword.MINI if spec.keyword == Keyword.MINIATURIZE else Keyword.GIGANTIC
                if marker not in target.keywords:
                    raise ValueError('Size derivatives require their Mini/Gigantic form marker')


def capture(entity, definition):
    return tuple(s for s in definition.hand_derivatives if s.keyword in entity.keywords)


@dataclass(frozen=True)
class CreatePlayDerivative(Effect):
    play_id: int
    spec: HandDerivativeSpec

    def __post_init__(self):
        _int(self.play_id, 'derivative play ID', 1)
        if type(self.spec) is not HandDerivativeSpec:
            raise ValueError('Expected HandDerivativeSpec')
        self.spec.__post_init__()


def after_spell_effects(play):
    return [CreatePlayDerivative(play.id, spec) for spec in play.hand_derivatives
            if spec.keyword == Keyword.TWINSPELL]


def after_hand_play(play):
    if play.countered or play.minion_result == "board_full":
        return []
    return [CreatePlayDerivative(play.id, spec) for spec in play.hand_derivatives
            if spec.keyword != Keyword.TWINSPELL]


def create(r, effect):
    from .play_history import play_record
    effect.__post_init__()
    play = play_record(r.state, effect.play_id)
    spec = effect.spec
    if (spec not in play.hand_derivatives or spec not in r.registry.card(play.card_id).hand_derivatives or
            play.interrupted or play.countered or
            play.completed != (spec.keyword != Keyword.TWINSPELL)):
        raise ResolutionError('Derivative does not match a captured play or its execution phase')
    player = r.player(play.player_id)
    zone = Zone.HAND if len(player.hand) < hand_capacity(player, r.rules) else Zone.GRAVEYARD
    entity = r.create_entity(player.id, spec.card_id, zone)
    entity.origin_entity_id = play.source_id
    # The terminal form's printed identity supplies stats/abilities, independently
    # of later changes to the source. No instance buffs, costs or lifetime carry.
    r.emit('card_created', source_id=play.source_id, target_id=entity.id, player_id=player.id,
           play_id=play.id, derivative=spec.keyword.value)
    if zone==Zone.GRAVEYARD:
        from .zones import emit_burn
        emit_burn(r,entity,profile='created_overflow',source_id=play.source_id,reason=spec.keyword.value,play_id=play.id)
    else:
        r.emit('card_added_to_hand',source_id=play.source_id,target_id=entity.id,player_id=player.id,
            reason=spec.keyword.value,play_id=play.id)


def register(mechanics):
    mechanics.register(CreatePlayDerivative, create)
