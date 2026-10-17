"""Versioned generation inventories, pure eligibility and deterministic sampling.

Inventories describe rule eligibility independently of executable card coverage.
Generation rules and declared pool/query exclusions define eligibility, never
absence from Registry.cards. These are trusted host definitions, not player input.
"""
from .card_creation import (CardSpellRepeatGrant, CreatedMinionGrant, CreatedMinionStats, DiscoveryMinionGift,
                            validate_declaration, validate_minion_grant, validate_minion_stats)
from dataclasses import dataclass

from .construction import ids, integer, name
from .effects import AddToHand, ChoiceOption, Effect, RequestChoice, Summon, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardAbilityCondition, CardClass, CardDefinition, CardMetadata, CardType, CostSpec, Keyword, Rarity, SpellSchool, SummonStats, validate_minion_subtypes
from .card_conditions import UnknownCardFactError, matches_ability_values
from .summon_quantities import SummonCause

SPECIAL_GENERATION_KEYWORDS = frozenset((Keyword.TITAN, Keyword.OLD_GOD, Keyword.QUEST, Keyword.QUESTLINE))


@dataclass(frozen=True)
class GenerationPolicy:
    allowed_special: tuple[Keyword, ...] = ()

    def __post_init__(self):
        enum_tuple(self.allowed_special, Keyword, 'allowed special generation keywords')
        if not set(self.allowed_special).issubset(SPECIAL_GENERATION_KEYWORDS):
            raise ValueError('Generation exceptions must name a normally excluded keyword')


def validate_policy(policy):
    if type(policy) is not GenerationPolicy: raise ValueError('Expected GenerationPolicy')
    policy.__post_init__()


def enum_tuple(value, kind, field):
    if type(value) is not tuple or any(type(v) is not kind for v in value) or len(set(value)) != len(value):
        raise ValueError(f'{field} must be a unique tuple of {kind.__name__}')


@dataclass(frozen=True)
class GenerationContext:
    target_id: str
    mode: str
    starting_decks: tuple[tuple[str, ...], tuple[str, ...]] | None = None

    def __post_init__(self):
        name(self.target_id, 'generation target')
        if self.mode not in ('experimental', 'standard', 'wild'):
            raise ValueError('Unsupported generation mode')
        if self.starting_decks is not None:
            if type(self.starting_decks) is not tuple or len(self.starting_decks) != 2:
                raise ValueError('Generation origin requires two immutable starting decks')
            for deck in self.starting_decks:
                ids(deck, 'generation starting deck', unique=False)

    @classmethod
    def from_dict(cls, value):
        if type(value) is not dict or set(value) != {'target_id', 'mode', 'starting_decks'}:
            raise ValueError('Invalid generation context fields')
        row = dict(value)
        if row['starting_decks'] is not None:
            decks = row['starting_decks']
            if type(decks) is not list or len(decks) != 2 or any(type(d) is not list for d in decks):
                raise ValueError('Saved generation origin requires two complete deck lists')
            row['starting_decks'] = tuple(tuple(d) for d in decks)
        return cls(**row)

    def to_dict(self):
        return {'target_id': self.target_id, 'mode': self.mode,
                'starting_decks': None if self.starting_decks is None else [list(d) for d in self.starting_decks]}


@dataclass(frozen=True)
class PoolCard:
    card_id: str
    kind: CardType
    cost: int
    metadata: CardMetadata
    spell_school: SpellSchool | None = None
    keywords: tuple[Keyword, ...] = ()
    identity: str | None = None
    battlecry: bool | None = None
    deathrattle: bool | None = None
    choose_one: bool | None = None

    def __post_init__(self):
        for field in ('deathrattle', 'choose_one'):
            if getattr(self, field) is not None and type(getattr(self, field)) is not bool:
                raise ValueError(f'Pool {field} identity requires boolean or unknown')
        if self.battlecry is not None and type(self.battlecry) is not bool:
            raise ValueError('Pool Battlecry identity requires boolean or unknown')
        if self.battlecry and self.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
            raise ValueError('This pool card kind cannot have a Battlecry')
        name(self.card_id, 'pool card ID')
        if type(self.kind) is not CardType or type(self.metadata) is not CardMetadata:
            raise ValueError('Pool cards require explicit type and metadata')
        integer(self.cost, 'printed cost', 0)
        self.metadata.__post_init__()
        if self.metadata.subtypes and self.kind != CardType.MINION:
            raise ValueError('Printed subtypes require a minion pool card')
        enum_tuple(self.keywords, Keyword, 'keywords')
        if self.spell_school is not None and (type(self.spell_school) is not SpellSchool or self.kind != CardType.SPELL):
            raise ValueError('Spell schools require a spell')
        if self.identity is not None:
            name(self.identity, 'generation identity')

    @property
    def generation_identity(self):
        # Constructed copy limits do not determine generation equivalence.
        return self.identity or self.card_id

    @classmethod
    def from_definition(cls, card: CardDefinition, *, identity=None):
        return cls(card.id, card.kind, card.cost, card.metadata, card.spell_school, card.keywords, identity,
                   card.battlecry is not None, card.deathrattle is not None, card.choose_one is not None)

    def filter_signature(self):
        m = self.metadata
        return (self.kind, self.cost, m.collectible, frozenset(m.classes), m.rarity,
                None if m.tribes is None else frozenset(m.tribes), self.spell_school, frozenset(self.keywords),
                None if m.factions is None else frozenset(m.factions), self.battlecry,
                None if m.subtypes is None else frozenset(m.subtypes), self.deathrattle, self.choose_one)


