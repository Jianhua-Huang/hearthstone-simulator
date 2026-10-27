"""Versioned generation inventories, pure eligibility and deterministic sampling.

Inventories describe rule eligibility independently of executable card coverage.
Generation rules and declared pool/query exclusions define eligibility, never
absence from Registry.cards. These are trusted host definitions, not player input.
"""
from .card_creation import (CardSpellRepeatGrant, CreatedMinionGrant, CreatedMinionStats, DiscoveryMinionGift,
                            validate_declaration, validate_minion_grant, validate_minion_stats)
from dataclasses import dataclass, replace

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
    attack: int | None = None

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
        if self.attack is not None:
            integer(self.attack, 'printed minion attack', 0)
            if self.kind != CardType.MINION:
                raise ValueError('Printed minion attack requires a minion pool card')
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
                   card.battlecry is not None, card.deathrattle is not None, card.choose_one is not None,
                   card.attack if card.kind == CardType.MINION else None)

    def filter_signature(self):
        m = self.metadata
        return (self.kind, self.cost, m.collectible, frozenset(m.classes), m.rarity,
                None if m.tribes is None else frozenset(m.tribes), self.spell_school, frozenset(self.keywords),
                None if m.factions is None else frozenset(m.factions), self.battlecry,
                None if m.subtypes is None else frozenset(m.subtypes), self.deathrattle, self.choose_one,
                m.runes, self.attack)


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
    runes_any: tuple[str, ...] = ()
    attack_parity: str | None = None
    card_ids: tuple[str, ...] = ()
    attack_equals: int | None = None
    keywords_none: tuple[Keyword, ...] = ()

    def __post_init__(self):
        if self.attack_equals is not None:
            integer(self.attack_equals, 'exact printed minion attack', 0)
        if self.attack_parity is not None and (type(self.attack_parity) is not str or
                                              self.attack_parity not in ('odd', 'even')):
            raise ValueError('Printed minion attack parity requires odd, even or None')
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
            if self.ability.ability != 'battlecry':
                raise ValueError('Pool structural ability filter supports Battlecry; printed Outcast uses keywords_all')
        for field, kind in (('kinds', CardType), ('classes', CardClass), ('rarities', Rarity),
                            ('spell_schools', SpellSchool), ('keywords_all', Keyword), ('keywords_none', Keyword)):
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
        ids(self.card_ids, 'query identities', unique=True)
        ids(self.runes_any, 'printed rune filters', unique=True)
        if not set(self.runes_any) <= {'blood', 'frost', 'unholy'}:
            raise ValueError('Printed rune filters require blood, frost or unholy')


