"""Printed minion copy material frozen at the actual hand-play submission.

Only intrinsic composition and Jade size belong to this base recipe. Local
buffs, magnetic attachments, silence and later transformations do not. Creation,
overflow and publication remain the ordinary CopyCard operation.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, Entity, SummonStats, Zone, _components, _int


@dataclass(frozen=True)
class PlayedMinionCopyMaterial:
    play_id: int
    source: SourceAllocationFact
    components: tuple[str, ...]
    jade_size: int | None
    turn: int
    action: int
    permanent_stats: SummonStats | None = None

    def __post_init__(self):
        for key in ('play_id', 'turn'): _int(getattr(self, key), 'played copy '+key, 1)
        _int(self.action, 'played copy action', 0)
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Played copy requires its complete original allocation')
        self.source.__post_init__()
        if (self.source.kind, self.source.zone) != (CardType.MINION, Zone.HAND):
            raise ValueError('Played base copy requires the original submitted hand minion')
        _components(self.components)
        from .permanent_minion_stats import validate_value
        validate_value(self.permanent_stats)
        if self.jade_size is not None:
            _int(self.jade_size, 'played innate Jade size', 1)
            if self.jade_size > 30 or self.components:
                raise ValueError('Invalid original played Jade recipe')

    @classmethod
    def capture(cls, state, source, play_id):
        if source.kind != CardType.MINION: return None
        from .permanent_minion_stats import value
        return cls(play_id, SourceAllocationFact.capture(state, source),
            source.components, source.jade_size, state.turn, state.action_number,value(source))

    def entity(self):
        s = self.source
        return Entity(s.entity_id, s.card_id, s.owner, s.controller, s.zone,
            kind=s.kind, zone_epoch=s.zone_epoch, entered_order=s.entered_order,
            components=self.components, jade_size=self.jade_size)


def validate_play(record):
    value = record.minion_copy_material
    if record.kind != CardType.MINION:
        if value is not None: raise ValueError('Only a played minion has a printed minion copy recipe')
        return
    if type(value) is not PlayedMinionCopyMaterial:
        raise ValueError('Played minion lost its original printed copy recipe')
    value.__post_init__()
    if (value.play_id, value.source.entity_id, value.source.controller,
            value.source.card_id, value.turn, value.action) != (
            record.id, record.source_id, record.player_id, record.card_id, record.turn, record.action):
        raise ValueError('Played minion copy borrowed another original hand submission')


def validate_material(state, registry, value):
    value.__post_init__()
    validate_allocation(state, registry, value.source)
    if value.turn > state.turn or value.action > state.action_number:
        raise ValueError('Played minion copy has future submission clocks')
    definition = registry.card(value.source.card_id)
    from .crafted_faces import composition_shape, PREFIX
    if not definition.hand_playable or not composition_shape(definition, value.components):
        raise ValueError('Played minion lost its original complete composition')
    if any(registry.card(cid).kind != CardType.MINION or registry.card(cid).starship_for or
            cid.startswith(PREFIX) for cid in value.components):
        raise ValueError('Played minion copy has invalid original components')
    from .jade import family_for
    family = family_for(registry, definition.id) if registry.jade_families else None
    if (family is None) != (value.jade_size is None) or family is not None and family.card_for(value.jade_size) != definition.id:
        raise ValueError('Played minion copy changed its intrinsic Jade identity')


def original_entity(state, registry, value):
    validate_material(state, registry, value)
    if not 1 <= value.play_id <= len(state.play_history) or state.play_history[value.play_id-1].minion_copy_material != value:
        raise ValueError('Played minion copy lost its actual committed hand history')
    return value.entity()


def from_dict(value):
    from .serialization import _row, _list
    row = _row(value, PlayedMinionCopyMaterial)
    row['source'] = allocation_from_dict(row['source'])
    row['components'] = tuple(_list(row['components'], 'original played composition'))
    row['permanent_stats']=None if row['permanent_stats']is None else SummonStats(**_row(row['permanent_stats'],SummonStats))
    return PlayedMinionCopyMaterial(**row)


def register(mechanics):
    mechanics.register_payload_type(PlayedMinionCopyMaterial)
