"""Player-wide Herald history and instance-local Soldier/appendage strength.

Herald is an effect, not a play counter. Rank is captured before this use counts;
existing minions do not change when another Herald completes. See m5-herald.md.
"""
from dataclasses import dataclass, replace

from .effects import Effect, GrantKeyword, _integer, _player, _source
from .errors import ResolutionError
from .model import CardClass, CardType, Enchantment, HeraldRecord, Keyword, Zone, _name


HERALD_CLASSES = frozenset((CardClass.WARRIOR, CardClass.DEMON_HUNTER,
    CardClass.SHAMAN, CardClass.ROGUE, CardClass.DEATH_KNIGHT, CardClass.WARLOCK))


def initialize_bindings(state):
    """Bind the starting class before any opening or scenario reactions."""
    for player in state.players.values():
        if player.hero_class in HERALD_CLASSES:
            player.herald_class = player.hero_class


def resolved_class(state, registry, player_id, source_id=None, source_card_id=None):
    """Existing binding, own class, single-class source, then opponent binding."""
    player = state.players[player_id]
    if player.herald_class is not None:
        return player.herald_class
    if player.hero_class in HERALD_CLASSES:
        return player.hero_class
    if source_card_id is None and source_id is not None:
        source_card_id = state.entities[source_id].card_id
    if source_card_id is not None:
        definition = registry.card(source_card_id)
        classes = definition.metadata.classes if definition.metadata is not None else ()
        if len(classes) == 1 and classes[0] in HERALD_CLASSES:
            return classes[0]
    opponent = state.players[3 - player_id]
    if opponent.herald_class is not None:
        return opponent.herald_class
    if opponent.hero_class in HERALD_CLASSES:
        return opponent.hero_class
    return None


def request_from_context(context, grant_keywords=()):
    """Keep the original accepted face if its physical source later changes."""
    if context.deathrattle is not None:
        card_id = context.deathrattle.card_id
    elif context.death is not None:
        card_id = context.death.card_id
    elif context.battlecry is not None:
        card_id = context.battlecry.payload.card_id
    elif context.cast is not None:
        card_id = context.cast.card_id
    elif context.play is not None:
        card_id = context.play.card_id
    else:
        card_id = context.source.card_id
    return Herald(context.player_id, context.source_id, grant_keywords, card_id)


def herald_count(state, player_id):
    _player(player_id)
    return sum(record.player_id == player_id for record in state.herald_history)