@dataclass(frozen=True)
class PoolMember:
    card_id: str
    weight: int = 1

    def __post_init__(self):
        name(self.card_id, 'pool member')
        integer(self.weight, 'pool weight')


@dataclass(frozen=True)
class PoolDefinition:
    id: str
    version: str
    target_id: str
    mode: str
    members: tuple[PoolMember, ...]
    excluded_card_ids: tuple[str, ...] = ()
    complete: bool = False

    def __post_init__(self):
        name(self.id, 'pool ID')
        name(self.version, 'pool version')
        GenerationContext(self.target_id, self.mode)
        if type(self.complete) is not bool or (self.mode != 'experimental' and not self.complete):
            raise ValueError('Formal generation pools require an explicit completeness declaration')
        if type(self.members) is not tuple or any(type(m) is not PoolMember for m in self.members):
            raise ValueError('Pool members must be an immutable tuple of PoolMember')
        for member in self.members:
            member.__post_init__()
        if len({m.card_id for m in self.members}) != len(self.members):
            raise ValueError('Duplicate pool member')
        ids(self.excluded_card_ids, 'pool exclusions', unique=True)
        if set(self.excluded_card_ids) - {m.card_id for m in self.members}:
            raise ValueError('Excluded cards must belong to the pool')

    @property
    def key(self):
        return self.id, self.target_id, self.mode


@dataclass(frozen=True)
class PoolQuery:
    kinds: tuple[CardType, ...] = ()
    min_cost: int | None = None
    max_cost: int | None = None
    collectible: bool | None = None
    class_mode: str = 'any'
    classes: tuple[CardClass, ...] = ()
    include_neutral: bool = True
    rarities: tuple[Rarity, ...] = ()
    tribes_any: tuple[str, ...] = ()
    spell_schools: tuple[SpellSchool, ...] = ()
    keywords_all: tuple[Keyword, ...] = ()
    exclude_card_ids: tuple[str, ...] = ()
    exclude_source: bool = False
    factions_any: tuple[str, ...] = ()
    ability: CardAbilityCondition | None = None
    subtypes_any: tuple[str, ...] = ()
    deathrattle: bool | None = None
    choose_one: bool | None = None
    # Common fields stay conjunctive; alternatives are a flat disjunction.
    any_of: tuple['PoolQuery', ...] = ()

    def __post_init__(self):
        if type(self.any_of) is not tuple or any(type(q) is not PoolQuery for q in self.any_of):
            raise ValueError('Query alternatives require an immutable tuple of PoolQuery')
        if self.any_of:
            if len(self.any_of) < 2:
                raise ValueError('Query alternatives require at least two clauses')
            for clause in self.any_of:
                if clause.any_of or clause.exclude_source or clause.exclude_card_ids:
                    raise ValueError('Query alternatives are flat metadata predicates; exclusions belong to the outer query')
                clause.__post_init__()
            if len(set(self.any_of)) != len(self.any_of):
                raise ValueError('Duplicate query alternative')
        for field in ('deathrattle', 'choose_one'):
            if getattr(self, field) is not None and type(getattr(self, field)) is not bool:
                raise ValueError(f'Pool {field} filter requires boolean or None')
        if self.ability is not None:
            if type(self.ability) is not CardAbilityCondition:
                raise ValueError('Pool ability filter requires CardAbilityCondition')
            self.ability.__post_init__()
        for field, kind in (('kinds', CardType), ('classes', CardClass), ('rarities', Rarity),
                            ('spell_schools', SpellSchool), ('keywords_all', Keyword)):
            enum_tuple(getattr(self, field), kind, field)
        for field in ('min_cost', 'max_cost'):
            if getattr(self, field) is not None:
                integer(getattr(self, field), field, 0)
        if self.min_cost is not None and self.max_cost is not None and self.min_cost > self.max_cost:
            raise ValueError('Invalid cost interval')
        if self.collectible is not None and type(self.collectible) is not bool:
            raise ValueError('collectible must be boolean or None')
        if self.class_mode not in ('any', 'current', 'other', 'specified'):
            raise ValueError('Invalid generation class mode')
        if (self.class_mode == 'specified') != bool(self.classes) or CardClass.NEUTRAL in self.classes:
            raise ValueError('Specified classes require playable classes; neutral is a separate flag')
        for field in ('include_neutral', 'exclude_source'):
            if type(getattr(self, field)) is not bool:
                raise ValueError(f'{field} must be boolean')
        ids(self.tribes_any, 'tribes_any', unique=True)
        ids(self.factions_any, 'factions_any', unique=True)
        validate_minion_subtypes(self.subtypes_any)
        ids(self.exclude_card_ids, 'query exclusions', unique=True)


