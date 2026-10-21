"""A copied spell's finite draw-cast grant and its immutable accepted draw basis."""
from dataclasses import asdict, dataclass
import json

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import _integer
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, CastWhenDrawnSpec, Keyword, Zone

KEY = '_granted_draw_cast'


@dataclass(frozen=True)
class GrantedDrawCastBasis:
    origin: SourceAllocationFact
    ability: AbilityInstance
    next_attachment_id: int

    def __post_init__(self):
        if type(self.origin) is not SourceAllocationFact or type(self.ability) is not AbilityInstance:
            raise ValueError('Draw-cast basis requires the original physical allocation and declaration')
        self.origin.__post_init__(); self.ability.__post_init__()
        _integer(self.next_attachment_id, 'draw-cast original attachment bound', 1)
        a = self.ability
        if (self.origin.kind != CardType.SPELL or self.origin.zone != Zone.DECK or
                a.draw_cast != CastWhenDrawnSpec() or a.consumed or a.id >= self.next_attachment_id or
                a.source_id is None or a.source_id >= self.origin.next_entity_id):
            raise ValueError('Draw-cast basis lost its original active spell grant')


def from_dict(value):
    from .serialization import _row, _ability_from_dict
    row = _row(value, GrantedDrawCastBasis)
    row['origin'] = allocation_from_dict(row['origin'])
    row['ability'] = _ability_from_dict(row['ability'])
    return GrantedDrawCastBasis(**row)


def validate_basis(state, registry, basis):
    basis.__post_init__()
    validate_allocation(state, registry, basis.origin)
    if (basis.next_attachment_id > state.next_attachment_id or basis.ability.source_id not in state.entities or
            not registry.card(basis.origin.card_id).hand_playable):
        raise ValueError('Draw-cast basis names a future attachment or unsupported physical source')


def validate_entity(state, registry, entity):
    grants = [a for a in entity.abilities if a.draw_cast is not None]
    if not grants: return
    if entity.kind != CardType.SPELL or not registry.card(entity.card_id).hand_playable:
        raise ValueError('Draw-cast declarations require ordinary physical spells')
    for a in grants:
        a.__post_init__()
        if a.source_id not in state.entities:
            raise ValueError('Draw-cast grant lost its original source')


def install(r, entity, source_id):
    if (entity.kind != CardType.SPELL or entity.zone != Zone.DECK or
            not r.registry.card(entity.card_id).hand_playable or source_id not in r.state.entities):
        raise ResolutionError('Copied draw casting requires its actual new deck spell and source')
    entity.abilities.append(AbilityInstance(attachment_id(r.state), 'keyword', source_id=source_id,
        keyword=Keyword.CASTS_WHEN_DRAWN, draw_cast=CastWhenDrawnSpec()))
    refresh_entity(entity)


def capture(state, registry, entity):
    if Keyword.CASTS_WHEN_DRAWN not in entity.keywords: return None
    validate_entity(state, registry, entity)
    grants = [a for a in entity.abilities if a.draw_cast is not None and not a.consumed]
    if not grants:
        raise ResolutionError('A granted draw-cast keyword needs its effective declaration')
    basis = GrantedDrawCastBasis(SourceAllocationFact.capture(state, entity), min(grants, key=lambda a: a.id),
        state.next_attachment_id)
    validate_basis(state, registry, basis)
    return basis


def event_data(basis):
    return {} if basis is None else {KEY: json.dumps(asdict(basis), ensure_ascii=False,
        sort_keys=True, separators=(',', ':'))}


def validate_record(state, registry, record):
    basis = record.cast_grant
    validate_basis(state, registry, basis)
    if (record.outcome != 'cast' or record.spec != CastWhenDrawnSpec() or
            registry.card(record.card_id).cast_when_drawn is not None or
            (record.entity_id, record.card_id) != (basis.origin.entity_id, basis.origin.card_id)):
        raise ValueError('Draw-cast grant changed its accepted ordinary spell policy')


def validate_boundary(game):
    from .hero_health_history import effective_events
    rows = {d.id: d for d in game._state.draw_history if d.cast_grant is not None}
    seen = set()
    for event in effective_events(game._events):
        data = dict(event.data)
        if KEY not in data: continue
        row = rows.get(data.get('draw_id'))
        if (event.kind != 'card_drawn' or row is None or row.id in seen or
                set(data) != {'draw_id', 'casts_when_drawn', KEY} or data['casts_when_drawn'] is not True or
                type(data[KEY]) is not str or from_dict(json.loads(data[KEY])) != row.cast_grant or
                (event.source_id, event.target_id, event.player_id, event.action) !=
                (row.source_id, row.entity_id, row.player_id, row.action)):
            raise ValueError('Draw-cast grant event lost or changed its exact original basis')
        seen.add(row.id)
    if seen != set(rows):
        raise ValueError('Granted draws and their original private witnesses disagree')