def herald_rank(count):
    _integer(count, 'Herald count', 0)
    return min(count // 2, 2)


def herald_multiplier(state, player_id):
    return 1 << herald_rank(herald_count(state, player_id))


def instance_multiplier(entity_or_death):
    rank = entity_or_death.herald_rank
    return 1 if rank is None else 1 << rank


def soldier_card(registry, hero_class):
    return next((card.id for card in registry.cards.values()
                 if card.herald_soldier_for == hero_class and hero_class is not None), None)


def initialize_instance(state, entity, definition, *, count=None):
    """Apply once on entry, after printed/base state and before summon reactions."""
    if not definition.herald_scaling or entity.zone != Zone.BOARD or entity.herald_rank is not None:
        return
    from .lifecycle import attachment_id, refresh_entity
    entity.herald_rank = herald_rank(herald_count(state, entity.controller)if count is None else count)
    extra = (1 << entity.herald_rank) - 1
    if extra:
        entity.enchantments.append(Enchantment(attachment_id(state), entity.id,
            definition.attack * extra, definition.health * extra, label='herald'))
        # Only the declared Soldier/appendage ability scales. Granted auras keep
        # their own values; current-state copies preserve this captured result.
        entity.abilities = [replace(a, attack=a.attack * (extra + 1), health=a.health * (extra + 1))
            if a.kind == 'aura' and a.origin == 'printed' else a for a in entity.abilities]
    refresh_entity(entity)


@dataclass(frozen=True)
class Herald(Effect):
    player_id: int
    source_id: int | None = None
    grant_keywords: tuple[Keyword, ...] = ()
    source_card_id: str | None = None

    def __post_init__(self):
        _player(self.player_id)
        _source(self.source_id)
        if self.source_card_id is not None:
            _name(self.source_card_id, 'original Herald source face')
            if self.source_id is None:
                raise ValueError('Original Herald face requires its physical source')
        if (type(self.grant_keywords) is not tuple or
                any(not isinstance(k, Keyword) for k in self.grant_keywords) or
                len(set(self.grant_keywords)) != len(self.grant_keywords)):
            raise ValueError('Herald grants require distinct typed keywords')
        # Reuse the public grant contract, rather than bypassing structured abilities.
        for keyword in self.grant_keywords:
            GrantKeyword(1, keyword)


def herald(r, effect):
    player = r.player(effect.player_id)
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Herald source does not exist')
    if effect.source_card_id is not None:
        r.registry.card(effect.source_card_id)
    herald_class = resolved_class(r.state, r.registry, player.id,
        effect.source_id, effect.source_card_id)
    # User-authorized local policy: no eligible binding is a complete Herald
    # no-op, including its counter. Other effects in the same body continue.
    if herald_class is None:
        return []
    card_id = soldier_card(r.registry, herald_class)
    if card_id is None:
        raise ResolutionError(f'No implemented Herald Soldier for class {herald_class}')
    player.herald_class = herald_class
    count = herald_count(r.state, player.id)
    soldier = None
    if len(player.board) < r.rules.max_board:
        position = player.board.index(effect.source_id) + 1 if effect.source_id in player.board else None
        soldier = r.create_entity(player.id, card_id, Zone.BOARD, position)
        r.refresh_auras()
    record = HeraldRecord(len(r.state.herald_history) + 1, player.id, effect.source_id,
        player.hero_class, card_id, soldier.id if soldier else None,
        count, herald_rank(count), r.state.turn, r.state.action_number, herald_class)
    r.state.herald_history.append(record)
    # Count and provenance commit even when no field slot was available.
    r.emit('heralded', source_id=effect.source_id, player_id=player.id,
           amount=count + 1, rank=herald_rank(count + 1))
    if soldier is None:
        r.emit('summon_failed', player_id=player.id, card_id=card_id, reason='board_full')
        return []
    r.emit('minion_summoned', source_id=soldier.id, target_id=soldier.id, player_id=player.id)
    return [GrantKeyword(soldier.id, keyword, effect.source_id) for keyword in effect.grant_keywords]


def validate_history(state, registry):
    if type(state.herald_history) is not list:
        raise ValueError('Herald history must be a list')
    counts = {1: 0, 2: 0}
    seen = set()
    previous = (0, 0)
    initial_classes = {}
    for player_id, player in state.players.items():
        if player.herald_class is not None and (
                type(player.herald_class) is not CardClass or player.herald_class not in HERALD_CLASSES):
            raise ValueError('Invalid bound Herald class')
        heroes = (e for e in state.entities.values() if e.owner == player_id and e.kind == CardType.HERO)
        original = min(heroes, key=lambda e: e.id, default=None)
        metadata = registry.card(original.card_id).metadata if original is not None else None
        classes = metadata.classes if metadata is not None else ()
        initial = classes[0] if len(classes) == 1 and classes[0] in HERALD_CLASSES else None
        initial_classes[player_id] = initial
        if initial is not None and player.herald_class != initial:
            raise ValueError('Starting Herald class binding changed')
    for index, record in enumerate(state.herald_history, 1):
        if type(record) is not HeraldRecord:
            raise ValueError('Invalid Herald record')
        record.__post_init__()
        if (record.id != index or record.count_before != counts[record.player_id] or
                record.rank != herald_rank(record.count_before) or
                record.herald_class not in HERALD_CLASSES or
                record.herald_class != state.players[record.player_id].herald_class or
                record.soldier_card_id != soldier_card(registry, record.herald_class) or
                record.source_id is not None and record.source_id not in state.entities or
                record.turn > state.turn or record.action > state.action_number or
                record.turn < previous[0] or record.action < previous[1]):
            raise ValueError('Invalid Herald provenance/count')
        if record.soldier_id is not None:
            entity = state.entities.get(record.soldier_id)
            if (entity is None or entity.id in seen or entity.kind != CardType.MINION or
                    entity.owner != record.player_id or
                    record.source_id is not None and entity.id <= record.source_id):
                raise ValueError('Invalid Herald Soldier identity')
            seen.add(entity.id)
        counts[record.player_id] += 1
        previous = (record.turn, record.action)
    for player_id, player in state.players.items():
        if initial_classes[player_id] is None and not counts[player_id] and player.herald_class is not None:
            raise ValueError('Herald binding has no starting class or accepted Herald')
    for entity in (*state.entities.values(), *state.death_history):
        rank = entity.herald_rank
        definition = registry.card(entity.card_id)
        if rank is not None and (type(rank) is not int or not 0 <= rank <= 2 or not definition.herald_scaling):
            raise ValueError('Invalid captured Herald rank')
        if entity.zone == Zone.BOARD and definition.herald_scaling and rank is None:
            raise ValueError('Board Soldier/appendage has no captured Herald rank')


def register(mechanics):
    mechanics.register(Herald, herald)
