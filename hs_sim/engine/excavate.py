"""Player-wide Excavate progress, versioned treasure tables and atomic rewards.

R-095: current hero class selects this use's maximum depth/reward. Crossing
classes with different maximum depths starts a new vein when needed.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, replace

from .construction import name
from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardClass, CardType, ExcavationRecord, Rarity, Zone
from .pools import GenerationContext, sample_candidates


from .model import PLAYABLE_CARD_CLASSES
PLAYABLE_CLASSES = PLAYABLE_CARD_CLASSES
RARITIES = (Rarity.COMMON, Rarity.RARE, Rarity.EPIC, Rarity.LEGENDARY)


@dataclass(frozen=True)
class ExcavationClass:
    hero_class: CardClass
    legendary_pool_id: str | None = None

    def __post_init__(self):
        if type(self.hero_class) is not CardClass or self.hero_class not in PLAYABLE_CLASSES:
            raise ValueError('Excavation requires a playable hero class')
        if self.legendary_pool_id is not None: name(self.legendary_pool_id, 'legendary treasure pool')


@dataclass(frozen=True)
class ExcavationProfile:
    id: str
    version: str
    target_id: str
    mode: str
    shared_pools: tuple[str, str, str]
    classes: tuple[ExcavationClass, ...]
    complete: bool = False

    def __post_init__(self):
        name(self.id, 'Excavation profile'); name(self.version, 'Excavation version')
        GenerationContext(self.target_id, self.mode)
        if type(self.complete) is not bool or self.mode != 'experimental' and not self.complete:
            raise ValueError('Formal Excavation profiles require an explicit completeness declaration')
        if type(self.shared_pools) is not tuple or len(self.shared_pools) != 3:
            raise ValueError('Excavation requires three shared rarity pools')
        for pool in self.shared_pools: name(pool, 'shared treasure pool')
        if len(set(self.shared_pools)) != 3: raise ValueError('Shared tiers require distinct pools')
        if type(self.classes) is not tuple or any(type(c) is not ExcavationClass for c in self.classes):
            raise ValueError('Excavation class rules must be immutable typed declarations')
        for rule in self.classes: rule.__post_init__()
        if len(self.classes) != len(PLAYABLE_CLASSES) or {c.hero_class for c in self.classes} != PLAYABLE_CLASSES:
            raise ValueError('Every playable class needs an explicit Excavation rule')

    @property
    def key(self): return self.id, self.target_id, self.mode

    def legendary_pool(self, hero_class):
        if type(hero_class) is not CardClass or hero_class not in PLAYABLE_CLASSES:
            raise ValueError('Excavation requires a known current hero class')
        return next(c.legendary_pool_id for c in self.classes if c.hero_class == hero_class)


def validate_profiles(registry):
    for profile in registry.excavation_profiles.values():
        profile.__post_init__(); context = GenerationContext(profile.target_id, profile.mode)
        pools = [(pool_id, n) for n, pool_id in enumerate(profile.shared_pools, 1)]
        pools += [(c.legendary_pool_id, 4) for c in profile.classes if c.legendary_pool_id is not None]
        for pool_id, tier in pools:
            pool = registry.pool(pool_id, context)
            if profile.complete and not pool.complete: raise ValueError('Complete Excavation requires complete pools')
            for member in pool.members:
                row = registry.pool_card(member.card_id)
                if row.metadata.rarity != RARITIES[tier-1] or row.kind not in (
                        CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO):
                    raise ValueError('Treasure rarity/type disagrees with its Excavation tier')


def excavation_count(state, player_id):
    _player(player_id)
    return sum(x.player_id == player_id for x in state.excavation_history)


def next_step(previous, maximum):
    if previous is None: return 1, 1
    if previous.tier == previous.maximum or previous.tier >= maximum:
        return previous.cycle + 1, 1
    return previous.cycle, previous.tier + 1


def candidates(registry, context, pool_id, *, executable):
    """Exact declared treasure inventory; ordinary random-card bans do not apply."""
    pool = registry.pool(pool_id, context)
    excluded = {registry.pool_card(i).generation_identity for i in pool.excluded_card_ids}
    unique = {}
    for member in sorted(pool.members, key=lambda m: m.card_id):
        row = registry.pool_card(member.card_id)
        if row.generation_identity in excluded: continue
        if executable:
            definition = registry.card(member.card_id)
            if not definition.hand_playable: raise ValueError('Excavation treasure is not hand playable')
        unique.setdefault(row.generation_identity, member)
    return tuple(unique.values())


@dataclass(frozen=True)
class Excavate(Effect):
    player_id: int
    source_id: int | None = None
    count: int = 1
    profile_id: str = 'excavate'

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        _integer(self.count, 'Excavation count', 0); name(self.profile_id, 'Excavation profile')


def excavate(r, effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Excavation count exceeds resolution budget')
    if effect.count == 0: return ()
    context = r.game._generation_context
    if context is None: raise ResolutionError('Excavation requires an explicit generation context')
    profile = r.registry.excavation_profile(effect.profile_id, context)
    player = r.player(effect.player_id)
    legendary = profile.legendary_pool(player.hero_class)
    maximum = 4 if legendary is not None else 3
    history = [x for x in r.state.excavation_history if x.player_id == player.id]
    previous = history[-1] if history else None
    if previous is not None and previous.profile_id != profile.id:
        raise ResolutionError('A player cannot switch Excavation profiles during a match')
    cycle, tier = next_step(previous, maximum)
    pool_id = legendary if tier == 4 else profile.shared_pools[tier-1]
    pool = r.registry.pool(pool_id, context)
    eligible = candidates(r.registry, context, pool_id, executable=True)
    if not eligible: raise ResolutionError('Excavation reward pool is empty')
    card_id = sample_candidates(r.game._rng, eligible, 1, replacement=True)[0]
    burned = len(player.hand) >= hand_capacity(player, r.rules)
    entity = r.create_entity(player.id, card_id, Zone.GRAVEYARD if burned else Zone.HAND)
    record = ExcavationRecord(len(r.state.excavation_history)+1, player.id, effect.source_id,
        player.hero_class, profile.id, profile.version, context.target_id, context.mode,
        pool_id, pool.version, len(history), cycle, tier, maximum, card_id, entity.id,
        burned, r.state.turn, r.state.action_number)
    r.state.excavation_history.append(record)
    r.emit('excavated', source_id=effect.source_id, player_id=player.id, amount=len(history)+1,
           cycle=cycle, tier=tier, maximum=maximum)
    r.emit('card_created', source_id=effect.source_id, target_id=entity.id, player_id=player.id)
    if burned:
        from .zones import emit_burn
        emit_burn(r,entity,profile='created_overflow',source_id=effect.source_id)
    else:
        r.emit('card_added_to_hand',source_id=effect.source_id,target_id=entity.id,player_id=player.id)
    return (replace(effect, count=effect.count-1),) if effect.count > 1 else ()


def validate_history(state, registry):
    if type(state.excavation_history) is not list: raise ValueError('Excavation history must be a list')
    latest = {}; counts = {1:0, 2:0}; rewards = set(); previous_time = (0,0)
    for index, record in enumerate(state.excavation_history, 1):
        if type(record) is not ExcavationRecord: raise ValueError('Invalid Excavation record')
        record.__post_init__()
        context = GenerationContext(record.target_id, record.mode)
        profile = registry.excavation_profile(record.profile_id, context)
        legendary = profile.legendary_pool(record.hero_class)
        maximum = 4 if legendary is not None else 3
        previous = latest.get(record.player_id)
        cycle, tier = next_step(previous, maximum)
        pool_id = legendary if tier == 4 else profile.shared_pools[tier-1]
        pool = registry.pool(pool_id, context)
        entity = state.entities.get(record.reward_id)
        if (record.id != index or record.count_before != counts[record.player_id] or
                record.profile_version != profile.version or (record.cycle,record.tier,record.maximum) != (cycle,tier,maximum) or
                record.pool_id != pool_id or record.pool_version != pool.version or
                previous is not None and record.profile_id != previous.profile_id or
                record.source_id is not None and record.source_id not in state.entities or
                entity is None or entity.owner != record.player_id or record.reward_id in rewards or
                record.source_id is not None and record.reward_id <= record.source_id or
                not previous_time <= (record.turn,record.action) <= (state.turn,state.action_number) or
                not any(m.card_id == record.card_id for m in candidates(registry,context,pool_id,executable=False))):
            raise ValueError('Invalid Excavation progress, reward or provenance')
        registry.card(record.card_id)
        acquired = any(x.entity_id == record.reward_id and x.card_id == record.card_id and
            (x.turn,x.action) == (record.turn,record.action) and x.reason == 'created' for x in state.hand_entries)
        if acquired == record.burned: raise ValueError('Excavation reward and initial hand acquisition disagree')
        latest[record.player_id] = record; counts[record.player_id] += 1; rewards.add(record.reward_id)
        previous_time = (record.turn,record.action)


def validate_context(game):
    context = game._generation_context
    if any(context is None or (x.target_id,x.mode) != (context.target_id,context.mode)
           for x in game._state.excavation_history):
        raise ValueError('Excavation history and generation context differ')


def progress(state, player_id):
    history = [r for r in state.excavation_history if r.player_id == player_id]
    last = history[-1] if history else None
    return {'count':len(history), 'cycle':last.cycle if last else 0,
            'depth':last.tier if last and last.tier < last.maximum else 0}


def register(mechanics):
    mechanics.register(Excavate, excavate)