def validate_pools(registry):
    """Missing executable definitions are allowed; contradictory metadata is not."""
    for row in registry.pool_cards.values():
        row.__post_init__()
        if row.card_id in registry.cards:
            actual = PoolCard.from_definition(registry.card(row.card_id), identity=row.identity)
            # An independent inventory may not yet attest this new scalar.
            # Keep unknown unknown; resolve_candidates must never borrow the
            # executable definition's value to decide eligibility.
            if row.attack is None:actual = replace(actual, attack=None)
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
                     printed_deathrattle=None, printed_choose_one=None, printed_attack=None):
    """Conjoin common facts and a flat OR; unknown is neither true nor false."""
    if type(query) is not PoolQuery:
        raise ValueError('Expected PoolQuery')
    query.__post_init__()
    if query.card_ids and card_id not in query.card_ids:
        return False
    missing = []
    if query.kinds and kind not in query.kinds:
        return False
    if (query.attack_parity is not None or query.attack_equals is not None) and kind != CardType.MINION:
        return False
    if query.subtypes_any and kind != CardType.MINION:
        return False
    if ((query.min_cost is not None and cost < query.min_cost) or
            (query.max_cost is not None and cost > query.max_cost)):
        return False
    needs_meta = (query.collectible is not None or query.class_mode != 'any' or not query.include_neutral
                  or query.rarities or query.tribes_any or query.factions_any or query.subtypes_any or query.runes_any)
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
    if set(query.keywords_none).intersection(keywords):
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
        if query.runes_any:
            if meta.runes is None:
                if meta.classes is not None and CardClass.DEATH_KNIGHT not in meta.classes:
                    return False
                missing.append(f'Unknown candidate printed rune requirements: {card_id}')
            elif not any(getattr(meta.runes, rune) > 0 for rune in query.runes_any):
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
    if query.attack_parity is not None:
        if printed_attack is None:
            missing.append(f'Unknown candidate printed minion attack: {card_id}')
        else:
            integer(printed_attack, 'printed minion attack', 0)
            if printed_attack % 2 != (1 if query.attack_parity == 'odd' else 0):
                return False
    if query.attack_equals is not None:
        if printed_attack is None:
            missing.append(f'Unknown candidate printed minion attack: {card_id}')
        else:
            integer(printed_attack, 'printed minion attack', 0)
            if printed_attack != query.attack_equals:
                return False
    if query.any_of:
        unknown_alternatives = []
        for clause in query.any_of:
            try:
                if matches_metadata(clause, card_id=card_id, kind=kind, cost=cost, meta=meta,
                        spell_school=spell_school, keywords=keywords, current_class=current_class,
                        printed_battlecry=printed_battlecry, current_battlecry=current_battlecry,
                        printed_deathrattle=printed_deathrattle, printed_choose_one=printed_choose_one,
                        printed_attack=printed_attack):
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
    from .generation_scopes import require_scope
    require_scope(registry,pool,query,current_class=current_class,source_card_id=source_card_id,
                  policy=policy,exclude_source_by_rule=exclude_source_by_rule)
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
        # 26.0.4 ordinary generation rule, independent of executable coverage.
        # Named and physical delivery never use this random-candidate query.
        if meta.runes is not None and meta.runes.total == 3:
            continue
        # Fabled roots and attached cards are excluded by independent declarations,
        # including unimplemented roots. Named delivery and physical cards bypass this query.
        if row.card_id in registry.fabled_generation_exclusions or row.generation_identity in registry.fabled_generation_exclusions:
            continue
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
                printed_deathrattle=row.deathrattle, printed_choose_one=row.choose_one,
                printed_attack=row.attack):
            continue
        from .starting_generation import eligible as starting_eligible
        if not starting_eligible(registry, context, player_id, row.card_id, row.keywords):
            continue
        if CardClass.DEATH_KNIGHT in meta.classes and meta.runes is None:
            raise UnknownCardFactError('Ordinary Death Knight generation requires known printed Runes: '+row.card_id)
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
    set_summoned_stats: SummonStats | None = None
    copy_selected_to_hand: bool = False
    shuffle_unselected_into_deck: bool = False
    keep_all_corpse_cost: int | None = None
    summon_copy_corpse_cost: int | None = None
    paired_choose_one: bool = False
    refresh_card_id: str | None = None
    memory_target: object | None = None
    excess_discount: bool = False
    spell_weapon_card_id: str | None = None
    summon_copies: int = 1
    entry_keywords: tuple[Keyword, ...] = ()
    repeat_until_seen: bool = False

    def __post_init__(self):
        from .discovery_profiles import validate_spec as validate_finite_discovery
        validate_finite_discovery(self)
        if self.spell_weapon_card_id is not None:
            from .spell_weapons import validate_spec
            validate_spec(self)
        if type(self.excess_discount) is not bool:raise ValueError('Excess discovery discount requires an explicit boolean')
        if self.excess_discount:
            from .discovery_discounts import validate_spec
            validate_spec(self)
        if self.refresh_card_id is not None:
            name(self.refresh_card_id,'discovery refresh control')
            if (self.source_id is None or self.destination!='hand' or self.count!=3 or self.discoveries!=1 or
                    self.delivery!='after_each' or not self.replacement or self.paired_choose_one or
                    type(self.query)is not PoolQuery or self.query.kinds!=(CardType.SPELL,) or self.query.collectible is not True or
                    any(x is not None for x in (self.cost,self.expires_turn,self.spell_repeat,self.cause,self.gift_pool,
                        self.summon_copy_stats,self.minion_grant,self.temporary_until_turn,self.set_summoned_stats,
                        self.keep_all_corpse_cost,self.summon_copy_corpse_cost)) or
                    any((self.heal_hero_by_printed_cost,self.freeze_summoned,self.gift_copy_to_hand,
                        self.copy_selected_to_hand,self.shuffle_unselected_into_deck))):
                raise ValueError('Risk refresh requires one ordinary source-bound spell discovery')
        if type(self.paired_choose_one)is not bool:raise ValueError('Paired Choose One discovery requires a boolean')
        if self.paired_choose_one and (
                self.source_id is None or self.destination!='hand' or self.count!=3 or self.discoveries!=1 or
                self.delivery!='after_each' or not self.replacement or self.position!='random' or
                type(self.query)is not PoolQuery or self.query.choose_one is not True or self.query.collectible is not True or
                any(x is not None for x in (self.cost,self.expires_turn,self.spell_repeat,self.cause,self.gift_pool,
                    self.summon_copy_stats,self.minion_grant,self.temporary_until_turn,self.set_summoned_stats,
                    self.keep_all_corpse_cost,self.summon_copy_corpse_cost)) or
                any((self.heal_hero_by_printed_cost,self.freeze_summoned,self.gift_copy_to_hand,
                    self.copy_selected_to_hand,self.shuffle_unselected_into_deck))):
            raise ValueError('Paired Choose One requires one plain source-bound hand discovery')
        if self.summon_copy_corpse_cost is not None:
            integer(self.summon_copy_corpse_cost, 'discovered copy corpse cost', 1)
            if (self.destination != 'hand' or self.cause is None or self.source_id is None or
                    self.count != 3 or self.discoveries != 1 or self.delivery != 'after_each' or not self.replacement or
                    type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                    self.query.collectible is not True or self.cost is not None or self.expires_turn is not None or
                    self.spell_repeat is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                    self.freeze_summoned or self.summon_copy_stats is not None or self.minion_grant is not None or
                    self.temporary_until_turn is not None or self.gift_copy_to_hand or self.set_summoned_stats is not None or
                    self.copy_selected_to_hand or self.shuffle_unselected_into_deck or self.keep_all_corpse_cost is not None):
                raise ValueError('Corpse-paid copy requires one plain attributed hand-minion discovery')
        if self.keep_all_corpse_cost is not None:
            integer(self.keep_all_corpse_cost, 'keep original discovery corpse cost', 1)
            if (self.source_id is None or self.destination != 'hand' or self.count != 3 or
                    self.discoveries != 1 or self.delivery != 'after_each' or not self.replacement or
                    self.position != 'random' or type(self.query) is not PoolQuery or
                    self.query.kinds != (CardType.MINION,) or self.query.collectible is not True or
                    self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                    self.cause is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                    self.freeze_summoned or self.summon_copy_stats is not None or self.minion_grant is not None or
                    self.temporary_until_turn is not None or self.gift_copy_to_hand or
                    self.set_summoned_stats is not None or self.copy_selected_to_hand or self.shuffle_unselected_into_deck):
                raise ValueError('Corpse-paid keep requires one source-bound plain three-option minion hand discovery')
        if type(self.shuffle_unselected_into_deck) is not bool:
            raise ValueError('Unselected discovery shuffle requires an explicit boolean')
        if self.shuffle_unselected_into_deck and (
                self.destination != 'hand' or self.source_id is None or self.count != 3 or self.discoveries != 1 or
                self.delivery != 'after_each' or not self.replacement or type(self.query) is not PoolQuery or
                self.query.kinds != (CardType.MINION,) or self.query.collectible is not True or
                not (self.gift_pool is None and self.query.rarities == (Rarity.LEGENDARY,) or
                     self.gift_pool is not None and self.query == PoolQuery(kinds=(CardType.MINION,),
                         min_cost=5, collectible=True, class_mode='current', tribes_any=('demon',))) or
                self.cost is not None or self.expires_turn is not None or
                self.spell_repeat is not None or self.cause is not None or
                self.heal_hero_by_printed_cost or self.freeze_summoned or self.summon_copy_stats is not None or
                self.minion_grant is not None or self.temporary_until_turn is not None or self.gift_copy_to_hand or
                self.set_summoned_stats is not None or self.copy_selected_to_hand):
            raise ValueError('Unselected shuffle requires one plain Legendary or paired high-cost Demon discovery')
        if type(self.copy_selected_to_hand) is not bool:
            raise ValueError('Selected discovery copy requires an explicit boolean')
        if self.copy_selected_to_hand and (
                self.destination != 'board' or self.cause is None or self.source_id is None or
                self.count != 3 or self.discoveries != 1 or self.delivery != 'after_each' or not self.replacement or
                type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                self.query.collectible is not True or self.cost is not None or self.expires_turn is not None or
                self.spell_repeat is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                self.freeze_summoned or self.summon_copy_stats is not None or self.minion_grant is not None or
                self.temporary_until_turn is not None or self.gift_copy_to_hand or self.set_summoned_stats is not None):
            raise ValueError('Selected copy requires one plain attributed board-minion discovery')
        if self.set_summoned_stats is not None:
            if type(self.set_summoned_stats) is not SummonStats:
                raise ValueError('Discovered summon stat setting requires typed stats')
            self.set_summoned_stats.__post_init__()
            if (self.set_summoned_stats.attack is None or self.set_summoned_stats.health is None or
                    self.destination != 'board' or self.cause is None or self.source_id is None or
                    self.count != 3 or self.discoveries != 1 or self.delivery != 'after_each' or not self.replacement or
                    type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                    self.query.collectible is not True or self.cost is not None or self.expires_turn is not None or
                    self.spell_repeat is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                    self.freeze_summoned or self.summon_copy_stats is not None or self.minion_grant is not None or
                    self.temporary_until_turn is not None or self.gift_copy_to_hand):
                raise ValueError('Discovered stat setting requires one plain attributed board-minion discovery')
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
            ordinary = (grant.attack >= 0 and grant.health >= 0 and not grant.keywords and
                        grant.reborn_policy is None and grant.identity is None and grant.special is None)
            prepared = grant == CreatedMinionGrant(special='prepare')
            after_play = grant.special=='after_play' and self.destination=='hand'
            hand = self.destination == 'hand' and self.discoveries == 1
            bottom = (ordinary and self.destination == 'deck' and self.position == 'bottom'
                      and self.discoveries == 2)
            if (not (ordinary or prepared or after_play) or
                    self.source_id is None or not (hand or bottom) or self.count!=3 or
                    self.delivery!='after_each' or not self.replacement or type(self.query)is not PoolQuery or
                    self.query.kinds!=(CardType.MINION,)or self.query.collectible is not True or
                    self.cost is not None or self.expires_turn is not None or self.spell_repeat is not None or
                    self.cause is not None or self.gift_pool is not None or self.heal_hero_by_printed_cost or
                    self.freeze_summoned or self.summon_copy_stats is not None):
                raise ValueError('Discovery grant requires one hand recipe or two plain positive-stat bottom-deck minions')
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
            if type(self.cause)is not SummonCause or (self.destination!='board'and self.summon_copy_stats is None and self.summon_copy_corpse_cost is None):raise ValueError('Typed summon cause requires board discovery or selected hand-copy declaration')
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
    entry_grant: CreatedMinionGrant | None = None
    minion_grant: CreatedMinionGrant | None = None

    def __post_init__(self):
        from .card_creation import validate_combined_shatter, validate_pool_entry_grant
        validate_minion_grant(self.minion_grant)
        if self.minion_grant is not None and (
                self.minion_grant not in (CreatedMinionGrant(special='hand_turn_discount'), CreatedMinionGrant(special='other_play_lock')) or
                self.source_id is None or self.destination != 'hand' or self.count != 1 or not self.replacement or
                type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                self.query.collectible is not True or self.minion_stats is not None or self.entry_grant is not None or
                self.spell_repeat is not None or self.combined_shatter or self.temporary_until_turn is not None or
                self.cost is not None or self.expires_turn is not None or self.cause is not None or
                self.shuffle_actor_id is not None or self.producer_profile_id is not None or self.board_position is not None):
            raise ValueError('Generated hand grant requires one plain source-bound hand minion')
        validate_combined_shatter(self.combined_shatter)
        validate_minion_stats(self.minion_stats)
        validate_pool_entry_grant(self.entry_grant)
        if self.entry_grant is not None and (
                type(self.cause) is not SummonCause or self.destination != 'board' or
                self.source_id != self.cause.source.entity_id or self.player_id != self.cause.player_id or
                type(self.query) is not PoolQuery or self.query.kinds != (CardType.MINION,) or
                self.query.collectible is not True or self.minion_stats is not None or
                self.spell_repeat is not None or self.combined_shatter or self.temporary_until_turn is not None or
                self.cost is not None or self.expires_turn is not None or self.shuffle_actor_id is not None):
            raise ValueError('Pool entry grant requires its original source-bound plain board minion batch')
        if self.shuffle_actor_id is not None:
            _player(self.shuffle_actor_id)
            if self.destination != 'deck' or self.position != 'random' or self.source_id is None:
                raise ValueError('Generated shuffle requires its original actor and random deck delivery')
            if self.minion_stats is None and (
                    type(self.query) is not PoolQuery or self.query.kinds != (CardType.SPELL,) or
                    self.query.collectible is not True or not self.replacement or self.cost is not None or
                    self.expires_turn is not None or self.spell_repeat is not None or self.cause is not None or
                    self.producer_profile_id is not None or self.combined_shatter or
                    self.temporary_until_turn is not None or self.board_position is not None):
                raise ValueError('Generated plain shuffle requires a source-bound collectible spell recipe')
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


