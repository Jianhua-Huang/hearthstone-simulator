"""Independent Jade growth and the immutable printed size of each physical golem.

Four real artwork templates represent thirty sizes. Size is an innate physical
base, not an enchantment or another card ID. Full-board attempts advance the
player's shared growth; copies and resurrection preserve size without advancing
it. Exact thresholds and lifecycle policies remain pending CN calibration.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardType, JadeGolemRecord, Zone


VERSION = 'jade-basics-v1'
STARTS = (1, 4, 7, 20)
MAXIMUM = 30
CLASSIC = 'jade.classic'


def size_value(size):
    if type(size) is not int or not 1 <= size <= MAXIMUM:
        raise ValueError('Jade innate size requires an exact integer from 1 to 30')


@dataclass(frozen=True)
class JadeGolemFamily:
    id: str
    version: str
    forms: tuple[str, ...]

    def __post_init__(self):
        for value in (self.id, self.version):
            if type(value) is not str or not value:
                raise ValueError('Named Jade family and version required')
        if (type(self.forms) is not tuple or len(self.forms) != len(STARTS) or
                any(type(cid) is not str or not cid for cid in self.forms) or
                len(set(self.forms)) != len(self.forms)):
            raise ValueError('Jade requires four distinct named artwork templates')

    def card_for(self, size):
        size_value(size)
        return self.forms[max(i for i, start in enumerate(STARTS) if start <= size)]


def family_for(registry, card_id):
    return next((f for f in registry.jade_families.values() if card_id in f.forms), None)


def validate_families(registry):
    seen = set()
    for key, family in registry.jade_families.items():
        if type(family) is not JadeGolemFamily or key != family.id:
            raise ValueError('Invalid registered Jade family')
        family.__post_init__()
        for cid, start in zip(family.forms, STARTS):
            if cid in seen:
                raise ValueError('Jade templates cannot belong to two artwork families')
            seen.add(cid)
            # Named missing adapters remain execution gaps, never blank bodies.
            if cid not in registry.cards:
                continue
            d = registry.card(cid)
            if (d.kind != CardType.MINION or d.metadata.collectible or
                    (d.attack, d.health, d.cost) != (start, start, min(10, start))):
                raise ValueError('Jade artwork template differs from its printed minimum')
            if d.herald_scaling or d.starship_for or d.colossal:
                raise ValueError('Jade templates require ordinary innate minion bases')


def imprint(entity, size):
    """Set only the innate printed base. Ordinary local enchantments stay separate."""
    size_value(size)
    entity.jade_size = size
    entity.base_attack = entity.base_health = size
    entity.base_cost = min(10, size)


def initialize_instance(entity, registry):
    entity.jade_size = None
    if registry is None or not registry.jade_families:
        return
    family = family_for(registry, entity.card_id)
    if family is not None:
        imprint(entity, STARTS[family.forms.index(entity.card_id)])


def inherit_printed(source, destination, *, state=None, permanent_stats=None, infused_damage=None):
    """A normal copy/revival inherits its original physical size, not current growth."""
    if source.card_id == destination.card_id and source.jade_size is not None:
        imprint(destination, source.jade_size)
    from .permanent_minion_stats import inherit
    if source.card_id == destination.card_id:
        inherit(state,source,destination,permanent_stats)
    from .infused_battlecries import inherit as inherit_infused
    inherit_infused(state,source,destination,infused_damage)
    from .carved_spells import inherit_weapon_material
    inherit_weapon_material(source,destination)


def printed_definition(registry, carrier):
    d = registry.card(carrier.card_id)
    from .carved_spells import weapon_material
    weapon=weapon_material(carrier)
    if weapon is not None:return replace(d,cost=registry.card(weapon[1]).cost)
    if carrier.jade_size is not None:
        d=replace(d,attack=carrier.jade_size,health=carrier.jade_size,cost=min(10,carrier.jade_size))
    from .permanent_minion_stats import value
    stats=value(carrier)
    return d if stats is None else replace(d,attack=stats.attack,health=stats.health)


def jade_count(state, player_id):
    _player(player_id)
    return sum(row.player_id == player_id for row in state.jade_history)


@dataclass(frozen=True)
class SummonJadeGolem(Effect):
    player_id: int
    source_id: int | None = None
    family_id: str = CLASSIC
    count: int = 1
    position: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        _integer(self.count, 'Jade summon count', 0)
        if type(self.family_id) is not str or not self.family_id:
            raise ValueError('Jade summon requires a named artwork family')
        if self.position is not None:
            _integer(self.position, 'Jade summon position', 0)


def summon(r, effect):
    effect.__post_init__()
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Jade summon count exceeds resolution budget')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Jade summon source does not exist')
    if not effect.count:
        return ()
    try:
        family = r.registry.jade_families[effect.family_id]
    except KeyError as exc:
        raise ResolutionError('Jade summon requires its registered artwork family') from exc
    player = r.player(effect.player_id)
    before = jade_count(r.state, player.id)
    size = min(MAXIMUM, before + 1)
    cid = family.card_for(size)
    r.registry.card(cid)  # Check even when the board is full; unknown is never a blank.
    position = effect.position
    if position is None and effect.source_id in player.board:
        position = player.board.index(effect.source_id) + 1
    entity = None
    if len(player.board) < r.rules.max_board:
        entity = r.create_entity(player.id, cid, Zone.BOARD, position)
        imprint(entity, size)
        r.refresh_auras()
    row = JadeGolemRecord(len(r.state.jade_history) + 1, player.id, effect.source_id,
        family.id, family.version, before, size, cid,
        None if entity is None else entity.id, r.state.turn, r.state.action_number)
    r.state.jade_history.append(row)
    # A private receipt is not an additional gameplay trigger window.
    r.emit('jade_golem_attempted', source_id=effect.source_id, player_id=player.id,
           amount=size, jade_id=row.id, _capture=False)
    if entity is None:
        r.emit('summon_failed', player_id=player.id, card_id=cid, reason='board_full')
        entry = ()
    else:
        from .colossal import enter_minion
        entry = enter_minion(r, entity, 'summon')
    tail = (replace(effect, count=effect.count - 1),) if effect.count > 1 else ()
    return (*entry, *tail)


def validate_instance(registry, carrier):
    family = family_for(registry, carrier.card_id) if registry.jade_families else None
    size = carrier.jade_size
    if family is None:
        if size is not None:
            raise ValueError('Only registered Jade templates carry innate Jade size')
        return
    size_value(size)
    if (family.card_for(size) != carrier.card_id or
            (carrier.base_attack, carrier.base_health, carrier.base_cost) != (size, size, min(10, size)) or
            carrier.zone in (Zone.HERO, Zone.HERO_POWER, Zone.WEAPON) or carrier.components):
        raise ValueError('Jade physical template, innate size and printed base disagree')


def validate_state(state, registry):
    if type(state.jade_history) is not list:
        raise ValueError('Jade history requires its ordered typed records')
    counts, seen, previous = {1: 0, 2: 0}, set(), (0, 0)
    for index, row in enumerate(state.jade_history, 1):
        if type(row) is not JadeGolemRecord:
            raise ValueError('Invalid Jade history record')
        row.__post_init__()
        family = registry.jade_families.get(row.family_id)
        if (family is None or family.version != row.family_version or
                row.id != index or row.count_before != counts[row.player_id] or
                row.size != min(MAXIMUM, row.count_before + 1) or
                family.card_for(row.size) != row.card_id or
                row.source_id is not None and row.source_id not in state.entities or
                row.turn > state.turn or row.action > state.action_number or
                row.turn < previous[0] or row.action < previous[1]):
            raise ValueError('Invalid Jade player growth or original provenance')
        registry.card(row.card_id)
        if row.entity_id is not None:
            entity = state.entities.get(row.entity_id)
            if (entity is None or entity.owner != row.player_id or entity.id in seen or
                    row.source_id is not None and entity.id <= row.source_id):
                raise ValueError('Invalid Jade original physical allocation')
            seen.add(entity.id)
        counts[row.player_id] += 1
        previous = (row.turn, row.action)
    for carrier in (*state.entities.values(), *state.death_history):
        validate_instance(registry, carrier)


def validate_event(event):
    if event.kind != 'jade_golem_attempted':
        return
    data = dict(event.data)
    if (set(data) != {'jade_id'} or type(data['jade_id']) is not int or data['jade_id'] < 1 or
            event.player_id not in (1, 2) or event.target_id is not None):
        raise ValueError('Invalid private Jade receipt')
    size_value(event.amount)


def event_record(state, event):
    validate_event(event)
    index = dict(event.data)['jade_id']
    if index > len(state.jade_history):
        raise ValueError('Jade receipt has no actual growth record')
    row = state.jade_history[index - 1]
    if (event.source_id, event.player_id, event.amount, event.action) != (
            row.source_id, row.player_id, row.size, row.action):
        raise ValueError('Jade receipt differs from its original attempt')


def validate_events(state, events):
    actual = [event for event in events if event.kind == 'jade_golem_attempted']
    if len(actual) != len(state.jade_history):
        raise ValueError('Jade history and complete actual receipts disagree')
    for index, event in enumerate(actual, 1):
        if dict(event.data).get('jade_id') != index:
            raise ValueError('Jade receipts lost original order')
        event_record(state, event)


def register(mechanics):
    mechanics.register(SummonJadeGolem, summon)