def validate_pools(registry):
    """Missing executable definitions are allowed; contradictory metadata is not."""
    for row in registry.pool_cards.values():
        row.__post_init__()
        if row.card_id in registry.cards:
            actual = PoolCard.from_definition(registry.card(row.card_id), identity=row.identity)
            if actual != row:
                raise ValueError(f'Pool metadata differs from executable definition: {row.card_id}')
    for pool in registry.pools.values():
        pool.__post_init__()
        identities = {}
        for member in pool.members:
            row = registry.pool_card(member.card_id)
            identity = row.generation_identity
            signature = row.filter_signature(), member.weight
            if identity in identities and identities[identity] != signature:
                raise ValueError(f'Conflicting generation aliases: {identity}')
            identities[identity] = signature


def matches_metadata(query, *, card_id, kind, cost, meta, spell_school, keywords, current_class=None,
                     printed_battlecry=None, current_battlecry=None,
                     printed_deathrattle=None, printed_choose_one=None):
    """Conjoin common facts and a flat OR; unknown is neither true nor false."""
    if type(query) is not PoolQuery:
        raise ValueError('Expected PoolQuery')
    query.__post_init__()
    missing = []
    if query.kinds and kind not in query.kinds:
        return False
    if query.subtypes_any and kind != CardType.MINION:
        return False
    if ((query.min_cost is not None and cost < query.min_cost) or
            (query.max_cost is not None and cost > query.max_cost)):
        return False
    needs_meta = (query.collectible is not None or query.class_mode != 'any' or not query.include_neutral
                  or query.rarities or query.tribes_any or query.factions_any or query.subtypes_any)
    if meta is None and needs_meta:
        missing.append(f'Unknown candidate metadata: {card_id}')
    if meta is not None:
        if query.collectible is not None:
            if meta.collectible is None:
                missing.append(f'Unknown candidate collectibility: {card_id}')
            elif meta.collectible != query.collectible:
                return False
        if query.class_mode != 'any' or not query.include_neutral:
            if meta.classes is None:
                missing.append(f'Unknown candidate classes: {card_id}')
            else:
                neutral = meta.classes == (CardClass.NEUTRAL,)
                if neutral:
                    if not query.include_neutral:
                        return False
                elif query.class_mode in ('current', 'other') and (
                        type(current_class) is not CardClass or current_class == CardClass.NEUTRAL):
                    missing.append(f'Unknown current hero class: {card_id}')
                elif ((query.class_mode == 'current' and current_class not in meta.classes) or
                      (query.class_mode == 'other' and current_class in meta.classes) or
                      (query.class_mode == 'specified' and not set(query.classes).intersection(meta.classes))):
                    return False
    if query.spell_schools and spell_school not in query.spell_schools:
        return False
    if not set(query.keywords_all).issubset(keywords):
        return False
    if meta is not None:
        if query.rarities:
            if meta.rarity is None:
                missing.append(f'Unknown candidate rarity: {card_id}')
            elif meta.rarity not in query.rarities:
                return False
        if query.tribes_any:
            if meta.tribes is None:
                missing.append(f'Unknown candidate tribes: {card_id}')
            elif 'all' not in meta.tribes and not set(query.tribes_any).intersection(meta.tribes):
                return False
        if query.factions_any:
            if meta.factions is None:
                missing.append(f'Unknown candidate factions: {card_id}')
            elif not set(query.factions_any).intersection(meta.factions):
                return False
        if query.subtypes_any:
            if meta.subtypes is None:
                missing.append(f'Unknown candidate minion subtypes: {card_id}')
            elif not set(query.subtypes_any).intersection(meta.subtypes):
                return False
    if query.ability is not None:
        try:
            if not matches_ability_values(query.ability, printed=printed_battlecry, current=current_battlecry):
                return False
        except UnknownCardFactError as error:
            missing.append(str(error))
    facts = (('deathrattle', printed_deathrattle), ('choose_one', printed_choose_one))
    for field, value in facts:
        wanted = getattr(query, field)
        if wanted is not None:
            if value is None:
                missing.append(f'Unknown candidate printed {field} identity: {card_id}')
            elif type(value) is not bool:
                raise ValueError(f'Invalid printed {field} identity: {card_id}')
            elif value != wanted:
                return False
    if query.any_of:
        unknown_alternatives = []
        for clause in query.any_of:
            try:
                if matches_metadata(clause, card_id=card_id, kind=kind, cost=cost, meta=meta,
                        spell_school=spell_school, keywords=keywords, current_class=current_class,
                        printed_battlecry=printed_battlecry, current_battlecry=current_battlecry,
                        printed_deathrattle=printed_deathrattle, printed_choose_one=printed_choose_one):
                    break
            except UnknownCardFactError as error:
                unknown_alternatives.append(str(error))
        else:
            if not unknown_alternatives:
                return False
            missing.extend(unknown_alternatives)
    if missing:
        raise UnknownCardFactError(missing[0])
    return True