@dataclass(frozen=True)
class FillHandFromPool(Effect):
    """Capture effective free hand slots once, then delegate one ordinary batch."""
    request: GenerateFromPool

    def __post_init__(self):
        if type(self.request) is not GenerateFromPool:
            raise ValueError('Hand fill requires its typed generation request')
        q = self.request
        q.__post_init__()
        temporary_spell = (q.query.kinds == (CardType.SPELL,) and q.temporary_until_turn is not None
                           and q.cost is None and q.expires_turn is None)
        permanent_spell = (q.query.kinds == (CardType.SPELL,) and q.temporary_until_turn is None
            and q.cost is None and q.expires_turn is None and q.spell_repeat is None
            and getattr(q, 'minion_grant', None) is None)
        turn_zero_spell = (q.query.kinds == (CardType.SPELL,) and q.cost == CostSpec(set_to=0) and
            q.expires_turn is not None and q.temporary_until_turn is None and q.spell_repeat is None and
            getattr(q,'minion_grant',None) is None)
        permanent_fire_one = (q.query == PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FIRE,)) and
            q.cost == CostSpec(set_to=1) and q.expires_turn is None and q.temporary_until_turn is None and q.spell_repeat is None and
            getattr(q,'minion_grant',None) is None)
        if (q.count != 1 or q.source_id is None or q.destination != 'hand' or not q.replacement or
                (q.query.kinds != (CardType.MINION,) and not (temporary_spell or permanent_spell or turn_zero_spell or permanent_fire_one)) or q.query.collectible is not True or
                (not temporary_spell and (q.spell_repeat is not None or q.temporary_until_turn is not None)) or
                q.cause is not None or q.producer_profile_id is not None or
                q.combined_shatter or q.board_position is not None or
                q.minion_stats is not None or q.shuffle_actor_id is not None):
            raise ValueError('Hand fill requires a reviewed source-bound minion or spell hand specification')


