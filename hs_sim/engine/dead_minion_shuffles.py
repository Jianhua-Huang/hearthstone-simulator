"""Random deck insertion of one original, just-dead physical minion."""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, validate_allocation
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import reset_to_definition
from .model import CardType, DeathRecord, Zone


@dataclass(frozen=True)
class ShuffleDeadMinion(Effect):
    card: SourceAllocationFact
    death: DeathRecord
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.card) is not SourceAllocationFact or type(self.death) is not DeathRecord:
            raise ValueError('Dead shuffle requires the complete original allocation and death')
        self.card.__post_init__(); self.death.__post_init__()
        _integer(self.death.id, 'dead shuffle death', 1)
        fact, death = self.card, self.death
        if (fact.kind, fact.zone, fact.controller) != (CardType.MINION, Zone.GRAVEYARD, self.player_id):
            raise ValueError('Dead shuffle requires the original controller graveyard residence')
        if (death.zone != Zone.BOARD or
                (fact.entity_id, fact.card_id, fact.owner, fact.controller, fact.zone_epoch, fact.entered_order) !=
                (death.entity_id, death.card_id, death.owner, death.controller,
                 death.cause.target_zone_epoch + 1, death.cause.target_entered_order)):
            raise ValueError('Dead shuffle allocation differs from its original board death')


def validate_request(state, registry, request):
    request.__post_init__()
    validate_allocation(state, registry, request.card)
    if next((d for d in state.death_history if d.id == request.death.id), None) != request.death:
        raise ValueError('Dead shuffle lost its complete original death record')
    definition = registry.card(request.card.card_id)
    if definition.kind != CardType.MINION or not definition.hand_playable or definition.interactable:
        raise ValueError('Dead shuffle requires an ordinary registered physical minion')
    if request.source_id is not None and request.source_id not in state.entities:
        raise ValueError('Dead shuffle issuer does not exist')


def shuffle_dead_minion(r, request):
    try:
        validate_request(r.state, r.registry, request)
    except ValueError as exc:
        raise ResolutionError(str(exc)) from exc
    fact = request.card
    entity = r.state.entities[fact.entity_id]
    if (entity.card_id, entity.kind, entity.owner, entity.controller, entity.zone,
            entity.zone_epoch, entity.entered_order) != (
            fact.card_id, fact.kind, fact.owner, fact.controller, fact.zone, fact.zone_epoch, fact.entered_order):
        r.stale(request, entity.id)
        return
    from .deck_capacity import admits, failure
    if not admits(r.state, request.player_id, entity):
        failure(r, request.player_id, entity.card_id, request.source_id, original=fact)
        return
    reset_to_definition(r.state, entity, r.registry.card(fact.card_id), r.registry,
                        preserve_jade=True, preserve_cthun=True)
    player = r.player(request.player_id)
    position = r.game._rng.randrange(len(player.deck) + 1)
    r.move(entity, Zone.DECK, position)
    r.refresh_auras()
    r.emit('card_shuffled', source_id=request.source_id, target_id=entity.id,
           player_id=player.id, position=position, _deck_insertion_mode='random')


def register(mechanics):
    mechanics.register(ShuffleDeadMinion, shuffle_dead_minion)