def resolve_candidates(registry, context, pool_id, query, *, current_class=None, source_card_id=None,
                       policy=GenerationPolicy(), player_id=None, exclude_source_by_rule=False):
    """Pure query. Validate every eligible member before deduplication or RNG."""
    if type(context) is not GenerationContext or type(query) is not PoolQuery:
        raise ValueError('Generation requires an explicit context and PoolQuery')
    context.__post_init__()
    query.__post_init__()
    validate_policy(policy)
    if type(exclude_source_by_rule) is not bool:
        raise ValueError('Generation source rule requires an explicit boolean')
    if player_id is not None:
        _player(player_id)
    pool = registry.pool(pool_id, context)
    if any(q.class_mode in ('current', 'other') for q in (query, *query.any_of)) and (type(current_class) is not CardClass or current_class == CardClass.NEUTRAL):
        raise ValueError('Generation requires a known current playable hero class')
    excluded = set(pool.excluded_card_ids) | set(query.exclude_card_ids)
    excluded_identities = {registry.pool_card(i).generation_identity for i in excluded if i in registry.pool_cards}
    if query.exclude_source:
        name(source_card_id, 'excluded source card')
        excluded.add(source_card_id)
        if source_card_id in registry.pool_cards:
            excluded_identities.add(registry.pool_card(source_card_id).generation_identity)
    # Ordinary collectible generation cannot create its source or a reviewed
    # edition of it. Pure queries, physical inventory and named recipes opt out.
    source_family = (set(registry.generation_family(source_card_id))
                     if exclude_source_by_rule and source_card_id is not None else set())
    source_identities = {registry.pool_card(cid).generation_identity for cid in source_family
                         if cid in registry.pool_cards}
    eligible = []
    for member in sorted(pool.members, key=lambda m: m.card_id):
        row = registry.pool_card(member.card_id)
        meta = row.metadata
        if meta.collectible is True and (row.card_id in source_family or row.generation_identity in source_identities):
            continue
        # Explicit Titan/main-quest bans, evaluated from independent inventory metadata.
        if (SPECIAL_GENERATION_KEYWORDS - set(policy.allowed_special)) & set(row.keywords):
            continue
        if row.card_id in excluded or row.generation_identity in excluded_identities:
            continue
        if not matches_metadata(query, card_id=row.card_id, kind=row.kind, cost=row.cost,
                meta=meta, spell_school=row.spell_school, keywords=row.keywords, current_class=current_class,
                printed_battlecry=row.battlecry, current_battlecry=row.battlecry,
                printed_deathrattle=row.deathrattle, printed_choose_one=row.choose_one):
            continue
        from .starting_generation import eligible as starting_eligible
        if not starting_eligible(registry, context, player_id, row.card_id, row.keywords):
            continue
        registry.card(row.card_id)  # Never filter by executable coverage.
        eligible.append(member)
    unique = {}
    for member in eligible:
        unique.setdefault(registry.pool_card(member.card_id).generation_identity, member)
    return tuple(unique.values())


def sample_candidates(rng, candidates, count, *, replacement):
    """Integer roulette over canonical candidates; no hidden class multiplier."""
    remaining, result = list(candidates), []
    for _ in range(count if replacement else min(count, len(remaining))):
        if not remaining:
            break
        ticket = rng.randrange(sum(m.weight for m in remaining))
        for index, member in enumerate(remaining):
            ticket -= member.weight
            if ticket < 0:
                result.append(member.card_id)
                if not replacement:
                    remaining.pop(index)
                break
    return tuple(result)


def validate_request(effect):
    _player(effect.player_id)
    _source(effect.source_id)
    name(effect.pool_id, 'pool ID')
    minimum = 0 if getattr(effect, 'producer_profile_id', None) is not None and effect.destination == 'board' else 1
    integer(effect.count, 'generation count', minimum)
    if type(effect.query) is not PoolQuery:
        raise ValueError('Expected PoolQuery')
    effect.query.__post_init__()


@dataclass(frozen=True)
class DiscoveryGiftPool:
    """An explicit version-bound inventory, independent of executable coverage."""
    id: str
    version: str
    generation_target: str
    mode: str
    members: tuple[DiscoveryMinionGift, ...]
    complete: bool = False

    def __post_init__(self):
        name(self.id, 'discovery gift pool ID');name(self.version, 'discovery gift pool version')
        GenerationContext(self.generation_target, self.mode)
        if type(self.complete) is not bool or self.mode != 'experimental' and not self.complete:
            raise ValueError('Formal gift pools require an explicit completeness declaration')
        if (type(self.members) is not tuple or len(self.members) < 3 or
                any(type(g) is not DiscoveryMinionGift for g in self.members)):
            raise ValueError('Complete immutable gift recipes required; unsupported bodies cannot be filtered')
        for gift in self.members:gift.__post_init__()
        if len({g.id for g in self.members}) != len(self.members):
            raise ValueError('Duplicate discovery gift identity')