def validate_delivery(effect):
    if type(effect.replacement) is not bool or effect.destination not in ('hand', 'board', 'deck','hand_or_opponent_top','memory'):
        raise ValueError('Invalid generation replacement or destination')
    if effect.destination == 'memory' or getattr(effect, 'memory_target', None) is not None:
        from .discovery_memory import validate_spec
        validate_spec(effect)
    if effect.destination=='hand_or_opponent_top':
        from .discovery_destinations import validate_spec
        validate_spec(effect)
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
        temporary_spell = (type(effect) is GenerateFromPool and effect.query.kinds == (CardType.SPELL,))
        if (effect.destination!='hand' or effect.source_id is None or not effect.replacement or
                type(effect.query)is not PoolQuery or (effect.query.kinds!=(CardType.MINION,) and not temporary_spell) or
                effect.query.collectible is not True or effect.cost is not None or
                effect.expires_turn is not None or (effect.spell_repeat is not None and not temporary_spell) or effect.cause is not None or
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
    from .generation_scopes import accepted_source_card
    source_card_id = accepted_source_card(r,effect,source_card_id)
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
    grant=getattr(effect,'minion_grant',None)
    if grant is not None and grant.special=='after_play':r.registry.behavior(grant.identity)
    if getattr(effect,'paired_choose_one',False):
        from .discovery import combined_creation_selection
        for member in candidates:combined_creation_selection(r.registry.card(member.card_id))
    if getattr(effect,'refresh_card_id',None) is not None:
        control=r.registry.card(effect.refresh_card_id)
        if control.kind!=CardType.SPELL or not control.choice_only:
            raise ResolutionError('Refresh control requires its registered option-only spell face')
    return candidates


def discover_from_pool(r, effect):
    from .discovery import start
    return start(r, effect)


def fill_hand_from_pool(r, effect):
    from dataclasses import replace
    from .hand_capacity import hand_capacity
    effect.__post_init__()
    if (effect.request.query.kinds==(CardType.SPELL,) and effect.request.cost == CostSpec(set_to=0) and
            effect.request.expires_turn!=r.state.turn):
        raise ValueError('Zero-cost spell fill requires the actual accepting turn deadline')
    player = r.player(effect.request.player_id)
    count = max(0, hand_capacity(player, r.rules) - len(player.hand))
    if not count:
        rows = generation_candidates(r, effect.request)
        from .costs import validate_creation_cost
        validate_creation_cost(r.state, effect.request, (r.registry.card(m.card_id) for m in rows))
        return ()
    return generate_from_pool(r, replace(effect.request, count=count))


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
                     source_id=effect.source_id,spell_repeat=effect.spell_repeat)for card_id in selected)
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


