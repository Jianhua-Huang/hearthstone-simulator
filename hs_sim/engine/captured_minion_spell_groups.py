"""One damage batch over the original finite minion references after reactions."""
from dataclasses import dataclass

from .effects import Damage, DamageBatch, Effect, _integer
from .model import CardType, DamageKind
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class DamageCapturedMinionGroup(Effect):
    targets: tuple[MinionReference, ...]
    amounts: tuple[int, ...]
    source_id: int

    def __post_init__(self):
        _integer(self.source_id, 'captured damage SPELL source', 1)
        if (type(self.targets) is not tuple or not 1 <= len(self.targets) <= 3 or
                type(self.amounts) is not tuple or len(self.targets) != len(self.amounts)):
            raise ValueError('Captured adjacent damage requires one to three complete original pairs')
        for ref, amount in zip(self.targets, self.amounts):
            reference_value(ref)
            _integer(amount, 'original minion spell damage', 0)
        if len({r.entity_id for r in self.targets}) != len(self.targets):
            raise ValueError('Captured damage cannot repeat an original physical minion')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        source = state.entities.get(self.source_id)
        if source is None or registry.card(source.card_id).kind != CardType.SPELL:
            raise ValueError('Captured damage lost its allocated SPELL source')
        for ref in self.targets:
            entity = state.entities.get(ref.entity_id)
            card = registry.card(ref.card_id)
            if (entity is None or card.kind != CardType.MINION or card.interactable is not None or
                    ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order):
                raise ValueError('Captured damage has an unknown or future original minion')


def damage(r, request):
    request.validate_in_state(r.state, r.registry)
    packets = []
    for ref, amount in zip(request.targets, request.amounts):
        if live_minion(r.state, ref) is None:
            r.stale(request, ref.entity_id)
        else:
            packets.append(Damage(ref.entity_id, amount, request.source_id, DamageKind.SPELL))
    return (DamageBatch(tuple(packets)),) if packets else ()


def register(mechanics):
    mechanics.register(DamageCapturedMinionGroup, damage)