@dataclass(frozen=True)
class DiscoverFromPool(Effect):
    player_id: int
    pool_id: str
    query: PoolQuery = PoolQuery()
    count: int = 3
    source_id: int | None = None
    prompt: str = '发现一张牌'
    policy: GenerationPolicy = GenerationPolicy()
    discoveries: int = 1
    destination: str = 'hand'
    delivery: str = 'after_each'
    replacement: bool = True
    position: str | int = 'random'
    cost: CostSpec | None = None
    expires_turn: int | None = None

    spell_repeat: CardSpellRepeatGrant | None = None
    cause: SummonCause | None = None
    gift_pool: DiscoveryGiftPool | None = None
    heal_hero_by_printed_cost: bool = False
    freeze_summoned: bool = False
    summon_copy_stats: SummonStats | None = None
    minion_grant: CreatedMinionGrant | None = None
    temporary_until_turn: int | None = None
    gift_copy_to_hand: bool = False

    def __post_init__(self):
        if type(self.gift_copy_to_hand) is not bool:
            raise ValueError('Selected gift copy requires an explicit boolean')
        if self.gift_copy_to_hand and (
                self.gift_pool is None or self.source_id is None or self.cost is not None or
                type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                self.query.collectible is not True or self.minion_grant is not None or
                self.temporary_until_turn is not None):
            raise ValueError('Selected gift copy requires one plain source-bound gifted minion discovery')
        validate_minion_grant(self.minion_grant)
        if self.minion_grant is not None:
            grant=self.minion_grant
            if (grant.attack<0 or grant.health<0 or grant.keywords or grant.reborn_policy is not None or
                    grant.identity is not None or grant.special is not None or
                    self.source_id is None or self.destination!='hand' or self.count!=3 or self.discoveries!=1 or
                    self.delivery!='after_each' or not self.replacement or type(self.query)is not PoolQuery or
                    self.query.kinds!=(CardType.MINION,)or self.query.collectible is not True or
                    self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                    self.cause is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                    self.freeze_summoned or self.summon_copy_stats is not None):
                raise ValueError('Ordinary discovery grant requires one source-bound positive-stat hand-minion recipe')
        if self.summon_copy_stats is not None:
            if type(self.summon_copy_stats)is not SummonStats:
                raise ValueError('Discovered copy requires typed summon stats')
            self.summon_copy_stats.__post_init__()
            if (self.summon_copy_stats.attack is None or self.summon_copy_stats.health is None or
                    self.destination!='hand'or self.cause is None or self.source_id is None or
                    self.count!=3 or self.discoveries!=1 or self.delivery!='after_each'or not self.replacement or
                    type(self.query)is not PoolQuery or self.query.kinds!=(CardType.MINION,)or self.query.collectible is not True or
                    self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                    self.gift_pool is not None or self.heal_hero_by_printed_cost or self.freeze_summoned):
                raise ValueError('Discovered copy requires one plain attributed hand-minion discovery')
        if type(self.freeze_summoned)is not bool:
            raise ValueError('Discovered summon freeze requires an explicit boolean')
        if self.freeze_summoned and (
                self.destination!='board'or self.cause is None or self.source_id is None or
                self.count!=3 or self.discoveries!=1 or self.delivery!='after_each'or not self.replacement or
                type(self.query)is not PoolQuery or self.query.kinds!=(CardType.MINION,)or self.query.collectible is not True or
                self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                self.gift_pool is not None or self.heal_hero_by_printed_cost):
            raise ValueError('Discovered freeze requires one ordinary attributed board-minion discovery')
        if type(self.heal_hero_by_printed_cost)is not bool:
            raise ValueError('Discovery cost healing must be an explicit boolean')
        if self.heal_hero_by_printed_cost and(
                self.source_id is None or self.count!=3 or self.discoveries!=1 or type(self.query)is not PoolQuery or
                self.query.kinds!=(CardType.SPELL,)or self.query.collectible is not True or
                self.destination!='hand'or self.delivery!='after_each'or not self.replacement or
                self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                self.cause is not None or self.gift_pool is not None):
            raise ValueError('Cost healing requires one ordinary source-bound collectible spell discovery')
        if self.gift_pool is not None:
            if type(self.gift_pool) is not DiscoveryGiftPool:raise ValueError('Expected DiscoveryGiftPool')
            self.gift_pool.__post_init__()
            if (self.count != 3 or self.discoveries != 1 or self.destination != 'hand' or
                    self.delivery != 'after_each' or not self.replacement or
                    self.expires_turn is not None or self.spell_repeat is not None or self.cause is not None):
                raise ValueError('Gift discovery currently requires one ordinary three-option hand discovery')
            if self.cost is not None:
                if type(self.cost) is not CostSpec:
                    raise ValueError('Gift discovery source cost requires CostSpec')
                self.cost.__post_init__()
                if (self.cost.set_to is not None or self.cost.delta > 0 or self.cost.minimum or
                        self.cost.payment is not None or self.cost.card_ids or
                        self.cost.ability is not None or CardType.MINION not in self.cost.card_types):
                    raise ValueError('Gift discovery source cost supports an ordinary reduction only')
        if self.cause is not None:
            if type(self.cause)is not SummonCause or (self.destination!='board'and self.summon_copy_stats is None):raise ValueError('Typed summon cause requires board discovery or selected hand-copy declaration')
            self.cause.__post_init__()
        validate_declaration(self.spell_repeat)
        validate_request(self)
        name(self.prompt, 'Discover prompt')
        validate_policy(self.policy)
        integer(self.discoveries, 'Discover repetitions', 0)
        if self.delivery not in ('after_each', 'after_all'):
            raise ValueError('Invalid discovery delivery timing')
        validate_delivery(self)