def validate_pool_entry_keywords(value):
    order=(Keyword.TAUNT,Keyword.LIFESTEAL,Keyword.RUSH)
    if (type(value)is not tuple or any(type(k)is not Keyword or k not in order for k in value)or
            value!=tuple(k for k in order if k in value)):
        raise ValueError('Pool entry keywords require an ordered Taunt/Lifesteal/Rush boon recipe')


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
    entry_dormant_turns: int | None = None
    on_summon: str | None = None
    followup_policy: str = 'live_friendly'

    def __post_init__(self):
        if type(self.followup_policy) is not str or self.followup_policy not in ('live_friendly','original_delivery'):
            raise ValueError('Unknown original pool delivery followup policy')
        if self.followup_policy == 'original_delivery' and self.on_summon is None:
            raise ValueError('Original delivery policy requires its explicit attributed callback')
        if self.on_summon is not None:
            from .effects import _behavior
            _behavior(self.on_summon)
            if self.cause is None or self.source_id is None or self.entry_keywords or self.entry_dormant_turns is not None:
                raise ValueError('Pool followup requires one source-bound plain attributed entry')
        if self.entry_dormant_turns is not None:
            integer(self.entry_dormant_turns,'pool pre-entry dormant turns',1)
            if self.cause is None or self.source_id is None or self.entry_keywords:
                raise ValueError('Dormant pool entry requires a source-bound plain summon material')
        if self.position is not None:integer(self.position,'pool summon board position',0)
        validate_pool_entry_keywords(self.entry_keywords)
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


def summon_from_pool(r,effect,*,producer_link=None):
    from .summon_quantities import reject_ambiguous
    if producer_link is not None:
        from .mana_worth_summons import ManaWorthEntryLink
        if type(producer_link) is not ManaWorthEntryLink or effect.cause is None:
            raise ValueError('Budget pool entry requires its typed original attribution and link')
    if effect.cause is None:reject_ambiguous(r)
    effect.__post_init__()
    rows=generation_candidates(r,effect.request())
    # Validate all eligible content even if there is no board space.
    if not rows and effect.empty=='error':raise ResolutionError('Empty summon pool')
    if effect.cause is not None:
        from .summon_quantities import SummonByCard,SummonEntryMaterial,accept
        from .pool_summons import PoolSummonBasis, entry_material
        basis=PoolSummonBasis.capture(r,effect.request(),rows,entry_keywords=effect.entry_keywords,
            entry_dormant_turns=effect.entry_dormant_turns,on_summon=effect.on_summon,
            followup_policy=effect.followup_policy)
        return accept(r,SummonByCard(effect.player_id,tuple(entry_material(basis,m.card_id)for m in rows),effect.cause,
            'weighted',position=effect.position,weights=tuple(m.weight for m in rows),pool_basis=basis,producer_link=producer_link))
    if len(r.player(effect.player_id).board)>=r.rules.max_board:
        r.emit('random_choice_skipped',source_id=effect.source_id,reason='board_full')
        return ()
    if not rows:return ()
    card_id=sample_candidates(r.game._rng,rows,1,replacement=True)[0]
    return (Summon(effect.player_id,card_id,position=effect.position),)