@dataclass(frozen=True)
class GenerateFromPool(Effect):
    player_id: int
    pool_id: str
    query: PoolQuery = PoolQuery()
    count: int = 1
    source_id: int | None = None
    replacement: bool = True
    destination: str = 'hand'
    position: str | int = 'random'
    cost: CostSpec | None = None
    expires_turn: int | None = None
    policy: GenerationPolicy = GenerationPolicy()

    spell_repeat: CardSpellRepeatGrant | None = None
    cause: SummonCause | None = None
    producer_profile_id: str | None = None
    combined_shatter: bool = False
    temporary_until_turn: int | None = None
    board_position: int | None = None
    minion_stats: CreatedMinionStats | None = None
    shuffle_actor_id: int | None = None

    def __post_init__(self):
        from .card_creation import validate_combined_shatter
        validate_combined_shatter(self.combined_shatter)
        validate_minion_stats(self.minion_stats)
        if self.shuffle_actor_id is not None:
            _player(self.shuffle_actor_id)
            if (self.destination != 'deck' or self.position != 'random' or self.source_id is None or
                    self.minion_stats is None):
                raise ValueError('Generated numeric shuffle requires its original actor and random deck delivery')
        if self.minion_stats is not None:
            if (self.source_id is None or
                    self.destination not in ('hand','deck') or not self.replacement or
                    type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                    self.query.collectible is not True or self.expires_turn is not None or
                    self.spell_repeat is not None or self.cause is not None or self.producer_profile_id is not None or
                    self.combined_shatter or self.temporary_until_turn is not None or self.board_position is not None):
                raise ValueError('Generated minion numeric recipe requires a plain source-bound hand or deck delivery')
        if self.producer_profile_id is not None:
            if type(self.producer_profile_id) is not str or not self.producer_profile_id or self.cause is None or self.destination != 'board':
                raise ValueError('Logical summon profile requires a named attributed board batch')
        if self.cause is not None:
            if type(self.cause)is not SummonCause or self.destination!='board':raise ValueError('Typed card summon cause requires board generation')
            self.cause.__post_init__()
        validate_declaration(self.spell_repeat)
        validate_request(self)
        validate_policy(self.policy)
        validate_delivery(self)


def validate_delivery(effect):
    if type(effect.replacement) is not bool or effect.destination not in ('hand', 'board', 'deck'):
        raise ValueError('Invalid generation replacement or destination')
    from .zones import position_value
    position_value(effect.position)
    if effect.destination != 'deck' and effect.position != 'random':
        raise ValueError('Generation insertion position applies only to the deck')
    if getattr(effect,'board_position',None)is not None:
        integer(effect.board_position,'generated board position',0)
        if effect.destination!='board' or effect.cause is None:
            raise ValueError('Generated board position requires attributed board delivery')
    if effect.temporary_until_turn is not None:
        integer(effect.temporary_until_turn, 'temporary pool card deadline', 1)
        if (effect.destination!='hand' or effect.source_id is None or not effect.replacement or
                type(effect.query)is not PoolQuery or effect.query.kinds!=(CardType.MINION,) or
                effect.query.collectible is not True or effect.cost is not None or
                effect.expires_turn is not None or effect.spell_repeat is not None or effect.cause is not None or
                getattr(effect,'combined_shatter',False) or getattr(effect,'minion_grant',None)is not None or
                getattr(effect,'gift_pool',None)is not None or getattr(effect,'heal_hero_by_printed_cost',False) or
                getattr(effect,'freeze_summoned',False) or getattr(effect,'summon_copy_stats',None)is not None or
                (type(effect)is DiscoverFromPool and
                 (effect.count!=3 or effect.discoveries!=1 or effect.delivery!='after_each'))):
            raise ValueError('Temporary pool cards require a plain source-bound hand-minion delivery')
    if getattr(effect,'combined_shatter',False) and effect.destination!='hand':
        raise ValueError('Combined Shatter generation requires hand delivery')
    from .effects import validate_generated_cost
    validate_generated_cost(effect.cost, effect.expires_turn)
    if effect.destination == 'board' and effect.spell_repeat is not None:
        raise ValueError('Created spell repetition requires hand or deck delivery')
    if effect.destination == 'board' and effect.cost is not None:
        raise ValueError('Generated cost applies only to hand or deck cards')


def generation_candidates(r, effect):
    effect.__post_init__()
    if getattr(effect,'temporary_until_turn',None)is not None and effect.temporary_until_turn!=r.state.turn:
        raise ResolutionError('Temporary pool deadline must be the accepted current turn')
    player = r.player(effect.player_id)
    source_card_id = None
    if effect.source_id is not None:
        if effect.source_id not in r.state.entities:
            raise ResolutionError('Generation source does not exist')
        source_card_id = r.state.entities[effect.source_id].card_id
    current_class = None
    if effect.query.class_mode in ('current', 'other'):
        current_class = player.hero_class
    candidates = resolve_candidates(r.registry, r.game._generation_context, effect.pool_id, effect.query,
                                    current_class=current_class, source_card_id=source_card_id,
                                    policy=getattr(effect, 'policy', GenerationPolicy()), player_id=effect.player_id,
                                    exclude_source_by_rule=True)
    board = getattr(effect, 'destination', 'hand') == 'board'
    if any((r.registry.card(m.card_id).kind != CardType.MINION if board
            else not r.registry.card(m.card_id).hand_playable) or r.registry.card(m.card_id).choice_only
           for m in candidates):
        raise ResolutionError('Eligible candidate cannot enter the generation destination')
    from .card_creation import validate_creation
    validate_creation(r.state, effect, (r.registry.card(m.card_id) for m in candidates))
    return candidates


def discover_from_pool(r, effect):
    from .discovery import start
    return start(r, effect)


def generate_from_pool(r, effect):
    if effect.destination=='board':
        from .summon_quantities import reject_ambiguous
        if effect.cause is None:reject_ambiguous(r)
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Generated work exceeds the resolution budget')
    candidates = generation_candidates(r, effect)
    from .costs import validate_creation_cost
    validate_creation_cost(r.state, effect, (r.registry.card(m.card_id) for m in candidates))
    if effect.cause is not None:
        from .pool_summons import accept_batch
        return accept_batch(r,effect,candidates)
    selected = sample_candidates(r.game._rng, candidates, effect.count, replacement=effect.replacement)
    # Freeze the entire draw before executing individual zone changes/triggers.
    return deliver_generated(effect, selected)


def deliver_generated(effect, selected):
    if effect.temporary_until_turn is not None:
        from .temporary_cards import CreateTemporaryCard
        return tuple(CreateTemporaryCard(effect.player_id,card_id,effect.temporary_until_turn,
                     source_id=effect.source_id)for card_id in selected)
    if effect.destination == 'board':
        return tuple(Summon(effect.player_id, card_id) for card_id in selected)
    if effect.destination == 'deck':
        from .zones import AddToDeck
        entries = tuple(AddToDeck(effect.player_id, card_id, effect.position, effect.source_id,
                               effect.cost, effect.expires_turn, spell_repeat=effect.spell_repeat,
                               minion_grant=getattr(effect,'minion_grant',None),
                               minion_stats=getattr(effect,'minion_stats',None)) for card_id in selected)
        if getattr(effect,'shuffle_actor_id',None) is not None:
            from .deck_shuffles import ShuffleDeckCards
            return (ShuffleDeckCards(effect.player_id, effect.shuffle_actor_id, entries, effect.source_id),) if entries else ()
        return entries
    return tuple(AddToHand(effect.player_id, card_id, effect.source_id,
                          cost=effect.cost, expires_turn=effect.expires_turn, spell_repeat=effect.spell_repeat,
                          minion_grant=getattr(effect,'minion_grant',None),
                          minion_stats=getattr(effect,'minion_stats',None),
                          combined_shatter=getattr(effect,'combined_shatter',False)) for card_id in selected)


@dataclass(frozen=True)
class GenerateFromCandidates(Effect):
    """Get one uniformly random card from a complete card-defined finite list."""
    player_id: int
    card_ids: tuple[str, ...]
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        ids(self.card_ids, 'hand generation candidates', unique=True)
        if not self.card_ids:
            raise ValueError('Hand generation candidates cannot be empty')


def validate_hand_candidates(registry, card_ids):
    for card_id in card_ids:
        card = registry.card(card_id)
        if not card.hand_playable or card.choice_only:
            raise ResolutionError('Every hand candidate must be a physical playable card')


def generate_from_candidates(r, effect):
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Generation source does not exist')
    # Validate the complete fixed list even when the destination hand is full.
    # Format eligibility is irrelevant to this explicitly named card recipe.
    validate_hand_candidates(r.registry, effect.card_ids)
    selected, = sample_candidates(r.game._rng, tuple(PoolMember(i) for i in sorted(effect.card_ids)),
                                  1, replacement=True)
    return (AddToHand(effect.player_id, selected, effect.source_id),)


@dataclass(frozen=True)
class SummonFromCandidates(Effect):
    """Uniform choice from a card-defined finite list, independent of format pools.

    The complete list is trusted content, never inferred from executable cards.
    Call repeatedly for multiple summons; each call observes current board space.
    """
    player_id: int
    card_ids: tuple[str, ...]
    source_id: int | None = None
    cause: SummonCause | None = None

    def __post_init__(self):
        if self.cause is not None:
            if type(self.cause)is not SummonCause:raise ValueError('Typed finite summon attribution required')
            self.cause.__post_init__()
        _player(self.player_id); _source(self.source_id)
        ids(self.card_ids, 'summon candidates', unique=True)
        if not self.card_ids:
            raise ValueError('Summon candidates cannot be empty')


def validate_summon_candidates(registry, card_ids):
    for card_id in card_ids:
        card = registry.card(card_id)
        if card.kind != CardType.MINION or card.choice_only:
            raise ResolutionError('Every summon candidate must be a physical minion')