@dataclass(frozen=True)
class FillBoardFromPool(Effect):
    """Capture actual free slots once, then use the attributed pool batch."""
    player_id: int
    pool_id: str
    query: PoolQuery
    source_id: int
    cause: SummonCause
    policy: GenerationPolicy = GenerationPolicy()

    def __post_init__(self):
        _player(self.player_id); integer(self.source_id,'fill source',1)
        if type(self.cause)is not SummonCause:
            raise ValueError('Pool fill requires original card attribution')
        self.cause.__post_init__()
        minion = self.cause.source.kind==CardType.MINION and self.cause.origin=='card_effect'
        spell = (self.cause.source.kind==CardType.SPELL and self.cause.origin=='spell_cast' and
            self.cause.cast_card_id==self.cause.source.card_id)
        if self.cause.source.entity_id!=self.source_id or not(minion or spell):
            raise ValueError('Pool fill requires its original minion effect or actual SPELL cast')
        if (type(self.query)is not PoolQuery or self.query.kinds!=(CardType.MINION,)
                or self.query.collectible is not True):
            raise ValueError('Pool fill requires a complete collectible minion query')
        self.request().__post_init__()

    def request(self):
        return GenerateFromPool(self.player_id,self.pool_id,self.query,source_id=self.source_id,
            destination='board',cause=self.cause,policy=self.policy)


def fill_board_from_pool(r,effect):
    effect.__post_init__()
    request=effect.request()
    candidates=generation_candidates(r,request)
    from .pool_summons import accept_batch
    return accept_batch(r,request,candidates,fill_board=True)


def validate_summon_boundary(game):
    if game._frame is None:return
    def check(work):
        if type(work) not in(SummonFromPool,FillBoardFromPool):return
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
    mechanics.register(FillHandFromPool, fill_hand_from_pool)
    mechanics.register(GenerateFromCandidates, generate_from_candidates)
    mechanics.register(SummonFromCandidates, summon_from_candidates)
    mechanics.register(SummonFromPool, summon_from_pool)
    mechanics.register(FillBoardFromPool, fill_board_from_pool)
    from .generated_spell_healing import register as register_generated_spell_healing
    register_generated_spell_healing(mechanics)
    from .playable_spell_generation import register as register_playable_spells
    register_playable_spells(mechanics)
    from .discovery import register
    register(mechanics)
    from .pool_offers import register as register_offers
    register_offers(mechanics)