def summon_from_candidates(r, effect):
    from .summon_quantities import reject_ambiguous
    if effect.cause is None:reject_ambiguous(r)
    player = r.player(effect.player_id)
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Generation source does not exist')
    # Validate even when full. Missing content cannot alter random probabilities.
    validate_summon_candidates(r.registry, effect.card_ids)
    if effect.cause is not None:
        from .summon_quantities import SummonByCard,SummonEntryMaterial,accept
        return accept(r,SummonByCard(effect.player_id,tuple(SummonEntryMaterial(i)for i in effect.card_ids),effect.cause,'random'))
    if len(player.board) >= r.rules.max_board:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='board_full')
        return ()
    card_id = r.game._rng.choice(effect.card_ids)
    return (Summon(effect.player_id, card_id),)


@dataclass(frozen=True)
class SummonFromPool(Effect):
    """One capacity-aware summon, without the preselection semantics of a batch."""
    player_id: int
    pool_id: str
    query: PoolQuery = PoolQuery(kinds=(CardType.MINION,),collectible=True)
    source_id: int | None = None
    policy: GenerationPolicy = GenerationPolicy()
    empty: str = 'skip'
    cause: SummonCause | None = None
    entry_keywords: tuple[Keyword,...] = ()
    position: int | None = None

    def __post_init__(self):
        if self.position is not None:integer(self.position,'pool summon board position',0)
        if (type(self.entry_keywords)is not tuple or self.entry_keywords not in((),(Keyword.TAUNT,)) or
                any(type(k)is not Keyword for k in self.entry_keywords)):
            raise ValueError('Pool entry keywords support only the declared Taunt recipe')
        if self.entry_keywords and(self.cause is None or self.source_id is None):
            raise ValueError('Pool entry keywords require original source and summon attribution')
        if self.cause is not None:
            if type(self.cause)is not SummonCause:raise ValueError('Typed pool summon attribution required')
            self.cause.__post_init__()
        if type(self.query) is not PoolQuery:raise ValueError('Pool summon requires PoolQuery')
        self.request().__post_init__()
        if self.query.kinds not in ((),(CardType.MINION,)):
            raise ValueError('Pool summoning requires a minion query')
        if self.empty not in ('skip','error'):raise ValueError('Invalid empty summon pool policy')

    def request(self):
        from dataclasses import replace
        return GenerateFromPool(self.player_id,self.pool_id,replace(self.query,kinds=(CardType.MINION,)),
            source_id=self.source_id,destination='board',policy=self.policy)


def summon_from_pool(r,effect):
    from .summon_quantities import reject_ambiguous
    if effect.cause is None:reject_ambiguous(r)
    effect.__post_init__()
    rows=generation_candidates(r,effect.request())
    # Validate all eligible content even if there is no board space.
    if not rows and effect.empty=='error':raise ResolutionError('Empty summon pool')
    if effect.cause is not None:
        from .summon_quantities import SummonByCard,SummonEntryMaterial,accept
        from .pool_summons import PoolSummonBasis
        basis=PoolSummonBasis.capture(r,effect.request(),rows,entry_keywords=effect.entry_keywords)
        return accept(r,SummonByCard(effect.player_id,tuple(SummonEntryMaterial(m.card_id,keywords=effect.entry_keywords)for m in rows),effect.cause,
            'weighted',position=effect.position,weights=tuple(m.weight for m in rows),pool_basis=basis))
    if len(r.player(effect.player_id).board)>=r.rules.max_board:
        r.emit('random_choice_skipped',source_id=effect.source_id,reason='board_full')
        return ()
    if not rows:return ()
    card_id=sample_candidates(r.game._rng,rows,1,replacement=True)[0]
    return (Summon(effect.player_id,card_id,position=effect.position),)


def validate_summon_boundary(game):
    if game._frame is None:return
    def check(work):
        if type(work) is not SummonFromPool:return
        work.__post_init__()
        if type(game._generation_context) is not GenerationContext:
            raise ValueError('Pool summon requires a generation context')
        game.registry.pool(work.pool_id,game._generation_context)
        if work.source_id is not None and work.source_id not in game._state.entities:
            raise ValueError('Pool summon source does not exist')
    for work in (*game._frame.prefix,*game._frame.continuation):check(work)
    for option in game._frame.options:
        for work in option.effects:check(work)


def register_generation(mechanics):
    mechanics.register_payload_type(PoolQuery)
    mechanics.register_payload_type(GenerationPolicy)
    mechanics.register_payload_type(DiscoveryMinionGift)
    mechanics.register_payload_type(DiscoveryGiftPool)
    mechanics.register(DiscoverFromPool, discover_from_pool)
    mechanics.register(GenerateFromPool, generate_from_pool)
    mechanics.register(GenerateFromCandidates, generate_from_candidates)
    mechanics.register(SummonFromCandidates, summon_from_candidates)
    mechanics.register(SummonFromPool, summon_from_pool)
    from .discovery import register
    register(mechanics)
    from .pool_offers import register as register_offers
    register_offers(mechanics)
