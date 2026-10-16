"""State and definition types, independent of the installed client and its catalog.

Definitions describe rules; entities describe one match. Health is derived from
maximum health and accumulated damage. Stat effects define explicit damage-reset
and removal policies. A dead entity may remain in a zone during resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import Registry


class CardType(StrEnum):
    HERO = "hero"
    MINION = "minion"
    SPELL = "spell"
    WEAPON = "weapon"
    HERO_POWER = "hero_power"
    LOCATION = "location"


class CardClass(StrEnum):
    NEUTRAL = 'neutral'
    DREAM = 'dream'
    DEATH_KNIGHT = 'death_knight'
    DEMON_HUNTER = 'demon_hunter'
    DRUID = 'druid'
    HUNTER = 'hunter'
    MAGE = 'mage'
    PALADIN = 'paladin'
    PRIEST = 'priest'
    ROGUE = 'rogue'
    SHAMAN = 'shaman'
    WARLOCK = 'warlock'
    WARRIOR = 'warrior'


PLAYABLE_CARD_CLASSES = frozenset(c for c in CardClass if c not in (CardClass.NEUTRAL,CardClass.DREAM))


class Rarity(StrEnum):
    NONE = 'none'
    FREE = 'free'
    COMMON = 'common'
    RARE = 'rare'
    EPIC = 'epic'
    LEGENDARY = 'legendary'


@dataclass(frozen=True)
class Runes:
    blood: int = 0
    frost: int = 0
    unholy: int = 0

    def __post_init__(self):
        for name in ('blood', 'frost', 'unholy'):
            _int(getattr(self, name), name, 0)

    @property
    def total(self):
        return self.blood + self.frost + self.unholy


@dataclass(frozen=True)
class CardMetadata:
    collectible: bool
    classes: tuple[CardClass, ...]
    rarity: Rarity | None
    deck_identity: str | None = None
    max_copies: int | None = None
    runes: Runes | None = None
    tribes: tuple[str, ...] | None = None
    factions: tuple[str, ...] | None = None
    subtypes: tuple[str, ...] | None = None

    def __post_init__(self):
        _bool(self.collectible, 'collectible')
        if (not isinstance(self.classes, tuple) or not self.classes or
                any(not isinstance(c, CardClass) for c in self.classes) or len(set(self.classes)) != len(self.classes)):
            raise ValueError('Card classes must be a nonempty unique tuple of CardClass')
        if CardClass.NEUTRAL in self.classes and len(self.classes) != 1:
            raise ValueError('Neutral cannot be combined with other classes')
        if self.rarity is not None and not isinstance(self.rarity, Rarity):
            raise ValueError('Invalid rarity')
        if self.deck_identity is not None:
            _name(self.deck_identity, 'deck_identity')
        if self.max_copies is not None:
            _int(self.max_copies, 'max_copies', 1)
        if self.runes is not None:
            if not isinstance(self.runes, Runes):
                raise ValueError('Invalid rune requirements')
            self.runes.__post_init__()
            if self.runes.total and CardClass.DEATH_KNIGHT not in self.classes:
                raise ValueError('Rune requirements require Death Knight class')
        if self.tribes is not None:
            if not isinstance(self.tribes, tuple) or len(set(self.tribes)) != len(self.tribes):
                raise ValueError('Tribes must be a unique tuple or unknown (None)')
            for tribe in self.tribes:
                _name(tribe, 'tribe')
        if self.factions is not None:
            if not isinstance(self.factions, tuple) or len(set(self.factions)) != len(self.factions):
                raise ValueError('Factions must be a unique tuple or unknown (None)')
            for faction in self.factions:
                _name(faction, 'faction')
        if self.subtypes is not None:
            validate_minion_subtypes(self.subtypes)


def validate_minion_subtypes(values):
    """Reviewed printed subtypes have no ordinary all-tribe wildcard."""
    if (type(values) is not tuple or
            any(type(value) is not str or value not in ('imp', 'whelp') for value in values) or
            len(set(values)) != len(values)):
        raise ValueError('Minion subtypes require unique imp/whelp strings in a tuple')


@dataclass(frozen=True)
class OpeningHook:
    phase: str
    behavior_id: str

    def __post_init__(self):
        if self.phase not in ('before_deal', 'after_mulligan'):
            raise ValueError('Unsupported opening hook phase')
        _name(self.behavior_id, 'opening behavior_id')


class Zone(StrEnum):
    QUEST = "quests"
    SECRET = "secrets"
    HERO = "hero"
    DECK = "deck"
    HAND = "hand"
    BOARD = "board"
    GRAVEYARD = "graveyard"
    SETASIDE = "setaside"
    PLAY = "pending_plays"
    WEAPON = "weapon"
    HERO_POWER = "hero_power"


class Keyword(StrEnum):
    QUEST = "quest"
    QUESTLINE = "questline"
    SIDEQUEST = "sidequest"
    SECRET = "secret"
    COMBO = "combo"
    OUTCAST = "outcast"
    FINALE = "finale"
    MANATHIRST = "manathirst"
    QUICKDRAW = "quickdraw"
    MAGNETIC = "magnetic"
    COLOSSAL = "colossal"
    HERALD = "herald"
    INVOKE = "invoke"
    SHATTER = "shatter"
    SHATTERED = "shattered"
    ECHO = "echo"
    REWIND = "rewind"
    CASTS_WHEN_DRAWN = "casts_when_drawn"
    TWINSPELL = "twinspell"
    MINIATURIZE = "miniaturize"
    GIGANTIFY = "gigantify"
    MINI = "mini"
    GIGANTIC = "gigantic"
    SPELLBURST = "spellburst"
    FRENZY = "frenzy"
    CORRUPT = "corrupt"
    CORRUPTED = "corrupted"
    INFUSE = "infuse"
    INFUSED = "infused"
    TAUNT = "taunt"
    DIVINE_SHIELD = "divine_shield"
    CHARGE = "charge"
    RUSH = "rush"
    WINDFURY = "windfury"
    MEGA_WINDFURY = "mega_windfury"
    POISONOUS = "poisonous"
    IMMUNE = "immune"
    IMMUNE_WHILE_ATTACKING = "immune_while_attacking"
    CANT_BE_FROZEN = "cant_be_frozen"
    DEATHRATTLE_SUPPRESSOR = "deathrattle_suppressor"
    HERO_POWER_SUPPRESSOR = "hero_power_suppressor"
    REBORN = "reborn"
    LIFESTEAL = "lifesteal"
    STEALTH = "stealth"
    ELUSIVE = "elusive"
    STARSHIP_PIECE = "starship_piece"
    TITAN = "titan"
    OLD_GOD = "old_god"


class DamageKind(StrEnum):
    EFFECT = "effect"
    SPELL = "spell"
    COMBAT = "combat"
    HERO_POWER = "hero_power"
    FATIGUE = "fatigue"
    MINION_ABILITY = "minion_ability"


class HealingKind(StrEnum):
    EFFECT = 'effect'
    SPELL = 'spell'
    HERO_POWER = 'hero_power'


def validate_reborn_policy(value, keyword):
    if value is not None and (type(value) is not str or value != 'full_health_enchantments' or
                             type(keyword) is not Keyword or keyword != Keyword.REBORN):
        raise ValueError('Only Reborn supports full_health_enchantments')


class SpellSchool(StrEnum):
    ARCANE = 'arcane'
    FIRE = 'fire'
    FROST = 'frost'
    NATURE = 'nature'
    HOLY = 'holy'
    SHADOW = 'shadow'
    FEL = 'fel'


class HealthFlow(StrEnum):
    DAMAGE = 'damage'
    HEALING = 'healing'


class HealthOp(StrEnum):
    ADD = 'add'
    SCALE = 'scale'
    SET = 'set'
    CAP = 'cap'
    FLOOR = 'floor'
    PREVENT = 'prevent'
    REDIRECT = 'redirect'
    CONVERT = 'convert'


class HealthLayer(StrEnum):
    SOURCE = 'source'
    TARGET = 'target'


@dataclass(frozen=True)
class HealthRule:
    """Serializable in-play packet rule; no hidden predicates or mutable closure."""
    flow: HealthFlow
    operation: HealthOp
    amount: int = 0
    denominator: int = 1
    layer: HealthLayer = HealthLayer.SOURCE
    source_relation: str = 'any'
    target_relation: str = 'any'
    target_kinds: tuple[CardType, ...] = (CardType.HERO, CardType.MINION)
    damage_kinds: tuple[DamageKind, ...] = ()
    healing_kinds: tuple[HealingKind, ...] = ()
    schools: tuple[SpellSchool, ...] = ()
    redirect_to: str | None = None

    def __post_init__(self):
        for field_name, enum in (('flow', HealthFlow), ('operation', HealthOp), ('layer', HealthLayer)):
            if not isinstance(getattr(self, field_name), enum):
                raise ValueError(f'Health rule {field_name} requires {enum.__name__}')
        _int(self.amount, 'health rule amount', None if self.operation == HealthOp.ADD else 0)
        _int(self.denominator, 'health rule denominator', 1)
        if self.operation != HealthOp.SCALE and self.denominator != 1:
            raise ValueError('Only scaling rules have a denominator')
        if self.operation in (HealthOp.PREVENT, HealthOp.REDIRECT, HealthOp.CONVERT) and self.amount != 0:
            raise ValueError('Routing, conversion and prevention have no numeric operand')
        if self.operation == HealthOp.FLOOR and (self.flow != HealthFlow.DAMAGE or
                self.layer != HealthLayer.TARGET or self.amount < 1):
            raise ValueError('Health FLOOR requires positive DAMAGE/TARGET operand')
        if self.source_relation not in ('any','friendly','enemy','self','friendly_elemental_minions','friendly_beast_minions') or self.target_relation not in ('any','friendly','enemy','self'):
            raise ValueError('Invalid health rule relation')
        if self.source_relation in ('friendly_elemental_minions','friendly_beast_minions'):
            operation,amount=((HealthOp.ADD,1)if self.source_relation=='friendly_elemental_minions'else(HealthOp.SCALE,2))
            if(self.flow!=HealthFlow.DAMAGE or self.layer!=HealthLayer.SOURCE or self.operation!=operation or self.amount!=amount
                    or self.denominator!=1 or self.target_relation!='any' or self.target_kinds!=(CardType.HERO,CardType.MINION)
                    or self.damage_kinds or self.healing_kinds or self.schools or self.redirect_to is not None):
                raise ValueError('Native tribal damage requires its complete ordinary source profile')
        for name, enum in (('target_kinds', CardType), ('damage_kinds', DamageKind),
                           ('healing_kinds', HealingKind), ('schools', SpellSchool)):
            items = getattr(self, name)
            if not isinstance(items, tuple) or any(not isinstance(v, enum) for v in items) or len(set(items)) != len(items):
                raise ValueError(f'Health rule {name} must be a unique enum tuple')
        if not self.target_kinds or set(self.target_kinds) - {CardType.HERO, CardType.MINION}:
            raise ValueError('Health rules target characters')
        if (self.flow == HealthFlow.DAMAGE and self.healing_kinds) or (self.flow == HealthFlow.HEALING and self.damage_kinds):
            raise ValueError('Packet kind filter must match rule flow')
        if self.operation == HealthOp.REDIRECT:
            if self.layer != HealthLayer.TARGET or self.redirect_to not in ('self', 'friendly_hero', 'enemy_hero'):
                raise ValueError('Redirection requires target layer and a supported destination')
        elif self.redirect_to is not None:
            raise ValueError('Only redirection rules have a destination')
        if self.operation == HealthOp.CONVERT and self.layer != HealthLayer.SOURCE:
            raise ValueError('Conversion occurs in the source layer')


class StatReference(StrEnum):
    """Read a target's settled visible value when an effect actually executes."""

    ATTACK = "attack"
    HEALTH = "health"
    MAX_HEALTH = "max_health"


class StatRelationOperand(StrEnum):
    SELF_CURRENT_HEALTH = "self_current_health"
    SELF_DAMAGED = "self_damaged"
    CONTROLLER_HAS_WEAPON = "controller_has_weapon"
    CONTROLLER_DISCARD_COUNT = "controller_discard_count"
    CONTROLLER_DECK_COUNT = "controller_deck_count"
    CONTROLLER_ARMOR = "controller_armor"
    OTHER_BATTLEFIELD_TRIBE_COUNT = "other_battlefield_tribe_count"
    CONTROLLER_OVERLOADED_MANA = "controller_overloaded_mana"
    CONTROLLER_HAS_SPELL_DAMAGE = "controller_has_spell_damage"
    CONTROLLER_OPPONENT_TURN = "controller_opponent_turn"


class StatRelationLayer(StrEnum):
    FINAL_ATTACK = "final_attack"
    CONDITIONAL_ATTACK = "conditional_attack"
    CONDITIONAL_HEALTH = "conditional_health"


@dataclass(frozen=True)
class StatRelationSpec:
    """Closed, self-only relation; broader expression graphs are unsupported."""

    target: StatReference = StatReference.ATTACK
    operand: StatRelationOperand = StatRelationOperand.SELF_CURRENT_HEALTH
    layer: StatRelationLayer = StatRelationLayer.FINAL_ATTACK
    amount: int = 0
    card_count: int | None = None
    comparison: str | None = None
    count_tribe: str | None = None

    def __post_init__(self):
        if (type(self.target) is not StatReference or self.target not in (StatReference.ATTACK, StatReference.HEALTH) or
                type(self.operand) is not StatRelationOperand or
                type(self.layer) is not StatRelationLayer or type(self.amount) is not int):
            raise ValueError('Unsupported continuous stat relation')
        if self.target == StatReference.HEALTH:
            if (self.operand != StatRelationOperand.CONTROLLER_DISCARD_COUNT or
                    self.layer != StatRelationLayer.CONDITIONAL_HEALTH or self.amount <= 0):
                raise ValueError('Conditional Health currently requires native positive discard count')
        elif self.layer == StatRelationLayer.CONDITIONAL_HEALTH:
            raise ValueError('Conditional Health layer requires a Health target')
        if self.operand != StatRelationOperand.CONTROLLER_DECK_COUNT and (
                self.card_count is not None or self.comparison is not None):
            raise ValueError('Only the current deck count relation carries a threshold/comparison')
        if self.operand != StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT and self.count_tribe is not None:
            raise ValueError('Only the other battlefield tribe relation carries a tribe')
        if self.operand == StatRelationOperand.SELF_CURRENT_HEALTH:
            if self.layer != StatRelationLayer.FINAL_ATTACK or self.amount != 0:
                raise ValueError('Self-health relation requires its final layer and zero amount')
        elif self.operand == StatRelationOperand.SELF_DAMAGED:
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Self-damaged relation requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_HAS_WEAPON:
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Weapon-presence relation requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_DISCARD_COUNT:
            expected = StatRelationLayer.CONDITIONAL_HEALTH if self.target == StatReference.HEALTH else StatRelationLayer.CONDITIONAL_ATTACK
            if self.layer != expected or self.amount <= 0:
                raise ValueError('Discard-count relation requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_DECK_COUNT:
            from .deck_conditions import DeckCountCondition
            DeckCountCondition(self.card_count, self.comparison)
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Deck-count relation requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_ARMOR:
            if self.layer != StatRelationLayer.FINAL_ATTACK or self.amount != 0:
                raise ValueError('Controller-armor weapon relation requires its final layer and zero amount')
        elif self.operand == StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT:
            _name(self.count_tribe, 'continuous battlefield count tribe')
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Other battlefield tribe count requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_OVERLOADED_MANA:
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Overload weapon Attack requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE:
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Spell Damage weapon Attack requires its conditional layer and positive amount')
        elif self.operand == StatRelationOperand.CONTROLLER_OPPONENT_TURN:
            if self.layer != StatRelationLayer.CONDITIONAL_ATTACK or self.amount <= 0:
                raise ValueError('Opponent-turn Attack requires its conditional layer and positive amount')
        else:
            raise ValueError('Unsupported continuous stat relation')


class PaymentType(StrEnum):
    MANA = 'mana'
    HEALTH = 'health'
    ARMOR = 'armor'
    CORPSES = 'corpses'


class Resource(StrEnum):
    CORPSES = 'corpses'


@dataclass(frozen=True)
class EquippedWeaponReference:
    """One physical equipped incarnation, including its original controller."""
    entity_id: int
    player_id: int
    card_id: str
    zone_epoch: int
    entered_order: int

    def __post_init__(self):
        _int(self.entity_id,'equipped weapon reference identity',1)
        if type(self.player_id) is not int or self.player_id not in (1,2):
            raise ValueError('Equipped weapon reference requires its original player')
        _name(self.card_id,'equipped weapon reference face')
        _int(self.zone_epoch,'equipped weapon reference epoch',0)
        _int(self.entered_order,'equipped weapon installation order',1)

    @classmethod
    def capture(cls,entity):
        if (type(entity) is not Entity or entity.kind!=CardType.WEAPON or entity.zone!=Zone.WEAPON
                or not entity.active or entity.durability<=0 or entity.doomed):
            raise ValueError('Reference capture requires a live equipped weapon')
        return cls(entity.id,entity.controller,entity.card_id,entity.zone_epoch,entity.entered_order)

    def payload(self):
        return tuple((name,getattr(self,name)) for name in ('entity_id','player_id','card_id','zone_epoch','entered_order'))


@dataclass(frozen=True)
class ArmorLossResult:
    """Immutable direct account delta, distinct from damage and payment."""
    player_id: int
    hero_id: int
    requested: int | None
    before: int
    after: int
    actual: int

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1,2):
            raise ValueError('Armor loss requires its actual player')
        _int(self.hero_id,'armor loss Hero',1)
        if self.requested is not None: _int(self.requested,'requested armor loss',0)
        for key in ('before','after','actual'): _int(getattr(self,key),'armor loss '+key,0)
        expected = self.before if self.requested is None else min(self.before,self.requested)
        if self.actual != expected or self.after != self.before-self.actual:
            raise ValueError('Armor loss changed its original account delta')

    def payload(self):
        return tuple((key,getattr(self,key)) for key in ('player_id','hero_id','requested','before','after','actual'))


@dataclass(frozen=True)
class ManaConsumptionRecord:
    """A direct non-cost debit, including its original source and account endpoints."""
    id: int
    player_id: int
    turn: int
    action: int
    requested: int | None
    actual: int
    mana_before: int
    mana_after: int
    max_mana: int
    overload_locked: int
    temporary_before: int
    temporary_after: int
    spent_before: int
    spent_after: int
    source_id: int | None
    source_card_id: str | None
    source_kind: CardType | None
    source_player_id: int | None
    cast_id: int | None

    def __post_init__(self):
        for key in ('id','turn'): _int(getattr(self,key),'mana consumption '+key,1)
        _int(self.action,'mana consumption action',0)
        if type(self.player_id) is not int or self.player_id not in (1,2):
            raise ValueError('Mana consumption requires its actual player')
        if self.requested is not None: _int(self.requested,'requested mana consumption',0)
        for key in ('actual','mana_before','mana_after','max_mana','overload_locked',
                'temporary_before','temporary_after','spent_before','spent_after'):
            _int(getattr(self,key),'mana consumption '+key,0)
        actual=self.mana_before if self.requested is None else min(self.mana_before,self.requested)
        temporary=min(self.temporary_before,actual)
        if (self.mana_before != max(0,self.max_mana-self.spent_before-self.overload_locked+self.temporary_before)
                or self.actual != actual or self.mana_after != self.mana_before-actual
                or self.temporary_after != self.temporary_before-temporary
                or self.spent_after != self.spent_before+actual-temporary
                or self.mana_after != max(0,self.max_mana-self.spent_after-self.overload_locked+self.temporary_after)):
            raise ValueError('Mana consumption changed its original account projection')
        if self.source_id is None:
            if any(x is not None for x in (self.source_card_id,self.source_kind,self.source_player_id,self.cast_id)):
                raise ValueError('System mana consumption invented a physical source')
        else:
            _int(self.source_id,'mana consumption source',1)
            _name(self.source_card_id,'mana consumption original source face')
            if type(self.source_kind) is not CardType or type(self.source_player_id) is not int or self.source_player_id not in (1,2):
                raise ValueError('Mana consumption requires its original source type and actor')
        if self.cast_id is not None:
            _int(self.cast_id,'mana consumption original cast',1)
            if self.source_kind != CardType.SPELL:
                raise ValueError('Only a Spell source can carry original cast attribution')

    def payload(self):
        from dataclasses import fields
        return tuple((f.name,(getattr(self,f.name).value if f.name=='source_kind' and self.source_kind is not None
            else getattr(self,f.name))) for f in fields(self))

    def mana_for(self,player_id):
        return self.actual if self.player_id==self.source_player_id==player_id and self.source_kind==CardType.SPELL else 0


@dataclass(frozen=True)
class CardAbilityCondition:
    """Structural card identity, independent of whether its effect can run now."""
    ability: str = 'battlecry'
    present: bool = True
    basis: str = 'current'

    def __post_init__(self):
        if type(self.ability) is not str or self.ability != 'battlecry':
            raise ValueError('Unsupported card ability condition')
        _bool(self.present, 'card ability presence')
        if type(self.basis) is not str or self.basis not in ('current', 'printed'):
            raise ValueError('Ability condition requires current or printed identity')


@dataclass(frozen=True)
class CostSpec:
    """One ordered cost operation, optionally changing its payment account."""
    delta: int = 0
    set_to: int | None = None
    minimum: int = 0
    card_types: tuple[CardType, ...] = (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO)
    payment: PaymentType | None = None

    # Empty means all IDs of the eligible kinds. A whitelist is content data,
    # never an inferred name match or a requirement to implement every family.
    card_ids: tuple[str, ...] = ()
    ability: CardAbilityCondition | None = None

    def __post_init__(self):
        if self.ability is not None:
            if type(self.ability) is not CardAbilityCondition:
                raise ValueError('Cost ability filter requires CardAbilityCondition')
            self.ability.__post_init__()
        _int(self.delta, 'cost delta')
        _int(self.minimum, 'cost minimum', 0)
        if self.set_to is not None:
            _int(self.set_to, 'cost set_to', 0)
            if self.delta:
                raise ValueError('Cannot add and set cost in one operation')
        if (not isinstance(self.card_types, tuple) or not self.card_types or
                any(not isinstance(k, CardType) for k in self.card_types) or
                len(set(self.card_types)) != len(self.card_types)):
            raise ValueError('Cost card_types must be a unique tuple of playable kinds')
        if self.payment is not None and not isinstance(self.payment, PaymentType):
            raise ValueError('Cost payment requires PaymentType')
        if (type(self.card_ids) is not tuple or
                any(type(i) is not str or not i.strip() for i in self.card_ids) or
                len(set(self.card_ids)) != len(self.card_ids)):
            raise ValueError('Cost card_ids must be a unique tuple of nonempty IDs')


@dataclass(frozen=True)
class CostAuraSpec:
    """A cost operation and its payer relation to the current aura controller."""
    cost: CostSpec
    relation: str = 'friendly'
    tribes_any: tuple[str, ...] = ()
    first_per_turn: bool = False
    every_nth_per_turn: int | None = None

    def __post_init__(self):
        if type(self.cost) is not CostSpec:
            raise ValueError('Cost aura requires a CostSpec operation')
        self.cost.__post_init__()
        if type(self.relation) is not str or self.relation not in ('friendly', 'enemy', 'any'):
            raise ValueError('Invalid cost aura payer relation')
        TribeChangeSpec('set', self.tribes_any).__post_init__()
        _bool(self.first_per_turn, 'first-per-turn cost aura')
        if self.every_nth_per_turn is not None:
            _int(self.every_nth_per_turn, 'periodic turn cost interval', 2)
            if (self.first_per_turn or self.relation != 'friendly' or
                    self.cost.card_types not in ((CardType.MINION,), (CardType.SPELL,)) or self.tribes_any or
                    self.cost.card_ids or self.cost.ability is not None or self.cost.payment is not None or
                    self.cost.minimum != 0 or not (self.cost.delta < 0 or self.cost.set_to is not None)):
                raise ValueError('Periodic turn auras require one independent friendly ordinary card type')
        if self.first_per_turn and (self.relation != 'friendly' or
                self.cost.card_types not in ((CardType.MINION,), (CardType.SPELL,)) or
                self.tribes_any or self.cost.card_ids or self.cost.ability is not None or
                self.cost.payment is not None or self.cost.minimum != 0 or
                not (self.cost.delta < 0 or self.cost.set_to is not None)):
            raise ValueError('First-per-turn auras require one friendly ordinary card type')
        if self.tribes_any and (self.relation != 'friendly' or
                self.cost.card_types != (CardType.MINION,) or self.cost.delta >= 0 or
                self.cost.set_to is not None or self.cost.minimum != 0 or
                self.cost.payment is not None or self.cost.card_ids or self.cost.ability is not None):
            raise ValueError('Tribal cost auras require a friendly minion reduction')


class CostScope(StrEnum):
    CARD = 'card'
    STARSHIP_LAUNCH = 'starship_launch'


def validate_cost_scope(scope, spec):
    if not isinstance(scope, CostScope):
        raise ValueError('Cost scope requires CostScope')
    if scope == CostScope.STARSHIP_LAUNCH and (
            spec.card_types != CostSpec().card_types or spec.card_ids or spec.ability is not None or spec.payment not in (None, PaymentType.MANA)):
        raise ValueError('Launch modifiers have no card type filter and use mana')


@dataclass(frozen=True)
class CostModifier:
    """Player-owned ongoing or next-N matching plays/uses modifier."""
    id: int
    spec: CostSpec
    source_id: int | None = None
    uses_remaining: int | None = None
    expires_turn: int | None = None
    scope: CostScope = CostScope.CARD
    tribes_any: tuple[str, ...] = ()
    combo_only: bool = False
    temporary_only: bool = False
    maximum_cost: int | None = None
    minion_keyword: Keyword | None = None
    minion_keyword_repetitions: int = 1

    def __post_init__(self):
        _int(self.id, 'cost modifier ID', 1)
        if type(self.minion_keyword_repetitions)is not int or self.minion_keyword_repetitions not in(1,2)or self.minion_keyword is None and self.minion_keyword_repetitions!=1:
            raise ValueError('Paid keyword repetitions require the actual finite Kindred Shield reward')
        if not isinstance(self.spec, CostSpec):
            raise ValueError('Cost modifier requires CostSpec')
        self.spec.__post_init__()
        validate_cost_scope(self.scope, self.spec)
        TribeChangeSpec('set',self.tribes_any).__post_init__()
        _bool(self.combo_only,'Combo-only cost');_bool(self.temporary_only,'Temporary-only cost')
        if sum((bool(self.tribes_any),self.combo_only,self.temporary_only))>1:
            raise ValueError('Player cost modifiers require one independent recipient selector')
        if (self.combo_only or self.temporary_only)and(self.scope!=CostScope.CARD or self.uses_remaining is None):
            raise ValueError('Qualified next-card prices require finite ordinary card uses')
        if self.maximum_cost is not None:
            _int(self.maximum_cost,'complete current cost threshold',0)
            if (not self.tribes_any or self.spec.payment!=PaymentType.HEALTH or self.spec.delta or
                    self.spec.set_to is not None or self.spec.minimum or self.uses_remaining is None):
                raise ValueError('Current price threshold requires a finite tribal payment-only Health modifier')
        if self.tribes_any and (self.scope != CostScope.CARD or self.spec.card_types != (CardType.MINION,)or
                not(self.spec.delta<0 and self.spec.payment is None or self.spec.set_to is not None and self.spec.payment is None or self.maximum_cost is not None)):
            raise ValueError('Tribal player prices require a minion reduction, set-price or qualified Health payment')
        if self.minion_keyword is not None and (
                self.minion_keyword is not Keyword.DIVINE_SHIELD or self.scope != CostScope.CARD or
                self.spec.card_types != (CardType.MINION,) or self.spec.delta >= 0 or
                self.spec.set_to is not None or self.spec.payment is not None or
                not self.tribes_any or self.uses_remaining != 1 or self.source_id is None):
            raise ValueError('Next-minion keyword requires one sourced tribal reduction and Divine Shield')
        for name in ('source_id', 'uses_remaining', 'expires_turn'):
            _optional_id(getattr(self, name), name)


@dataclass(frozen=True)
class CostUseReceipt:
    """A quote/use clock fact; never a claim about actual resource debit."""
    id: int
    player_id: int
    source_id: int
    source_card_id: str
    turn: int
    action: int
    origin: str
    amount: int
    payment: PaymentType
    modifier_ids: tuple[int, ...]
    player_modifiers: tuple[CostModifier, ...]
    consumable_ids: tuple[int, ...]
    current_deck: CurrentDeckCountMatch | None = None
    permanent_mana: PermanentManaMatch | None = None
    kindred_sources: tuple[PlayerEffect, ...] = ()

    def __post_init__(self):
        if type(self.kindred_sources)is not tuple or any(type(x)is not PlayerEffect for x in self.kindred_sources):
            raise ValueError('Kindred payment sources require complete immutable player instances')
        if self.kindred_sources and self.origin!='payment':raise ValueError('Only an original payment consumes intrinsic Kindred sources')
        for x in self.kindred_sources:x.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.kindred_sources,self.kindred_sources[1:])):
            raise ValueError('Kindred payment sources require their complete unique order')
        for name in ('id', 'source_id', 'turn'): _int(getattr(self, name), 'cost use '+name, 1)
        _int(self.action, 'cost use action', 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2): raise ValueError('Invalid cost use payer')
        _name(self.source_card_id, 'cost use face'); _int(self.amount, 'cost use amount', 0)
        if type(self.payment) is not PaymentType or self.origin not in ('payment', 'effect_launch'):
            raise ValueError('Invalid cost use account or origin')
        for values in (self.modifier_ids, self.consumable_ids):
            if type(values) is not tuple or any(type(i) is not int or i < 1 for i in values):
                raise ValueError('Cost use identities require an immutable integer tuple')
            if any(a >= b for a,b in zip(values, values[1:])): raise ValueError('Cost use IDs require global order')
        if type(self.player_modifiers) is not tuple or any(type(m) is not CostModifier for m in self.player_modifiers):
            raise ValueError('Cost use needs complete player modifiers')
        for modifier in self.player_modifiers: modifier.__post_init__()
        ids = tuple(m.id for m in self.player_modifiers)
        if any(a >= b for a,b in zip(ids, ids[1:])) or not set(ids) <= set(self.modifier_ids):
            raise ValueError('Cost use player sources disagree with quote IDs')
        if self.consumable_ids != tuple(m.id for m in self.player_modifiers if m.uses_remaining is not None):
            raise ValueError('Cost use finite source set must be exact')
        if self.current_deck is not None:
            if type(self.current_deck) is not CurrentDeckCountMatch or self.origin != 'payment':
                raise ValueError('Only a paid hand price carries an original current deck condition')
            self.current_deck.__post_init__()
            if (self.current_deck.player_id != self.player_id or self.current_deck.turn > self.turn
                    or self.current_deck.action > self.action):
                raise ValueError('Cost-use receipt changed its original deck payer or borrowed a future price')
        if self.origin == 'effect_launch' and any(m.scope != CostScope.STARSHIP_LAUNCH for m in self.player_modifiers):
            raise ValueError('Effect launch consumes only launch quote sources')
        if self.permanent_mana is not None:
            if type(self.permanent_mana) is not PermanentManaMatch or self.origin != 'payment':
                raise ValueError('Only paid hand pricing carries a permanent mana condition')
            self.permanent_mana.__post_init__()
            if (self.permanent_mana.player_id != self.player_id or self.permanent_mana.turn > self.turn
                    or self.permanent_mana.action > self.action or self.current_deck is not None):
                raise ValueError('Mana-price receipt changed payer, window or condition family')


class TargetMode(StrEnum):
    REQUIRED = "required"
    IF_AVAILABLE = "if_available"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class TargetSpec:
    """Action target domain; card-specific conditions remain registry predicates."""

    mode: TargetMode = TargetMode.REQUIRED
    zones: tuple[Zone, ...] = (Zone.HERO, Zone.BOARD)
    kinds: tuple[CardType, ...] = (CardType.HERO, CardType.MINION)
    relation: str = "any"
    exclude_source: bool = True

    def __post_init__(self):
        if not isinstance(self.mode, TargetMode):
            raise ValueError("target mode must be a TargetMode")
        for name, enum in (("zones", Zone), ("kinds", CardType)):
            values = getattr(self, name)
            if (not isinstance(values, tuple) or not values or
                    any(not isinstance(value, enum) for value in values) or len(set(values)) != len(values)):
                raise ValueError(f"target {name} must be a nonempty unique tuple of {enum.__name__}")
        if self.relation not in ("any", "friendly", "enemy"):
            raise ValueError("invalid target relation")
        _bool(self.exclude_source, "target exclude_source")


@dataclass(frozen=True)
class ActivatedAbilitySpec:
    """One finite minion action; policy and usage are separate from card behavior."""
    id: str
    behavior_id: str
    card_id: str | None = None
    targeting: TargetSpec | None = None
    target_rule: str = 'any_entity'
    use_rule: str = 'always'
    requires_board_space: bool = False

    def __post_init__(self):
        for name in ('id', 'behavior_id', 'target_rule', 'use_rule'):
            _name(getattr(self, name), f'activated ability {name}')
        if self.card_id is not None:
            _name(self.card_id, 'activated ability card_id')
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec:
                raise ValueError('Activated ability requires TargetSpec')
            self.targeting.__post_init__()
        _bool(self.requires_board_space, 'activated ability requires_board_space')


@dataclass(frozen=True)
class TribeChangeSpec:
    """Ordered changes to a minion's current tribes, separate from printed metadata."""
    operation: str
    tribes: tuple[str, ...]

    def __post_init__(self):
        if type(self.operation) is not str or self.operation not in ('add', 'set', 'remove'):
            raise ValueError('Unknown tribe change operation')
        if (type(self.tribes) is not tuple or any(type(t) is not str for t in self.tribes)
                or len(set(self.tribes)) != len(self.tribes)):
            raise ValueError('Tribe changes require unique immutable string tribes')
        for tribe in self.tribes:
            _name(tribe, 'changed tribe')
        if not self.tribes and self.operation != 'set':
            raise ValueError('Only set can specify an empty tribe set')


@dataclass(frozen=True)
class CthunRitualStamp:
    player_id: int
    first_id: int
    last_id: int
    version: str

    def __post_init__(self):
        _int(self.player_id, 'Cthun ritual player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid Cthun ritual player')
        _int(self.first_id, 'Cthun first growth', 1)
        _int(self.last_id, 'Cthun last growth', self.first_id)
        _name(self.version, 'Cthun ritual version')


@dataclass(frozen=True)
class CthunGrowthRecord:
    id: int
    player_id: int
    source_id: int | None
    attack: int
    health: int
    version: str
    turn: int
    action: int
    taunt: bool = False

    def __post_init__(self):
        _int(self.id, 'Cthun growth ID', 1)
        _int(self.player_id, 'Cthun growth player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid Cthun growth player')
        _optional_id(self.source_id, 'Cthun growth source')
        _int(self.attack, 'Cthun growth attack', 0)
        _int(self.health, 'Cthun growth health', 0)
        _bool(self.taunt, 'Cthun growth Taunt')
        if not self.attack and not self.health and not self.taunt:
            raise ValueError('An actual Cthun growth requires stats or Taunt')
        _name(self.version, 'Cthun growth version')
        _int(self.turn, 'Cthun growth turn', 1)
        _int(self.action, 'Cthun growth action', 0)


@dataclass(frozen=True)
class HandPlayLock:
    """A pure manual-play gate using an existing actual owner-start clock."""
    deadline: OwnerTurnExpiry
    owner_starts: int

    def __post_init__(self):
        if type(self.deadline) is not OwnerTurnExpiry: raise ValueError('Hand play lock requires its original owner clock')
        self.deadline.__post_init__(); _int(self.owner_starts, 'hand play lock owner starts', 1)
        if self.deadline.boundary != 'turn_started': raise ValueError('Hand play lock requires a genuine owner-start boundary')


@dataclass(frozen=True)
class Enchantment:
    """Ordered numeric operation or a separate pure current-tribe identity change."""

    id: int
    source_id: int | None = None
    attack: int = 0
    health: int = 0
    cost: int = 0
    expires_turn: int | None = None
    remove_on_silence: bool = True
    label: str = "buff"
    set_attack: int | None = None
    set_health: int | None = None
    set_cost: int | None = None
    cost_minimum: int = 0
    payment: PaymentType | None = None
    magnetic_id: int | None = None
    tribe_change: TribeChangeSpec | None = None
    cthun_ritual: CthunRitualStamp | None = None
    control_return_player_id: int | None = None
    owner_turn_expiry: OwnerTurnExpiry | None = None
    hand_play_lock: HandPlayLock | None = None
    control_return_expiry: OwnerTurnExpiry | None = None

    def __post_init__(self) -> None:
        _int(self.id, "enchantment ID", 1)
        _optional_id(self.source_id, "enchantment source_id")
        _optional_id(self.magnetic_id, 'magnetic group')
        for name in ("attack", "health", "cost"):
            _int(getattr(self, name), f"enchantment {name}")
        _optional_id(self.expires_turn, "enchantment expires_turn")
        _bool(self.remove_on_silence, "enchantment remove_on_silence")
        _name(self.label, "enchantment label")
        if self.hand_play_lock is not None:
            if type(self.hand_play_lock) is not HandPlayLock: raise ValueError('Hand play lock requires its typed original clock')
            self.hand_play_lock.__post_init__()
            if (self.label != 'hand_play_lock' or self.source_id is None or not self.remove_on_silence or
                    self.attack or self.health or self.cost or self.cost_minimum or self.payment is not None or
                    self.expires_turn is not None or self.magnetic_id is not None or self.owner_turn_expiry is not None or
                    self.tribe_change is not None or self.cthun_ritual is not None or self.control_return_player_id is not None or
                    any(getattr(self,'set_'+name)is not None for name in ('attack','health','cost'))):
                raise ValueError('Hand play lock requires a separate pure removable gate')
        elif self.label == 'hand_play_lock': raise ValueError('Hand play lock label requires its complete clock')
        if self.owner_turn_expiry is not None:
            if type(self.owner_turn_expiry) is not OwnerTurnExpiry:
                raise ValueError('Numeric owner expiry requires its typed original clock')
            self.owner_turn_expiry.__post_init__()
            if (self.owner_turn_expiry.boundary != 'turn_started' or self.expires_turn is not None or
                    self.cost or self.cost_minimum or self.payment is not None or self.magnetic_id is not None or
                    self.tribe_change is not None or self.cthun_ritual is not None or self.control_return_player_id is not None or
                    any(getattr(self, 'set_' + n) is not None for n in ('attack','health','cost')) or
                    self.label != 'buff' or not self.remove_on_silence):
                raise ValueError('Numeric owner expiry requires an independent additive removable buff')
        if self.control_return_player_id is not None:
            _int(self.control_return_player_id, 'control return player', 1)
            if (self.control_return_player_id not in (1, 2) or self.label != 'temporary_control' or
                    self.source_id is None or (self.expires_turn is None) == (self.control_return_expiry is None) or not self.remove_on_silence or
                    self.attack or self.health or self.cost or self.cost_minimum or self.payment is not None or
                    self.magnetic_id is not None or self.tribe_change is not None or self.cthun_ritual is not None or
                    any(getattr(self, 'set_' + n) is not None for n in ('attack', 'health', 'cost'))):
                raise ValueError('Temporary control requires a separate removable timed control enchantment')
        elif self.label == 'temporary_control':
            raise ValueError('Temporary control label requires its original return player')
        if self.control_return_expiry is not None:
            if type(self.control_return_expiry) is not OwnerTurnExpiry:
                raise ValueError('Control return requires its typed original owner-end clock')
            self.control_return_expiry.__post_init__()
            if (self.control_return_player_id != self.control_return_expiry.player_id or
                    self.control_return_expiry.boundary != 'turn_ended'):
                raise ValueError('Control return clock must name the original return player and end boundary')
        if self.cthun_ritual is not None:
            if type(self.cthun_ritual) is not CthunRitualStamp:
                raise ValueError('Cthun increment requires its typed original ritual stamp')
            self.cthun_ritual.__post_init__()
            if (self.label != 'cthun_ritual' or self.remove_on_silence or
                    self.attack < 0 or self.health < 0 or not (self.attack or self.health) or
                    self.source_id is not None or self.expires_turn is not None or
                    self.cost or self.cost_minimum or self.payment is not None or
                    self.magnetic_id is not None or self.tribe_change is not None or
                    any(getattr(self, 'set_' + n) is not None for n in ('attack', 'health', 'cost'))):
                raise ValueError('Cthun ritual requires a separate permanent numeric increment')
        elif self.label == 'cthun_ritual':
            raise ValueError('Cthun ritual label requires an original typed stamp')
        _int(self.cost_minimum, 'cost_minimum', 0)
        if self.payment is not None and not isinstance(self.payment, PaymentType):
            raise ValueError('Enchantment payment requires PaymentType')
        for name in ("attack", "health", "cost"):
            value = getattr(self, f"set_{name}")
            if value is not None:
                _int(value, f"enchantment set_{name}", 0)
                if getattr(self, name) != 0:
                    raise ValueError(f"Cannot add and set {name} in one enchantment")
        if self.tribe_change is not None:
            if type(self.tribe_change) is not TribeChangeSpec:
                raise ValueError('Tribe enchantment requires TribeChangeSpec')
            self.tribe_change.__post_init__()
            if (self.attack or self.health or self.cost or self.cost_minimum or self.payment is not None
                    or any(getattr(self, 'set_' + n) is not None for n in ('attack', 'health', 'cost'))
                    or self.magnetic_id is not None):
                raise ValueError('Tribe changes require a separate pure identity enchantment')


@dataclass(frozen=True)
class EndTurnSpec:
    """Explicit natural end-turn eligibility, separate from a reusable body."""

    turn_scope: str = 'controller'
    condition_id: str = 'always'

    def __post_init__(self):
        if type(self.turn_scope) is not str or self.turn_scope not in ('controller', 'opponent', 'either'):
            raise ValueError('Invalid end-turn scope')
        _name(self.condition_id, 'end-turn condition')


@dataclass(frozen=True)
class LimitedTriggerSpec:
    event: str
    behavior_id: str
    condition_id: str = 'always'
    uses: int = 1
    keyword: Keyword | None = None
    end_turn: EndTurnSpec | None = None
    reset: str = 'instance'

    def __post_init__(self):
        for name in ('event', 'behavior_id', 'condition_id'):
            _name(getattr(self, name), name)
        _int(self.uses, 'trigger uses', 1)
        if type(self.reset) is not str or self.reset not in ('instance', 'turn'):
            raise ValueError('Unknown finite trigger budget scope')
        if self.reset == 'turn' and self.end_turn is not None:
            raise ValueError('Classified end-turn budgets require their own explicit policy')
        if self.end_turn is not None:
            if type(self.end_turn) is not EndTurnSpec:
                raise ValueError('Expected EndTurnSpec')
            self.end_turn.__post_init__()
            if self.event != 'turn_ended' or self.keyword is not None:
                raise ValueError('Classified limited end-turn triggers require turn_ended and no keyword')
        if self.keyword is not None:
            if self.keyword not in (Keyword.SPELLBURST, Keyword.FRENZY) or not isinstance(self.keyword, Keyword):
                raise ValueError('Invalid limited trigger keyword')
            expected = 'card_played' if self.keyword == Keyword.SPELLBURST else 'damage_dealt'
            if self.uses != 1 or self.event != expected or self.reset != 'instance':
                raise ValueError('Keyword triggers require their event and one use')

    @classmethod
    def spellburst(cls, behavior_id):
        return cls('card_played', behavior_id, keyword=Keyword.SPELLBURST)

    @classmethod
    def frenzy(cls, behavior_id):
        return cls('damage_dealt', behavior_id, keyword=Keyword.FRENZY)


@dataclass(frozen=True)
class HandProgressSpec:
    kind: str
    goal: int = 1
    upgrade_card_id: str | None = None
    on_progress: str | None = None
    on_complete: str | None = None
    repeat: bool = False
    event: str | None = None
    condition_id: str = 'always'
    health_to_durability: bool = False
    amount_basis: str = 'one'
    upgrade_cost_policy: str = 'preserve'
    zone: Zone | tuple[Zone, ...] = Zone.HAND

    def __post_init__(self):
        if not (type(self.zone) is Zone and self.zone in (Zone.HAND, Zone.DECK) or
                type(self.zone) is tuple and all(type(z) is Zone for z in self.zone)
                and self.zone == (Zone.HAND, Zone.DECK)):
            raise ValueError('Stored progress listens only in hand or deck, or their explicit ordered pair')
        if Zone.DECK in self.zones and (
                self.kind != 'event' or self.goal != 1 or not self.repeat or
                self.upgrade_card_id is not None or self.on_progress is not None or
                self.on_complete is None or self.health_to_durability or self.amount_basis != 'one'):
            raise ValueError('Native deck listeners require repeated single-event completion bodies')
        if self.kind not in ('corrupt', 'infuse', 'event', 'spell_cast'):
            raise ValueError('Unknown hand progress kind')
        if type(self.amount_basis) is not str or self.amount_basis not in ('one', 'event_amount'):
            raise ValueError('Unknown hand progress amount basis')
        if self.amount_basis != 'one' and (self.kind != 'event' or self.repeat):
            raise ValueError('Event amounts require nonrepeating generic hand progress')
        if (type(self.upgrade_cost_policy) is not str or
                self.upgrade_cost_policy not in ('preserve', 'clear_local') or
                self.upgrade_cost_policy != 'preserve' and self.upgrade_card_id is None):
            raise ValueError('Cost replacement policy requires an actual upgrade form')
        _int(self.goal, 'hand progress goal', 1)
        _name(self.condition_id, 'hand progress condition')
        for name in ('upgrade_card_id', 'on_progress', 'on_complete', 'event'):
            if getattr(self, name) is not None:
                _name(getattr(self, name), name)
        for name in ('repeat', 'health_to_durability'):
            _bool(getattr(self, name), name)
        if (self.kind == 'event') != (self.event is not None):
            raise ValueError('Only generic hand progress specifies an event')
        if self.kind == 'corrupt' and self.goal != 1:
            raise ValueError('Corrupt advances one stage per qualifying play')
        if self.repeat and self.upgrade_card_id is not None:
            raise ValueError('Repeated progress uses callbacks; next forms declare their own stages')
        if self.health_to_durability and self.upgrade_card_id is None:
            raise ValueError('Health conversion requires an upgrade form')
        if self.kind=='spell_cast':
            if any(x is not None for x in (self.upgrade_card_id,self.on_progress,self.on_complete)) or self.repeat or self.health_to_durability:
                raise ValueError('Held-spell facts cannot upgrade, repeat or invoke callbacks')
        elif self.upgrade_card_id is None and self.on_complete is None:
            raise ValueError('Hand progress requires a completion effect or form')

    @property
    def zones(self):
        return (self.zone,) if type(self.zone) is Zone else self.zone

    @property
    def event_kind(self):
        return {'corrupt': 'card_played', 'infuse': 'minion_died'}.get(self.kind, self.event)

    @property
    def keyword(self):
        return {'corrupt': Keyword.CORRUPT, 'infuse': Keyword.INFUSE}.get(self.kind)


def validate_defining_hand_spec(spec):
    """The native turn-start shifters, not an arbitrary retained attachment."""
    if type(spec) is not HandProgressSpec:
        raise ValueError('Defining hand source requires HandProgressSpec')
    spec.__post_init__()
    if (spec.kind != 'event' or spec.event != 'turn_started' or spec.zone != Zone.HAND or
            spec.goal != 1 or not spec.repeat or spec.on_complete is None or
            spec.on_progress is not None or spec.upgrade_card_id is not None or
            spec.health_to_durability or spec.amount_basis != 'one'):
        raise ValueError('Defining hand source supports native repeated own-turn bodies only')


@dataclass(frozen=True)
class HeldSpellProgress:
    spec: HandProgressSpec
    cast_ids: tuple[int, ...]
    before_cast_id: int

    def __post_init__(self):
        if type(self.spec) is not HandProgressSpec or self.spec.kind!='spell_cast':
            raise ValueError('Held-spell fact requires spell progress declaration')
        self.spec.__post_init__(); _int(self.before_cast_id,'held-spell cast bound',1)
        if type(self.cast_ids) is not tuple or len(self.cast_ids)>self.spec.goal:
            raise ValueError('Held-spell facts require bounded immutable witnesses')
        for i in self.cast_ids:
            _int(i,'held-spell witness',1)
            if i>=self.before_cast_id:raise ValueError('Held-spell witness exceeds captured bound')
        if any(a>=b for a,b in zip(self.cast_ids,self.cast_ids[1:])):
            raise ValueError('Held-spell witnesses require chronological unique IDs')

    @property
    def completed(self):return len(self.cast_ids)==self.spec.goal


@dataclass(frozen=True)
class HandProgressCandidate:
    source_id: int
    ability_id: int
    player_id: int

    def __post_init__(self):
        for name in ('source_id', 'ability_id', 'player_id'):
            _int(getattr(self, name), name, 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid hand progress player')


@dataclass(frozen=True)
class TriggerCandidate:
    source_id: int
    ability_id: int
    player_id: int
    entered_order: int

    def __post_init__(self):
        for name in ('source_id', 'ability_id', 'player_id', 'entered_order'):
            _int(getattr(self, name), name, 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid trigger candidate player')


@dataclass(frozen=True)
class DeckSacrificeSpec:
    """Replace named friendly minions' adjacent sacrifices with enemy deck minions."""
    card_ids: tuple[str, ...]

    def __post_init__(self):
        if (type(self.card_ids) is not tuple or not self.card_ids or
                any(type(i) is not str or not i.strip() for i in self.card_ids) or
                len(set(self.card_ids)) != len(self.card_ids)):
            raise ValueError('Deck sacrifice requires a nonempty unique tuple of card IDs')


@dataclass(frozen=True)
class KeywordAuraSpec:
    """Continuous contributions with explicit native self/recipient scopes."""

    keyword: Keyword
    target: str = 'friendly_hero'
    include_self: bool = False
    adjacent_only: bool = False
    condition: str = 'always'
    tribes_any: tuple[str, ...] = ()
    card_ids: tuple[str, ...] = ()

    def __post_init__(self):
        supported = {Keyword.WINDFURY, Keyword.MEGA_WINDFURY, Keyword.TAUNT, Keyword.CHARGE, Keyword.RUSH,
                     Keyword.POISONOUS, Keyword.LIFESTEAL, Keyword.IMMUNE, Keyword.IMMUNE_WHILE_ATTACKING, Keyword.CANT_BE_FROZEN, Keyword.ELUSIVE}
        hand = self.target in ('friendly_hand_minions', 'friendly_hand_spells', 'friendly_hand')
        if hand:
            supported.add(Keyword.ECHO)
        if type(self.keyword) is not Keyword or self.keyword not in supported:
            raise ValueError('Keyword aura requires a supported continuous keyword')
        if not hand and self.target not in ('friendly_hero', 'friendly_minions', 'enemy_minions', 'self'):
            raise ValueError('Unsupported keyword aura target')
        _bool(self.include_self, 'keyword aura include_self')
        _bool(self.adjacent_only, 'keyword aura adjacent_only')
        TribeChangeSpec('set', self.tribes_any).__post_init__()
        _aura_card_ids(self.card_ids)
        if self.target == 'enemy_minions' and (self.keyword != Keyword.TAUNT or self.include_self or
                self.adjacent_only or self.condition != 'always' or self.tribes_any or self.card_ids):
            raise ValueError('Native enemy keyword aura requires ordinary board Taunt')
        if self.card_ids and (self.target != 'friendly_minions' or self.condition != 'always' or
                self.adjacent_only or self.tribes_any):
            raise ValueError('Card identity keyword auras require ordinary board scope and one selector')
        if self.tribes_any and (self.keyword != Keyword.CHARGE or
                self.target != 'friendly_minions' or self.condition != 'always' or self.adjacent_only):
            raise ValueError('Tribal keyword aura currently requires ordinary board Charge')
        if type(self.condition) is not str or self.condition not in ('always', 'self_damaged', 'controller_has_weapon', 'controller_turn','controller_no_other_minions'):
            raise ValueError('Unsupported continuous keyword condition')
        if (self.target == 'self') != (self.condition in ('self_damaged','controller_has_weapon','controller_no_other_minions')):
            raise ValueError('Conditional keyword requires its own self target')
        if self.condition == 'controller_turn' and (self.target != 'friendly_hero' or
                self.keyword != Keyword.IMMUNE or self.include_self or self.adjacent_only or self.tribes_any or self.card_ids):
            raise ValueError('Controller-turn keyword aura requires independent hero immunity')
        if self.target == 'self' and (self.include_self or self.adjacent_only):
            raise ValueError('Conditional self keywords do not use board positions')
        if self.condition == 'self_damaged' and self.keyword != Keyword.WINDFURY:
            raise ValueError('Self-damaged keyword currently supports the known Windfury profile')
        if self.condition == 'controller_has_weapon' and self.keyword != Keyword.CHARGE:
            raise ValueError('Weapon-presence keyword currently supports the known Charge profile')
        if self.condition=='controller_no_other_minions' and self.keyword!=Keyword.IMMUNE:
            raise ValueError('No-other-minion keyword requires the native self Immune profile')
        if hand and (self.include_self or self.adjacent_only or
                     self.target != 'friendly_hand_minions' and self.keyword != Keyword.ECHO):
            raise ValueError('Hand aura scope cannot use board positions or minion-only spell keywords')
        if self.keyword == Keyword.CANT_BE_FROZEN and (self.target != 'friendly_minions' or
                self.condition != 'always' or self.adjacent_only or self.tribes_any or self.card_ids):
            raise ValueError('Freeze prevention aura requires ordinary friendly board minions')
        if self.adjacent_only and self.include_self:
            raise ValueError('Adjacent keyword auras exclude their source')
        if self.target == 'friendly_hero' and (self.include_self or self.adjacent_only or
                self.keyword in (Keyword.TAUNT, Keyword.CHARGE, Keyword.RUSH)):
            raise ValueError('Unsupported hero keyword aura scope')


class HealthLossKind(StrEnum):
    DAMAGE = 'damage'
    PAYMENT = 'payment'
    EFFECT = 'effect'


@dataclass(frozen=True)
class SummonQuantitySpec:
    """Explicit live product on summons attributed to this source's player."""
    factor: int = 2
    source_kinds: tuple[CardType,...] = (CardType.SPELL,CardType.MINION,CardType.WEAPON,CardType.HERO,CardType.LOCATION)
    profile: str = 'card_cause_live_attachment_product_selected_entry'

    def __post_init__(self):
        _int(self.factor,'summon quantity factor',2)
        if self.profile!='card_cause_live_attachment_product_selected_entry':raise ValueError('Unsupported summon quantity policy')
        if (type(self.source_kinds)is not tuple or not self.source_kinds or len(set(self.source_kinds))!=len(self.source_kinds) or
                any(type(k)is not CardType or k not in (CardType.SPELL,CardType.MINION,CardType.WEAPON,CardType.HERO,CardType.LOCATION,CardType.HERO_POWER) for k in self.source_kinds)):
            raise ValueError('Quantity requires explicit unique physical source kinds')


@dataclass(frozen=True)
class HealthLossFloorSpec:
    """Explicit EFFECT debit scope; maximum matching floor is local M6 policy."""
    floor: int = 1
    kinds: tuple[HealthLossKind, ...] = (HealthLossKind.EFFECT,)
    target_relation: str = 'self'
    target_kinds: tuple[CardType, ...] = (CardType.HERO, CardType.MINION)

    def __post_init__(self):
        _int(self.floor, 'effect health debit floor', 1)
        if type(self.kinds) is not tuple or self.kinds != (HealthLossKind.EFFECT,) or any(type(k) is not HealthLossKind for k in self.kinds):
            raise ValueError('Health loss floor supports only explicit EFFECT scope')
        if type(self.target_relation) is not str or self.target_relation not in ('any', 'self', 'friendly', 'enemy'):
            raise ValueError('Unknown health loss floor relationship')
        if (type(self.target_kinds) is not tuple or not self.target_kinds or
                any(type(k) is not CardType or k not in (CardType.HERO, CardType.MINION) for k in self.target_kinds) or
                len(set(self.target_kinds)) != len(self.target_kinds)):
            raise ValueError('Health loss floor requires unique character kinds')


@dataclass(frozen=True)
class HealthLossReplacementSpec:
    """Replace a friendly hero's impending health loss with max-health gain."""
    own_turn_only: bool = True
    kinds: tuple[HealthLossKind, ...] = tuple(HealthLossKind)

    def __post_init__(self):
        _bool(self.own_turn_only, 'health loss replacement turn restriction')
        if (type(self.kinds) is not tuple or not self.kinds or
                any(type(k) is not HealthLossKind for k in self.kinds) or
                len(set(self.kinds)) != len(self.kinds)):
            raise ValueError('Health loss replacement requires unique loss kinds')


@dataclass(frozen=True)
class DeathrattleRecipient:
    """Physical payload carrier and its face at the original group window."""
    carrier_id: int
    card_id: str
    kind: CardType

    def __post_init__(self):
        _int(self.carrier_id, 'accepted Deathrattle carrier', 1)
        if type(self.card_id) is not str:
            raise ValueError('Accepted Deathrattle card identity requires a string')
        _name(self.card_id, 'accepted Deathrattle card')
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO):
            raise ValueError('Accepted Deathrattle recipient requires a physical carrier kind')


@dataclass(frozen=True)
class DeathrattleRecipientMetadataFilter:
    """Printed tribes of the physical recipient face at Deathrattle acceptance."""
    basis: str = 'accepted_carrier_face_printed'
    tribes_any: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.basis) is not str or self.basis != 'accepted_carrier_face_printed':
            raise ValueError('Unsupported Deathrattle recipient metadata basis')
        if (type(self.tribes_any) is not tuple or
                any(type(tribe) is not str for tribe in self.tribes_any) or
                len(set(self.tribes_any)) != len(self.tribes_any)):
            raise ValueError('Deathrattle recipient tribes require a unique immutable string tuple')
        for tribe in self.tribes_any:
            _name(tribe, 'Deathrattle recipient tribe')


@dataclass(frozen=True)
class DeathrattleRepeatMatchSpec:
    recipient_metadata: DeathrattleRecipientMetadataFilter | None = None
    source_eligibility: RepeatSourceEligibility | None = None

    def __post_init__(self):
        if self.recipient_metadata is not None:
            if type(self.recipient_metadata) is not DeathrattleRecipientMetadataFilter:
                raise ValueError('Deathrattle matching requires DeathrattleRecipientMetadataFilter')
            self.recipient_metadata.__post_init__()
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('Deathrattle source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()


@dataclass(frozen=True)
class DeathrattleRepeatSpec:
    """Set-count policy with explicit accepted carrier and payload matching."""
    repetitions: int = 2
    kinds: tuple[CardType, ...] = (CardType.MINION,)
    scope: str = 'friendly'
    origins: tuple[str, ...] = ('printed','granted')
    match: DeathrattleRepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.repetitions, 'Deathrattle repetitions', 2)
        if (type(self.kinds) is not tuple or not self.kinds or len(set(self.kinds))!=len(self.kinds) or
                any(type(k) is not CardType or k not in (CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO) for k in self.kinds)):
            raise ValueError('Deathrattle repetition requires unique physical carrier kinds')
        if type(self.scope) is not str or self.scope not in ('friendly','self'):
            raise ValueError('Unknown Deathrattle repeat scope')
        if (type(self.origins) is not tuple or not self.origins or len(set(self.origins))!=len(self.origins) or
                any(type(o) is not str or o not in ('printed','granted') for o in self.origins)):
            raise ValueError('Deathrattle repetition requires unique payload origins')
        if self.match is not None:
            if type(self.match) is not DeathrattleRepeatMatchSpec:
                raise ValueError('Deathrattle matching requires DeathrattleRepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class EndTurnRepeatMatchSpec:
    """Sustained condition on a physical board end-turn repeat source."""
    source_eligibility: RepeatSourceEligibility | None = None

    def __post_init__(self):
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('End-turn source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()


@dataclass(frozen=True)
class EndTurnRepeatSpec:
    """Set-count policy on all classified or physical-minion end-turn bodies."""
    repetitions: int = 2
    scope: str = 'all'
    match: EndTurnRepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.repetitions, 'end-turn repetitions', 2)
        if type(self.scope) is not str or self.scope not in ('all', 'minion'):
            raise ValueError('Invalid end-turn repeat scope')
        if self.match is not None:
            if type(self.match) is not EndTurnRepeatMatchSpec:
                raise ValueError('End-turn matching requires EndTurnRepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class HeroPowerRepeatMatchSpec:
    """Sustained condition on the physical board source of a power policy."""
    source_eligibility: RepeatSourceEligibility | None = None

    def __post_init__(self):
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('Hero power source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()


@dataclass(frozen=True)
class HeroPowerUseAuraSpec:
    """Native friendly per-installed-power cap; None is truly unbounded."""
    limit: int | None = 2

    def __post_init__(self):
        if self.limit is not None:
            _int(self.limit, 'native Hero Power use cap', 1)


@dataclass(frozen=True)
class HeroPowerRepeatSpec:
    """Set-count policy for friendly hero power payloads from board minions."""
    repetitions: int = 2
    match: HeroPowerRepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.repetitions, 'hero power repetitions', 2)
        if self.match is not None:
            if type(self.match) is not HeroPowerRepeatMatchSpec:
                raise ValueError('Hero power matching requires HeroPowerRepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class BattlecryRecipientMetadataFilter:
    """Printed tribes of the physical recipient face at Battlecry acceptance."""
    basis: str = 'accepted_carrier_face_printed'
    tribes_any: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.basis) is not str or self.basis != 'accepted_carrier_face_printed':
            raise ValueError('Unsupported Battlecry recipient metadata basis')
        if (type(self.tribes_any) is not tuple or
                any(type(tribe) is not str for tribe in self.tribes_any) or
                len(set(self.tribes_any)) != len(self.tribes_any)):
            raise ValueError('Battlecry recipient tribes require a unique immutable string tuple')
        for tribe in self.tribes_any:
            _name(tribe, 'Battlecry recipient tribe')


@dataclass(frozen=True)
class BattlecryRepeatMatchSpec:
    recipient_metadata: BattlecryRecipientMetadataFilter | None = None
    source_eligibility: RepeatSourceEligibility | None = None

    def __post_init__(self):
        if self.recipient_metadata is not None:
            if type(self.recipient_metadata) is not BattlecryRecipientMetadataFilter:
                raise ValueError('Battlecry matching requires BattlecryRecipientMetadataFilter')
            self.recipient_metadata.__post_init__()
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('Battlecry source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()


@dataclass(frozen=True)
class BattlecryRepeatSpec:
    """Set-count policy shared by board auras and player modifiers."""
    repetitions: int = 2
    kinds: tuple[CardType, ...] = (CardType.MINION, CardType.WEAPON, CardType.HERO)
    scope: str = 'friendly'
    match: BattlecryRepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.repetitions, 'Battlecry repetitions', 2)
        if (type(self.kinds) is not tuple or not self.kinds or len(set(self.kinds)) != len(self.kinds) or
                any(type(k) is not CardType or k not in (CardType.MINION, CardType.WEAPON, CardType.HERO) for k in self.kinds)):
            raise ValueError('Battlecry repetition requires unique physical card kinds')
        if type(self.scope) is not str or self.scope not in ('friendly', 'self'):
            raise ValueError('Unknown Battlecry repeat scope')
        if self.scope == 'self' and self.kinds != (CardType.MINION,):
            raise ValueError('Self Battlecry repetition requires only the physical minion kind')
        if self.match is not None:
            if type(self.match) is not BattlecryRepeatMatchSpec:
                raise ValueError('Battlecry matching requires BattlecryRepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class BattlecryRepeatModifier:
    id: int
    spec: BattlecryRepeatSpec
    source_id: int | None
    source_card_id: str | None
    created_turn: int
    uses_remaining: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _int(self.id, 'Battlecry modifier ID', 1)
        if type(self.spec) is not BattlecryRepeatSpec: raise ValueError('Invalid player Battlecry specification')
        self.spec.__post_init__()
        if self.spec.scope != 'friendly':
            raise ValueError('Player Battlecry policies cannot require a physical self carrier')
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player Battlecry policies cannot require a physical board carrier')
        _optional_id(self.source_id, 'Battlecry modifier source')
        if (self.source_id is None) != (self.source_card_id is None): raise ValueError('Battlecry modifier source identity disagrees')
        if self.source_card_id is not None: _name(self.source_card_id, 'Battlecry modifier source card')
        _int(self.created_turn, 'Battlecry modifier creation', 1)
        if self.uses_remaining is not None: _int(self.uses_remaining, 'Battlecry modifier uses', 1)
        if self.expires_turn is not None: _int(self.expires_turn, 'Battlecry modifier expiry', self.created_turn)


@dataclass(frozen=True)
class BattlecryRepeatPlan:
    repetitions: int = 1
    contributors: tuple[int, ...] = ()  # Captured attachment IDs, not live lookups.
    consumable_ids: tuple[int, ...] = ()

    def __post_init__(self):
        _int(self.repetitions, 'captured Battlecry repetitions', 1)
        if type(self.contributors) is not tuple or len(set(self.contributors)) != len(self.contributors):
            raise ValueError('Battlecry repeat contributors must be unique immutable IDs')
        for value in self.contributors: _int(value, 'Battlecry repeat contributor', 1)
        if (type(self.consumable_ids) is not tuple or len(set(self.consumable_ids)) != len(self.consumable_ids) or
                not set(self.consumable_ids) <= set(self.contributors)):
            raise ValueError('Battlecry consumption must reference unique captured contributors')
        for value in self.consumable_ids: _int(value, 'Battlecry consumable contributor', 1)
        if (self.repetitions > 1) != bool(self.contributors):
            raise ValueError('Repeated Battlecries require captured contributors')


@dataclass(frozen=True)
class BattlecryRecipient:
    """Physical payload carrier and its accepted face, independent of provenance."""
    carrier_id: int
    card_id: str
    kind: CardType

    def __post_init__(self):
        _int(self.carrier_id, 'accepted Battlecry carrier', 1)
        if type(self.card_id) is not str:
            raise ValueError('Accepted Battlecry card identity requires a string')
        _name(self.card_id, 'accepted Battlecry card')
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
            raise ValueError('Accepted Battlecry recipient requires a physical hand card kind')


@dataclass(frozen=True)
class BattlecryAcceptanceReceipt:
    """Post-entry hand payload acceptance; an empty body set is explicit."""
    player_id: int
    payloads: tuple[BattlecryPayload, ...]
    plan: BattlecryRepeatPlan | None
    recipient: BattlecryRecipient

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid accepted Battlecry player')
        if type(self.recipient) is not BattlecryRecipient:
            raise ValueError('Battlecry acceptance requires its physical recipient')
        self.recipient.__post_init__()
        if (type(self.payloads) is not tuple or any(type(b) is not BattlecryPayload for b in self.payloads) or
                len({b.ability_id for b in self.payloads}) != len(self.payloads)):
            raise ValueError('Battlecry acceptance requires a complete immutable ability set')
        for payload in self.payloads: payload.__post_init__()
        if (self.plan is not None) != bool(self.payloads):
            raise ValueError('Battlecry acceptance plan and ability set disagree')
        if self.plan is not None:
            if type(self.plan) is not BattlecryRepeatPlan: raise ValueError('Invalid accepted Battlecry plan')
            self.plan.__post_init__()


@dataclass(frozen=True)
class ComboRecipient:
    """Physical receiver and its face at one of the independent Combo windows."""
    carrier_id: int
    card_id: str
    kind: CardType

    def __post_init__(self):
        _int(self.carrier_id, 'accepted Combo carrier', 1)
        if type(self.card_id) is not str:
            raise ValueError('Accepted Combo card identity requires a string')
        _name(self.card_id, 'accepted Combo card')
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
            raise ValueError('Accepted Combo recipient requires a physical hand card kind')


@dataclass(frozen=True)
class ComboRecipientMetadataFilter:
    basis: str = 'accepted_window_face_printed'
    tribes_any: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.basis) is not str or self.basis != 'accepted_window_face_printed':
            raise ValueError('Unsupported Combo recipient metadata basis')
        if (type(self.tribes_any) is not tuple or
                any(type(tribe) is not str for tribe in self.tribes_any) or
                len(set(self.tribes_any)) != len(self.tribes_any)):
            raise ValueError('Combo recipient tribes require a unique immutable string tuple')
        for tribe in self.tribes_any:
            _name(tribe, 'Combo recipient tribe')


@dataclass(frozen=True)
class ComboRepeatMatchSpec:
    recipient_metadata: ComboRecipientMetadataFilter | None = None
    source_eligibility: RepeatSourceEligibility | None = None

    def __post_init__(self):
        if self.recipient_metadata is not None:
            if type(self.recipient_metadata) is not ComboRecipientMetadataFilter:
                raise ValueError('Combo matching requires ComboRecipientMetadataFilter')
            self.recipient_metadata.__post_init__()
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('Combo source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()


@dataclass(frozen=True)
class ComboRepeatSpec:
    """Set-count policy shared by board auras and player modifiers."""
    repetitions: int = 2
    kinds: tuple[CardType, ...] = (CardType.MINION,)
    scope: str = 'friendly'
    match: ComboRepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.repetitions, 'Combo repetitions', 2)
        if (type(self.kinds) is not tuple or not self.kinds or len(set(self.kinds)) != len(self.kinds) or
                any(type(k) is not CardType or k not in (CardType.MINION, CardType.WEAPON, CardType.HERO) for k in self.kinds)):
            raise ValueError('Combo repetition requires unique physical card kinds')
        if type(self.scope) is not str or self.scope not in ('friendly', 'self'):
            raise ValueError('Unknown Combo repeat scope')
        if self.scope == 'self' and self.kinds != (CardType.MINION,):
            raise ValueError('Self Combo repetition requires only the physical minion kind')
        if self.match is not None:
            if type(self.match) is not ComboRepeatMatchSpec:
                raise ValueError('Combo matching requires ComboRepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class ComboRepeatModifier:
    id: int
    spec: ComboRepeatSpec
    source_id: int | None
    source_card_id: str | None
    created_turn: int
    uses_remaining: int | None = None
    expires_turn: int | None = None
    trigger: str = 'play'

    def __post_init__(self):
        if self.trigger not in ('play','activation'): raise ValueError('Unknown Combo policy trigger')
        _int(self.id, 'Combo modifier ID', 1)
        if type(self.spec) is not ComboRepeatSpec: raise ValueError('Invalid player Combo specification')
        self.spec.__post_init__()
        if self.spec.scope != 'friendly':
            raise ValueError('Player Combo policies cannot require a physical self carrier')
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player Combo policies cannot require a physical board carrier')
        _optional_id(self.source_id, 'Combo modifier source')
        if (self.source_id is None) != (self.source_card_id is None): raise ValueError('Combo modifier source identity disagrees')
        if self.source_card_id is not None: _name(self.source_card_id, 'Combo modifier source card')
        _int(self.created_turn, 'Combo modifier creation', 1)
        if self.uses_remaining is not None: _int(self.uses_remaining, 'Combo modifier uses', 1)
        if self.expires_turn is not None: _int(self.expires_turn, 'Combo modifier expiry', self.created_turn)


@dataclass(frozen=True)
class ComboRepeatPlan:
    repetitions: int = 1
    contributors: tuple[int, ...] = ()  # Captured attachment IDs, not live lookups.
    consumable_ids: tuple[int, ...] = ()

    def __post_init__(self):
        _int(self.repetitions, 'captured Combo repetitions', 1)
        if type(self.contributors) is not tuple or len(set(self.contributors)) != len(self.contributors):
            raise ValueError('Combo repeat contributors must be unique immutable IDs')
        for value in self.contributors: _int(value, 'Combo repeat contributor', 1)
        if (type(self.consumable_ids) is not tuple or len(set(self.consumable_ids)) != len(self.consumable_ids) or
                not set(self.consumable_ids) <= set(self.contributors)):
            raise ValueError('Combo consumption must reference unique captured contributors')
        for value in self.consumable_ids: _int(value, 'Combo consumable contributor', 1)
        if (self.repetitions > 1) != bool(self.contributors):
            raise ValueError('Repeated Battlecries require captured contributors')


@dataclass(frozen=True)
class ComboPolicyReceipt:
    id: int
    play_id: int | None
    phase: str
    turn: int
    action: int
    recipient: ComboRecipient
    eligible: bool
    modifiers: tuple[ComboRepeatModifier, ...]
    consumption_applied: bool = False
    origin: str = 'paid_hand'
    physical_child_id: int | None = None
    player_id: int | None = None

    def __post_init__(self):
        _int(self.id,'Combo receipt ID',1)
        if self.origin == 'paid_hand':
            _int(self.play_id, 'Combo receipt play', 1)
            if self.physical_child_id is not None or self.player_id is not None:
                raise ValueError('Paid Combo receipt cannot borrow a generated origin')
        elif self.origin == 'generated_body':
            _int(self.physical_child_id, 'Combo actual physical child', 1)
            _int(self.player_id, 'Combo generated player', 1)
            if self.play_id is not None or self.player_id not in (1, 2) or self.phase != 'activation':
                raise ValueError('Generated Combo has only its independent activation window')
        else:
            raise ValueError('Unknown Combo policy acceptance origin')
        if type(self.phase) is not str or self.phase not in ('play','activation'):
            raise ValueError('Unknown Combo policy phase')
        _int(self.turn, 'Combo receipt turn', 1)
        _int(self.action, 'Combo receipt action', 1 if self.origin == 'paid_hand' else 0)
        if type(self.recipient) is not ComboRecipient:
            raise ValueError('Combo receipt requires its physical window recipient')
        self.recipient.__post_init__()
        _bool(self.eligible, 'Combo receipt eligible')
        _bool(self.consumption_applied, 'Combo receipt consumption applied')
        if (type(self.modifiers) is not tuple or
                any(type(m) is not ComboRepeatModifier for m in self.modifiers)):
            raise ValueError('Combo receipt requires captured modifiers')
        if not self.eligible and self.modifiers:
            raise ValueError('An ineligible Combo window cannot capture player policies')
        for m in self.modifiers:
            m.__post_init__()
            if m.trigger!=self.phase:raise ValueError('Combo receipt phase differs from its policy')
        if any(a.id>=b.id for a,b in zip(self.modifiers,self.modifiers[1:])):
            raise ValueError('Combo receipt modifiers must preserve acquisition order')


@dataclass(frozen=True)
class ComboAcceptanceReceipt:
    player_id: int
    recipient: ComboRecipient
    status: str
    payloads: tuple[ComboPayload, ...]
    plan: ComboRepeatPlan | None
    policy_receipt_id: int
    colossal_record_id: int | None = None

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid accepted Combo player')
        if type(self.recipient) is not ComboRecipient:
            raise ValueError('Combo acceptance requires its physical window recipient')
        self.recipient.__post_init__()
        if type(self.status) is not str or self.status not in (
                'activated', 'disabled', 'no_payload', 'countered', 'board_full',
                'magnetized', 'colossal_canceled'):
            raise ValueError('Unknown Combo acceptance status')
        validate_combo_payloads(self.payloads)
        _int(self.policy_receipt_id, 'Combo activation policy receipt', 1)
        _optional_id(self.colossal_record_id, 'Combo Colossal record')
        if self.status == 'activated':
            if not self.payloads or type(self.plan) is not ComboRepeatPlan:
                raise ValueError('Activated Combo acceptance requires declarations and a complete plan')
            self.plan.__post_init__()
        elif self.plan is not None or (bool(self.payloads) != (self.status == 'disabled')):
            raise ValueError('Inactive Combo acceptance has an invalid declaration or plan set')
        if self.status == 'colossal_canceled' and self.colossal_record_id is None:
            raise ValueError('Canceled Colossal Combo acceptance requires its paid-entry record')
        if (self.status in ('countered', 'board_full', 'magnetized') and self.colossal_record_id is not None or
                self.colossal_record_id is not None and self.recipient.kind != CardType.MINION):
            raise ValueError('Combo Colossal provenance requires delayed physical minion entry')


@dataclass(frozen=True)
class RecipientMetadataFilter:
    """Printed metadata of the recipient face accepted by its rule window."""
    basis: str = 'accepted_face_printed'
    spell_schools: tuple[SpellSchool, ...] = ()

    def __post_init__(self):
        if type(self.basis) is not str or self.basis != 'accepted_face_printed':
            raise ValueError('Unsupported repeat recipient metadata basis')
        if (type(self.spell_schools) is not tuple or
                any(type(s) is not SpellSchool for s in self.spell_schools) or
                len(set(self.spell_schools)) != len(self.spell_schools)):
            raise ValueError('Repeat schools require a unique immutable SpellSchool tuple')


@dataclass(frozen=True)
class RepeatWitnessProfile:
    """Registered qualification policy for controlled board minion witnesses."""
    id: str
    basis: str = 'current_face_printed'
    include_dormant: bool = True
    include_starship_building: bool = False
    include_doomed: bool = True
    require_positive_health: bool = False

    def __post_init__(self):
        if type(self.id) is not str:
            raise ValueError('Repeat witness profile ID requires a string')
        _name(self.id, 'Repeat witness profile ID')
        if type(self.basis) is not str or self.basis != 'current_face_printed':
            raise ValueError('Unsupported repeat witness metadata basis')
        for name in ('include_dormant', 'include_starship_building',
                     'include_doomed', 'require_positive_health'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('Repeat witness presence flags require booleans')


@dataclass(frozen=True)
class RepeatSourceEligibility:
    """A controlled-minion presence condition on an actual board carrier."""
    profile_id: str
    tribes_any: tuple[str, ...] = ()
    exclude_carrier: bool = False

    def __post_init__(self):
        if type(self.profile_id) is not str:
            raise ValueError('Repeat source profile ID requires a string')
        _name(self.profile_id, 'Repeat source profile ID')
        if (type(self.tribes_any) is not tuple or
                any(type(tribe) is not str for tribe in self.tribes_any) or
                len(set(self.tribes_any)) != len(self.tribes_any)):
            raise ValueError('Repeat witness tribes require a unique immutable string tuple')
        for tribe in self.tribes_any:
            _name(tribe, 'Repeat witness tribe')
        if type(self.exclude_carrier) is not bool:
            raise ValueError('Repeat carrier exclusion requires a boolean')


@dataclass(frozen=True)
class CostQueryProfile:
    """Registered pure price policy for an accepted physical hand spell."""
    id: str
    subject: str = 'accepted_paid_hand_spell'
    local_basis: str = 'window_physical'
    external_basis: str = 'window_live'
    minimum_basis: str = 'submitted_hand'
    intrinsic_profile_id: str = 'cost.intrinsic.before-local-v1'

    def __post_init__(self):
        if type(self.id) is not str:
            raise ValueError('Cost query profile ID requires a string')
        _name(self.id, 'Cost query profile ID')
        expected = dict(subject='accepted_paid_hand_spell', local_basis='window_physical',
                        external_basis='window_live', minimum_basis='submitted_hand',
                        intrinsic_profile_id='cost.intrinsic.before-local-v1')
        if any(type(getattr(self, name)) is not str or getattr(self, name) != value
               for name, value in expected.items()):
            raise ValueError('Unsupported cost query profile policy')


@dataclass(frozen=True)
class RepeatCostFilter:
    """Inclusive numeric cost bounds, separate from a resource debit."""
    basis: str
    minimum: int | None = None
    maximum: int | None = None
    quote_profile_id: str | None = None

    def __post_init__(self):
        if type(self.basis) is not str or self.basis not in ('printed', 'local', 'submitted_quote', 'window_quote'):
            raise ValueError('Unsupported repeat cost basis')
        for name in ('minimum', 'maximum'):
            if getattr(self, name) is not None:
                _int(getattr(self, name), 'repeat cost '+name, 0)
        if self.minimum is None and self.maximum is None:
            raise ValueError('Repeat cost matching requires at least one bound')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('Repeat cost bounds are reversed')
        if self.basis == 'window_quote':
            if type(self.quote_profile_id) is not str:
                raise ValueError('Window cost matching requires a registered profile ID')
            _name(self.quote_profile_id, 'Repeat cost profile ID')
        elif self.quote_profile_id is not None:
            raise ValueError('Only window cost matching carries a query profile')


@dataclass(frozen=True)
class RepeatMatchSpec:
    recipient_metadata: RecipientMetadataFilter | None = None
    source_eligibility: RepeatSourceEligibility | None = None
    recipient_cost: RepeatCostFilter | None = None

    def __post_init__(self):
        if self.recipient_metadata is not None:
            if type(self.recipient_metadata) is not RecipientMetadataFilter:
                raise ValueError('Repeat matching requires RecipientMetadataFilter')
            self.recipient_metadata.__post_init__()
        if self.source_eligibility is not None:
            if type(self.source_eligibility) is not RepeatSourceEligibility:
                raise ValueError('Repeat source matching requires RepeatSourceEligibility')
            self.source_eligibility.__post_init__()
        if self.recipient_cost is not None:
            if type(self.recipient_cost) is not RepeatCostFilter:
                raise ValueError('Repeat cost matching requires RepeatCostFilter')
            self.recipient_cost.__post_init__()


@dataclass(frozen=True)
class SpellRepeatSpec:
    """Set a spell's effect execution count; overlapping declarations use max."""
    casts: int = 2
    class_mode: str = 'other'
    match: RepeatMatchSpec | None = None

    def __post_init__(self):
        _int(self.casts, 'spell execution count', 2)
        if type(self.class_mode) is not str or self.class_mode not in ('other', 'any'):
            raise ValueError('Unsupported spell repeat class scope')
        if self.match is not None:
            if type(self.match) is not RepeatMatchSpec:
                raise ValueError('Spell matching requires RepeatMatchSpec')
            self.match.__post_init__()


@dataclass(frozen=True)
class SpellRepeatModifier:
    id: int
    spec: SpellRepeatSpec
    source_id: int | None
    source_card_id: str | None
    created_turn: int
    uses_remaining: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _int(self.id, 'Spell modifier ID', 1)
        if type(self.spec) is not SpellRepeatSpec: raise ValueError('Invalid player spell specification')
        self.spec.__post_init__()
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player spell policies cannot require a physical board carrier')
        _optional_id(self.source_id, 'Spell modifier source')
        if (self.source_id is None) != (self.source_card_id is None): raise ValueError('Spell modifier source identity disagrees')
        if self.source_card_id is not None: _name(self.source_card_id, 'Spell modifier source card')
        _int(self.created_turn, 'Spell modifier creation', 1)
        if self.uses_remaining is not None: _int(self.uses_remaining, 'Spell modifier uses', 1)
        if self.expires_turn is not None: _int(self.expires_turn, 'Spell modifier expiry', self.created_turn)


@dataclass(frozen=True)
class SpellPolicyReceipt:
    id: int
    play_id: int
    hero_class: CardClass | None
    modifiers: tuple[SpellRepeatModifier, ...]

    def __post_init__(self):
        _int(self.id, 'spell receipt ID', 1); _int(self.play_id, 'spell receipt play', 1)
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Invalid captured spell hero class')
        if (type(self.modifiers) is not tuple or not self.modifiers or
                any(type(m) is not SpellRepeatModifier for m in self.modifiers)):
            raise ValueError('Spell receipt requires captured modifiers')
        for m in self.modifiers: m.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.modifiers,self.modifiers[1:])):
            raise ValueError('Spell receipt modifiers must preserve acquisition order')


@dataclass(frozen=True)
class SpellChoiceMemo:
    key: str
    selected_ids: tuple[str, ...]

    def __post_init__(self):
        _name(self.key, 'repeat choice key')
        if (type(self.selected_ids) is not tuple or
                any(type(i) is not str or not i.strip() for i in self.selected_ids) or
                len(set(self.selected_ids)) != len(self.selected_ids)):
            raise ValueError('Repeat choices require unique immutable option IDs')


@dataclass(frozen=True)
class SpellRepeatRecord:
    """Execution progress belonging to one paid play, never another play."""
    play_id: int
    target_id: int | None
    casts: int
    behavior_ids: tuple[str, ...]
    completed: int = 0
    running: bool = False
    finished: bool = False
    interrupted: bool = False
    choices: tuple[SpellChoiceMemo, ...] = ()

    def __post_init__(self):
        _int(self.play_id, 'repeat play ID', 1)
        _optional_id(self.target_id, 'repeat target')
        _int(self.casts, 'spell execution count', 2)
        _int(self.completed, 'completed spell executions', 0)
        for key in ('running', 'finished', 'interrupted'):
            _bool(getattr(self, key), 'repeat ' + key)
        if (self.completed > self.casts or self.running and self.completed == self.casts or
                self.finished and self.completed != self.casts or
                self.finished and self.interrupted or (self.finished or self.interrupted) and self.running):
            raise ValueError('Invalid repeat progress')
        if type(self.behavior_ids) is not tuple or any(type(b) is not str or not b for b in self.behavior_ids):
            raise ValueError('Repeat behaviors require immutable IDs')
        if type(self.choices) is not tuple or any(type(c) is not SpellChoiceMemo for c in self.choices):
            raise ValueError('Repeat choices require immutable memos')
        for choice in self.choices:
            choice.__post_init__()
        if len({c.key for c in self.choices}) != len(self.choices):
            raise ValueError('Duplicate repeat choice key')


@dataclass(frozen=True)
class CounterPolicySpec:
    kind: CardType
    uses: int = 1
    key: str | None = None

    def __post_init__(self):
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('Counter policies require a minion or spell kind')
        _int(self.uses, 'counter uses', 1)
        if self.key is not None:
            _name(self.key, 'counter refresh key')


@dataclass(frozen=True)
class TimedKeywordSpec:
    """A printed/granted flag lasting through a player's turn boundary."""

    keyword: Keyword
    boundary: str = 'turn_started'
    player: str = 'controller'
    occurrences: int = 1

    def __post_init__(self):
        if type(self.keyword) is not Keyword or self.keyword not in (
                Keyword.STEALTH, Keyword.TAUNT, Keyword.DIVINE_SHIELD,
                Keyword.CHARGE, Keyword.RUSH, Keyword.WINDFURY, Keyword.MEGA_WINDFURY, Keyword.IMMUNE, Keyword.IMMUNE_WHILE_ATTACKING,
                Keyword.POISONOUS, Keyword.LIFESTEAL, Keyword.REBORN, Keyword.ELUSIVE):
            raise ValueError('Timed keywords require a supported combat flag')
        if type(self.boundary) is not str or self.boundary not in ('turn_started', 'turn_ended'):
            raise ValueError('Invalid timed keyword boundary')
        if type(self.player) is not str or self.player not in ('controller', 'opponent'):
            raise ValueError('Invalid timed keyword player')
        _int(self.occurrences, 'timed keyword occurrences', 1)


@dataclass(frozen=True)
class KeywordExpiry:
    """An actual own-turn deadline bound once, independent of control changes."""

    player_id: int
    created_turn: int
    owner_turn_index: int
    boundary: str
    created_owner_turn_id: int | None = None

    def __post_init__(self):
        _int(self.player_id, 'keyword expiry player', 1)
        if self.player_id not in (1, 2): raise ValueError('Invalid keyword expiry player')
        _int(self.created_turn, 'keyword expiry creation turn', 1)
        _int(self.owner_turn_index, 'keyword expiry own-turn index', 1)
        _optional_id(self.created_owner_turn_id, 'keyword expiry creation interval')
        if type(self.boundary) is not str or self.boundary not in ('turn_started', 'turn_ended'):
            raise ValueError('Invalid keyword expiry boundary')


# Keep the existing private type identity while exposing its shared clock role.
OwnerTurnExpiry = KeywordExpiry


@dataclass(frozen=True)
class CurrentTurnFactQuery:
    """Closed current-interval public facts; no general event-log history query."""
    kind: str
    phase: str
    window: str
    origins: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in ('spell_cast', 'hero_attack'):
            raise ValueError('Unsupported current-turn fact kind')
        if type(self.window) is not str or self.window not in ('current_turn', 'owner_turn'):
            raise ValueError('Current-turn facts require an explicit interval window')
        if type(self.origins) is not tuple or any(type(o) is not str for o in self.origins) or len(set(self.origins)) != len(self.origins):
            raise ValueError('Current-turn origins require unique immutable names')
        if self.kind == 'spell_cast':
            if type(self.phase) is not str or self.phase not in ('attempt', 'payload_accepted', 'completed'):
                raise ValueError('Unsupported current-turn cast phase')
            if not self.origins or any(o not in ('hand', 'repeat', 'effect', 'draw', 'history') for o in self.origins):
                raise ValueError('Current-turn casts require explicit known origins')
        elif type(self.phase) is not str or self.phase != 'declared' or self.origins:
            raise ValueError('Hero current-turn facts currently support declarations only')


@dataclass(frozen=True)
class AttackPolicyCondition:
    """Pure current public facts. History and bound-source conditions are separate axes."""
    attribute: str
    comparison: str
    value: int
    board_scope: str | None = None
    board_presence: str | None = None
    turn_fact: CurrentTurnFactQuery | None = None

    def __post_init__(self):
        if type(self.attribute) is not str or self.attribute not in (
                'attack', 'health', 'damage', 'controller_armor',
                'controller_hand_size', 'controller_spell_damage', 'battlefield_minion_count', 'current_turn_fact_count'):
            raise ValueError('Unsupported attack policy condition attribute')
        if self.attribute == 'battlefield_minion_count':
            if type(self.board_scope) is not str or self.board_scope not in ('friendly', 'opponent', 'both'):
                raise ValueError('Battlefield count requires explicit owner scope')
            if type(self.board_presence) is not str or self.board_presence not in ('board_present', 'live', 'active'):
                raise ValueError('Battlefield count requires explicit presence policy')
        elif self.board_scope is not None or self.board_presence is not None:
            raise ValueError('Only battlefield count conditions carry board policies')
        if self.attribute == 'current_turn_fact_count':
            if type(self.turn_fact) is not CurrentTurnFactQuery:
                raise ValueError('Current-turn condition requires a typed fact query')
            self.turn_fact.__post_init__()
        elif self.turn_fact is not None:
            raise ValueError('Only current-turn conditions carry a turn fact query')
        if type(self.comparison) is not str or self.comparison not in ('lt', 'le', 'eq', 'ne', 'ge', 'gt'):
            raise ValueError('Unsupported attack policy condition comparison')
        _int(self.value, 'attack policy condition value', 0)


@dataclass(frozen=True)
class AttackPolicySpec:
    """A removable current attack restriction or maximum-total policy."""
    mode: str
    attacks_per_turn: int | None = None
    conditions: tuple[AttackPolicyCondition, ...] = ()

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in (
                'cannot_attack', 'cannot_attack_heroes', 'attacks_per_turn','friendly_ignore_taunt'):
            raise ValueError('Unsupported attack policy mode')
        if self.mode != 'attacks_per_turn' and self.attacks_per_turn is not None:
            raise ValueError('Only attack maximum policies specify a total')
        if self.attacks_per_turn is not None:
            _int(self.attacks_per_turn, 'maximum attacks per turn', 1)
        if type(self.conditions) is not tuple or any(type(c) is not AttackPolicyCondition for c in self.conditions):
            raise ValueError('Attack policy conditions require an immutable typed tuple')
        for condition in self.conditions:
            condition.__post_init__()
        if self.mode=='friendly_ignore_taunt' and self.conditions:
            raise ValueError('Friendly Taunt bypass requires an unconditional native provider')


@dataclass(frozen=True)
class BoardPresenceReference:
    """One original physical minion's uninterrupted board residence."""
    entity_id: int
    presence_id: int

    def __post_init__(self):
        _int(self.entity_id, 'board presence entity', 1)
        _int(self.presence_id, 'board presence identity', 1)

    @classmethod
    def capture(cls, state, entity_id):
        from .board_presence import capture_board_presence
        return capture_board_presence(state, entity_id)


@dataclass(frozen=True)
class AttackSourcePolicy:
    """Explicit current presence, captured-face and silence policies; no callback."""
    presence: str
    transform: str
    silence: str

    def __post_init__(self):
        if type(self.presence) is not str or self.presence not in ('board_present', 'live', 'active'):
            raise ValueError('Unsupported attack source presence policy')
        if type(self.transform) is not str or self.transform not in ('preserve', 'captured_epoch'):
            raise ValueError('Unsupported attack source transformation policy')
        if type(self.silence) is not str or self.silence not in ('ignore', 'requires_unsilenced'):
            raise ValueError('Unsupported attack source silence policy')


@dataclass(frozen=True)
class AttackSourceBinding:
    reference: BoardPresenceReference
    policy: AttackSourcePolicy
    captured_zone_epoch: int | None = None

    def __post_init__(self):
        if type(self.reference) is not BoardPresenceReference or type(self.policy) is not AttackSourcePolicy:
            raise ValueError('Attack source binding requires typed reference and policy')
        self.reference.__post_init__()
        self.policy.__post_init__()
        if self.policy.transform == 'captured_epoch':
            _int(self.captured_zone_epoch, 'attack source captured epoch', 0)
        elif self.captured_zone_epoch is not None:
            raise ValueError('Preserved source bindings do not carry a captured face epoch')

    @classmethod
    def capture(cls, state, entity_id, policy):
        if type(policy) is not AttackSourcePolicy:
            raise ValueError('Attack source capture requires AttackSourcePolicy')
        policy.__post_init__()
        reference = BoardPresenceReference.capture(state, entity_id)
        epoch = state.entities[entity_id].zone_epoch if policy.transform == 'captured_epoch' else None
        return cls(reference, policy, epoch)


@dataclass(frozen=True)
class PrintedAttackPolicyDeclaration:
    definition_id: str
    policy_index: int

    def __post_init__(self):
        _name(self.definition_id, 'printed attack declaration definition')
        _int(self.policy_index, 'printed attack declaration index', 0)


@dataclass(frozen=True)
class SelfPrintedAttackReference:
    carrier: BoardPresenceReference
    declaration: PrintedAttackPolicyDeclaration
    ability_id: int

    def __post_init__(self):
        if type(self.carrier) is not BoardPresenceReference or type(self.declaration) is not PrintedAttackPolicyDeclaration:
            raise ValueError('Self printed attack reference requires typed residence and declaration')
        self.carrier.__post_init__()
        self.declaration.__post_init__()
        _int(self.ability_id, 'original printed attack ability', 1)


@dataclass(frozen=True)
class PrintedAttackPermitRequest:
    reference: SelfPrintedAttackReference
    expires_owner_turn_id: int

    def __post_init__(self):
        if type(self.reference) is not SelfPrintedAttackReference:
            raise ValueError('Printed attack request requires typed original reference')
        self.reference.__post_init__()
        _int(self.expires_owner_turn_id, 'printed attack request owner turn', 1)


@dataclass(frozen=True)
class PrintedAttackPermit:
    declaration: PrintedAttackPolicyDeclaration
    permitted_ability_id: int
    expires_owner_turn_id: int

    def __post_init__(self):
        if type(self.declaration) is not PrintedAttackPolicyDeclaration:
            raise ValueError('Printed attack permit requires typed declaration')
        self.declaration.__post_init__()
        _int(self.permitted_ability_id, 'local printed attack ability', 1)
        _int(self.expires_owner_turn_id, 'printed attack permit owner turn', 1)


@dataclass(frozen=True)
class WeaponWearProfile:
    scope: str = 'self_weapon'
    window: str = 'pre_wear_current'
    presence: str = 'active_living'

    def __post_init__(self):
        if self.scope not in ('self_weapon','friendly_minion') or self.window not in ('pre_wear_current','combat_accept_original') or self.presence not in ('board_present','living','active_living'):
            raise ValueError('Unsupported closed weapon wear profile')
        if any(type(v)is not str for v in (self.scope,self.window,self.presence)):raise ValueError('Invalid wear profile types')


@dataclass(frozen=True)
class WeaponWearPredicate:
    kind: str
    value: str = ''
    presence: str = 'active_living'

    def __post_init__(self):
        if type(self.kind)is not str or type(self.value)is not str or self.kind not in ('defender_kind','friendly_tribe_present','own_turn'):
            raise ValueError('Unsupported weapon wear predicate')
        if self.presence not in ('board_present','living','active_living'):raise ValueError('Unsupported wear witness presence')
        if self.kind=='defender_kind' and self.value not in ('minion','hero'):raise ValueError('Invalid wear defender kind')
        if self.kind=='friendly_tribe_present' and (not self.value or self.value.lower()!=self.value):raise ValueError('Wear tribe requires normalized metadata')
        if self.kind=='own_turn' and self.value:raise ValueError('Own-turn predicate has no free operand')


@dataclass(frozen=True)
class WeaponWearSpec:
    mode: str
    profile: WeaponWearProfile = WeaponWearProfile()
    predicates: tuple[WeaponWearPredicate, ...] = ()
    priority: int = 0
    attack_loss: int = 1
    origin: str = 'combat_wear'

    def __post_init__(self):
        if type(self.mode)is not str or self.mode not in ('replace_with_attack','prevent_durability') or self.origin!='combat_wear':raise ValueError('Unsupported weapon wear mode/origin')
        if type(self.profile)is not WeaponWearProfile:raise ValueError('Expected closed typed wear profile')
        self.profile.__post_init__()
        if type(self.predicates)is not tuple or any(type(p)is not WeaponWearPredicate for p in self.predicates):raise ValueError('Wear predicates must be typed tuple')
        for p in self.predicates:p.__post_init__()
        _int(self.priority,'wear priority',0)
        if self.attack_loss!=1 or type(self.attack_loss)is not int:raise ValueError('Only fixed one attack wear replacement is supported')


@dataclass(frozen=True)
class PrintedWeaponWearDeclaration:
    card_id: str
    index: int

    def __post_init__(self):_name(self.card_id,'wear declaration card');_int(self.index,'wear declaration index',0)


@dataclass(frozen=True)
class WeaponWearRow:
    ability_id: int
    spec: WeaponWearSpec
    origin: str
    source_id: int | None
    expires_turn: int | None
    declaration: PrintedWeaponWearDeclaration | None
    consumed: bool
    grant_allocation: tuple[tuple[str, int | str], ...] | None

    def __post_init__(self):
        _int(self.ability_id,'wear ability',1)
        if type(self.spec)is not WeaponWearSpec:raise ValueError('Expected typed wear specification')
        self.spec.__post_init__()
        if self.origin not in ('printed','granted'):raise ValueError('Unknown wear row origin')
        _optional_id(self.source_id,'wear row source');_optional_id(self.expires_turn,'wear expiry')
        if self.declaration is not None:
            if type(self.declaration)is not PrintedWeaponWearDeclaration:raise ValueError('Expected printed wear declaration')
            self.declaration.__post_init__()
        if self.origin=='printed' and self.declaration is None:raise ValueError('Printed wear row lacks its declaration')
        _bool(self.consumed,'wear consumed row')
        if self.source_id is not None:
            from .allocation_facts import allocation_from_payload
            if allocation_from_payload(self.grant_allocation).entity_id!=self.source_id:raise ValueError('Wear grant lacks original issuer allocation')
        elif self.grant_allocation is not None:raise ValueError('Anonymous wear grant cannot carry issuer allocation')


@dataclass(frozen=True)
class WeaponWearCarrier:
    allocation: tuple[tuple[str, int | str], ...]
    health: int
    attack: int
    durability: int
    doomed: bool
    active: bool
    silenced: bool
    presence_id: int | None
    tribes: tuple[str, ...] | None
    rows: tuple[WeaponWearRow, ...]
    tribe_changes: tuple[Enchantment, ...]
    tribe_exclusions: tuple[str, ...]

    def __post_init__(self):
        from .allocation_facts import allocation_from_payload
        allocation_from_payload(self.allocation).__post_init__()
        _int(self.health,'wear carrier health')
        _int(self.attack,'wear carrier attack',0);_int(self.durability,'wear carrier durability')
        for n in ('doomed','active','silenced'):_bool(getattr(self,n),'wear carrier '+n)
        _optional_id(self.presence_id,'wear board residence')
        if self.tribes is not None and (type(self.tribes)is not tuple or any(type(x)is not str for x in self.tribes)):raise ValueError('Invalid wear metadata tribes')
        _tribe_changes(self.tribe_changes)
        from .tribes import TribeState
        if self.tribes is not None:
            TribeState(self.tribes, self.tribe_exclusions)
        elif self.tribe_exclusions:
            raise ValueError('Unknown tribes cannot have concrete exclusions')
        if type(self.tribe_exclusions) is not tuple:
            raise ValueError('Wear tribe exclusions require a typed tuple')
        if type(self.rows)is not tuple or any(type(x)is not WeaponWearRow for x in self.rows):raise ValueError('Invalid complete wear rows')
        for x in self.rows:x.__post_init__()
        ids=[x.ability_id for x in self.rows]
        if ids!=sorted(set(ids)):raise ValueError('Wear rows must be unique in attachment order')


@dataclass(frozen=True)
class WeaponWearInputs:
    record_id: int
    player_id: int
    active_player: int
    turn: int
    owner_turn_id: int
    action_number: int
    root_action_number: int
    event_cursor: int
    next_attachment_id: int
    defender_kind: CardType
    hero_allocation: tuple[tuple[str, int | str], ...]
    weapon: WeaponWearCarrier
    board: tuple[WeaponWearCarrier, ...]

    def __post_init__(self):
        for n in ('record_id','turn','owner_turn_id','next_attachment_id'):_int(getattr(self,n),'wear '+n,1)
        for n in ('action_number','root_action_number','event_cursor'):_int(getattr(self,n),'wear '+n,0)
        if self.player_id not in (1,2) or self.active_player not in (1,2) or type(self.player_id)is not int or type(self.active_player)is not int:raise ValueError('Invalid wear player')
        if type(self.defender_kind)is not CardType or self.defender_kind not in (CardType.MINION,CardType.HERO):raise ValueError('Invalid accepted wear defender kind')
        if type(self.weapon)is not WeaponWearCarrier or type(self.board)is not tuple or any(type(x)is not WeaponWearCarrier for x in self.board):raise ValueError('Wear inputs require complete typed carriers')
        self.weapon.__post_init__()
        from .allocation_facts import allocation_from_payload
        allocation_from_payload(self.hero_allocation).__post_init__()
        for x in self.board:x.__post_init__()


@dataclass(frozen=True)
class WeaponWearDecision:
    entity_id: int
    ability_id: int
    eligible: bool

    def __post_init__(self):_int(self.entity_id,'wear decision source',1);_int(self.ability_id,'wear decision ability',1);_bool(self.eligible,'wear decision')


@dataclass(frozen=True)
class WeaponWearPlan:
    decisions: tuple[WeaponWearDecision, ...]
    replacement: tuple[int,int] | None
    preventions: tuple[tuple[int,int], ...]
    axis: str
    amount: int

    def __post_init__(self):
        if type(self.decisions)is not tuple or any(type(x)is not WeaponWearDecision for x in self.decisions):raise ValueError('Expected complete wear decision rows')
        for x in self.decisions:x.__post_init__()
        def key(x):
            if type(x)is not tuple or len(x)!=2:raise ValueError('Invalid wear source key')
            for v in x:_int(v,'wear source key',1)
        if self.replacement is not None:key(self.replacement)
        if type(self.preventions)is not tuple:raise ValueError('Expected prevention tuple')
        for x in self.preventions:key(x)
        if self.axis not in ('durability','attack'):raise ValueError('Invalid wear loss axis')
        _int(self.amount,'wear amount',0)
        if self.amount>1:raise ValueError('Unsupported wear amount')


@dataclass(frozen=True)
class WeaponWearReceipt:
    current: WeaponWearInputs
    plan: WeaponWearPlan
    durability_before: int
    durability_after: int
    attack_before: int
    attack_after: int
    attack_enchantment_id: int | None
    original_stale: bool
    event_cursor: int

    def __post_init__(self):
        if type(self.current)is not WeaponWearInputs or type(self.plan)is not WeaponWearPlan:raise ValueError('Invalid typed wear receipt')
        self.current.__post_init__();self.plan.__post_init__()
        for n in ('durability_before','durability_after'):_int(getattr(self,n),'wear '+n)
        for n in ('attack_before','attack_after','event_cursor'):_int(getattr(self,n),'wear '+n,0)
        _optional_id(self.attack_enchantment_id,'wear attack attachment');_bool(self.original_stale,'wear stale')


@dataclass(frozen=True)
class NativeSourceCondition:
    kind: str
    max_hand: int | None = None

    def __post_init__(self):
        if type(self.kind)is not str or self.kind not in('self_damaged','controller_hand_at_most'):
            raise ValueError('Unsupported native provider condition')
        if self.kind=='controller_hand_at_most':_int(self.max_hand,'native source hand limit',0)
        elif self.max_hand is not None:raise ValueError('Only hand-size qualifications carry a threshold')


@dataclass(frozen=True)
class HandMirrorSpec:
    attack: int = 3
    health: int = 4

    def __post_init__(self):
        _int(self.attack,'hand mirror attack',0);_int(self.health,'hand mirror health',1)


@dataclass(frozen=True)
class HandMirrorBinding:
    declaring_card_id: str
    player_id: int
    play_id: int | None = None

    def __post_init__(self):
        _name(self.declaring_card_id,'native hand mirror origin')
        if type(self.player_id)is not int or self.player_id not in(1,2):raise ValueError('Hand mirror requires its original controller')
        _optional_id(self.play_id,'hand mirror committed play')


@dataclass(frozen=True)
class NativeDeathrattleSpec:
    kind: str
    card_id: str | None = None
    attack: int = 0
    health: int = 0

    def __post_init__(self):
        if self.kind not in ('summon_growth', 'draw_link', 'discard_link'):
            raise ValueError('Unknown native Deathrattle memory profile')
        _int(self.attack, 'native summon base Attack', 0)
        _int(self.health, 'native summon base Health', 0)
        if self.kind == 'summon_growth':
            _name(self.card_id, 'native Deathrattle summon card')
            if self.health < 1:raise ValueError('Native summon requires positive initial Health')
        elif self.card_id is not None or self.attack or self.health:
            raise ValueError('Native linkage cannot carry summon material')


@dataclass(frozen=True)
class RememberedDraw:
    draw_id: int
    entity_id: int
    hand_entry_id: int
    source_id: int

    def __post_init__(self):
        for name in ('draw_id','entity_id','hand_entry_id','source_id'):
            _int(getattr(self,name), 'remembered draw '+name, 1)


@dataclass(frozen=True)
class DeathrattleMemory:
    spec: NativeDeathrattleSpec
    growth_steps: int = 0
    draws: tuple[RememberedDraw, ...] = ()
    discard_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.spec) is not NativeDeathrattleSpec:raise ValueError('Native memory requires its complete printed profile')
        self.spec.__post_init__();_int(self.growth_steps,'native summon growth steps',0)
        if type(self.draws) is not tuple or any(type(x) is not RememberedDraw for x in self.draws):
            raise ValueError('Native draw memory requires immutable physical draw links')
        for item in self.draws:item.__post_init__()
        if (self.spec.kind=='summon_growth'and self.draws or self.spec.kind=='draw_link'and self.growth_steps):
            raise ValueError('Native Deathrattle memory mixed unrelated payloads')
        ids=tuple(x.draw_id for x in self.draws)
        if ids!=tuple(sorted(set(ids))):raise ValueError('Remembered draws must retain their original unique order')
        if type(self.discard_ids) is not tuple or any(type(i) is not int or i < 1 for i in self.discard_ids):
            raise ValueError('Discard memory requires immutable positive occurrence identities')
        if self.discard_ids != tuple(sorted(set(self.discard_ids))):
            raise ValueError('Remembered discards must retain their original unique order')
        if (self.spec.kind != 'discard_link' and self.discard_ids or
                self.spec.kind == 'discard_link' and (self.draws or self.growth_steps)):
            raise ValueError('Native discard memory cannot mix unrelated payloads')


@dataclass(frozen=True)
class SpellBaseDamageValue:
    """A generated spell's native number, tied to its genuine death source."""
    card_id: str
    amount: int
    deathrattle_id: int

    def __post_init__(self):
        _name(self.card_id,'native spell value face')
        _int(self.amount,'native spell base damage',0)
        _int(self.deathrattle_id,'native spell original Deathrattle',1)


@dataclass(frozen=True)
class AbilityInstance:
    """A printed or granted ability with serializable identity and usage state."""

    id: int
    kind: str
    source_id: int | None = None
    origin: str = "granted"
    keyword: Keyword | None = None
    behavior_id: str | None = None
    event: str | None = None
    attack: int = 0
    include_self: bool = False
    consumed: bool = False
    expires_turn: int | None = None
    remove_on_silence: bool = True
    spell_damage: int = 0
    health: int = 0
    cost_aura: CostAuraSpec | None = None
    health_rule: HealthRule | None = None
    health_rule_expiry: OwnerTurnExpiry | None = None
    activation: ActivatedAbilitySpec | None = None
    limited_trigger: LimitedTriggerSpec | None = None
    uses_remaining: int | None = None
    trigger_turn: int | None = None
    hand_progress: HandProgressSpec | None = None
    defining_card_id: str | None = None
    progress_value: int = 0
    progress_completions: int = 0
    progress_keys: tuple[str, ...] = ()
    progress_units: tuple[int, ...] = ()
    magnetic_id: int | None = None
    adjacent_only: bool = False
    deck_sacrifice: DeckSacrificeSpec | None = None
    keyword_aura: KeywordAuraSpec | None = None
    battlecry_repeat: BattlecryRepeatSpec | None = None
    deathrattle_repeat: DeathrattleRepeatSpec | None = None
    combo_repeat: ComboRepeatSpec | None = None
    spell_repeat: SpellRepeatSpec | None = None
    health_loss_replacement: HealthLossReplacementSpec | None = None
    health_loss_floor: HealthLossFloorSpec | None = None
    summon_quantity: SummonQuantitySpec | None = None
    weapon_wear_policy: WeaponWearSpec | None = None
    weapon_wear_declaration: PrintedWeaponWearDeclaration | None = None
    battlecry_card_id: str | None = None
    combo_card_id: str | None = None
    counter_policy: CounterPolicySpec | None = None
    timed_keyword: TimedKeywordSpec | None = None
    keyword_expiry: KeywordExpiry | None = None
    deathrattle_card_id: str | None = None
    deathrattle_grant_card_id: str | None = None
    hero_power_repeat: HeroPowerRepeatSpec | None = None
    end_turn: EndTurnSpec | None = None
    end_turn_repeat: EndTurnRepeatSpec | None = None
    attack_policy: AttackPolicySpec | None = None
    attack_source_binding: AttackSourceBinding | None = None
    attack_policy_declaration: PrintedAttackPolicyDeclaration | None = None
    printed_attack_permit: PrintedAttackPermit | None = None
    stat_relation: StatRelationSpec | None = None
    cthun_ritual: CthunRitualStamp | None = None
    aura_target: str = 'friendly_minions'
    aura_condition: str = 'always'
    aura_tribes_any: tuple[str, ...] = ()
    spell_damage_schools: tuple[SpellSchool, ...] = ()
    aura_card_ids: tuple[str, ...] = ()
    reborn_policy: str | None = None
    hero_power_use_aura: HeroPowerUseAuraSpec | None = None
    hand_mirror: HandMirrorBinding | None = None
    native_condition: NativeSourceCondition | None = None
    deathrattle_memory: DeathrattleMemory | None = None
    corpse_gain_card_id: str | None = None
    turn_draw_card_id: str | None = None
    spell_base_value: SpellBaseDamageValue | None = None

    def __post_init__(self) -> None:
        _int(self.id, "ability ID", 1)
        if self.kind=='turn_draw_suppression':
            _name(self.turn_draw_card_id,'native turn draw declaration')
            from dataclasses import fields
            allowed={'id','kind','source_id','origin','turn_draw_card_id'}
            if self.origin!='printed'or self.source_id is None or any(getattr(self,f.name)!=f.default for f in fields(self)if f.name not in allowed):
                raise ValueError('Turn draw suppression requires one removable native printed source')
        elif self.turn_draw_card_id is not None:raise ValueError('Only turn draw suppression carries its declaration')
        if self.kind=='spell_base_value':
            if type(self.spell_base_value)is not SpellBaseDamageValue:raise ValueError('Native spell requires its complete typed base value')
            self.spell_base_value.__post_init__()
            from dataclasses import fields
            allowed={'id','kind','source_id','origin','spell_base_value'}
            if self.origin!='granted'or self.source_id is None or any(getattr(self,f.name)!=f.default for f in fields(self)if f.name not in allowed):
                raise ValueError('Native spell value cannot mix unrelated ability material')
        elif self.spell_base_value is not None:raise ValueError('Only native spell values carry base damage material')
        if self.kind == 'corpse_gain':
            _name(self.corpse_gain_card_id, 'native corpse gain card')
            if self.origin != 'printed' or self.source_id is None or not self.remove_on_silence:
                raise ValueError('Corpse gain requires a removable native physical source')
            from dataclasses import fields
            allowed = {'id', 'kind', 'source_id', 'origin', 'corpse_gain_card_id'}
            if any(getattr(self, f.name) != f.default for f in fields(self) if f.name not in allowed):
                raise ValueError('Corpse gain source cannot carry an unrelated ability profile')
        elif self.corpse_gain_card_id is not None:
            raise ValueError('Only corpse gain sources carry their native declaration')
        if self.deathrattle_memory is not None:
            if type(self.deathrattle_memory) is not DeathrattleMemory:
                raise ValueError('Expected typed native Deathrattle memory')
            self.deathrattle_memory.__post_init__()
            if (self.kind!='deathrattle'or self.origin!='printed'or self.source_id is None or
                    self.expires_turn is not None or self.consumed or not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Native Deathrattle memory requires removable unconsumed printed provenance')
        if self.kind == 'board_full_awaken':
            from dataclasses import fields
            allowed = {'id', 'kind', 'source_id', 'origin'}
            if (self.origin != 'printed' or self.source_id is None or
                    any(getattr(self, f.name) != f.default for f in fields(self) if f.name not in allowed)):
                raise ValueError('Full-board awakening requires an unconsumed removable native declaration')
        if self.native_condition is not None:
            from .native_conditions import leaf
            if (self.kind!=leaf(self.native_condition)or self.origin!='printed'or self.source_id is None or
                    self.expires_turn is not None or self.consumed or not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Conditional provider requires removable unconsumed native printed provenance')
        if self.hand_mirror is not None:
            from dataclasses import fields
            if type(self.hand_mirror)is not HandMirrorBinding:raise ValueError('Hand mirror requires its complete native binding')
            self.hand_mirror.__post_init__()
            allowed={'id','kind','source_id','origin','hand_mirror'}
            if (self.kind!='hand_mirror'or self.origin!='printed'or self.source_id is None or
                    any(getattr(self,f.name)!=f.default for f in fields(self)if f.name not in allowed)):
                raise ValueError('Hand mirror requires a pure native source')
        elif self.kind=='hand_mirror':raise ValueError('Hand mirror lost its native binding')
        validate_reborn_policy(self.reborn_policy, self.keyword)
        if self.reborn_policy is not None and (self.kind != 'keyword' or self.origin not in ('granted','printed') or
                self.remove_on_silence is not True or self.timed_keyword is not None or
                self.origin == 'printed' and (self.source_id is None or self.expires_turn is not None)):
            raise ValueError('Full-health Reborn requires a removable keyword grant or native declaration')
        if self.kind == 'cleave':
            from dataclasses import fields
            allowed = {'id', 'kind', 'source_id', 'origin'}
            if (self.origin != 'printed' or self.source_id is None or
                    any(getattr(self, f.name) != f.default for f in fields(self) if f.name not in allowed)):
                raise ValueError('Cleave requires a pure native removable declaration')
        if self.cthun_ritual is not None:
            if type(self.cthun_ritual) is not CthunRitualStamp:
                raise ValueError('Cthun Taunt requires its typed original ritual stamp')
            self.cthun_ritual.__post_init__()
            if (self.kind != 'keyword' or self.keyword != Keyword.TAUNT or
                    self.origin != 'granted' or self.remove_on_silence):
                raise ValueError('Cthun ritual ability requires permanent granted Taunt')
            from dataclasses import fields
            allowed = {'id', 'kind', 'keyword', 'origin', 'remove_on_silence', 'cthun_ritual'}
            if any(getattr(self, f.name) != f.default for f in fields(self) if f.name not in allowed):
                raise ValueError('Cthun Taunt cannot carry other ability state')
        if self.kind == 'stat_relation':
            if type(self.stat_relation) is not StatRelationSpec:
                raise ValueError('Stat relation requires a typed specification')
            self.stat_relation.__post_init__()
            if self.magnetic_id is not None or not self.remove_on_silence:
                raise ValueError('Stat relations require removable non-fusion lifecycle')
            if self.stat_relation.operand == StatRelationOperand.SELF_DAMAGED and self.origin != 'printed':
                raise ValueError('Self-damaged attack currently requires a printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_HAS_WEAPON and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Weapon-presence attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_OPPONENT_TURN and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Opponent-turn Attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_DISCARD_COUNT and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Discard-count attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_DECK_COUNT and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Deck-count attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_ARMOR and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Controller-armor weapon Attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Other battlefield tribe Attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_OVERLOADED_MANA and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Overload weapon Attack requires an active native printed declaration')
            if self.stat_relation.operand == StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE and (
                    self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or self.consumed):
                raise ValueError('Spell Damage weapon Attack requires an active native printed declaration')
        elif self.stat_relation is not None:
            raise ValueError('Only stat relation abilities carry StatRelationSpec')
        if self.attack_policy_declaration is not None:
            if self.kind != 'attack_policy' or type(self.attack_policy_declaration) is not PrintedAttackPolicyDeclaration:
                raise ValueError('Only attack policies carry a printed declaration')
            self.attack_policy_declaration.__post_init__()
        if self.kind == 'attack_policy' and self.origin == 'printed' and self.attack_policy_declaration is None:
            raise ValueError('Printed attack policy requires its exact declaration')
        if self.kind == 'printed_attack_permit':
            if type(self.printed_attack_permit) is not PrintedAttackPermit:
                raise ValueError('Printed attack permit requires its typed payload')
            self.printed_attack_permit.__post_init__()
            if self.origin != 'granted' or self.expires_turn is None or not self.remove_on_silence or self.magnetic_id is not None:
                raise ValueError('Printed attack permit requires temporary local granted lifecycle')
        elif self.printed_attack_permit is not None:
            raise ValueError('Only printed attack permits carry their payload')
        if self.kind == 'attack_policy':
            if type(self.attack_policy) is not AttackPolicySpec:
                raise ValueError('Attack policy ability requires AttackPolicySpec')
            self.attack_policy.__post_init__()
        elif self.attack_policy is not None:
            raise ValueError('Only attack policy abilities carry AttackPolicySpec')
        if self.attack_source_binding is not None:
            if self.kind != 'attack_policy' or type(self.attack_source_binding) is not AttackSourceBinding:
                raise ValueError('Only attack policy abilities carry AttackSourceBinding')
            self.attack_source_binding.__post_init__()
            if self.origin != 'granted' or self.source_id != self.attack_source_binding.reference.entity_id:
                raise ValueError('Bound attack grant must identify its original physical source')
        if self.end_turn is not None:
            if type(self.end_turn) is not EndTurnSpec:
                raise ValueError('Expected EndTurnSpec')
            self.end_turn.__post_init__()
            if self.kind not in ('trigger', 'dormant_trigger') or self.event != 'turn_ended':
                raise ValueError('Only turn_ended trigger abilities carry EndTurnSpec')
        for name in ('deathrattle_card_id', 'deathrattle_grant_card_id'):
            value = getattr(self, name)
            if value is not None:
                _name(value, name)
                if self.kind != 'deathrattle': raise ValueError('Only Deathrattles carry declaration/grant provenance')
        if self.kind == 'deathrattle' and self.origin == 'printed' and self.deathrattle_card_id is None:
            raise ValueError('Printed Deathrattle requires its declaration card')
        if self.deathrattle_grant_card_id is not None and (self.origin != 'granted' or self.source_id is None):
            raise ValueError('Deathrattle grant provenance requires an identified grant')
        if self.kind=='deathrattle' and self.origin=='granted' and self.source_id is not None and self.deathrattle_grant_card_id is None:
            raise ValueError('Identified Deathrattle grant requires its captured source card')
        if self.timed_keyword is not None:
            if type(self.timed_keyword) is not TimedKeywordSpec:
                raise ValueError('Expected TimedKeywordSpec')
            self.timed_keyword.__post_init__()
            if self.kind != 'keyword' or self.keyword != self.timed_keyword.keyword or self.expires_turn is not None:
                raise ValueError('Timed keyword must match its flag and use only one expiry policy')
            if self.keyword_expiry is not None:
                if type(self.keyword_expiry) is not KeywordExpiry:
                    raise ValueError('Expected KeywordExpiry')
                self.keyword_expiry.__post_init__()
                if self.keyword_expiry.boundary != self.timed_keyword.boundary:
                    raise ValueError('Timed keyword and deadline boundaries disagree')
        elif self.keyword_expiry is not None:
            raise ValueError('Keyword expiry requires a timed keyword specification')
        if self.kind == 'combo': _name(self.combo_card_id, 'Combo declaration card')
        elif self.combo_card_id is not None: raise ValueError('Only Combo abilities have a Combo declaration card')
        if self.kind == 'battlecry':
            _name(self.battlecry_card_id, 'Battlecry declaration card')
        elif self.battlecry_card_id is not None:
            raise ValueError('Only Battlecry abilities have a declaration card')
        _optional_id(self.magnetic_id, 'magnetic group')
        _optional_id(self.source_id, "ability source_id")
        _optional_id(self.expires_turn, "ability expires_turn")
        if not isinstance(self.kind, str) or self.kind not in {"keyword", "trigger", "limited_trigger", "counter_policy", "hand_progress", "defining_hand_source", "hand_mirror", "deathrattle", "aura", "battlecry", "combo", "on_play", "on_use", "on_launch", "on_awaken", "dormant_trigger", "board_full_awaken", "spell_damage", "cost_aura", "health_rule", "activated", "deck_sacrifice", "keyword_aura", "spell_repeat", "card_spell_repeat", "battlecry_repeat", "deathrattle_repeat", "hero_power_repeat", "end_turn_repeat", "combo_repeat", "health_loss_replacement", "health_loss_floor", "rewind_retention", "choose_both", "attack_policy", "printed_attack_permit", "stat_relation", "weapon_wear_policy", "summon_quantity", "cleave", "on_discard", "on_destroyed"}:
            if self.kind not in ('hero_power_use_aura', 'corpse_gain', 'turn_draw_suppression', 'spell_base_value'):
                raise ValueError("unsupported ability kind")
        if self.kind == 'hero_power_use_aura':
            if type(self.hero_power_use_aura) is not HeroPowerUseAuraSpec:
                raise ValueError('Native Hero Power use aura requires its complete declaration')
            self.hero_power_use_aura.__post_init__()
            if (self.origin != 'printed' or self.expires_turn is not None or
                    not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Hero Power use aura requires a removable ordinary native source')
        elif self.hero_power_use_aura is not None:
            raise ValueError('Only Hero Power use auras carry their cap declaration')
        if self.kind in ('on_discard', 'on_destroyed'):
            if self.origin != 'printed' or self.source_id is None or self.remove_on_silence is not True:
                raise ValueError('Own-discard body requires a removable native declaration')
            from dataclasses import fields
            allowed = {'id','kind','source_id','origin','behavior_id','remove_on_silence'}
            if any(getattr(self,f.name) != f.default for f in fields(self) if f.name not in allowed):
                raise ValueError('Own-discard declaration cannot carry another ability profile')
        if self.kind == 'end_turn_repeat':
            if type(self.end_turn_repeat) is not EndTurnRepeatSpec:
                raise ValueError('End-turn repeat requires EndTurnRepeatSpec')
            self.end_turn_repeat.__post_init__()
        elif self.end_turn_repeat is not None:
            raise ValueError('Only end-turn repeat abilities carry EndTurnRepeatSpec')
        if self.kind == 'hero_power_repeat':
            if type(self.hero_power_repeat) is not HeroPowerRepeatSpec:
                raise ValueError('Hero power repeat requires HeroPowerRepeatSpec')
            self.hero_power_repeat.__post_init__()
        elif self.hero_power_repeat is not None:
            raise ValueError('Only hero power repeat abilities carry HeroPowerRepeatSpec')
        if self.kind == 'summon_quantity':
            if type(self.summon_quantity) is not SummonQuantitySpec:raise ValueError('Typed summon quantity specification required')
            self.summon_quantity.__post_init__()
        elif self.summon_quantity is not None:raise ValueError('Quantity specification on another ability kind')
        if self.kind == 'health_loss_floor':
            if type(self.health_loss_floor) is not HealthLossFloorSpec:
                raise ValueError('Health loss floor requires its typed specification')
            self.health_loss_floor.__post_init__()
        elif self.health_loss_floor is not None:
            raise ValueError('Only health loss floor abilities carry their specification')
        if self.kind == 'weapon_wear_policy':
            if type(self.weapon_wear_policy)is not WeaponWearSpec:raise ValueError('Expected typed wear policy')
            self.weapon_wear_policy.__post_init__()
            if self.weapon_wear_declaration is not None:
                if type(self.weapon_wear_declaration)is not PrintedWeaponWearDeclaration:raise ValueError('Expected printed wear declaration')
                self.weapon_wear_declaration.__post_init__()
            if self.origin=='printed' and self.weapon_wear_declaration is None:raise ValueError('Printed wear policy lacks identity')
        elif self.weapon_wear_policy is not None or self.weapon_wear_declaration is not None:raise ValueError('Wear fields on another ability kind')
        if self.kind == 'health_loss_replacement':
            if type(self.health_loss_replacement) is not HealthLossReplacementSpec:
                raise ValueError('Health loss replacement requires a specification')
            self.health_loss_replacement.__post_init__()
        elif self.health_loss_replacement is not None:
            raise ValueError('Only health loss replacements carry their specification')
        if self.kind == 'deathrattle_repeat':
            if type(self.deathrattle_repeat) is not DeathrattleRepeatSpec:
                raise ValueError('Deathrattle repetition requires its specification')
            self.deathrattle_repeat.__post_init__()
        elif self.deathrattle_repeat is not None:
            raise ValueError('Only Deathrattle repeat abilities carry a repeat specification')
        if self.kind == 'battlecry_repeat':
            if type(self.battlecry_repeat) is not BattlecryRepeatSpec:
                raise ValueError('Battlecry repeat requires BattlecryRepeatSpec')
            self.battlecry_repeat.__post_init__()
        elif self.battlecry_repeat is not None:
            raise ValueError('Only Battlecry repeat auras carry BattlecryRepeatSpec')
        if self.kind == 'combo_repeat':
            if type(self.combo_repeat) is not ComboRepeatSpec:
                raise ValueError('Combo repeat requires ComboRepeatSpec')
            self.combo_repeat.__post_init__()
        elif self.combo_repeat is not None:
            raise ValueError('Only Combo repeat auras carry ComboRepeatSpec')
        if self.kind in ('spell_repeat','card_spell_repeat'):
            if type(self.spell_repeat) is not SpellRepeatSpec:
                raise ValueError('Spell repeat requires SpellRepeatSpec')
            self.spell_repeat.__post_init__()
        elif self.spell_repeat is not None:
            raise ValueError('Only spell repeat auras or card attachments carry SpellRepeatSpec')
        if self.kind=='card_spell_repeat' and (self.spell_repeat.class_mode!='any' or self.spell_repeat.match is not None or
                self.origin!='granted' or self.consumed or not self.remove_on_silence or self.magnetic_id is not None):
            raise ValueError('Card spell repeats require active unconditional removable grants')
        _spell_damage_school_selector(self.spell_damage_schools)
        if self.spell_damage_schools and (self.kind != 'spell_damage' or self.spell_damage <= 0 or
                self.origin != 'printed' or self.source_id is None or self.consumed or
                self.expires_turn is not None or not self.remove_on_silence or self.magnetic_id is not None):
            raise ValueError('School spell damage requires a positive native removable minion declaration')
        if self.kind == 'keyword_aura':
            if type(self.keyword_aura) is not KeywordAuraSpec:
                raise ValueError('Keyword aura requires KeywordAuraSpec')
            self.keyword_aura.__post_init__()
            if (self.keyword_aura.condition != 'always' or self.keyword_aura.tribes_any or self.keyword_aura.card_ids) and (self.origin != 'printed' or
                    self.source_id is None or self.expires_turn is not None or self.consumed or
                    not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Conditional self keywords require native removable non-fusion declarations')
        elif self.keyword_aura is not None:
            raise ValueError('Only keyword auras carry KeywordAuraSpec')
        if self.kind == 'deck_sacrifice':
            if type(self.deck_sacrifice) is not DeckSacrificeSpec:
                raise ValueError('Deck sacrifice aura requires DeckSacrificeSpec')
            self.deck_sacrifice.__post_init__()
        elif self.deck_sacrifice is not None:
            raise ValueError('Only deck sacrifice auras carry DeckSacrificeSpec')
        _int(self.progress_value, 'hand progress value', 0)
        _int(self.progress_completions, 'hand progress completions', 0)
        if type(self.progress_keys) is not tuple or any(type(k) is not str or not k for k in self.progress_keys):
            raise ValueError('Progress witnesses must be immutable keys')
        if len(set(self.progress_keys)) != len(self.progress_keys):
            raise ValueError('Duplicate progress witness')
        if type(self.progress_units) is not tuple or len(self.progress_units) != len(self.progress_keys):
            raise ValueError('Progress witnesses require matching immutable unit counts')
        for units in self.progress_units:
            _int(units, 'progress witness units', 1)
        for key in self.progress_keys:
            prefix, separator, number = key.partition(':')
            if prefix not in ('play', 'death', 'event', 'cast') or separator != ':' or not number.isascii() or not number.isdigit() or str(int(number)) != number or int(number) < 1:
                raise ValueError('Invalid progress witness key')
        if self.kind in ('hand_progress', 'defining_hand_source'):
            if type(self.hand_progress) is not HandProgressSpec:
                raise ValueError('Hand progress requires a specification')
            self.hand_progress.__post_init__()
            if self.hand_progress.amount_basis == 'one' and any(units != 1 for units in self.progress_units):
                raise ValueError('Unit progress requires one unit per witness')
            if (self.progress_value > self.hand_progress.goal or
                    self.consumed != (self.progress_value == self.hand_progress.goal) or
                    self.consumed and (self.hand_progress.repeat or self.progress_completions == 0) or
                    self.progress_completions > len(self.progress_keys) or
                    self.progress_value > sum(self.progress_units)):
                raise ValueError('Invalid hand progress state')
        elif self.hand_progress is not None or self.progress_value or self.progress_completions or self.progress_keys or self.progress_units:
            raise ValueError('Only hand progress abilities carry progress state')
        if self.kind == 'defining_hand_source':
            validate_defining_hand_spec(self.hand_progress)
            if type(self.defining_card_id) is not str:
                raise ValueError('Defining source requires its original card identity')
            _name(self.defining_card_id, 'defining source card')
            if (self.origin != 'printed' or self.source_id is None or self.expires_turn is not None or
                    not self.remove_on_silence or self.magnetic_id is not None or self.consumed or
                    self.progress_value or self.progress_completions != len(self.progress_keys) or
                    any(not k.startswith('event:') for k in self.progress_keys)):
                raise ValueError('Invalid native defining source binding')
        elif self.defining_card_id is not None:
            raise ValueError('Only a native defining source carries an original card identity')
        if self.kind == 'limited_trigger':
            if type(self.limited_trigger) is not LimitedTriggerSpec:
                raise ValueError('Limited trigger ability requires a specification')
            self.limited_trigger.__post_init__()
            _int(self.uses_remaining, 'remaining trigger uses', 0)
            if self.limited_trigger.reset == 'turn':
                _int(self.trigger_turn, 'finite trigger actual turn', 1)
            elif self.trigger_turn is not None:
                raise ValueError('Instance-global triggers cannot carry a turn budget')
            if self.uses_remaining > self.limited_trigger.uses or self.consumed != (self.uses_remaining == 0):
                raise ValueError('Invalid limited trigger consumption')
        elif self.limited_trigger is not None:
            raise ValueError('Only limited triggers carry LimitedTriggerSpec')
        if self.kind != 'limited_trigger' and self.trigger_turn is not None:
            raise ValueError('Only finite triggers carry a trigger turn')
        if self.kind == 'counter_policy':
            if type(self.counter_policy) is not CounterPolicySpec:
                raise ValueError('Counter ability requires CounterPolicySpec')
            self.counter_policy.__post_init__()
            _int(self.uses_remaining, 'remaining counter uses', 0)
            if self.uses_remaining > self.counter_policy.uses or self.consumed != (self.uses_remaining == 0):
                raise ValueError('Invalid counter policy consumption')
            if self.origin != 'granted' or not self.remove_on_silence:
                raise ValueError('Counter policies must be removable grants')
        elif self.counter_policy is not None:
            raise ValueError('Only counter abilities carry CounterPolicySpec')
        if self.kind not in ('counter_policy', 'limited_trigger') and self.uses_remaining is not None:
            raise ValueError('Only finite trigger/counter abilities carry usage state')
        if self.kind == 'activated':
            if type(self.activation) is not ActivatedAbilitySpec:
                raise ValueError('Activated ability requires an activation spec')
            self.activation.__post_init__()
        elif self.activation is not None:
            raise ValueError('Only activated abilities may carry an activation spec')
        if self.kind == 'health_rule':
            if not isinstance(self.health_rule, HealthRule):
                raise ValueError('Health rule ability requires HealthRule')
            self.health_rule.__post_init__()
        elif self.health_rule is not None:
            raise ValueError('Only health_rule abilities may specify health_rule')
        if self.health_rule_expiry is not None:
            if type(self.health_rule_expiry)is not OwnerTurnExpiry or self.kind!='health_rule' or self.expires_turn is not None:
                raise ValueError('Owner health expiry requires one independent health-rule clock')
            self.health_rule_expiry.__post_init__()
            if self.health_rule_expiry.boundary!='turn_started':raise ValueError('Health rule expiry requires an actual owner start')
        if self.kind == 'cost_aura':
            if type(self.cost_aura) is not CostAuraSpec:
                raise ValueError('Cost aura requires CostAuraSpec')
            self.cost_aura.__post_init__()
            if (self.cost_aura.tribes_any or self.cost_aura.first_per_turn or self.cost_aura.every_nth_per_turn is not None) and (
                    self.origin != 'printed' or self.source_id is None or self.consumed or
                    self.expires_turn is not None or not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Native filtered cost auras require removable unconsumed printed provenance')
        elif self.cost_aura is not None:
            raise ValueError('Only cost auras may specify cost_aura')
        if not isinstance(self.origin, str) or self.origin not in {"printed", "granted"}:
            raise ValueError("ability origin must be printed or granted")
        _int(self.attack, "ability attack")
        _int(self.health, "ability health", 0)
        _int(self.spell_damage, "ability spell_damage", 0)
        if self.kind == "spell_damage":
            if self.spell_damage < 1:
                raise ValueError("spell damage ability requires a positive amount")
        elif self.spell_damage != 0:
            raise ValueError("only spell damage abilities may specify spell_damage")
        for name in ("include_self", "consumed", "remove_on_silence"):
            _bool(getattr(self, name), f"ability {name}")
        if self.kind == "keyword":
            if not isinstance(self.keyword, Keyword):
                raise ValueError("keyword ability requires a Keyword value")
            if self.keyword in (Keyword.DEATHRATTLE_SUPPRESSOR, Keyword.HERO_POWER_SUPPRESSOR) and (self.origin != 'printed' or
                    self.expires_turn is not None or self.timed_keyword is not None or
                    not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Global prohibition requires its removable native declaration')
            if self.keyword in (Keyword.SPELLBURST, Keyword.FRENZY, Keyword.CORRUPT, Keyword.INFUSE):
                raise ValueError('Finite trigger keywords require a limited trigger instance')
        elif self.keyword is not None:
            raise ValueError("only keyword abilities may specify keyword")
        if self.kind in {"trigger", "deathrattle", "battlecry", "combo", "on_play", "on_use", "on_launch", "on_awaken", "dormant_trigger", "on_discard", "on_destroyed"}:
            _name(self.behavior_id, "ability behavior_id")
        elif self.behavior_id is not None:
            raise ValueError("this ability kind cannot specify behavior_id")
        if self.kind in {"trigger", "dormant_trigger"}:
            _name(self.event, "ability event")
        elif self.event is not None:
            raise ValueError("only trigger abilities may specify event")
        _bool(self.adjacent_only, 'adjacent_only')
        if self.adjacent_only and self.include_self:
            raise ValueError('Adjacent auras cannot include their source')
        if self.kind != "aura" and (self.attack != 0 or self.health != 0 or self.include_self or self.adjacent_only):
            raise ValueError("only aura abilities may specify attack, health or include_self")
        if self.kind == 'aura':
            self.aura_spec.__post_init__()
            if (self.aura_condition != 'always' or self.aura_tribes_any or self.aura_card_ids) and (
                    self.origin != 'printed' or self.source_id is None or self.consumed or
                    self.expires_turn is not None or not self.remove_on_silence or self.magnetic_id is not None):
                raise ValueError('Conditional weapon auras require removable unconsumed printed provenance')
        elif (type(self.aura_tribes_any) is not tuple or self.aura_tribes_any or
              type(self.aura_card_ids) is not tuple or self.aura_card_ids or
              type(self.aura_target) is not str or self.aura_target != 'friendly_minions' or
              type(self.aura_condition) is not str or self.aura_condition != 'always'):
            raise ValueError('Only aura abilities carry aura target or condition')

    @property
    def aura_spec(self) -> AuraSpec:
        return AuraSpec(self.attack, self.include_self, self.health, self.adjacent_only,
                        self.aura_target, self.aura_condition, self.aura_tribes_any, self.aura_card_ids)

    @property
    def end_turn_spec(self) -> EndTurnSpec | None:
        return self.limited_trigger.end_turn if self.kind == 'limited_trigger' else self.end_turn


@dataclass(frozen=True)
class DeathCause:
    """The first fatal transition of one incarnation, frozen before cleanup."""

    kind: str
    reason: str
    target_id: int
    target_card_id: str
    target_controller: int
    target_zone_epoch: int
    target_entered_order: int
    turn: int
    active_player: int
    source_id: int | None = None
    source_card_id: str | None = None
    source_controller: int | None = None
    source_zone_epoch: int | None = None
    source_entered_order: int | None = None
    result: tuple[tuple[str, object], ...] = ()

    def __post_init__(self):
        from .death_causes import validate_cause
        validate_cause(self)

    @property
    def health_result(self):
        from .health_outcomes import result_from_payload
        return result_from_payload(self.result) if self.result else None


@dataclass(frozen=True)
class DeathRecord:
    """Last state before leaving the board; later transformations cannot alter it."""

    id: int
    batch: int
    entity_id: int
    card_id: str
    owner: int
    controller: int
    position: int
    turn: int
    attack: int
    max_health: int
    damage: int
    base_attack: int
    base_health: int
    base_cost: int
    cause: DeathCause
    keywords: tuple[Keyword, ...] = ()
    abilities: tuple[AbilityInstance, ...] = ()
    enchantments: tuple[Enchantment, ...] = ()
    frozen_until_owner_turn: int | None = None
    herald_rank: int | None = None
    zone: Zone = Zone.BOARD
    durability: int = 0
    corpse_value: int = 0
    components: tuple[str, ...] = ()
    jade_size: int | None = None
    deathrattles_blocked: bool = False

    def __post_init__(self) -> None:
        _bool(self.deathrattles_blocked, 'death Deathrattle prohibition receipt')
        if type(self.cause) is not DeathCause:
            raise ValueError('Death record requires a frozen cause')
        self.cause.__post_init__()
        if (self.cause.target_id != self.entity_id or self.cause.target_card_id != self.card_id
                or self.cause.turn > self.turn):
            raise ValueError('Death record and cause identity disagree')
        _components(self.components)
        if self.jade_size is not None and (type(self.jade_size) is not int or not 1 <= self.jade_size <= 30):
            raise ValueError('Invalid frozen innate Jade size')
        if self.herald_rank is not None and (type(self.herald_rank) is not int or not 0 <= self.herald_rank <= 2):
            raise ValueError('Invalid death record Herald rank')
        if not isinstance(self.zone, Zone) or self.zone not in (Zone.BOARD, Zone.WEAPON, Zone.HERO):
            raise ValueError('Death records require an explicit board, weapon or Hero zone')
        _int(self.durability, 'death durability')
        _int(self.corpse_value, 'death corpse_value', 0)
        if self.zone != Zone.BOARD and self.corpse_value:
            raise ValueError('Only minion deaths produce corpses')
        _optional_id(self.frozen_until_owner_turn, "death frozen_until_owner_turn")
        for name in ("id", "batch", "entity_id", "turn"):
            _int(getattr(self, name), f"death record {name}", 1)
        for name in ("position", "attack", "damage", "base_attack", "base_health", "base_cost"):
            _int(getattr(self, name), f"death record {name}", 0)
        _int(self.max_health, "death record max_health")
        _name(self.card_id, "death record card_id")
        for name in ("owner", "controller"):
            value = getattr(self, name)
            _int(value, f"death record {name}")
            if value not in (1, 2):
                raise ValueError(f"death record {name} must identify a player")
        if not isinstance(self.keywords, tuple) or any(not isinstance(k, Keyword) for k in self.keywords):
            raise ValueError("death record keywords must be a tuple of Keyword values")
        if len(set(self.keywords)) != len(self.keywords):
            raise ValueError("death record contains duplicate keywords")
        for name, cls in (("abilities", AbilityInstance), ("enchantments", Enchantment)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(not isinstance(v, cls) for v in values):
                raise ValueError(f"death record {name} must be an immutable tuple of {cls.__name__}")
        attachments = (*self.abilities, *self.enchantments)
        for ability in self.abilities:
            ability.__post_init__()
        if self.deathrattles_blocked and not any(a.kind == 'deathrattle' and not a.consumed for a in self.abilities):
            raise ValueError('Deathrattle prohibition receipt requires its structural death abilities')
        if any(a.kind == 'stat_relation' and not a.consumed and
               a.stat_relation.operand == StatRelationOperand.SELF_CURRENT_HEALTH for a in self.abilities):
            if self.attack != max(0, self.max_health - self.damage):
                raise ValueError('Frozen stat relation attack differs from its own final health')
        activated = [a.activation.id for a in self.abilities if a.kind == 'activated']
        if len(activated) != len(set(activated)):
            raise ValueError('Duplicate activated ability key in a death record')
        if len({item.id for item in attachments}) != len(attachments):
            raise ValueError("death record contains duplicate attachment IDs")
        if any(a.id >= b.id for a, b in zip(self.enchantments, self.enchantments[1:])):
            raise ValueError("death enchantments must preserve acquisition order")


@dataclass(frozen=True)
class SummonStats:
    attack: int | None = None
    health: int | None = None

    def __post_init__(self):
        if self.attack is None and self.health is None:
            raise ValueError('Summon stats must override at least one attribute')
        if self.attack is not None: _int(self.attack, 'summon attack', 0)
        if self.health is not None: _int(self.health, 'summon health', 1)


def validate_summon_stats(value):
    if value is not None:
        if type(value) is not SummonStats: raise ValueError('Expected SummonStats')
        value.__post_init__()


@dataclass(frozen=True)
class ResurrectionRecord:
    id: int
    death_id: int
    entity_id: int
    player_id: int
    turn: int
    action: int
    source_id: int | None = None
    stats: SummonStats | None = None
    entered_order: int = 0
    zone_epoch: int = 0

    def __post_init__(self):
        for name in ('id', 'death_id', 'entity_id', 'player_id', 'turn'):
            _int(getattr(self, name), name, 1)
        _int(self.action, 'resurrection action', 0)
        _optional_id(self.source_id, 'resurrection source')
        validate_summon_stats(self.stats)
        _int(self.entered_order, 'resurrection entry order', 1)
        _int(self.zone_epoch, 'resurrection zone epoch', 0)
        if self.player_id not in (1, 2): raise ValueError('Invalid resurrection player')


@dataclass(frozen=True)
class TriggerSpec:
    event: str
    behavior_id: str
    end_turn: EndTurnSpec | None = None

    def __post_init__(self):
        _name(self.event, 'trigger event')
        _name(self.behavior_id, 'trigger behavior')
        if self.end_turn is not None:
            if type(self.end_turn) is not EndTurnSpec:
                raise ValueError('Expected EndTurnSpec')
            self.end_turn.__post_init__()
            if self.event != 'turn_ended':
                raise ValueError('Only turn_ended triggers carry EndTurnSpec')


def _aura_card_ids(value):
    if (type(value) is not tuple or any(type(i) is not str or not i.strip() for i in value) or
            len(set(value)) != len(value)):
        raise ValueError('Aura card IDs require a unique immutable tuple of nonempty IDs')


@dataclass(frozen=True)
class AuraSpec:
    """Continuous minion bonuses with native tribe or damaged-weapon scope."""

    attack: int = 0
    include_self: bool = False
    health: int = 0
    adjacent_only: bool = False
    target: str = 'friendly_minions'
    condition: str = 'always'
    tribes_any: tuple[str, ...] = ()
    card_ids: tuple[str, ...] = ()

    def __post_init__(self):
        TribeChangeSpec('set', self.tribes_any).__post_init__()
        _aura_card_ids(self.card_ids)
        if self.card_ids and (self.target != 'friendly_minions' or self.condition != 'always' or
                self.adjacent_only or self.tribes_any):
            raise ValueError('Card identity stat auras require ordinary board scope and one selector')
        if self.card_ids:
            _int(self.attack, 'card identity aura Attack')
            _int(self.health, 'card identity aura Health', 0)
            _bool(self.include_self, 'card identity aura include_self')
            _bool(self.adjacent_only, 'card identity aura adjacent_only')
        if self.tribes_any:
            if self.target != 'friendly_minions' or self.condition != 'always' or self.adjacent_only:
                raise ValueError('Tribal stat aura requires ordinary nonadjacent board scope')
            if type(self.attack) is not int or type(self.health) is not int or self.health < 0:
                raise ValueError('Tribal stat aura requires integer Attack and nonnegative Health')
            _bool(self.include_self, 'tribal stat aura include_self')
            _bool(self.adjacent_only, 'tribal stat aura adjacent_only')
        if (type(self.target) is not str or type(self.condition) is not str or
                (self.target, self.condition) not in (
                    ('friendly_minions', 'always'), ('friendly_weapon', 'self_damaged'),
                    ('friendly_hero', 'controller_turn'))):
            raise ValueError('Unsupported stat aura target or condition')
        if self.condition == 'self_damaged':
            _int(self.attack, 'conditional weapon Attack', 1)
            _int(self.health, 'conditional weapon health', 0)
            _bool(self.include_self, 'conditional weapon include_self')
            _bool(self.adjacent_only, 'conditional weapon adjacent_only')
            if self.health != 0 or self.include_self or self.adjacent_only:
                raise ValueError('Conditional weapon auras only add Attack without positional flags')
        if self.target=='friendly_hero':
            _int(self.attack,'own-turn hero aura Attack',1)
            if self.health!=0 or self.include_self or self.adjacent_only or self.tribes_any or self.card_ids:
                raise ValueError('Own-turn hero auras only add native Attack to the current friendly hero')


@dataclass(frozen=True)
class ChooseBranch:
    id: str
    label: str
    behavior_id: str
    targeting: TargetSpec | None = None
    target_rule: str = 'any_entity'
    requires_board_space: bool = False

    def __post_init__(self):
        for name in ('id', 'label', 'behavior_id', 'target_rule'):
            _name(getattr(self, name), 'Choose One '+name)
        _bool(self.requires_board_space, 'branch board requirement')
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec:
                raise ValueError('Choose One branch requires TargetSpec')
            self.targeting.__post_init__()
        if self.behavior_id == 'engine.choose_one':
            raise ValueError('Choose One branch cannot recursively dispatch itself')


@dataclass(frozen=True)
class ChooseOneSpec:
    branches: tuple[ChooseBranch, ...]
    combined: ChooseBranch

    def __post_init__(self):
        if (type(self.branches) is not tuple or len(self.branches) < 2 or
                any(type(b) is not ChooseBranch for b in self.branches) or type(self.combined) is not ChooseBranch):
            raise ValueError('Choose One requires branches and an explicit combined branch')
        choices = (*self.branches, self.combined)
        for branch in choices: branch.__post_init__()
        if len({b.id for b in choices}) != len(choices):
            raise ValueError('Choose One branch identifiers must be distinct')


@dataclass(frozen=True)
class ChooseBranchSelection:
    """A physical card's saved preference, with explicit activation authority."""
    card_id: str
    branch_id: str
    origins: tuple[str, ...] = ('hand',)
    combination: str = 'override'

    def __post_init__(self):
        _name(self.card_id, 'preselected card'); _name(self.branch_id, 'preselected branch')
        allowed = ('hand', 'cast_effect', 'cast_draw', 'cast_history', 'physical', 'power_manual', 'power_effect')
        if (type(self.origins) is not tuple or not self.origins or
                any(type(o) is not str or o not in allowed for o in self.origins) or
                len(set(self.origins)) != len(self.origins)):
            raise ValueError('Branch preselection requires explicit unique origins')
        if type(self.combination) is not str or self.combination not in ('override', 'strict'):
            raise ValueError('Unknown preselection combination policy')


@dataclass(frozen=True)
class HandActionSpec:
    """A declared alternative hand operation, separate from playing the card."""

    id: str
    kind: str
    cost: int
    upgrade_card_id: str | None = None
    on_use: str | None = None
    use_rule: str = 'always'

    def __post_init__(self):
        for name in ('id', 'use_rule'):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f'Invalid hand action {name}')
        _int(self.cost, 'hand action cost', 0)
        if self.kind not in ('trade', 'forge', 'prepare'):
            raise ValueError('Unsupported hand action kind')
        for name in ('upgrade_card_id', 'on_use'):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f'Invalid hand action {name}')
        if (self.kind == 'forge') != (self.upgrade_card_id is not None):
            raise ValueError('Only Forge requires an upgrade definition')
        if self.kind == 'prepare' and (self.cost != 1 or self.on_use is not None or self.use_rule != 'always'):
            raise ValueError('Prepare has a one-mana minimum and no extra action body or rule')


@dataclass(frozen=True)
class HandPreparation:
    """One investment, an immediate discount and a global-turn play lock."""
    turn: int
    mana_spent: int
    cost_id: int

    def __post_init__(self):
        _int(self.turn, 'Prepare turn', 1)
        _int(self.mana_spent, 'Prepare mana spent', 1)
        _int(self.cost_id, 'Prepare cost attachment', 1)


@dataclass(frozen=True)
class QuestStageSpec:
    card_id: str
    goal: int
    events: tuple[str, ...]
    progress_behavior: str
    reward_behavior: str

    def __post_init__(self):
        for name in ('card_id', 'progress_behavior', 'reward_behavior'):
            _name(getattr(self, name), name)
        _int(self.goal, 'quest goal', 1)
        if type(self.events) is not tuple or not self.events or len(set(self.events)) != len(self.events):
            raise ValueError('Quest events must be a nonempty unique tuple')
        for event in self.events:
            _name(event, 'quest event')


@dataclass(frozen=True)
class QuestSpec:
    kind: str
    stages: tuple[QuestStageSpec, ...]

    def __post_init__(self):
        if self.kind not in ('quest', 'questline', 'sidequest', 'repeatable_quest'):
            raise ValueError('Unsupported quest kind')
        if (type(self.stages) is not tuple or len(self.stages) != (3 if self.kind == 'questline' else 1)
                or any(type(s) is not QuestStageSpec for s in self.stages)):
            raise ValueError('Quest requires one stage; Questline requires three')
        for stage in self.stages:
            stage.__post_init__()
        if len({s.card_id for s in self.stages}) != len(self.stages):
            raise ValueError('Quest stages require distinct display cards')

    @property
    def starts_in_hand(self):
        return self.kind != 'sidequest'


@dataclass(frozen=True)
class QuestProgress:
    id: int
    stage: int = 0
    value: int = 0
    keys: tuple[str, ...] = ()
    completing: bool = False

    def __post_init__(self):
        _int(self.id, 'quest instance', 1)
        _int(self.stage, 'quest stage', 0)
        _int(self.value, 'quest progress', 0)
        _bool(self.completing, 'quest completing')
        if type(self.keys) is not tuple or len(set(self.keys)) != len(self.keys):
            raise ValueError('Quest keys must be a unique immutable tuple')
        for key in self.keys:
            _name(key, 'quest progress key')


@dataclass(frozen=True)
class SecretSpec:
    key: str
    events: tuple[str, ...]
    condition_id: str
    behavior_id: str
    turn: str = 'opponent'
    requires_board_space: bool = False

    def __post_init__(self):
        for name in ('key', 'condition_id', 'behavior_id'):
            _name(getattr(self, name), name)
        if type(self.events) is not tuple or not self.events or len(set(self.events)) != len(self.events):
            raise ValueError('Secret events must be a nonempty unique tuple')
        for event in self.events:
            _name(event, 'secret event')
        if self.turn not in ('opponent', 'owner', 'any'):
            raise ValueError('Invalid secret turn policy')
        _bool(self.requires_board_space, 'secret board-space requirement')


@dataclass(frozen=True)
class HandEntryRecord:
    """A successful physical entry to a hand, distinct from draw attempts."""
    id: int
    entity_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    zone_epoch: int
    from_zone: Zone | None
    reason: str

    def __post_init__(self):
        for name in ('id', 'entity_id', 'player_id'):
            _int(getattr(self, name), name, 1)
        for name in ('turn', 'action', 'zone_epoch'):
            _int(getattr(self, name), name, 0)
        _name(self.card_id, 'acquired card')
        if self.player_id not in (1, 2) or self.from_zone is not None and not isinstance(self.from_zone, Zone):
            raise ValueError('Invalid hand entry owner or zone')
        if self.reason not in ('scenario', 'created', 'move', 'draw', 'return', 'shatter', 'recombine'):
            raise ValueError('Unknown hand entry reason')
        if self.reason == 'scenario' and (self.turn != 0 or self.action != 0 or self.from_zone is not None):
            raise ValueError('Scenario hand predates normal play')


@dataclass(frozen=True)
class HandDerivativeSpec:
    keyword: Keyword
    card_id: str

    def __post_init__(self):
        if type(self.keyword) is not Keyword or self.keyword not in (
                Keyword.TWINSPELL, Keyword.MINIATURIZE, Keyword.GIGANTIFY):
            raise ValueError('Unsupported hand derivative keyword')
        _name(self.card_id, 'hand derivative card')


@dataclass(frozen=True)
class BoardMinionCostSpec:
    """One mana less per ordinary resident minion, before local cost edits."""
    scope: str = 'friendly'
    profile_id: str = 'cost.board-minions-v1'

    def __post_init__(self):
        if type(self.scope) is not str or self.scope not in ('friendly', 'enemy', 'all'):
            raise ValueError('Board minion costs require friendly, enemy or all scope')
        if type(self.profile_id) is not str or self.profile_id != 'cost.board-minions-v1':
            raise ValueError('Unsupported board minion cost policy')


@dataclass(frozen=True)
class BoardMinionCostRow:
    entity_id: int
    card_id: str

    def __post_init__(self):
        _int(self.entity_id, 'board cost physical ID', 1)
        _name(self.card_id, 'board cost physical face')


@dataclass(frozen=True)
class BoardMinionCostFact:
    spec: BoardMinionCostSpec
    player_id: int
    next_entity_id: int
    boards: tuple[tuple[BoardMinionCostRow, ...], tuple[BoardMinionCostRow, ...]]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not BoardMinionCostSpec:
            raise ValueError('Board cost requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Board cost requires its actual payer')
        _int(self.next_entity_id, 'board cost allocator', 1)
        if (type(self.boards) is not tuple or len(self.boards) != 2 or any(type(board) is not tuple
                or any(type(row) is not BoardMinionCostRow for row in board) for board in self.boards)):
            raise ValueError('Board cost requires both complete ordered board inventories')
        identities = []
        for board in self.boards:
            for row in board:
                row.__post_init__()
                if row.entity_id >= self.next_entity_id:
                    raise ValueError('Board cost contains a future physical entity')
                identities.append(row.entity_id)
        if len(set(identities)) != len(identities):
            raise ValueError('Board cost cannot count a physical entity twice')
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'board cost '+name, 0)
        maximum = len(identities) if self.spec.scope == 'all' else len(self.boards[
            self.player_id - 1 if self.spec.scope == 'friendly' else 2 - self.player_id])
        if self.quantity > maximum or self.after != max(0, self.before - self.quantity):
            raise ValueError('Board cost result differs from its complete count operation')


@dataclass(frozen=True)
class HandCountCostSpec:
    """One mana less per own other/all card or per opponent card in hand."""
    scope: str = 'friendly_other'
    profile_id: str = 'cost.hand-count-v1'

    def __post_init__(self):
        if type(self.scope) is not str or self.scope not in ('friendly_other', 'friendly', 'enemy'):
            raise ValueError('Hand count costs require own other/all cards or opponent cards')
        if type(self.profile_id) is not str or self.profile_id != 'cost.hand-count-v1':
            raise ValueError('Unsupported hand count cost policy')


@dataclass(frozen=True)
class HandCountCostFact:
    spec: HandCountCostSpec
    player_id: int
    next_entity_id: int
    hands: tuple[tuple[int, ...], tuple[int, ...]]
    subject_id: int | None
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not HandCountCostSpec:
            raise ValueError('Hand count requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Hand count requires its actual payer')
        _int(self.next_entity_id, 'hand count allocator', 1)
        if type(self.hands) is not tuple or len(self.hands) != 2 or any(type(hand) is not tuple for hand in self.hands):
            raise ValueError('Hand count requires both complete ordered physical inventories')
        identities = []
        for hand in self.hands:
            for eid in hand:
                _int(eid, 'hand count physical ID', 1)
                if eid >= self.next_entity_id:
                    raise ValueError('Hand count contains a future physical entity')
                identities.append(eid)
        if len(set(identities)) != len(identities):
            raise ValueError('Hand count cannot count a physical entity twice')
        if self.subject_id is not None:
            _int(self.subject_id, 'hand count physical subject', 1)
            if self.subject_id >= self.next_entity_id:
                raise ValueError('Hand count subject is newer than its captured allocator')
            if self.subject_id in self.hands[2 - self.player_id]:
                raise ValueError('Hand count subject cannot belong to the opponent hand')
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'hand count ' + name, 0)
        quantity = (len(self.hands[self.player_id - 1]) - int(self.subject_id in self.hands[self.player_id - 1])
            if self.spec.scope == 'friendly_other' else
            len(self.hands[self.player_id - 1]) + int(self.subject_id not in self.hands[self.player_id - 1])
            if self.spec.scope == 'friendly' else len(self.hands[2 - self.player_id]))
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Hand count result differs from its complete count operation')


@dataclass(frozen=True)
class HeroMissingHealthCostSpec:
    profile_id: str = 'cost.hero-missing-health-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.hero-missing-health-v1', 'cost.hero-health-at-most-fifteen-v1'):
            raise ValueError('Unsupported hero missing-health cost policy')


@dataclass(frozen=True)
class HeroMissingHealthCostFact:
    spec: HeroMissingHealthCostSpec
    player_id: int
    next_entity_id: int
    hero_id: int
    hero_card_id: str
    max_health: int
    health: int
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not HeroMissingHealthCostSpec:
            raise ValueError('Hero missing health requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Hero missing health requires its actual payer')
        _int(self.next_entity_id, 'hero price allocator', 1)
        _int(self.hero_id, 'hero price physical ID', 1)
        _name(self.hero_card_id, 'hero price physical face')
        if self.hero_id >= self.next_entity_id:
            raise ValueError('Hero price contains a future physical entity')
        for name in ('max_health', 'health'):
            _int(getattr(self, name), 'hero price ' + name)
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'hero price ' + name, 0)
        quantity = (self.max_health - self.health if self.spec.profile_id == 'cost.hero-missing-health-v1'
                    else 5 if self.health <= 15 else 0)
        if self.health > self.max_health or self.quantity != quantity:
            raise ValueError('Hero price quantity differs from its finite current health policy')
        if self.after != max(0, self.before - self.quantity):
            raise ValueError('Hero price result differs from its complete count operation')


@dataclass(frozen=True)
class PlayerArmorCostSpec:
    profile_id: str = 'cost.player-current-hero-armor-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.player-current-hero-armor-v1', 'cost.player-current-hero-no-armor-zero-v1'):
            raise ValueError('Unsupported current hero Armor price policy')


@dataclass(frozen=True)
class PlayerArmorCostFact:
    spec: PlayerArmorCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    hero_allocation: tuple[tuple[str, int | str], ...]
    armor: int
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerArmorCostSpec:
            raise ValueError('Armor price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Armor price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order'): _int(getattr(self, name), 'Armor price '+name, 1)
        for name in ('action', 'armor', 'quantity', 'before', 'after'): _int(getattr(self, name), 'Armor price '+name, 0)
        if type(self.hero_allocation) is not tuple:
            raise ValueError('Armor price requires its complete original hero allocation')
        from .allocation_facts import allocation_from_payload
        original = allocation_from_payload(self.hero_allocation)
        canonical = tuple((key, value.value if isinstance(value, StrEnum) else value)
                          for key, value in original.payload())
        if self.hero_allocation != canonical or any(type(value) not in (int, str)
                                                   for _, value in self.hero_allocation):
            raise ValueError('Armor price requires its complete ordered primitive allocation')
        if (original.kind, original.zone, original.owner, original.controller,
                original.next_entity_id, original.next_order) != (
                CardType.HERO, Zone.HERO, self.player_id, self.player_id, self.next_entity_id, self.next_order):
            raise ValueError('Armor price changed its original payer hero or allocation bounds')
        after = (max(0, self.before-self.armor) if self.spec.profile_id == 'cost.player-current-hero-armor-v1'
                 else 0 if self.armor == 0 else self.before)
        if self.quantity != self.armor or self.after != after:
            raise ValueError('Armor price differs from its complete original current Armor')


@dataclass(frozen=True)
class PlayerWeaponAttackCostSpec:
    profile_id: str = 'cost.player-equipped-weapon-attack-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-equipped-weapon-attack-v1':
            raise ValueError('Unsupported equipped weapon Attack price policy')


@dataclass(frozen=True)
class PlayerWeaponAttackCostFact:
    spec: PlayerWeaponAttackCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    weapon_allocation: tuple[tuple[str, int | str], ...] | None
    attack: int | None
    durability: int | None
    doomed: bool | None
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerWeaponAttackCostSpec:
            raise ValueError('Weapon price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Weapon price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order'): _int(getattr(self, name), 'weapon price '+name, 1)
        for name in ('action', 'quantity', 'before', 'after'): _int(getattr(self, name), 'weapon price '+name, 0)
        if self.weapon_allocation is None:
            if any(v is not None for v in (self.attack, self.durability, self.doomed)):
                raise ValueError('An absent weapon price cannot invent original equipment values')
            quantity = 0
        else:
            from .allocation_facts import allocation_from_payload
            original = allocation_from_payload(self.weapon_allocation)
            canonical = tuple((key, value.value if isinstance(value, StrEnum) else value)
                              for key, value in original.payload())
            if self.weapon_allocation != canonical or any(type(value) not in (int, str)
                                                         for _, value in self.weapon_allocation):
                raise ValueError('Weapon price requires its complete ordered primitive allocation')
            if (original.kind, original.zone, original.controller, original.next_entity_id, original.next_order) != (
                    CardType.WEAPON, Zone.WEAPON, self.player_id, self.next_entity_id, self.next_order):
                raise ValueError('Weapon price changed its original equipped payer or allocation bounds')
            _int(self.attack, 'weapon price actual Attack', 0)
            _int(self.durability, 'weapon price actual durability')
            _bool(self.doomed, 'weapon price doomed qualification')
            quantity = self.attack if self.durability > 0 and not self.doomed else 0
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Weapon price differs from original live equipment Attack')


@dataclass(frozen=True)
class PlayerSpellCountCostSpec:
    profile_id: str = 'cost.player-spell-count-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.player-spell-count-v1', 'cost.player-distinct-spell-school-count-v1',
                'cost.player-fel-spell-count-v1'):
            raise ValueError('Unsupported personal spell-count cost policy')


@dataclass(frozen=True)
class PlayerSpellCountCostRow:
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    origin: str
    play_id: int | None
    iteration: int
    payload_started: bool
    failure: str | None
    spell_school: SpellSchool | None = None

    def __post_init__(self):
        for name in ('id', 'source_id', 'turn', 'iteration'):
            _int(getattr(self, name), 'personal spell row ' + name, 1)
        _int(self.action, 'personal spell row action', 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Personal spell row requires its actual caster')
        _name(self.card_id, 'personal spell row original face')
        _optional_id(self.play_id, 'personal spell row original hand play')
        _bool(self.payload_started, 'personal spell row accepted payload')
        if self.spell_school is not None and type(self.spell_school) is not SpellSchool:
            raise ValueError('Personal spell row requires its original declared school')
        if type(self.origin) is not str or self.origin not in ('hand', 'repeat', 'effect', 'draw', 'history'):
            raise ValueError('Personal spell row requires a known physical cast origin')
        automatic = self.origin in ('effect', 'draw', 'history')
        if automatic != (self.play_id is None) or (self.origin == 'repeat') != (self.iteration > 1):
            raise ValueError('Personal spell row changed its original hand root or iteration')
        if self.failure not in (None, 'countered', 'no_target', 'invalid_target'):
            raise ValueError('Personal spell row contains an unknown attempt result')
        if (self.failure is not None and self.payload_started or
                automatic and self.failure == 'countered' or
                not automatic and self.failure not in (None, 'countered') or
                not automatic and self.failure is None and not self.payload_started):
            raise ValueError('Personal spell row changed its physical acceptance boundary')

    def counts_for(self, player_id):
        return self.player_id == player_id and self.origin == 'hand' and self.payload_started and self.failure is None


def _player_spell_count_quantity(spec, player_id, rows):
    personal = tuple(row for row in rows if row.counts_for(player_id))
    if spec.profile_id == 'cost.player-spell-count-v1':
        return len(personal)
    if spec.profile_id == 'cost.player-fel-spell-count-v1':
        return sum(row.spell_school is SpellSchool.FEL for row in personal)
    return len({row.spell_school for row in personal if row.spell_school is not None})


@dataclass(frozen=True)
class PlayerSpellCountCostFact:
    spec: PlayerSpellCountCostSpec
    player_id: int
    next_entity_id: int
    cast_history_length: int
    rows: tuple[PlayerSpellCountCostRow, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerSpellCountCostSpec:
            raise ValueError('Personal spell cost requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Personal spell cost requires its actual payer')
        _int(self.next_entity_id, 'personal spell price allocator', 1)
        _int(self.cast_history_length, 'personal spell price original cursor', 0)
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'personal spell price ' + name, 0)
        if type(self.rows) is not tuple or any(type(row) is not PlayerSpellCountCostRow for row in self.rows):
            raise ValueError('Personal spell cost requires its complete immutable cast prefix')
        if len(self.rows) != self.cast_history_length:
            raise ValueError('Personal spell cost lost a row from its original cast cursor')
        last_turn = last_action = 0
        for index, row in enumerate(self.rows, 1):
            row.__post_init__()
            if (row.id != index or row.source_id >= self.next_entity_id or
                    row.turn < last_turn or row.action < last_action):
                raise ValueError('Personal spell cost lost its ordered original allocation prefix')
            last_turn, last_action = row.turn, row.action
        quantity = _player_spell_count_quantity(self.spec, self.player_id, self.rows)
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Personal spell cost differs from its complete original count')


@dataclass(frozen=True)
class PlayerHeroPowerCountCostSpec:
    profile_id: str = 'cost.player-hero-power-count-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-hero-power-count-v1':
            raise ValueError('Unsupported personal hero power count policy')


@dataclass(frozen=True)
class PlayerHeroPowerCountCostRow:
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    origin: str
    activator_id: int | None
    parent_id: int | None
    cost: int | None
    payment: PaymentType | None
    uses_before: int
    player_uses_before: int
    failure: str | None

    def __post_init__(self):
        for name in ('id', 'source_id', 'turn'):
            _int(getattr(self, name), 'personal power row ' + name, 1)
        for name in ('action', 'uses_before', 'player_uses_before'):
            _int(getattr(self, name), 'personal power row ' + name, 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Personal power row requires its actual player')
        _name(self.card_id, 'personal power row original face')
        for name in ('activator_id', 'parent_id'):
            _optional_id(getattr(self, name), 'personal power row ' + name)
        if type(self.origin) is not str or self.origin not in ('manual', 'effect'):
            raise ValueError('Personal power row requires its original activation origin')
        if self.parent_id is not None and self.parent_id >= self.id:
            raise ValueError('Personal power row changed its original nesting')
        if self.origin == 'manual':
            _int(self.cost, 'personal power row original payment', 0)
            if (type(self.payment) is not PaymentType or self.activator_id is not None or
                    self.parent_id is not None or self.failure is not None):
                raise ValueError('Personal power row changed its paid manual root')
        elif (self.cost is not None or self.payment is not None or
                self.failure not in (None, 'no_target', 'invalid_target', 'passive', 'disabled')):
            raise ValueError('Personal power row changed its automatic activation')

    def counts_for(self, player_id):
        return self.player_id == player_id and self.origin == 'manual' and self.failure is None


@dataclass(frozen=True)
class PlayerHeroPowerCountCostFact:
    spec: PlayerHeroPowerCountCostSpec
    player_id: int
    next_entity_id: int
    hero_power_history_length: int
    rows: tuple[PlayerHeroPowerCountCostRow, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerHeroPowerCountCostSpec:
            raise ValueError('Personal power price requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Personal power price requires its actual payer')
        _int(self.next_entity_id, 'personal power price allocator', 1)
        _int(self.hero_power_history_length, 'personal power price original cursor', 0)
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'personal power price ' + name, 0)
        if type(self.rows) is not tuple or any(type(row) is not PlayerHeroPowerCountCostRow for row in self.rows):
            raise ValueError('Personal power price requires its complete immutable prefix')
        if len(self.rows) != self.hero_power_history_length:
            raise ValueError('Personal power price lost an original activation row')
        last_turn = last_action = 0
        for index, row in enumerate(self.rows, 1):
            row.__post_init__()
            if (row.id != index or row.source_id >= self.next_entity_id or
                    row.activator_id is not None and row.activator_id >= self.next_entity_id or
                    row.turn < last_turn or row.action < last_action):
                raise ValueError('Personal power price lost its ordered original allocation prefix')
            last_turn, last_action = row.turn, row.action
        quantity = sum(row.counts_for(self.player_id) for row in self.rows)
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Personal power price differs from its complete original count')


@dataclass(frozen=True)
class PlayerSpellManaCostSpec:
    profile_id: str = 'cost.player-spell-mana-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-spell-mana-v1':
            raise ValueError('Unsupported personal spell mana policy')


@dataclass(frozen=True)
class PlayerSpellManaCostRow:
    id: int
    source_id: int
    player_id: int
    card_id: str
    kind: CardType
    turn: int
    action: int
    cost: int
    payment: PaymentType
    mana_before: int
    mana_after: int
    hand_entry_id: int
    hand_entry_turn: int

    def __post_init__(self):
        for name in ('id', 'source_id', 'turn', 'action', 'hand_entry_id'):
            _int(getattr(self, name), 'spell mana row ' + name, 1)
        for name in ('cost', 'mana_before', 'mana_after', 'hand_entry_turn'):
            _int(getattr(self, name), 'spell mana row ' + name, 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Spell mana row requires its actual payer')
        _name(self.card_id, 'spell mana row original face')
        if type(self.kind) is not CardType or type(self.payment) is not PaymentType:
            raise ValueError('Spell mana row requires original typed kind and account')
        if (self.hand_entry_turn > self.turn or
                self.mana_after != self.mana_before - (self.cost if self.payment == PaymentType.MANA else 0)):
            raise ValueError('Spell mana row changed its original resource debit')

    def mana_for(self, player_id):
        return (self.mana_before - self.mana_after if self.player_id == player_id
                and self.kind == CardType.SPELL and self.payment == PaymentType.MANA else 0)


@dataclass(frozen=True)
class PlayerSpellManaCostFact:
    spec: PlayerSpellManaCostSpec
    player_id: int
    next_entity_id: int
    play_history_length: int
    rows: tuple[PlayerSpellManaCostRow, ...]
    quantity: int
    before: int
    after: int
    consumption_rows: tuple[ManaConsumptionRecord, ...] = ()
    consumption_history_length: int = 0

    def __post_init__(self):
        if type(self.spec) is not PlayerSpellManaCostSpec:
            raise ValueError('Spell mana price requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Spell mana price requires its actual payer')
        _int(self.next_entity_id, 'spell mana price allocator', 1)
        _int(self.play_history_length, 'spell mana price original cursor', 0)
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'spell mana price ' + name, 0)
        if type(self.rows) is not tuple or any(type(row) is not PlayerSpellManaCostRow for row in self.rows):
            raise ValueError('Spell mana price requires its complete immutable prefix')
        if len(self.rows) != self.play_history_length:
            raise ValueError('Spell mana price lost an original physical play')
        last_turn = last_action = 0
        for index, row in enumerate(self.rows, 1):
            row.__post_init__()
            if (row.id != index or row.source_id >= self.next_entity_id or
                    row.turn < last_turn or row.action <= last_action):
                raise ValueError('Spell mana price lost its ordered original allocation prefix')
            last_turn, last_action = row.turn, row.action
        _int(self.consumption_history_length,'spell mana direct consumption cursor',0)
        if (type(self.consumption_rows) is not tuple or len(self.consumption_rows)!=self.consumption_history_length
                or any(type(row) is not ManaConsumptionRecord for row in self.consumption_rows)):
            raise ValueError('Spell mana price requires its complete direct consumption prefix')
        last_turn=last_action=0
        for index,row in enumerate(self.consumption_rows,1):
            row.__post_init__()
            if (row.id!=index or row.turn<last_turn or row.action<last_action
                    or row.source_id is not None and row.source_id>=self.next_entity_id):
                raise ValueError('Spell mana price lost original direct consumption allocation/chronology')
            last_turn,last_action=row.turn,row.action
        quantity = sum(row.mana_for(self.player_id) for row in (*self.rows,*self.consumption_rows))
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Spell mana price differs from its complete actual expenditure')


@dataclass(frozen=True)
class MinionDeathCostSpec:
    profile_id: str = 'cost.minion-deaths-friendly-game-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.minion-deaths-friendly-game-v1', 'cost.minion-deaths-both-turn-v1'):
            raise ValueError('Unsupported minion death quantity policy')


@dataclass(frozen=True)
class MinionDeathCostFact:
    spec: MinionDeathCostSpec
    player_id: int
    turn: int
    next_entity_id: int
    next_attachment_id: int
    next_order: int
    next_death_id: int
    next_death_batch: int
    death_history_length: int
    records: tuple[DeathRecord, ...]
    selected_ids: tuple[int, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not MinionDeathCostSpec:
            raise ValueError('Death price requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Death price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_attachment_id', 'next_order',
                     'next_death_id', 'next_death_batch'):
            _int(getattr(self, name), 'death price ' + name, 1)
        for name in ('death_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'death price ' + name, 0)
        if type(self.records) is not tuple or any(type(row) is not DeathRecord for row in self.records):
            raise ValueError('Death price requires the complete original immutable ledger')
        if len(self.records) != self.death_history_length or self.next_death_id != len(self.records) + 1:
            raise ValueError('Death price lost an original destruction occurrence')
        last_batch = last_turn = 0
        batch_turns, batch_entities = {}, set()
        for index, row in enumerate(self.records, 1):
            row.__post_init__()
            cause = row.cause
            if (row.id != index or row.entity_id >= self.next_entity_id or
                    row.batch < last_batch or row.batch >= self.next_death_batch or
                    not last_turn <= row.turn <= self.turn or
                    cause.target_entered_order >= self.next_order or
                    cause.source_id is not None and (cause.source_id >= self.next_entity_id or
                        cause.source_entered_order >= self.next_order) or
                    any(a.id >= self.next_attachment_id for a in (*row.abilities, *row.enchantments))):
                raise ValueError('Death price changed its original chronology or allocation prefix')
            result = cause.health_result
            if result is not None and result.weapon_id is not None and result.weapon_id >= self.next_entity_id:
                raise ValueError('Death price borrowed a later weapon source')
            if row.batch in batch_turns and batch_turns[row.batch] != row.turn or (row.batch, row.entity_id) in batch_entities:
                raise ValueError('Death price changed its original complete batch')
            batch_turns[row.batch] = row.turn; batch_entities.add((row.batch, row.entity_id))
            last_batch, last_turn = row.batch, row.turn
        if type(self.selected_ids) is not tuple:
            raise ValueError('Death price requires ordered original selected occurrences')
        for death_id in self.selected_ids: _int(death_id, 'selected death occurrence', 1)
        selected = set(self.selected_ids)
        if len(selected) != len(self.selected_ids) or tuple(r.id for r in self.records if r.id in selected) != self.selected_ids:
            raise ValueError('Death price lost its ordered original selection')
        for row in self.records:
            if row.id not in selected: continue
            if (row.zone != Zone.BOARD or
                    self.spec.profile_id == 'cost.minion-deaths-friendly-game-v1' and row.controller != self.player_id or
                    self.spec.profile_id == 'cost.minion-deaths-both-turn-v1' and row.turn != self.turn):
                raise ValueError('Death price changed its original relation or turn scope')
        if self.quantity != len(self.selected_ids) or self.after != max(0, self.before - self.quantity):
            raise ValueError('Death price differs from its original occurrence count')


@dataclass(frozen=True)
class CorpseSpendRecord:
    id: int
    player_id: int
    turn: int
    action: int
    origin: str
    amount: int
    balance_before: int
    balance_after: int
    source_id: int | None = None
    source_card_id: str | None = None
    operation_id: int | None = None

    def __post_init__(self):
        for name in ('id', 'turn'):
            _int(getattr(self, name), 'corpse spend ' + name, 1)
        for name in ('action', 'amount', 'balance_before', 'balance_after'):
            _int(getattr(self, name), 'corpse spend ' + name, 0)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Corpse spending requires its actual player')
        if type(self.origin) is not str or self.origin not in ('fixed', 'capped', 'payment'):
            raise ValueError('Unknown corpse debit producer')
        if self.balance_after != self.balance_before - self.amount:
            raise ValueError('Corpse spending differs from its original actual debit')
        _optional_id(self.source_id, 'corpse physical source')
        if self.source_id is None:
            if self.source_card_id is not None:
                raise ValueError('Source-less corpse spending invented an original face')
        else:
            _name(self.source_card_id, 'corpse original source face')
        _optional_id(self.operation_id, 'corpse capped operation')
        if (self.origin == 'capped') != (self.operation_id is not None):
            raise ValueError('Corpse spending changed its capped operation identity')
        if self.origin == 'fixed' and self.source_id is not None:
            raise ValueError('Fixed legacy spending invented an implicit source')
        if self.origin == 'payment' and self.source_id is None:
            raise ValueError('Corpse currency payment lost its physical source')

    def payload(self):
        from dataclasses import fields
        return tuple((field.name, getattr(self, field.name)) for field in fields(self))


@dataclass(frozen=True)
class PlayerCorpseSpendCostSpec:
    profile_id: str = 'cost.player-corpse-spent-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-corpse-spent-v1':
            raise ValueError('Unsupported all-game actual corpse-spend policy')


@dataclass(frozen=True)
class PlayerCorpseSpendCostFact:
    spec: PlayerCorpseSpendCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_resource_operation_id: int
    corpse_spend_history_length: int
    records: tuple[CorpseSpendRecord, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerCorpseSpendCostSpec:
            raise ValueError('Corpse price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Corpse price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_resource_operation_id'):
            _int(getattr(self, name), 'corpse price ' + name, 1)
        for name in ('action', 'corpse_spend_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'corpse price ' + name, 0)
        from .player_corpse_spend_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class HealingRecord:
    """One original healing-related result, with the original resolver action."""
    id: int
    action: int
    result: tuple[tuple[str, object], ...]

    def __post_init__(self):
        from .healing_history import validate_record
        validate_record(self)

    @property
    def health_result(self):
        from .health_outcomes import result_from_payload
        return result_from_payload(self.result)


@dataclass(frozen=True)
class DamageRecord:
    """One original damage-related result, with the original resolver action."""
    id: int
    action: int
    result: tuple[tuple[str, object], ...]

    def __post_init__(self):
        from .damage_history import validate_record
        validate_record(self)

    @property
    def health_result(self):
        from .health_outcomes import result_from_payload
        return result_from_payload(self.result)


@dataclass(frozen=True)
class PlayerCharacterAttackCostSpec:
    profile_id: str = 'cost.player-character-attack-declared-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-character-attack-declared-v1':
            raise ValueError('Unsupported original character declaration price policy')


@dataclass(frozen=True)
class PlayerCharacterAttackCostFact:
    spec: PlayerCharacterAttackCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    next_window_id: int
    records: tuple[CharacterAttackRecord, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerCharacterAttackCostSpec:
            raise ValueError('Character declaration price requires its finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Character declaration price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order', 'next_window_id'):
            _int(getattr(self, name), 'character declaration price ' + name, 1)
        for name in ('action', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'character declaration price ' + name, 0)
        from .character_attack_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class PlayerSpellDamageCostSpec:
    profile_id: str = 'cost.player-spell-damage-turn-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-spell-damage-turn-v1':
            raise ValueError('Unsupported current-turn actual spell damage price policy')


@dataclass(frozen=True)
class PlayerSpellDamageCostRow:
    record: DamageRecord
    source_kind: CardType | None

    def __post_init__(self):
        if type(self.record) is not DamageRecord:
            raise ValueError('Spell damage price requires the original settled packet')
        self.record.__post_init__()
        if (self.source_kind is not None and type(self.source_kind) is not CardType or
                (self.source_kind is None) != (self.record.health_result.source_card_id is None)):
            raise ValueError('Spell damage price requires the original typed source kind')


@dataclass(frozen=True)
class PlayerSpellDamageCostFact:
    spec: PlayerSpellDamageCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    next_damage_id: int
    rows: tuple[PlayerSpellDamageCostRow, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerSpellDamageCostSpec:
            raise ValueError('Spell damage price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Spell damage price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order', 'next_damage_id'):
            _int(getattr(self, name), 'spell damage price ' + name, 1)
        for name in ('action', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'spell damage price ' + name, 0)
        from .spell_damage_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class HeroDamageTakenCostSpec:
    profile_id: str = 'cost.hero-own-turns-damage-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.hero-own-turns-damage-v1', 'cost.enemy-hero-current-turn-damage-count-v1'):
            raise ValueError('Unsupported actual received hero damage price policy')


@dataclass(frozen=True)
class HeroDamageTakenCostFact:
    spec: HeroDamageTakenCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    next_damage_id: int
    records: tuple[DamageRecord, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not HeroDamageTakenCostSpec:
            raise ValueError('Received-damage price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Received-damage price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order', 'next_damage_id'):
            _int(getattr(self, name), 'received-damage price ' + name, 1)
        for name in ('action', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'received-damage price ' + name, 0)
        from .hero_damage_taken_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class HeroHealthChangeRecord:
    id: int
    player_id: int
    active_player: int
    turn: int
    action: int
    owner_turn_id: int
    event_kind: str
    old_hero_id: int
    old_hero_card_id: str
    hero_id: int
    hero_card_id: str
    health_before: int
    max_health_before: int
    health_after: int
    max_health_after: int

    def __post_init__(self):
        for name in ('player_id', 'active_player'):
            value = getattr(self, name)
            if type(value) is not int or value not in (1, 2):
                raise ValueError('Hero health change requires actual players')
        for name in ('id', 'turn', 'old_hero_id', 'hero_id'):
            _int(getattr(self, name), 'hero health change ' + name, 1)
        for name in ('action', 'owner_turn_id'):
            _int(getattr(self, name), 'hero health change ' + name, 0)
        for name in ('health_before', 'health_after', 'max_health_before', 'max_health_after'):
            _int(getattr(self, name), 'hero health change ' + name)
        for name in ('old_hero_card_id', 'hero_card_id'):
            _name(getattr(self, name), 'hero health change ' + name)
        if (type(self.event_kind) is not str or self.event_kind not in (
                'health_resolved', 'health_lost', 'health_loss_floor_resolved',
                'max_health_gained', 'max_health_lost', 'health_spent', 'stats_changed',
                'enchantment_removed', 'attachments_expired', 'hero_replaced', 'hero_recovered', 'hero_health_set')):
            raise ValueError('Unknown hero health change origin')
        if (self.health_before == self.health_after or self.health_before > self.max_health_before or
                self.health_after > self.max_health_after):
            raise ValueError('Hero change requires an actual remaining-health difference')
        if self.event_kind != 'hero_replaced' and (
                self.old_hero_id != self.hero_id or self.old_hero_card_id != self.hero_card_id):
            raise ValueError('Only hero replacement may change physical health identity')
        if self.event_kind=='hero_health_set' and self.max_health_before!=self.max_health_after:
            raise ValueError('Remaining Hero assignment cannot change maximum health')

    def transition(self):
        return (self.player_id, self.old_hero_id, self.old_hero_card_id, self.health_before,
                self.max_health_before, self.hero_id, self.hero_card_id,
                self.health_after, self.max_health_after)


@dataclass(frozen=True)
class HeroHealthChangeCostSpec:
    profile_id: str = 'cost.hero-own-turn-health-changes-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.hero-own-turn-health-changes-v1':
            raise ValueError('Unsupported own-turn hero health-change price policy')


@dataclass(frozen=True)
class HeroHealthChangeCostFact:
    spec: HeroHealthChangeCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_hero_health_change_id: int
    health_history_length: int
    records: tuple[HeroHealthChangeRecord, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not HeroHealthChangeCostSpec:
            raise ValueError('Health-change price requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Health-change price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_hero_health_change_id'):
            _int(getattr(self, name), 'health-change price ' + name, 1)
        for name in ('action', 'health_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'health-change price ' + name, 0)
        if type(self.records) is not tuple or any(type(row) is not HeroHealthChangeRecord for row in self.records):
            raise ValueError('Health-change price requires its complete immutable original ledger')
        if len(self.records) != self.health_history_length or self.next_hero_health_change_id != len(self.records) + 1:
            raise ValueError('Health-change price lost an original occurrence or cursor')
        last_turn = last_action = last_owner = 0
        for index, row in enumerate(self.records, 1):
            row.__post_init__()
            if (row.id != index or not last_turn <= row.turn <= self.turn or
                    not last_action <= row.action <= self.action or row.owner_turn_id < last_owner or
                    max(row.old_hero_id, row.hero_id) >= self.next_entity_id):
                raise ValueError('Health-change price changed its original chronology or physical allocation')
            last_turn, last_action, last_owner = row.turn, row.action, row.owner_turn_id
        quantity = sum(row.player_id == self.player_id == row.active_player and row.owner_turn_id > 0
                       for row in self.records)
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Health-change price differs from its complete own-turn occurrence count')


@dataclass(frozen=True)
class PlayerSummonCountCostSpec:
    profile_id: str = 'cost.player-summoned-totem-count-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.player-summoned-totem-count-v1', 'cost.player-summoned-beast-count-v1'):
            raise ValueError('Unsupported successful summon quantity price policy')


@dataclass(frozen=True)
class PlayerSummonCountCostFact:
    spec: PlayerSummonCountCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_order: int
    next_successful_summon_id: int
    # Concrete SuccessfulSummonRecord values; module-owned validation avoids import cycles.
    records: tuple
    selected_ids: tuple[int, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerSummonCountCostSpec:
            raise ValueError('Summon price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Summon price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_order', 'next_successful_summon_id'):
            _int(getattr(self, name), 'summon price ' + name, 1)
        for name in ('action', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'summon price ' + name, 0)
        if type(self.selected_ids) is not tuple:
            raise ValueError('Summon price requires its complete ordered physical selection')
        for identity in self.selected_ids:
            _int(identity, 'selected successful summon', 1)
        from .player_summon_count_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class PlayerDrawCountCostSpec:
    profile_id: str = 'cost.player-physical-draw-count-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id not in (
                'cost.player-physical-draw-count-v1', 'cost.player-physical-draw-count-turn-v1'):
            raise ValueError('Unsupported physical draw quantity price policy')


@dataclass(frozen=True)
class PlayerDrawCountCostFact:
    spec: PlayerDrawCountCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    cast_history_length: int
    draw_history_length: int
    records: tuple['DrawRecord', ...]
    selected_ids: tuple[int, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerDrawCountCostSpec:
            raise ValueError('Draw price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Draw price requires its actual payer')
        for name in ('turn', 'next_entity_id'):
            _int(getattr(self, name), 'draw price ' + name, 1)
        for name in ('action', 'cast_history_length', 'draw_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'draw price ' + name, 0)
        if type(self.records) is not tuple or any(type(row) is not DrawRecord for row in self.records):
            raise ValueError('Draw price requires its complete immutable original draw prefix')
        if len(self.records) != self.draw_history_length:
            raise ValueError('Draw price lost an original attempt or cursor')
        if type(self.selected_ids) is not tuple:
            raise ValueError('Draw price requires its complete ordered physical selection')
        for draw_id in self.selected_ids: _int(draw_id, 'selected physical draw', 1)
        last_turn = last_action = 0
        cast_ids = set()
        for index, row in enumerate(self.records, 1):
            row.__post_init__()
            if (row.id != index or not last_turn <= row.turn <= self.turn or
                    not last_action <= row.action <= self.action or
                    any(eid is not None and eid >= self.next_entity_id for eid in (row.entity_id, row.source_id))):
                raise ValueError('Draw price changed its original chronology or physical allocation')
            if row.cast_id is not None:
                if row.cast_id > self.cast_history_length or row.cast_id in cast_ids:
                    raise ValueError('Draw price borrowed a later or duplicated original cast')
                cast_ids.add(row.cast_id)
            if row.parent_id is not None:
                parent = self.records[row.parent_id - 1]
                if (parent.outcome != 'cast' or parent.replacement_id != row.id or
                        parent.player_id != row.player_id or row.source_id != parent.entity_id or
                        parent.turn > row.turn or parent.action > row.action):
                    raise ValueError('Draw price changed an original replacement parent')
            if row.replacement_id is not None:
                if row.replacement_id > len(self.records):
                    raise ValueError('Draw price borrowed a later replacement draw')
                child = self.records[row.replacement_id - 1]
                if (child.parent_id != row.id or row.phase in ('pending_cast', 'casting', 'pending_replacement') or
                        row.phase in ('after_draw', 'done') and not child.completed):
                    raise ValueError('Draw price changed its original replacement progress')
            elif row.outcome == 'cast' and row.spec.replacement and row.phase in ('replacing', 'after_draw', 'done'):
                raise ValueError('Draw price lost an accepted original replacement draw')
            last_turn, last_action = row.turn, row.action
        selected = tuple(row.id for row in self.records if row.player_id == self.player_id and
            row.outcome != 'fatigue' and (self.spec.profile_id != 'cost.player-physical-draw-count-turn-v1' or
                row.turn == self.turn))
        if self.selected_ids != selected or self.quantity != len(selected) or self.after != max(0, self.before - len(selected)):
            raise ValueError('Draw price differs from its complete original physical draw quantity')


@dataclass(frozen=True)
class OverloadRecord:
    id: int
    player_id: int
    turn: int
    action: int
    owner_turn_id: int
    mana_event_sequence: int
    event_sequence: int
    amount: int
    pending_before: int
    pending_after: int

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Overload history requires its actual affected player')
        for name in ('id', 'turn', 'mana_event_sequence', 'event_sequence', 'amount', 'pending_after'):
            _int(getattr(self, name), 'overload record ' + name, 1)
        for name in ('action', 'owner_turn_id', 'pending_before'):
            _int(getattr(self, name), 'overload record ' + name, 0)
        if self.mana_event_sequence >= self.event_sequence or self.pending_after - self.pending_before != self.amount:
            raise ValueError('Overload record differs from its original positive increment')


@dataclass(frozen=True)
class PlayerOverloadCostSpec:
    profile_id: str = 'cost.player-overload-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-overload-v1':
            raise ValueError('Unsupported all-game overload quantity policy')


@dataclass(frozen=True)
class PlayerOverloadCostFact:
    spec: PlayerOverloadCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    next_overload_id: int
    overload_history_length: int
    records: tuple[OverloadRecord, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerOverloadCostSpec:
            raise ValueError('Overload price requires its complete declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Overload price requires its actual payer')
        for name in ('turn', 'next_entity_id', 'next_overload_id'):
            _int(getattr(self, name), 'overload price ' + name, 1)
        for name in ('action', 'overload_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'overload price ' + name, 0)
        if type(self.records) is not tuple or any(type(row) is not OverloadRecord for row in self.records):
            raise ValueError('Overload price requires the complete immutable original ledger')
        if len(self.records) != self.overload_history_length or self.next_overload_id != len(self.records) + 1:
            raise ValueError('Overload price lost an original increment')
        last_turn = last_action = last_owner = last_event = 0
        for index, row in enumerate(self.records, 1):
            row.__post_init__()
            if (row.id != index or not last_turn <= row.turn <= self.turn or
                    not last_action <= row.action <= self.action or row.owner_turn_id < last_owner or
                    row.mana_event_sequence <= last_event):
                raise ValueError('Overload price changed its original chronology or allocation prefix')
            last_turn, last_action, last_owner, last_event = row.turn, row.action, row.owner_turn_id, row.event_sequence
        quantity = sum(row.amount for row in self.records if row.player_id == self.player_id)
        if self.quantity != quantity or self.after != max(0, self.before - quantity):
            raise ValueError('Overload price differs from complete actual crystal increments')


@dataclass(frozen=True)
class CurrentDeckCountMatch:
    """Original complete payer DECK for one inclusive conditional price query."""
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    deck: tuple[int, ...]
    card_count: int
    comparison: str
    matched: bool

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Deck-count price requires its actual payer')
        _int(self.turn, 'deck-count price turn', 1)
        _int(self.action, 'deck-count price action', 0)
        _int(self.next_entity_id, 'deck-count price allocator', 1)
        _int(self.card_count, 'deck-count price threshold', 0)
        if type(self.comparison) is not str or self.comparison not in ('at_most', 'at_least'):
            raise ValueError('Deck-count price requires an inclusive comparison')
        _bool(self.matched, 'deck-count price aggregate')
        if type(self.deck) is not tuple:
            raise ValueError('Deck-count price requires its complete ordered physical DECK')
        for eid in self.deck:
            _int(eid, 'deck-count price physical ID', 1)
            if eid >= self.next_entity_id:
                raise ValueError('Deck-count price contains a future physical entity')
        if len(set(self.deck)) != len(self.deck):
            raise ValueError('Deck-count price cannot count a physical entity twice')
        matched = len(self.deck) <= self.card_count if self.comparison == 'at_most' else len(self.deck) >= self.card_count
        if self.matched != matched:
            raise ValueError('Deck-count price aggregate differs from its complete physical inventory')


@dataclass(frozen=True)
class PermanentManaMatch:
    player_id: int
    turn: int
    action: int
    maximum: int
    threshold: int

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Permanent mana condition requires its actual payer')
        _int(self.turn, 'permanent mana turn', 1)
        for name in ('action', 'maximum', 'threshold'):
            _int(getattr(self, name), 'permanent mana '+name, 0)

    @property
    def matched(self):
        return self.maximum >= self.threshold


@dataclass(frozen=True)
class IntrinsicCostSpec:
    delta: int = 0
    set_to: int | None = None
    minimum: int = 0
    condition: str = 'previous_owner_turn_type'
    history_profile_id: str = 'owner-turn.latest-closed-v1'
    profile_id: str = 'cost.intrinsic.before-local-v1'
    card_count: int | None = None
    comparison: str | None = None
    mana_crystals: int | None = None

    def __post_init__(self):
        _int(self.delta, 'intrinsic cost delta')
        _int(self.minimum, 'intrinsic cost minimum', 0)
        if self.set_to is not None: _int(self.set_to, 'intrinsic cost set', 0)
        if type(self.condition) is not str or self.condition not in (
                'previous_owner_turn_type', 'previous_owner_turn_elemental', 'hero_healed_this_turn', 'current_deck_count', 'permanent_mana_at_least', 'hand_other_class',
                'hand_other_dragon', 'board_dormant_minion', 'board_no_minions', 'turn_holy_and_shadow',
                'hand_edge', 'controlled_legendary', 'own_deck_shuffle_count'):
            raise ValueError('Unsupported intrinsic cost declaration policy')
        if self.condition == 'current_deck_count':
            _int(self.card_count, 'intrinsic current deck threshold', 0)
            if type(self.comparison) is not str or self.comparison not in ('at_most', 'at_least'):
                raise ValueError('Intrinsic current deck price requires an inclusive comparison')
            if self.delta > 0 or self.set_to is not None or self.minimum != 0:
                raise ValueError('Current deck price supports one conditional flat discount')
        elif self.card_count is not None or self.comparison is not None:
            raise ValueError('Historical intrinsic conditions cannot invent current deck operands')
        if self.condition == 'permanent_mana_at_least':
            _int(self.mana_crystals, 'permanent mana threshold', 0)
            if self.delta != 0 or self.set_to is None or self.minimum != 0:
                raise ValueError('Permanent mana price requires one fixed cost assignment')
        elif self.mana_crystals is not None:
            raise ValueError('Other intrinsic conditions cannot invent a mana threshold')
        if self.condition == 'hand_other_class' and (self.delta != 0 or self.set_to is None or self.minimum != 0):
            raise ValueError('Hand other-class price requires one fixed cost assignment')
        if self.condition in ('hand_other_dragon', 'board_dormant_minion') and (
                self.delta >= 0 or self.set_to is not None or self.minimum != 0):
            raise ValueError('Current presence price requires one flat discount')
        if self.condition in ('turn_holy_and_shadow', 'board_no_minions', 'hand_edge', 'controlled_legendary') and (
                self.delta != 0 or self.set_to is None or self.minimum != 0):
            raise ValueError('Finite conditional price requires one fixed assignment')
        if self.condition == 'own_deck_shuffle_count' and (self.delta != -1 or self.set_to is not None or self.minimum != 0):
            raise ValueError('Shuffle count requires the finite one-per-operation discount')
        history = ('deck.shuffle.operations-game-v1' if self.condition == 'own_deck_shuffle_count' else
                   'deck.current-count-v1' if self.condition == 'current_deck_count' else
                   'mana.permanent-crystals-v1' if self.condition == 'permanent_mana_at_least' else
                   'hand.current-other-class-v1' if self.condition == 'hand_other_class' else
                   'hand.current-edge-v1' if self.condition == 'hand_edge' else
                   'controlled.current-legendary-v1' if self.condition == 'controlled_legendary' else
                   'hand.current-other-dragon-v1' if self.condition == 'hand_other_dragon' else
                   'board.current-dormant-minion-v1' if self.condition == 'board_dormant_minion' else
                   'board.current-no-minions-v1' if self.condition == 'board_no_minions' else
                   'cast.current-turn-holy-shadow-v1' if self.condition == 'turn_holy_and_shadow' else
                   'healing.hero-this-turn-v1' if self.condition == 'hero_healed_this_turn' else 'owner-turn.latest-closed-v1')
        for name, value in (('history_profile_id', history),
                            ('profile_id', 'cost.intrinsic.before-local-v1')):
            if type(getattr(self, name)) is not str or getattr(self, name) != value:
                raise ValueError('Unsupported intrinsic cost declaration policy')


@dataclass(frozen=True)
class HandOtherClassRow:
    entity_id: int
    card_id: str
    matched: bool

    def __post_init__(self):
        _int(self.entity_id, 'hand class physical entity', 1)
        _name(self.card_id, 'hand class original face')
        _bool(self.matched, 'hand class row match')


@dataclass(frozen=True)
class HandOtherClassMatch:
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    hero_class: CardClass
    rows: tuple[HandOtherClassRow, ...]
    profile_id: str = 'hand.current-other-class-v1'

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1,2):
            raise ValueError('Hand class condition requires its original player')
        _int(self.turn, 'hand class turn', 1)
        _int(self.action, 'hand class action', 0)
        _int(self.next_entity_id, 'hand class allocation boundary', 1)
        if type(self.hero_class) is not CardClass or self.hero_class == CardClass.NEUTRAL:
            raise ValueError('Hand class condition requires a known playable hero class')
        if self.profile_id != 'hand.current-other-class-v1' or type(self.profile_id) is not str:
            raise ValueError('Unknown hand class condition profile')
        if type(self.rows) is not tuple or any(type(row) is not HandOtherClassRow for row in self.rows):
            raise ValueError('Hand class condition requires complete immutable physical rows')
        for row in self.rows:
            row.__post_init__()
            if row.entity_id >= self.next_entity_id:
                raise ValueError('Hand class condition contains a future physical entity')
        if len({row.entity_id for row in self.rows}) != len(self.rows):
            raise ValueError('Hand class condition repeats a physical entity')

    @property
    def matched(self):
        return any(row.matched for row in self.rows)


@dataclass(frozen=True)
class PlayerPlayedClassCostSpec:
    card_class: CardClass | None = CardClass.PALADIN
    profile_id: str = 'cost.player-played-class-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str:
            raise ValueError('Unsupported original played-class price policy')
        if self.profile_id == 'cost.player-played-class-v1':
            if type(self.card_class) is not CardClass or self.card_class == CardClass.NEUTRAL:
                raise ValueError('Played-class price requires one original playable class')
        elif self.profile_id in ('cost.player-played-card-count-turn-v1',
                                'cost.player-played-outside-starting-deck-v1',
                                'cost.player-last-played-cost-v1'):
            if self.card_class is not None:
                raise ValueError('All-card play price does not filter an original class')
        else:
            raise ValueError('Unsupported original played-class price policy')


@dataclass(frozen=True)
class PlayerPlayedClassCostRow:
    face: FrozenPlayedFaceFact
    turn: int
    action: int
    hand_entry_id: int
    hand_entry_turn: int
    accepted_cost: int

    def __post_init__(self):
        if type(self.face) is not FrozenPlayedFaceFact:
            raise ValueError('Played-class row requires its complete original frozen face')
        self.face.__post_init__()
        for name in ('turn', 'action', 'hand_entry_id'):
            _int(getattr(self, name), 'played-class row ' + name, 1)
        _int(self.hand_entry_turn, 'played-class original acquisition turn', 0)
        _int(self.accepted_cost, 'original accepted hand Cost', 0)
        if self.hand_entry_turn > self.turn:
            raise ValueError('Played-class row predates its original acquisition')


@dataclass(frozen=True)
class PlayerPlayedClassCostFact:
    spec: PlayerPlayedClassCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    play_history_length: int
    rows: tuple[PlayerPlayedClassCostRow, ...]
    selected_ids: tuple[int, ...]
    quantity: int
    before: int
    after: int
    starting_entities: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    starting_cards: tuple[tuple[str, ...], tuple[str, ...]] | None = None

    def __post_init__(self):
        if type(self.spec) is not PlayerPlayedClassCostSpec:
            raise ValueError('Played-class price requires its original declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Played-class price requires its actual payer')
        for name in ('turn', 'next_entity_id'): _int(getattr(self, name), 'played-class price ' + name, 1)
        for name in ('action', 'play_history_length', 'quantity', 'before', 'after'):
            _int(getattr(self, name), 'played-class price ' + name, 0)
        if type(self.rows) is not tuple or any(type(row) is not PlayerPlayedClassCostRow for row in self.rows):
            raise ValueError('Played-class price requires its immutable complete face prefix')
        if len(self.rows) != self.play_history_length:
            raise ValueError('Played-class price lost an original physical play')
        if type(self.selected_ids) is not tuple or any(type(value) is not int for value in self.selected_ids):
            raise ValueError('Played-class price requires its complete exact selection')
        from .play_history import (matches_played_class, matches_outside_starting_deck,
                                   validate_starting_deck_identity)
        outside = self.spec.profile_id == 'cost.player-played-outside-starting-deck-v1'
        if outside:
            validate_starting_deck_identity(self.starting_entities, self.starting_cards, self.next_entity_id)
        elif self.starting_entities is not None or self.starting_cards is not None:
            raise ValueError('An original class/turn price cannot invent starting-deck operands')
        selected, last_turn, last_action = [], 0, 0
        for index, row in enumerate(self.rows, 1):
            row.__post_init__()
            if (row.face.play_id != index or row.face.source_id >= self.next_entity_id or
                    not last_turn <= row.turn <= self.turn or not last_action < row.action <= self.action):
                raise ValueError('Played-class price lost its original ordered allocation window')
            matched = (True if self.spec.profile_id == 'cost.player-last-played-cost-v1' else
                       matches_outside_starting_deck(row.face, self.starting_entities) if outside else
                       row.turn == self.turn if self.spec.profile_id == 'cost.player-played-card-count-turn-v1'
                       else matches_played_class(row.face, self.spec.card_class))
            if matched and row.face.player_id == self.player_id: selected.append(row.face.play_id)
            last_turn, last_action = row.turn, row.action
        if self.spec.profile_id == 'cost.player-last-played-cost-v1':
            selected = selected[-1:]
            quantity = 0 if not selected else self.rows[selected[0]-1].accepted_cost
        else:
            quantity = len(selected)
        if self.selected_ids != tuple(selected) or self.quantity != quantity or self.after != max(0, self.before-self.quantity):
            raise ValueError('Played-class price differs from its complete original class quantity')


@dataclass(frozen=True)
class OwnerTurnQueryBoundaryFact:
    turn: int
    action: int
    status: str
    owner_history_length: int
    play_history_length: int
    last_owner_turn: OwnerTurnRecord | None
    opening_stage: str | None
    opening_first_player: int | None

    def __post_init__(self):
        _int(self.turn, 'intrinsic query turn', 1)
        for name in ('action', 'owner_history_length', 'play_history_length'):
            _int(getattr(self, name), 'intrinsic query '+name, 0)
        if type(self.status) is not str or self.status not in ('playing', 'finished', 'draw'):
            raise ValueError('Intrinsic query requires its captured game status')
        if self.owner_history_length:
            if type(self.last_owner_turn) is not OwnerTurnRecord:
                raise ValueError('Intrinsic query requires its complete last owner interval')
            self.last_owner_turn.__post_init__()
            if self.last_owner_turn.id != self.owner_history_length or self.last_owner_turn.turn != self.turn:
                raise ValueError('Intrinsic query last interval differs from its captured prefix')
            record = self.last_owner_turn
            clocks = (record.start_action, record.publication_action, record.end_action, record.closed_action,
                      None if record.start_interruption is None else record.start_interruption.game_ended_action)
            if any(clock is not None and clock > self.action for clock in clocks):
                raise ValueError('Intrinsic query boundary contains owner progress newer than its capture action')
            if self.status == 'playing' and record.closed:
                raise ValueError('Playing intrinsic query cannot have a closed current interval')
        elif self.last_owner_turn is not None:
            raise ValueError('Pre-first intrinsic query has no actual owner interval')
        if self.opening_stage is None:
            if self.opening_first_player is not None or not self.owner_history_length:
                raise ValueError('Intrinsic query has no complete scenario or opening identity')
        elif (type(self.opening_stage) is not str or self.opening_stage not in
              ('dealing', 'mulligan', 'starting', 'complete') or
              type(self.opening_first_player) is not int or self.opening_first_player not in (1, 2)):
            raise ValueError('Intrinsic query requires an explicit opening identity')
        if (self.opening_stage is not None and self.opening_stage != 'complete') != (self.owner_history_length == 0):
            raise ValueError('Intrinsic quotation phase disagrees with genuine owner history')


@dataclass(frozen=True)
class PlayerElementalStreakCostSpec:
    profile_id: str = 'cost.player-consecutive-elemental-turns-v1'

    def __post_init__(self):
        if type(self.profile_id) is not str or self.profile_id != 'cost.player-consecutive-elemental-turns-v1':
            raise ValueError('Unsupported finite consecutive Elemental price policy')


@dataclass(frozen=True)
class PlayerElementalStreakCostFact:
    spec: PlayerElementalStreakCostSpec
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    boundary: OwnerTurnQueryBoundaryFact
    owner_turns: tuple['OwnerTurnRecord', ...]
    rows: tuple[PlayerPlayedClassCostRow, ...]
    selected_interval_ids: tuple[int, ...]
    quantity: int
    before: int
    after: int

    def __post_init__(self):
        if type(self.spec) is not PlayerElementalStreakCostSpec:
            raise ValueError('Elemental price requires its complete finite declaration')
        self.spec.__post_init__()
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Elemental price requires its actual payer')
        _int(self.turn, 'Elemental price turn', 1)
        _int(self.action, 'Elemental price action', 0)
        _int(self.next_entity_id, 'Elemental price allocator', 1)
        for name in ('quantity', 'before', 'after'):
            _int(getattr(self, name), 'Elemental price '+name, 0)
        from .player_elemental_streak_costs import validate_operand
        validate_operand(self)


@dataclass(frozen=True)
class IntrinsicCostOperationFact:
    rule_index: int
    spec: IntrinsicCostSpec
    condition_index: int
    applied: bool
    before: int
    after: int

    def __post_init__(self):
        for name in ('rule_index', 'condition_index', 'before', 'after'):
            _int(getattr(self, name), 'intrinsic operation '+name, 0)
        if type(self.spec) is not IntrinsicCostSpec or type(self.applied) is not bool:
            raise ValueError('Intrinsic operation requires its complete declaration and relation')
        self.spec.__post_init__()


@dataclass(frozen=True)
class HeroHealedTurnMatch:
    """Complete original healing prefix for one finite target-hero/turn bool."""
    player_id: int
    turn: int
    action: int
    next_healing_id: int
    records: tuple[HealingRecord, ...]
    matched: bool

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Hero-healed condition requires its actual target player')
        _int(self.turn, 'hero-healed turn', 1); _int(self.action, 'hero-healed action', 0)
        _int(self.next_healing_id, 'hero-healed allocation cursor', 1)
        _bool(self.matched, 'hero-healed aggregate')
        if type(self.records) is not tuple or self.next_healing_id != len(self.records) + 1:
            raise ValueError('Hero-healed condition lost its complete original healing prefix')
        last_turn = last_action = 0; last_packet = (0, 0); matched = False
        for index, row in enumerate(self.records, 1):
            if type(row) is not HealingRecord: raise ValueError('Hero-healed condition requires immutable healing facts')
            row.__post_init__(); result = row.health_result; packet = (result.batch_id, result.packet_index)
            if (row.id != index or not last_turn <= result.turn <= self.turn or
                    not last_action <= row.action <= self.action or packet <= last_packet):
                raise ValueError('Hero-healed condition changed its complete original chronology')
            matched |= (result.turn == self.turn and result.target_controller == self.player_id
                        and result.target_kind == CardType.HERO.value and result.healed > 0)
            last_turn, last_action, last_packet = result.turn, row.action, packet
        if self.matched != matched:
            raise ValueError('Hero-healed aggregate differs from its complete actual target history')


PRESENCE_COST_CONDITIONS = ('hand_other_dragon', 'board_dormant_minion', 'board_no_minions', 'turn_holy_and_shadow',
                            'hand_edge', 'controlled_legendary')
CONTROLLED_PLAY_ZONES = (Zone.HERO, Zone.HERO_POWER, Zone.BOARD, Zone.WEAPON, Zone.SECRET, Zone.QUEST)


@dataclass(frozen=True)
class CostPresenceRow:
    entity_id: int
    card_id: str
    controller: int
    kind: CardType
    zone: Zone
    zone_epoch: int
    entered_order: int
    dormant: bool
    tribe_changes: tuple[Enchantment, ...] = ()

    def __post_init__(self):
        _int(self.entity_id, 'presence physical entity', 1); _name(self.card_id, 'presence original face')
        if type(self.controller) is not int or self.controller not in (1,2):
            raise ValueError('Presence row requires its original controller')
        if type(self.kind) is not CardType or type(self.zone) is not Zone or self.zone not in (Zone.HAND,*CONTROLLED_PLAY_ZONES):
            raise ValueError('Presence row requires its original hand/board type')
        if self.zone == Zone.BOARD and self.kind not in (CardType.MINION,CardType.LOCATION):
            raise ValueError('Presence board row is not a resident minion or location')
        if self.zone not in (Zone.HAND, Zone.BOARD) and self.kind != {
                Zone.HERO: CardType.HERO, Zone.HERO_POWER: CardType.HERO_POWER, Zone.WEAPON: CardType.WEAPON,
                Zone.SECRET: CardType.SPELL, Zone.QUEST: CardType.SPELL}[self.zone]:
            raise ValueError('Controlled presence row lost its actual in-play type')
        _int(self.zone_epoch, 'presence epoch', 0); _int(self.entered_order, 'presence entry', 0)
        _bool(self.dormant, 'presence dormancy')
        if self.dormant and (self.zone != Zone.BOARD or self.kind != CardType.MINION):
            raise ValueError('Only a resident minion can be dormant')
        if type(self.tribe_changes) is not tuple or any(type(x) is not Enchantment for x in self.tribe_changes):
            raise ValueError('Presence row requires immutable original tribe attachments')
        for item in self.tribe_changes:
            item.__post_init__()
            if item.tribe_change is None: raise ValueError('Presence row contains an unrelated attachment')
        if len({x.id for x in self.tribe_changes}) != len(self.tribe_changes):
            raise ValueError('Repeated original tribe attachment')


@dataclass(frozen=True)
class CostPresenceMatch:
    player_id: int
    condition: str
    turn: int
    action: int
    next_entity_id: int
    next_attachment_id: int
    source_id: int | None
    matched: bool
    hand: tuple[CostPresenceRow, ...] = ()
    boards: tuple[tuple[CostPresenceRow, ...], ...] = ((), ())
    cast_rows: tuple[PlayerSpellCountCostRow, ...] = ()

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1,2) or self.condition not in PRESENCE_COST_CONDITIONS:
            raise ValueError('Unsupported finite presence payer or condition')
        for name in ('turn','next_entity_id','next_attachment_id'): _int(getattr(self,name),'presence '+name,1)
        _int(self.action,'presence action',0); _optional_id(self.source_id,'presence physical subject')
        _bool(self.matched,'presence aggregate')
        if self.source_id is not None and self.source_id >= self.next_entity_id:
            raise ValueError('Presence price borrowed a future physical subject')
        if type(self.hand) is not tuple or type(self.boards) is not tuple or len(self.boards) != 2 or any(type(x) is not tuple for x in self.boards):
            raise ValueError('Presence requires complete immutable zone inventories')
        rows = (*self.hand,*self.boards[0],*self.boards[1])
        if any(type(x) is not CostPresenceRow for x in rows): raise ValueError('Presence inventory contains an untyped row')
        for x in rows:
            x.__post_init__()
            if x.entity_id >= self.next_entity_id or any(e.id >= self.next_attachment_id or (
                    e.source_id is not None and e.source_id >= self.next_entity_id) for e in x.tribe_changes):
                raise ValueError('Presence inventory borrowed a future allocation')
        if len({x.entity_id for x in rows}) != len(rows): raise ValueError('Repeated physical presence identity')
        if any((x.controller,x.zone)!=(self.player_id,Zone.HAND) for x in self.hand) or any(
                x.controller != player or x.zone not in (CONTROLLED_PLAY_ZONES if self.condition == 'controlled_legendary'
                    else (Zone.BOARD,)) for player,board in enumerate(self.boards,1) for x in board):
            raise ValueError('Presence inventory borrowed another physical zone')
        if type(self.cast_rows) is not tuple or any(type(x) is not PlayerSpellCountCostRow for x in self.cast_rows):
            raise ValueError('Presence requires the complete original cast prefix')
        last_turn,last_action=0,0
        for index,row in enumerate(self.cast_rows,1):
            row.__post_init__()
            if row.id != index or not last_turn <= row.turn <= self.turn or not last_action <= row.action <= self.action or row.source_id >= self.next_entity_id:
                raise ValueError('Presence changed the original cast chronology or allocator')
            last_turn,last_action=row.turn,row.action
        if self.condition in ('hand_other_dragon', 'hand_edge') and (self.boards != ((),()) or self.cast_rows) or (
                self.condition in ('board_dormant_minion', 'board_no_minions') and (self.hand or self.cast_rows)) or (
                self.condition == 'controlled_legendary' and (self.hand or self.cast_rows or self.boards[2-self.player_id])) or (
                self.condition == 'turn_holy_and_shadow' and (self.hand or self.boards != ((),()))):
            raise ValueError('Presence borrowed operands from another condition')

        expected=None
        if self.condition == 'hand_edge':
            expected=bool(self.hand and self.source_id is not None and self.source_id in
                          (self.hand[0].entity_id, self.hand[-1].entity_id))
        if self.condition == 'board_dormant_minion':
            expected=any(x.kind == CardType.MINION and x.dormant for board in self.boards for x in board)
        elif self.condition == 'turn_holy_and_shadow':
            schools={x.spell_school for x in self.cast_rows if x.player_id == self.player_id and x.turn == self.turn
                     and x.payload_started and x.failure is None}
            expected={SpellSchool.HOLY,SpellSchool.SHADOW} <= schools
        if expected is not None and self.matched != expected:
            raise ValueError('Presence aggregate differs from complete original operands')


@dataclass(frozen=True)
class DeckShuffleCostMatch:
    player_id: int
    turn: int
    action: int
    next_entity_id: int
    records: tuple
    selected_ids: tuple[int, ...]
    quantity: int
    matched: bool

    def __post_init__(self):
        from .deck_shuffles import validate_cost_match
        validate_cost_match(self)


@dataclass(frozen=True)
class IntrinsicCostStageFact:
    profile_id: str
    player_id: int
    card_id: str
    kind: CardType
    printed_cost: int
    base_cost: int
    amount: int
    boundary: OwnerTurnQueryBoundaryFact
    rules: tuple[IntrinsicCostSpec, ...]
    condition_facts: tuple[PreviousOwnerTurnMatch | HeroHealedTurnMatch | CurrentDeckCountMatch | PermanentManaMatch | HandOtherClassMatch | CostPresenceMatch | DeckShuffleCostMatch, ...]
    operations: tuple[IntrinsicCostOperationFact, ...]
    board_minions: BoardMinionCostFact | None = None
    hand_cards: HandCountCostFact | None = None
    hero_missing_health: HeroMissingHealthCostFact | None = None
    player_spells: PlayerSpellCountCostFact | None = None
    player_hero_powers: PlayerHeroPowerCountCostFact | None = None
    player_spell_mana: PlayerSpellManaCostFact | None = None
    minion_deaths: MinionDeathCostFact | None = None
    player_overload: PlayerOverloadCostFact | None = None
    player_played_class: PlayerPlayedClassCostFact | None = None
    hero_health_changes: HeroHealthChangeCostFact | None = None
    player_draws: PlayerDrawCountCostFact | None = None
    weapon_attack: PlayerWeaponAttackCostFact | None = None
    player_armor: PlayerArmorCostFact | None = None
    player_summons: PlayerSummonCountCostFact | None = None
    player_elemental_streak: PlayerElementalStreakCostFact | None = None
    player_corpses: PlayerCorpseSpendCostFact | None = None
    hero_damage_taken: HeroDamageTakenCostFact | None = None
    player_spell_damage: PlayerSpellDamageCostFact | None = None
    player_character_attacks: PlayerCharacterAttackCostFact | None = None
    kindred_sources: tuple[PlayerEffect, ...] = ()

    def __post_init__(self):
        if type(self.kindred_sources)is not tuple or any(type(x)is not PlayerEffect for x in self.kindred_sources):
            raise ValueError('Intrinsic Kindred sources require complete immutable instances')
        for x in self.kindred_sources:x.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.kindred_sources,self.kindred_sources[1:])):
            raise ValueError('Intrinsic Kindred sources lost original order')
        if self.kindred_sources and(len(self.rules)!=1 or self.rules[0].condition!='previous_owner_turn_type'):
            raise ValueError('Kindred repetition only applies to the native intrinsic type reduction')
        if type(self.profile_id) is not str or self.profile_id != 'cost.intrinsic.before-local-v1':
            raise ValueError('Unsupported intrinsic stage profile')
        if type(self.player_id) is not int or self.player_id not in (1, 2) or type(self.kind) is not CardType:
            raise ValueError('Invalid intrinsic quotation subject')
        _name(self.card_id, 'intrinsic quotation card')
        for name in ('printed_cost', 'base_cost', 'amount'): _int(getattr(self, name), 'intrinsic stage '+name, 0)
        if type(self.boundary) is not OwnerTurnQueryBoundaryFact:
            raise ValueError('Intrinsic stage requires its complete original history boundary')
        self.boundary.__post_init__()
        if self.board_minions is not None:
            if type(self.board_minions) is not BoardMinionCostFact:
                raise ValueError('Intrinsic stage requires a typed original board count')
            self.board_minions.__post_init__()
            if (self.board_minions.player_id, self.board_minions.before) != (self.player_id, self.base_cost):
                raise ValueError('Board count differs from the intrinsic payer or original base')
        if self.hand_cards is not None:
            if type(self.hand_cards) is not HandCountCostFact:
                raise ValueError('Intrinsic stage requires a typed original hand count')
            self.hand_cards.__post_init__()
            if (self.hand_cards.player_id, self.hand_cards.before) != (self.player_id, self.base_cost):
                raise ValueError('Hand count differs from the intrinsic payer or original base')
            if self.board_minions is not None:
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
        if self.hero_missing_health is not None:
            if type(self.hero_missing_health) is not HeroMissingHealthCostFact:
                raise ValueError('Intrinsic stage requires typed original hero health')
            self.hero_missing_health.__post_init__()
            if (self.hero_missing_health.player_id, self.hero_missing_health.before) != (self.player_id, self.base_cost):
                raise ValueError('Hero health differs from the intrinsic payer or original base')
            if self.board_minions is not None or self.hand_cards is not None:
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
        if self.player_spells is not None:
            if type(self.player_spells) is not PlayerSpellCountCostFact:
                raise ValueError('Intrinsic stage requires typed original personal spell counts')
            self.player_spells.__post_init__()
            if (self.player_spells.player_id, self.player_spells.before) != (self.player_id, self.base_cost):
                raise ValueError('Personal spell count differs from the intrinsic payer or base')
            if any(value is not None for value in (self.board_minions, self.hand_cards, self.hero_missing_health)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
            if any(row.turn > self.boundary.turn or row.action > self.boundary.action for row in self.player_spells.rows):
                raise ValueError('Personal spell cost contains casts newer than its quotation window')
        if self.player_hero_powers is not None:
            if type(self.player_hero_powers) is not PlayerHeroPowerCountCostFact:
                raise ValueError('Intrinsic stage requires typed original personal power counts')
            self.player_hero_powers.__post_init__()
            if (self.player_hero_powers.player_id, self.player_hero_powers.before) != (self.player_id, self.base_cost):
                raise ValueError('Personal power count differs from the intrinsic payer or base')
            if any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
            if any(row.turn > self.boundary.turn or row.action > self.boundary.action for row in self.player_hero_powers.rows):
                raise ValueError('Personal power cost contains activations newer than its quotation window')
        if self.player_spell_mana is not None:
            if type(self.player_spell_mana) is not PlayerSpellManaCostFact:
                raise ValueError('Intrinsic stage requires typed original spell mana expenditure')
            self.player_spell_mana.__post_init__()
            if (self.player_spell_mana.player_id, self.player_spell_mana.before) != (self.player_id, self.base_cost):
                raise ValueError('Spell mana expenditure differs from the intrinsic payer or base')
            if any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
            if (self.player_spell_mana.play_history_length != self.boundary.play_history_length or
                    any(row.turn > self.boundary.turn or row.action > self.boundary.action
                        for row in (*self.player_spell_mana.rows,*self.player_spell_mana.consumption_rows))):
                raise ValueError('Spell mana cost changed its complete original quotation prefix')
        if self.minion_deaths is not None:
            if type(self.minion_deaths) is not MinionDeathCostFact:
                raise ValueError('Intrinsic stage requires typed original minion death occurrences')
            self.minion_deaths.__post_init__()
            if (self.minion_deaths.player_id, self.minion_deaths.before, self.minion_deaths.turn) != (
                    self.player_id, self.base_cost, self.boundary.turn):
                raise ValueError('Death price differs from the original intrinsic payer, base or turn')
            if any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
        if self.player_overload is not None:
            if type(self.player_overload) is not PlayerOverloadCostFact:
                raise ValueError('Intrinsic stage requires typed original overload increments')
            self.player_overload.__post_init__()
            if (self.player_overload.player_id, self.player_overload.before,
                    self.player_overload.turn, self.player_overload.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Overload price differs from original payer, base or quotation window')
            if any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
            if any(row.owner_turn_id > self.boundary.owner_history_length for row in self.player_overload.records):
                raise ValueError('Overload price borrowed a later owner interval')
        if self.player_played_class is not None:
            if type(self.player_played_class) is not PlayerPlayedClassCostFact:
                raise ValueError('Intrinsic stage requires typed original played-class quantity')
            self.player_played_class.__post_init__()
            played = self.player_played_class
            if (played.player_id, played.before, played.turn, played.action, played.play_history_length) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action, self.boundary.play_history_length):
                raise ValueError('Played-class price differs from its original payer, base or complete window')
            if any(value is not None for value in (self.board_minions, self.hand_cards, self.hero_missing_health,
                    self.player_spells, self.player_hero_powers, self.player_spell_mana, self.minion_deaths, self.player_overload)):
                raise ValueError('Multiple intrinsic quantity formulas require a real reviewed source')
            if any(row.face.owner_turn_id is not None and row.face.owner_turn_id > self.boundary.owner_history_length
                   for row in played.rows):
                raise ValueError('Played-class price borrowed a later owner interval')
        if self.hero_health_changes is not None:
            health = self.hero_health_changes
            if type(health) is not HeroHealthChangeCostFact:
                raise ValueError('Intrinsic stage requires typed original hero health changes')
            health.__post_init__()
            if (health.player_id, health.before, health.turn, health.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Health-change price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths, self.player_overload, self.player_played_class)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
            if any(row.owner_turn_id > self.boundary.owner_history_length for row in health.records):
                raise ValueError('Health-change price borrowed a later genuine owner interval')
        if self.player_draws is not None:
            draws = self.player_draws
            if type(draws) is not PlayerDrawCountCostFact:
                raise ValueError('Intrinsic stage requires typed original physical draws')
            draws.__post_init__()
            if (draws.player_id, draws.before, draws.turn, draws.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Draw price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths, self.player_overload,
                    self.player_played_class, self.hero_health_changes)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.weapon_attack is not None:
            weapon = self.weapon_attack
            if type(weapon) is not PlayerWeaponAttackCostFact:
                raise ValueError('Intrinsic stage requires typed original equipped weapon Attack')
            weapon.__post_init__()
            if (weapon.player_id, weapon.before, weapon.turn, weapon.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Weapon price differs from original payer, base or quotation window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths, self.player_overload,
                    self.player_played_class, self.hero_health_changes, self.player_draws)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_armor is not None:
            if type(self.player_armor) is not PlayerArmorCostFact:
                raise ValueError('Intrinsic stage requires typed original current hero Armor')
            self.player_armor.__post_init__()
            armor = self.player_armor
            if (armor.player_id, armor.before, armor.turn, armor.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Armor price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths, self.player_overload,
                    self.player_played_class, self.hero_health_changes, self.player_draws, self.weapon_attack)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_summons is not None:
            summons = self.player_summons
            if type(summons) is not PlayerSummonCountCostFact:
                raise ValueError('Intrinsic stage requires typed original successful summons')
            summons.__post_init__()
            if (summons.player_id, summons.before, summons.turn, summons.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Summon price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers,
                    self.player_spell_mana, self.minion_deaths, self.player_overload,
                    self.player_played_class, self.hero_health_changes, self.player_draws,
                    self.weapon_attack, self.player_armor)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_elemental_streak is not None:
            streak = self.player_elemental_streak
            if type(streak) is not PlayerElementalStreakCostFact:
                raise ValueError('Intrinsic stage requires typed original consecutive Elemental intervals')
            streak.__post_init__()
            if (streak.player_id, streak.before, streak.boundary) != (self.player_id, self.base_cost, self.boundary):
                raise ValueError('Elemental price differs from its original payer, base or complete window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_corpses is not None:
            corpses = self.player_corpses
            if type(corpses) is not PlayerCorpseSpendCostFact:
                raise ValueError('Intrinsic stage requires typed original successful corpse debits')
            corpses.__post_init__()
            if (corpses.player_id, corpses.before, corpses.turn, corpses.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Corpse price differs from its original payer, base or complete window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons,
                    self.player_elemental_streak)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.hero_damage_taken is not None:
            damage = self.hero_damage_taken
            if type(damage) is not HeroDamageTakenCostFact:
                raise ValueError('Intrinsic stage requires typed original received-damage packets')
            damage.__post_init__()
            if (damage.player_id, damage.before, damage.turn, damage.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Received-damage price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons,
                    self.player_elemental_streak, self.player_corpses)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_spell_damage is not None:
            damage = self.player_spell_damage
            if type(damage) is not PlayerSpellDamageCostFact or self.kind is not CardType.SPELL:
                raise ValueError('Intrinsic stage requires typed current-turn Spell damage packets')
            damage.__post_init__()
            if (damage.player_id, damage.before, damage.turn, damage.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Spell damage price differs from its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons,
                    self.player_elemental_streak, self.player_corpses, self.hero_damage_taken)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.player_character_attacks is not None:
            attacks = self.player_character_attacks
            if type(attacks) is not PlayerCharacterAttackCostFact or self.kind is not CardType.SPELL:
                raise ValueError('Intrinsic stage requires a typed original character declaration price')
            attacks.__post_init__()
            if (attacks.player_id, attacks.before, attacks.turn, attacks.action) != (
                    self.player_id, self.base_cost, self.boundary.turn, self.boundary.action):
                raise ValueError('Character declaration price changed its original payer, base or window')
            if self.rules or any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons,
                    self.player_elemental_streak, self.player_corpses, self.hero_damage_taken, self.player_spell_damage)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if type(self.rules) is not tuple or any(type(rule) is not IntrinsicCostSpec for rule in self.rules):
            raise ValueError('Intrinsic stage requires complete immutable rules')
        condition_cls = (DeckShuffleCostMatch if self.rules and self.rules[0].condition == 'own_deck_shuffle_count' else
                         CurrentDeckCountMatch if self.rules and self.rules[0].condition == 'current_deck_count' else
                         PermanentManaMatch if self.rules and self.rules[0].condition == 'permanent_mana_at_least' else
                         HandOtherClassMatch if self.rules and self.rules[0].condition == 'hand_other_class' else
                         HeroHealedTurnMatch if self.rules and self.rules[0].condition == 'hero_healed_this_turn' else
                         CostPresenceMatch if self.rules and self.rules[0].condition in PRESENCE_COST_CONDITIONS else PreviousOwnerTurnMatch)
        for name, cls in (('rules', IntrinsicCostSpec), ('condition_facts', condition_cls),
                          ('operations', IntrinsicCostOperationFact)):
            values = getattr(self, name)
            if type(values) is not tuple or any(type(v) is not cls for v in values):
                raise ValueError('Intrinsic stage requires complete immutable '+name)
            for value in values: value.__post_init__()
        if len(self.operations) != len(self.rules) or len(self.condition_facts) != int(bool(self.rules)):
            raise ValueError('Intrinsic stage lost a complete rule or unique condition')
        if len({r.condition for r in self.rules}) > 1:
            raise ValueError('Mixed intrinsic history conditions require a real reviewed source')
        if self.rules and self.rules[0].condition in PRESENCE_COST_CONDITIONS:
            match=self.condition_facts[0]
            expected_kind = CardType.SPELL if self.rules[0].condition in ('hand_edge', 'controlled_legendary') else CardType.MINION
            if self.kind != expected_kind or len(self.rules) != 1 or (match.player_id,match.condition,match.turn,match.action) != (
                    self.player_id,self.rules[0].condition,self.boundary.turn,self.boundary.action):
                raise ValueError('Presence price changed its ordinary subject, declaration or original window')
            if any(getattr(self,n) is not None for n in ('board_minions','hand_cards','hero_missing_health','player_spells',
                    'player_hero_powers','player_spell_mana','minion_deaths','player_overload','player_played_class',
                    'hero_health_changes','player_draws','weapon_attack','player_armor','player_summons',
                    'player_elemental_streak','player_corpses','hero_damage_taken','player_spell_damage','player_character_attacks')):
                raise ValueError('Presence does not combine with another intrinsic quantity formula')
        if self.rules and self.rules[0].condition == 'hand_other_class':
            if self.kind != CardType.SPELL or len(self.rules) != 1:
                raise ValueError('Hand class price requires one independent physical Spell rule')
            condition = self.condition_facts[0]
            if (condition.player_id,condition.turn,condition.action) != (self.player_id,self.boundary.turn,self.boundary.action):
                raise ValueError('Hand class price changed its original player or window')
        if self.rules and self.rules[0].condition == 'current_deck_count':
            if self.kind != CardType.SPELL or len(self.rules) != 1 or any(value is not None for value in (
                    self.board_minions, self.hand_cards, self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana, self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes, self.player_draws, self.weapon_attack, self.player_armor, self.player_summons, self.player_elemental_streak, self.player_corpses, self.hero_damage_taken)):
                raise ValueError('Current deck price requires one physical Spell discount without other intrinsic formulas')
            condition = self.condition_facts[0]
            if (condition.turn, condition.action, condition.card_count, condition.comparison) != (
                    self.boundary.turn, self.boundary.action, self.rules[0].card_count, self.rules[0].comparison):
                raise ValueError('Current deck price changed its original window or printed threshold')
        if self.rules and self.rules[0].condition in ('previous_owner_turn_elemental', 'hero_healed_this_turn'):
            if self.rules[0].condition == 'previous_owner_turn_elemental' and self.condition_facts[0].query != PlayedTypeQuery(CardType.MINION, ('elemental',)):
                raise ValueError('Elemental intrinsic condition changed its fixed original Minion query')
            if any(value is not None for value in (self.board_minions, self.hand_cards,
                    self.hero_missing_health, self.player_spells, self.player_hero_powers, self.player_spell_mana,
                    self.minion_deaths, self.player_overload, self.player_played_class, self.hero_health_changes,
                    self.player_draws, self.weapon_attack, self.player_armor, self.player_summons,
                    self.player_elemental_streak)):
                raise ValueError('Multiple intrinsic formulas require a real reviewed source')
        if self.rules and self.rules[0].condition == 'permanent_mana_at_least':
            if self.kind != CardType.SPELL or len(self.rules) != 1 or any(value is not None for value in (
                    self.board_minions,self.hand_cards,self.hero_missing_health,self.player_spells,self.player_hero_powers,
                    self.player_spell_mana,self.minion_deaths,self.player_overload,self.player_played_class,
                    self.hero_health_changes,self.player_draws,self.weapon_attack,self.player_armor,self.player_summons,
                    self.player_elemental_streak,self.player_corpses,self.hero_damage_taken)):
                raise ValueError('Permanent mana price requires one independent physical Spell rule')
            condition = self.condition_facts[0]
            if (condition.turn,condition.action,condition.threshold) != (
                    self.boundary.turn,self.boundary.action,self.rules[0].mana_crystals):
                raise ValueError('Permanent mana price changed its original window or threshold')
        if any(f.player_id != self.player_id for f in self.condition_facts):
            raise ValueError('Intrinsic stage borrowed another payer history')
        for condition in self.condition_facts:
            if type(condition) is DeckShuffleCostMatch:
                if self.kind != CardType.MINION or len(self.rules) != 1 or (condition.turn,condition.action) != (self.boundary.turn,self.boundary.action):
                    raise ValueError('Shuffle pricing changed its original physical Minion window')
                continue
            if type(condition) is CostPresenceMatch: continue
            if type(condition) is HandOtherClassMatch:
                continue
            if type(condition) is PermanentManaMatch:
                continue
            if type(condition) is CurrentDeckCountMatch:
                continue
            if type(condition) is HeroHealedTurnMatch:
                if self.kind != CardType.MINION or (condition.turn, condition.action) != (self.boundary.turn, self.boundary.action):
                    raise ValueError('Hero-healed condition changed its original physical Minion window')
                continue
            record = condition.owner_turn
            if record is not None:
                clocks = (record.start_action, record.publication_action, record.end_action, record.closed_action,
                          None if record.start_interruption is None else record.start_interruption.game_ended_action)
                if (record.id > self.boundary.owner_history_length or record.turn > self.boundary.turn
                        or any(clock is not None and clock > self.boundary.action for clock in clocks)):
                    raise ValueError('Intrinsic selected interval is newer than its original query boundary')
        if any((o.rule_index, o.spec, o.condition_index) != (i, self.rules[i], 0)
               for i, o in enumerate(self.operations)):
            raise ValueError('Intrinsic operations must preserve complete declaration order')
        count = (self.board_minions if self.board_minions is not None else
                 self.hand_cards if self.hand_cards is not None else
                 self.hero_missing_health if self.hero_missing_health is not None else
                 self.player_spells if self.player_spells is not None else
                 self.player_hero_powers if self.player_hero_powers is not None else
                 self.player_spell_mana if self.player_spell_mana is not None else
                 self.minion_deaths if self.minion_deaths is not None else
                 self.player_overload if self.player_overload is not None else
                 self.player_played_class if self.player_played_class is not None else
                 self.hero_health_changes if self.hero_health_changes is not None else
                 self.player_draws if self.player_draws is not None else
                 self.weapon_attack if self.weapon_attack is not None else
                 self.player_armor if self.player_armor is not None else
                 self.player_summons if self.player_summons is not None else
                 self.player_elemental_streak if self.player_elemental_streak is not None else
                 self.player_corpses if self.player_corpses is not None else
                 self.hero_damage_taken if self.hero_damage_taken is not None else
                 self.player_spell_damage if self.player_spell_damage is not None else self.player_character_attacks)
        if not self.rules and self.amount != (self.base_cost if count is None else count.after):
            raise ValueError('Empty intrinsic stage cannot change the physical base')


@dataclass(frozen=True)
class GeneratedCostQuoteInput:
    player_id: int
    card_id: str
    kind: CardType
    base_cost: int
    initial_cost: CostSpec | None
    minimum_cost: int = 0

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2) or type(self.kind) is not CardType:
            raise ValueError('Invalid generated cost subject')
        _name(self.card_id, 'generated cost card')
        _int(self.base_cost, 'generated cost base', 0)
        _int(self.minimum_cost, 'generated cost minimum', 0)
        if self.initial_cost is not None:
            if type(self.initial_cost) is not CostSpec: raise ValueError('Generated cost requires complete CostSpec')
            self.initial_cost.__post_init__()


@dataclass(frozen=True)
class GeneratedCostQuoteFact:
    quote_input: GeneratedCostQuoteInput
    intrinsic: IntrinsicCostStageFact
    local_amount: int
    local_payment: PaymentType
    amount: int
    payment: PaymentType
    contributions: tuple[CostContribution, ...]
    modifier_ids: tuple[int, ...]
    consumable_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.quote_input) is not GeneratedCostQuoteInput or type(self.intrinsic) is not IntrinsicCostStageFact:
            raise ValueError('Generated cost fact requires complete operands and intrinsic stage')
        self.quote_input.__post_init__(); self.intrinsic.__post_init__()
        if (self.intrinsic.player_id, self.intrinsic.card_id, self.intrinsic.kind, self.intrinsic.base_cost) != (
                self.quote_input.player_id, self.quote_input.card_id, self.quote_input.kind, self.quote_input.base_cost):
            raise ValueError('Generated intrinsic stage differs from its hypothetical subject')
        if self.intrinsic.hand_cards is not None and self.intrinsic.hand_cards.subject_id is not None:
            raise ValueError('Generated hand count cannot borrow a physical subject')
        if self.intrinsic.condition_facts and type(self.intrinsic.condition_facts[0]) is CostPresenceMatch and self.intrinsic.condition_facts[0].source_id is not None:
            raise ValueError('Generated presence cannot borrow a physical subject')
        for name in ('local_amount', 'amount'): _int(getattr(self, name), 'generated fact '+name, 0)
        if type(self.local_payment) is not PaymentType or type(self.payment) is not PaymentType:
            raise ValueError('Generated fact requires typed payment accounts')
        if type(self.contributions) is not tuple or any(type(c) is not CostContribution or c.kind == 'local_enchantment' for c in self.contributions):
            raise ValueError('Generated facts contain only complete external contributions')
        for c in self.contributions:
            c.__post_init__()
            if c.first_play is not None:
                validate_first_play_quote_boundary(c.first_play, self.quote_input.player_id, self.intrinsic.boundary)
        for values in (self.modifier_ids, self.consumable_ids):
            if type(values) is not tuple or any(type(i) is not int or i < 1 for i in values) or any(a >= b for a,b in zip(values, values[1:])):
                raise ValueError('Generated external IDs require unique global order')
        if self.modifier_ids != tuple(c.id for c in self.contributions) or self.consumable_ids != tuple(
                c.id for c in self.contributions if c.kind == 'player_modifier' and c.modifier.uses_remaining is not None):
            raise ValueError('Generated cost IDs differ from complete contributions')
        if any(c.player_id != self.quote_input.player_id for c in self.contributions if c.kind == 'player_modifier'):
            raise ValueError('Generated cost modifier borrowed another payer')


@dataclass(frozen=True)
class CostQuoteInput:
    """Explicit physical quote operands; no synthetic state entity is needed."""
    source_id: int
    player_id: int
    card_id: str
    kind: CardType
    base_cost: int
    enchantments: tuple[Enchantment, ...]
    abilities: tuple[AbilityInstance, ...]
    minimum_cost: int = 0
    hand_lifetime: HandLifetime | None = None

    def __post_init__(self):
        _int(self.source_id, 'cost quote source', 1)
        if type(self.player_id) is not int or self.player_id not in (1, 2) or type(self.kind) is not CardType:
            raise ValueError('Invalid cost quote subject')
        if type(self.card_id) is not str:
            raise ValueError('Cost quote face requires a string')
        _name(self.card_id, 'cost quote face')
        _int(self.base_cost, 'cost quote base', 0)
        _int(self.minimum_cost, 'cost quote minimum', 0)
        if self.hand_lifetime is not None:
            if type(self.hand_lifetime)is not HandLifetime:raise ValueError('Temporary price qualifier requires complete HandLifetime')
            self.hand_lifetime.__post_init__()
            if self.minimum_cost<self.hand_lifetime.minimum_cost:raise ValueError('Temporary price lost its original hand floor')
        for items, cls in ((self.enchantments, Enchantment), (self.abilities, AbilityInstance)):
            if type(items) is not tuple or any(type(item) is not cls for item in items):
                raise ValueError('Cost quote subject requires immutable complete attachments')
            for item in items: item.__post_init__()
        ids = [item.id for item in (*self.enchantments, *self.abilities)]
        if len(set(ids)) != len(ids):
            raise ValueError('Cost quote input cannot reuse an attachment identity')


@dataclass(frozen=True)
class FirstPlayCostFact:
    """Original hand prefix, plus physical CAST operands for periodic spells."""
    player_id: int
    kind: CardType
    turn: int
    action: int
    next_entity_id: int
    play_history_length: int
    rows: tuple[PlayerPlayedClassCostRow, ...]
    cast_rows: tuple[PlayerSpellCountCostRow, ...] | None = None
    cast_history_length: int | None = None

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('First-play price requires its actual payer')
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('First-play price requires one supported card type')
        for name in ('turn', 'next_entity_id'): _int(getattr(self, name), 'first-play price '+name, 1)
        for name in ('action', 'play_history_length'): _int(getattr(self, name), 'first-play price '+name, 0)
        if type(self.rows) is not tuple or len(self.rows) != self.play_history_length or any(
                type(row) is not PlayerPlayedClassCostRow for row in self.rows):
            raise ValueError('First-play price lost its complete original paid-hand prefix')
        last_turn = last_action = 0
        for index, row in enumerate(self.rows, 1):
            row.__post_init__()
            if (row.face.play_id != index or row.face.source_id >= self.next_entity_id or
                    not last_turn <= row.turn <= self.turn or not last_action < row.action <= self.action):
                raise ValueError('First-play price changed its original ordered allocation window')
            last_turn, last_action = row.turn, row.action

        if self.cast_rows is None:
            if self.cast_history_length is not None:
                raise ValueError('Hand ordinal cannot invent a physical cast cursor')
        else:
            if self.kind != CardType.SPELL or type(self.cast_rows) is not tuple:
                raise ValueError('Physical spell ordinal requires complete typed cast rows')
            _int(self.cast_history_length, 'periodic spell original cursor', 0)
            if len(self.cast_rows) != self.cast_history_length:
                raise ValueError('Periodic spell price lost its complete physical cast prefix')
            last_turn = last_action = 0
            for index, row in enumerate(self.cast_rows, 1):
                if type(row) is not PlayerSpellCountCostRow:
                    raise ValueError('Periodic spell price requires a physical cast operand')
                row.__post_init__()
                if (row.id != index or row.source_id >= self.next_entity_id or
                        row.play_id is not None and row.play_id > self.play_history_length or
                        not last_turn <= row.turn <= self.turn or not last_action <= row.action <= self.action):
                    raise ValueError('Periodic spell price changed its original cast allocation window')
                last_turn, last_action = row.turn, row.action

    @property
    def is_first(self):
        return self.ordinal == 1

    @property
    def ordinal(self):
        if self.cast_rows is not None:
            return 1 + sum(row.player_id == self.player_id and row.turn == self.turn and
                           row.payload_started and row.failure is None for row in self.cast_rows)
        return 1 + sum((row.face.player_id, row.face.kind, row.turn) ==
                       (self.player_id, self.kind, self.turn) for row in self.rows)


def validate_first_play_quote_boundary(first, player_id, boundary):
    if (first.player_id, first.turn, first.action, first.play_history_length) != (
            player_id, boundary.turn, boundary.action, boundary.play_history_length):
        raise ValueError('First-play price differs from its original quotation boundary')


@dataclass(frozen=True)
class CostContribution:
    """One complete local or external price operation and its physical owner."""
    kind: str
    player_id: int
    carrier_id: int | None
    enchantment: Enchantment | None = None
    modifier: CostModifier | None = None
    ability: AbilityInstance | None = None
    first_play: FirstPlayCostFact | None = None

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in ('local_enchantment', 'player_modifier', 'cost_aura'):
            raise ValueError('Invalid cost contribution family')
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid cost contribution owner')
        _optional_id(self.carrier_id, 'cost contribution carrier')
        expected = {'local_enchantment': ('enchantment', Enchantment),
                    'player_modifier': ('modifier', CostModifier),
                    'cost_aura': ('ability', AbilityInstance)}
        name, cls = expected[self.kind]
        if type(getattr(self, name)) is not cls or any(getattr(self, other) is not None
                for other in ('enchantment', 'modifier', 'ability') if other != name):
            raise ValueError('Cost contribution requires exactly its complete typed source')
        getattr(self, name).__post_init__()
        if (self.kind == 'player_modifier') != (self.carrier_id is None):
            raise ValueError('Cost contribution physical carrier disagrees with its family')
        if self.kind == 'player_modifier' and self.modifier.scope != CostScope.CARD:
            raise ValueError('Physical card quotes require card cost modifiers')
        if self.kind == 'cost_aura' and (self.ability.kind != 'cost_aura' or self.ability.consumed):
            raise ValueError('Cost contribution requires an unconsumed cost aura')
        first = self.kind == 'cost_aura' and (self.ability.cost_aura.first_per_turn or
                                            self.ability.cost_aura.every_nth_per_turn is not None)
        if first:
            if type(self.first_play) is not FirstPlayCostFact:
                raise ValueError('First-play cost contribution lost its original history operands')
            self.first_play.__post_init__()
            if self.ability.cost_aura.cost.card_types != (self.first_play.kind,):
                raise ValueError('First-play price history changed its card-type qualifier')
            physical_spells = (self.ability.cost_aura.every_nth_per_turn is not None and
                               self.first_play.kind == CardType.SPELL)
            if physical_spells != (self.first_play.cast_rows is not None):
                raise ValueError('Periodic spell price changed its counting policy')
        elif self.first_play is not None:
            raise ValueError('Ordinary price contributions cannot invent first-play history')

    @property
    def id(self):
        return (self.enchantment if self.enchantment is not None else
                self.modifier if self.modifier is not None else self.ability).id


@dataclass(frozen=True)
class CostQuoteFact:
    """Frozen complete price operands and result, never an account debit."""
    profile_id: str | None
    quote_input: CostQuoteInput
    local_amount: int
    local_payment: PaymentType
    amount: int
    payment: PaymentType
    contributions: tuple[CostContribution, ...]
    modifier_ids: tuple[int, ...]
    consumable_ids: tuple[int, ...]
    intrinsic: IntrinsicCostStageFact

    def __post_init__(self):
        if self.profile_id is not None:
            if type(self.profile_id) is not str:
                raise ValueError('Cost quote fact profile requires a string')
            _name(self.profile_id, 'Cost quote fact profile')
        if type(self.quote_input) is not CostQuoteInput:
            raise ValueError('Cost quote fact requires complete physical operands')
        self.quote_input.__post_init__()
        if type(self.intrinsic) is not IntrinsicCostStageFact:
            raise ValueError('Physical quote requires its complete intrinsic stage')
        self.intrinsic.__post_init__()
        if (self.intrinsic.player_id, self.intrinsic.card_id, self.intrinsic.kind, self.intrinsic.base_cost) != (
                self.quote_input.player_id, self.quote_input.card_id, self.quote_input.kind, self.quote_input.base_cost):
            raise ValueError('Physical intrinsic stage differs from its captured subject')
        board = self.intrinsic.board_minions
        if self.intrinsic.condition_facts and type(self.intrinsic.condition_facts[0]) is CostPresenceMatch and self.intrinsic.condition_facts[0].source_id != self.quote_input.source_id:
            raise ValueError('Physical presence price differs from its captured subject')
        if board is not None and self.quote_input.source_id >= board.next_entity_id:
            raise ValueError('Physical board price subject is newer than its captured allocator')
        if self.intrinsic.hand_cards is not None and self.intrinsic.hand_cards.subject_id != self.quote_input.source_id:
            raise ValueError('Physical hand count differs from its quoted subject')
        hero = self.intrinsic.hero_missing_health
        if hero is not None and self.quote_input.source_id >= hero.next_entity_id:
            raise ValueError('Physical hero price subject is newer than its captured allocator')
        personal = self.intrinsic.player_spells
        if personal is not None and self.quote_input.source_id >= personal.next_entity_id:
            raise ValueError('Physical personal spell price subject is newer than its captured allocator')
        powers = self.intrinsic.player_hero_powers
        if powers is not None and self.quote_input.source_id >= powers.next_entity_id:
            raise ValueError('Physical personal power price subject is newer than its captured allocator')
        spell_mana = self.intrinsic.player_spell_mana
        if spell_mana is not None and self.quote_input.source_id >= spell_mana.next_entity_id:
            raise ValueError('Physical spell mana price subject is newer than its captured allocator')
        deaths = self.intrinsic.minion_deaths
        if deaths is not None and self.quote_input.source_id >= deaths.next_entity_id:
            raise ValueError('Physical death price subject is newer than its captured allocator')
        overload = self.intrinsic.player_overload
        if overload is not None and self.quote_input.source_id >= overload.next_entity_id:
            raise ValueError('Physical overload price subject is newer than its captured allocator')
        played_class = self.intrinsic.player_played_class
        if played_class is not None and self.quote_input.source_id >= played_class.next_entity_id:
            raise ValueError('Physical played-class price subject is newer than its captured allocator')
        health_changes = self.intrinsic.hero_health_changes
        if health_changes is not None and self.quote_input.source_id >= health_changes.next_entity_id:
            raise ValueError('Physical health-change price subject is newer than its captured allocator')
        summons = self.intrinsic.player_summons
        if summons is not None and self.quote_input.source_id >= summons.next_entity_id:
            raise ValueError('Physical summon price subject is newer than its captured allocator')
        streak = self.intrinsic.player_elemental_streak
        if streak is not None and self.quote_input.source_id >= streak.next_entity_id:
            raise ValueError('Physical Elemental price subject is newer than its captured allocator')
        corpses = self.intrinsic.player_corpses
        if corpses is not None and self.quote_input.source_id >= corpses.next_entity_id:
            raise ValueError('Physical corpse price subject is newer than its captured allocator')
        damage = self.intrinsic.hero_damage_taken
        if damage is not None and self.quote_input.source_id >= damage.next_entity_id:
            raise ValueError('Physical received-damage price subject is newer than its captured allocator')
        spell_damage = self.intrinsic.player_spell_damage
        if spell_damage is not None and self.quote_input.source_id >= spell_damage.next_entity_id:
            raise ValueError('Physical spell-damage price subject is newer than its captured allocator')
        character_attacks = self.intrinsic.player_character_attacks
        if character_attacks is not None and self.quote_input.source_id >= character_attacks.next_entity_id:
            raise ValueError('Physical character-price subject is newer than its captured allocator')
        for name in ('local_amount', 'amount'): _int(getattr(self, name), 'cost fact '+name, 0)
        if type(self.local_payment) is not PaymentType or type(self.payment) is not PaymentType:
            raise ValueError('Cost quote fact requires typed payment accounts')
        if type(self.contributions) is not tuple or any(type(c) is not CostContribution for c in self.contributions):
            raise ValueError('Cost quote fact requires complete ordered contributions')
        for c in self.contributions:
            c.__post_init__()
            if c.first_play is not None:
                validate_first_play_quote_boundary(c.first_play, self.quote_input.player_id, self.intrinsic.boundary)
        local = tuple(c for c in self.contributions if c.kind == 'local_enchantment')
        external = tuple(c for c in self.contributions if c.kind != 'local_enchantment')
        if self.contributions != (*local, *external) or tuple(c.enchantment for c in local) != self.quote_input.enchantments:
            raise ValueError('Cost quote local operations must preserve complete input order')
        if any((c.carrier_id, c.player_id) != (self.quote_input.source_id, self.quote_input.player_id) for c in local):
            raise ValueError('Local cost contribution differs from its physical subject')
        for values in (self.modifier_ids, self.consumable_ids):
            if type(values) is not tuple or any(type(i) is not int or i < 1 for i in values) or any(a >= b for a,b in zip(values, values[1:])):
                raise ValueError('Cost quote external identities require unique global order')
        if tuple(c.id for c in external) != self.modifier_ids:
            raise ValueError('Cost quote IDs differ from its complete external contributions')
        ids = [c.id for c in self.contributions]
        if len(set(ids)) != len(ids):
            raise ValueError('Cost quote contributions cannot reuse an identity')
        if any(c.player_id != self.quote_input.player_id for c in external if c.kind == 'player_modifier'):
            raise ValueError('Cost quote player modifier differs from its payer')
        if self.consumable_ids != tuple(c.id for c in external if c.kind == 'player_modifier' and c.modifier.uses_remaining is not None):
            raise ValueError('Cost quote finite player sources must be exact')


@dataclass(frozen=True)
class HandPlayCostReceipt:
    """Submitted price, its original hand acquisition and quotation clock."""
    quote_origin: str
    turn: int
    action: int
    hand_entry_id: int
    zone_epoch: int
    printed_cost: int
    quote: CostQuoteFact

    def __post_init__(self):
        if type(self.quote_origin) is not str or self.quote_origin not in ('current_hand', 'rewind_root'):
            raise ValueError('Invalid submitted cost quote origin')
        for name in ('turn', 'hand_entry_id'): _int(getattr(self, name), 'submitted cost '+name, 1)
        for name in ('action', 'zone_epoch', 'printed_cost'): _int(getattr(self, name), 'submitted cost '+name, 0)
        if type(self.quote) is not CostQuoteFact or self.quote.quote_input.kind not in (
                CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.HERO, CardType.LOCATION):
            raise ValueError('Submitted hand cost requires a complete physical hand quote')
        self.quote.__post_init__()
        board = self.quote.intrinsic.board_minions
        if board is not None and any(row.entity_id == self.quote.quote_input.source_id
                for rows in board.boards for row in rows):
            raise ValueError('Submitted hand price cannot count its own not-yet-played minion')
        hand = self.quote.intrinsic.hand_cards
        if hand is not None and self.quote.quote_input.source_id not in hand.hands[self.quote.quote_input.player_id - 1]:
            raise ValueError('Submitted hand price lost its own original hand resident')


@dataclass(frozen=True)
class SpellCostFacts:
    """Price facts captured once at one existing Spell acceptance window."""
    printed_cost: int
    cost_input: CostQuoteInput
    local_amount: int
    local_payment: PaymentType
    intrinsic: IntrinsicCostStageFact
    window_quotes: tuple[CostQuoteFact, ...] = ()

    def __post_init__(self):
        _int(self.printed_cost, 'Spell printed cost fact', 0)
        _int(self.local_amount, 'Spell local cost fact', 0)
        if type(self.cost_input) is not CostQuoteInput or self.cost_input.kind != CardType.SPELL:
            raise ValueError('Spell cost facts require a physical Spell input')
        self.cost_input.__post_init__()
        if type(self.intrinsic) is not IntrinsicCostStageFact:
            raise ValueError('Spell cost facts require their complete intrinsic stage')
        self.intrinsic.__post_init__()
        if (self.intrinsic.player_id, self.intrinsic.card_id, self.intrinsic.kind, self.intrinsic.base_cost,
                self.intrinsic.printed_cost) != (self.cost_input.player_id, self.cost_input.card_id,
                self.cost_input.kind, self.cost_input.base_cost, self.printed_cost):
            raise ValueError('Spell intrinsic stage differs from its original physical operands')
        if type(self.local_payment) is not PaymentType:
            raise ValueError('Spell local cost fact requires a payment account')
        if type(self.window_quotes) is not tuple or any(type(q) is not CostQuoteFact for q in self.window_quotes):
            raise ValueError('Spell cost facts require complete immutable window quotes')
        for q in self.window_quotes:
            q.__post_init__()
            if q.profile_id is None or q.quote_input != self.cost_input or q.intrinsic != self.intrinsic or (q.local_amount, q.local_payment) != (self.local_amount, self.local_payment):
                raise ValueError('Spell window quote differs from its accepted physical operands')
        profiles = [q.profile_id for q in self.window_quotes]
        if profiles != sorted(set(profiles)):
            raise ValueError('Spell window quotes require unique sorted profile IDs')

    @property
    def card_id(self):
        return self.cost_input.card_id


@dataclass(frozen=True)
class SpellSubmissionReceipt:
    """The complete player-policy set accepted at a paid hand submission."""
    hero_class: CardClass | None
    modifiers: tuple[SpellRepeatModifier, ...]
    cost_facts: SpellCostFacts | None = None

    def __post_init__(self):
        if self.cost_facts is not None:
            if type(self.cost_facts) is not SpellCostFacts:
                raise ValueError('Spell submission requires typed cost facts')
            self.cost_facts.__post_init__()
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Invalid Spell submission hero class')
        if type(self.modifiers) is not tuple or any(type(m) is not SpellRepeatModifier for m in self.modifiers):
            raise ValueError('Spell submission requires immutable complete modifiers')
        for modifier in self.modifiers: modifier.__post_init__()
        if any(a.id >= b.id for a,b in zip(self.modifiers,self.modifiers[1:])):
            raise ValueError('Spell submission modifiers require ordered unique identities')


@dataclass(frozen=True)
class SpellRepeatContributor:
    carrier_id: int
    ability: AbilityInstance

    def __post_init__(self):
        _int(self.carrier_id, 'Spell repeat carrier', 1)
        if type(self.ability) is not AbilityInstance or self.ability.kind != 'spell_repeat':
            raise ValueError('Spell repeat contributor requires its complete ability')
        self.ability.__post_init__()


@dataclass(frozen=True)
class SpellPayloadReceipt:
    """Compact original late-window facts, including a one-cast/empty root."""
    target_id: int | None
    behavior_ids: tuple[str, ...]
    hero_class: CardClass | None
    contributors: tuple[SpellRepeatContributor, ...]
    casts: int
    cost_facts: SpellCostFacts | None = None

    def __post_init__(self):
        if self.cost_facts is not None:
            if type(self.cost_facts) is not SpellCostFacts:
                raise ValueError('Spell payload requires typed cost facts')
            self.cost_facts.__post_init__()
        _optional_id(self.target_id, 'Spell accepted target')
        _int(self.casts, 'Spell accepted execution count', 1)
        if self.hero_class is not None and type(self.hero_class) is not CardClass:
            raise ValueError('Invalid Spell payload hero class')
        if type(self.behavior_ids) is not tuple:
            raise ValueError('Spell accepted behaviors require an immutable tuple')
        for behavior in self.behavior_ids: _name(behavior, 'Spell accepted behavior')
        if (type(self.contributors) is not tuple or
                any(type(c) is not SpellRepeatContributor for c in self.contributors)):
            raise ValueError('Spell acceptance requires complete immutable contributors')
        for contributor in self.contributors: contributor.__post_init__()
        if len({c.ability.id for c in self.contributors}) != len(self.contributors):
            raise ValueError('Spell acceptance cannot repeat a contributor identity')


@dataclass(frozen=True)
class OwnerTurnStartInterruption:
    """Recorded while the genuine pending BeginTurnEvents is still queued."""
    root_action: int
    game_ended_event: int
    game_ended_action: int
    pending_work: str = 'BeginTurnEvents'
    pending_count: int = 1

    def __post_init__(self):
        _int(self.root_action, 'startup root action', 1)
        _int(self.game_ended_event, 'startup terminal event', 1)
        _int(self.game_ended_action, 'startup terminal action', self.root_action)
        if type(self.pending_work) is not str or self.pending_work != 'BeginTurnEvents':
            raise ValueError('Startup interruption requires the genuine pending start work')
        if type(self.pending_count) is not int or self.pending_count != 1:
            raise ValueError('Startup interruption requires exactly one pending start work')


@dataclass(frozen=True)
class OwnerTurnRecord:
    """A genuinely started owner interval, closed only at stable handoff."""
    id: int
    player_id: int
    owner_index: int
    turn: int
    previous_id: int | None
    start_action: int
    start_event: int
    origin: str
    closed_action: int | None = None
    closed_event: int | None = None
    publication_event: int | None = None
    publication_action: int | None = None
    end_event: int | None = None
    end_action: int | None = None
    start_interruption: OwnerTurnStartInterruption | None = None

    def __post_init__(self):
        for name in ('id', 'owner_index', 'turn'):
            _int(getattr(self, name), name, 1)
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid owner-turn player')
        _optional_id(self.previous_id, 'previous owner-turn')
        if self.previous_id is not None and self.previous_id >= self.id:
            raise ValueError('Owner-turn predecessor must be earlier')
        for name in ('start_action', 'start_event'):
            _int(getattr(self, name), name, 0)
        if self.origin not in ('scenario', 'actual') or type(self.origin) is not str:
            raise ValueError('Invalid owner-turn start origin')
        if (self.closed_action is None) != (self.closed_event is None):
            raise ValueError('Owner-turn closure requires both cursors')
        if self.closed_action is not None:
            _int(self.closed_action, 'owner-turn closing action', self.start_action)
            _int(self.closed_event, 'owner-turn closing event', self.start_event)
        for event_name, action_name in (('publication_event', 'publication_action'), ('end_event', 'end_action')):
            event, action = getattr(self, event_name), getattr(self, action_name)
            if (event is None) != (action is None):
                raise ValueError('Owner-turn event progress requires both event and action')
            if event is not None:
                _int(event, event_name, self.start_event + 1)
                _int(action, action_name, self.start_action)
        if self.origin == 'scenario' and (self.publication_event is not None or self.start_interruption is not None):
            raise ValueError('Conceptual scenario start has no actual publication work')
        if self.end_event is not None and self.publication_event is not None and self.end_event <= self.publication_event:
            raise ValueError('Natural end must follow genuine start publication')
        if self.closed and (self.end_event is None or self.end_event > self.closed_event or self.end_action > self.closed_action):
            raise ValueError('Closed owner interval requires its settled natural end')
        if self.start_interruption is not None:
            if type(self.start_interruption) is not OwnerTurnStartInterruption:
                raise ValueError('Expected typed startup interruption')
            self.start_interruption.__post_init__()
            if (self.origin != 'actual' or self.publication_event is not None or self.end_event is not None or self.closed
                    or self.start_interruption.root_action != self.start_action
                    or self.start_interruption.game_ended_event <= self.start_event):
                raise ValueError('Startup interruption cannot replace published or ended turn progress')

    @property
    def closed(self):
        return self.closed_action is not None


@dataclass(frozen=True)
class FrozenPlayedFaceFact:
    """Immutable hand-submission face, independent of later entity changes."""
    play_id: int
    source_id: int
    player_id: int
    owner_turn_id: int | None
    card_id: str
    kind: CardType
    metadata: CardMetadata | None
    spell_school: SpellSchool | None
    opening_stage: str | None = None
    opening_first_player: int | None = None

    def __post_init__(self):
        for name in ('play_id', 'source_id'):
            _int(getattr(self, name), name, 1)
        _optional_id(self.owner_turn_id, 'actual submitted owner-turn')
        if self.owner_turn_id is None:
            if (type(self.opening_stage) is not str or self.opening_stage not in ('dealing', 'mulligan', 'starting')
                    or type(self.opening_first_player) is not int or self.opening_first_player not in (1, 2)):
                raise ValueError('Pre-first submission requires its explicit opening phase identity')
        elif self.opening_stage is not None or self.opening_first_player is not None:
            raise ValueError('An actual-turn submitted face cannot borrow an opening phase')
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid frozen played-face player')
        _name(self.card_id, 'frozen played face')
        if type(self.kind) is not CardType or self.kind == CardType.HERO_POWER:
            raise ValueError('Frozen played face requires a hand-card kind')
        if self.metadata is not None:
            if type(self.metadata) is not CardMetadata:
                raise ValueError('Frozen played face requires explicit CardMetadata or unknown')
            self.metadata.__post_init__()
        if self.spell_school is not None and (
                type(self.spell_school) is not SpellSchool or self.kind != CardType.SPELL):
            raise ValueError('Frozen played-face school belongs only to a Spell')


@dataclass(frozen=True)
class PlayedTypeQuery:
    kind: CardType
    tribes: tuple[str, ...] | None = None
    spell_school: SpellSchool | None = None

    def __post_init__(self):
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION, CardType.SPELL):
            raise ValueError('Previous-own-turn type query supports Minion or Spell')
        if self.tribes is not None:
            if (type(self.tribes) is not tuple or len(set(self.tribes)) != len(self.tribes)
                    or any(type(t) is not str or not t.strip() for t in self.tribes)):
                raise ValueError('History query tribes require a unique immutable tuple')
        if self.kind == CardType.SPELL and self.tribes is not None:
            raise ValueError('A Spell history query cannot declare tribes')
        if self.spell_school is not None and (
                self.kind != CardType.SPELL or type(self.spell_school) is not SpellSchool):
            raise ValueError('History query school belongs only to a Spell')


@dataclass(frozen=True)
class OwnerTurnMatchRow:
    face: FrozenPlayedFaceFact
    matched: bool

    def __post_init__(self):
        if type(self.face) is not FrozenPlayedFaceFact or type(self.matched) is not bool:
            raise ValueError('History match requires a complete typed face and bool')
        self.face.__post_init__()


@dataclass(frozen=True)
class PreviousOwnerTurnMatch:
    player_id: int
    query: PlayedTypeQuery
    owner_turn: OwnerTurnRecord | None
    rows: tuple[OwnerTurnMatchRow, ...]
    matched: bool
    profile_id: str = 'owner-turn.latest-closed-v1'

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid previous-own-turn query player')
        if type(self.query) is not PlayedTypeQuery:
            raise ValueError('History match requires its original query')
        self.query.__post_init__()
        if type(self.profile_id) is not str or self.profile_id != 'owner-turn.latest-closed-v1':
            raise ValueError('Unsupported previous-own-turn query profile')
        if type(self.rows) is not tuple or any(type(r) is not OwnerTurnMatchRow for r in self.rows):
            raise ValueError('History match requires complete ordered rows')
        for row in self.rows: row.__post_init__()
        if self.owner_turn is not None:
            if type(self.owner_turn) is not OwnerTurnRecord:
                raise ValueError('History match requires a typed owner interval')
            self.owner_turn.__post_init__()
            if not self.owner_turn.closed or self.owner_turn.player_id != self.player_id:
                raise ValueError('Previous-owner match requires a closed own interval')
            if any((r.face.player_id, r.face.owner_turn_id, r.face.kind) !=
                    (self.player_id, self.owner_turn.id, self.query.kind) for r in self.rows):
                raise ValueError('History match row differs from its interval or query')
        elif self.rows:
            raise ValueError('A pre-first-turn history query has no candidate rows')
        if any(a.face.play_id >= b.face.play_id for a, b in zip(self.rows, self.rows[1:])):
            raise ValueError('History match rows require ordered unique play identities')
        if type(self.matched) is not bool or self.matched != any(r.matched for r in self.rows):
            raise ValueError('History aggregate differs from its complete rows')


@dataclass(frozen=True)
class OwnerTurnTypeMatch:
    """One original own interval, including its complete matching/false rows."""
    owner_turn: OwnerTurnRecord
    rows: tuple[OwnerTurnMatchRow, ...]
    matched: bool

    def __post_init__(self):
        if type(self.owner_turn) is not OwnerTurnRecord:
            raise ValueError('Owner-type relation requires its original typed interval')
        self.owner_turn.__post_init__()
        if type(self.rows) is not tuple or any(type(r) is not OwnerTurnMatchRow for r in self.rows):
            raise ValueError('Owner-type relation requires complete immutable rows')
        for row in self.rows:
            row.__post_init__()
            if (row.face.player_id, row.face.owner_turn_id) != (self.owner_turn.player_id, self.owner_turn.id):
                raise ValueError('Owner-type relation face differs from its own interval')
        if any(a.face.play_id >= b.face.play_id for a, b in zip(self.rows, self.rows[1:])):
            raise ValueError('Owner-type relation faces require ordered unique play identities')
        if type(self.matched) is not bool or self.matched != any(r.matched for r in self.rows):
            raise ValueError('Owner-type aggregate differs from its complete rows')


@dataclass(frozen=True)
class OwnerTurnTypeHistory:
    """Pure original interval relation; not a saved source-authentication proof."""
    player_id: int
    query: PlayedTypeQuery
    intervals: tuple[OwnerTurnTypeMatch, ...]
    outside_owner_turn_faces: tuple[FrozenPlayedFaceFact, ...]
    profile_id: str = 'owner-turn.all-intervals-printed-type-v1'

    def __post_init__(self):
        if type(self.player_id) is not int or self.player_id not in (1, 2):
            raise ValueError('Invalid owner-type history player')
        if type(self.query) is not PlayedTypeQuery:
            raise ValueError('Owner-type history requires its original explicit query')
        self.query.__post_init__()
        if self.query.kind == CardType.MINION and self.query.tribes is None:
            raise ValueError('History subject has unknown Minion tribes')
        if type(self.profile_id) is not str or self.profile_id != 'owner-turn.all-intervals-printed-type-v1':
            raise ValueError('Unsupported owner-type history profile')
        if type(self.intervals) is not tuple or any(type(r) is not OwnerTurnTypeMatch for r in self.intervals):
            raise ValueError('Owner-type history requires ordered immutable interval relations')
        from .owner_turns import _match_face
        previous = None
        faces = []
        for index, relation in enumerate(self.intervals, 1):
            relation.__post_init__()
            interval = relation.owner_turn
            if (interval.player_id != self.player_id or interval.owner_index != index
                    or interval.previous_id != (None if previous is None else previous.id)):
                raise ValueError('Owner-type history changed its complete own interval chain')
            if previous is not None and (not previous.closed or interval.id <= previous.id or interval.turn <= previous.turn):
                raise ValueError('Owner-type history changed original interval order or closure')
            for row in relation.rows:
                if row.face.kind != self.query.kind or row.matched != _match_face(row.face, self.query):
                    raise ValueError('Owner-type history row differs from its original type query')
                faces.append(row.face)
            previous = interval
        if any(a.play_id >= b.play_id for a, b in zip(faces, faces[1:])):
            raise ValueError('Owner-type history lost original hand-submission order')
        if (type(self.outside_owner_turn_faces) is not tuple
                or any(type(f) is not FrozenPlayedFaceFact for f in self.outside_owner_turn_faces)):
            raise ValueError('Outside-own-interval faces require immutable original submissions')
        own_ids = {r.owner_turn.id for r in self.intervals}
        for face in self.outside_owner_turn_faces:
            face.__post_init__()
            if ((face.player_id, face.kind) != (self.player_id, self.query.kind)
                    or face.owner_turn_id in own_ids):
                raise ValueError('Outside-own-interval face borrowed an own interval or another query')
        if any(a.play_id >= b.play_id for a, b in zip(self.outside_owner_turn_faces, self.outside_owner_turn_faces[1:])):
            raise ValueError('Outside-own-interval faces require original unique submission order')
        faces.extend(self.outside_owner_turn_faces)
        if len({f.play_id for f in faces}) != len(faces):
            raise ValueError('Owner-type history duplicated a submitted face')


@dataclass(frozen=True)
class PaidHandClose:
    action: int
    event_cursor: int

    def __post_init__(self):
        _int(self.action, 'paid hand closing action', 1)
        _int(self.event_cursor, 'paid hand closing event cursor', 1)


@dataclass(frozen=True)
class PaidHandInterruption:
    action: int
    game_ended_event: int

    def __post_init__(self):
        _int(self.action, 'paid hand interruption action', 1)
        _int(self.game_ended_event, 'paid hand interruption terminal event', 1)


from .actions import PlayCard, PlayBodyTarget


@dataclass(frozen=True)
class PaidBodyTargetEntityFact:
    """Complete scalar inputs for engine-owned original target predicates."""
    id: int
    card_id: str
    owner: int
    controller: int
    zone: Zone
    kind: CardType
    active: bool
    doomed: bool
    health: int
    attack: int
    max_health: int
    damage: int
    durability: int
    keywords: tuple[Keyword, ...]
    tribe_changes: tuple[Enchantment, ...]

    def __post_init__(self):
        _int(self.id, 'original target entity', 1)
        if type(self.card_id) is not str or not self.card_id:
            raise ValueError('Original target fact requires its registered card')
        for seat in (self.owner, self.controller):
            if type(seat) is not int or seat not in (1, 2):
                raise ValueError('Original target fact requires an exact seat')
        if type(self.zone) is not Zone or type(self.kind) is not CardType:
            raise ValueError('Original target fact requires exact zone and kind')
        _bool(self.active, 'original target participation')
        _bool(self.doomed, 'original target doomed')
        _int(self.health, 'original target health')
        _int(self.attack, 'original target attack', 0)
        _int(self.max_health, 'original target maximum health')
        _int(self.damage, 'original target damage', 0)
        if self.health != self.max_health - self.damage:
            raise ValueError('Original target health contradicts its maximum health and damage')
        _int(self.durability, 'original target durability')
        if (type(self.keywords) is not tuple or any(type(k) is not Keyword for k in self.keywords)
                or tuple(sorted(set(self.keywords), key=lambda k: k.value)) != self.keywords):
            raise ValueError('Original target keywords require canonical unique order')
        _tribe_changes(self.tribe_changes)
        if self.tribe_changes and self.kind != CardType.MINION:
            raise ValueError('Only original minion facts can carry tribe changes')


@dataclass(frozen=True)
class PaidTargetObservation:
    """Complete detached public input plus host-only physical reference bindings."""
    observation_json: str
    references: tuple[tuple[int, str], ...]

    def __post_init__(self):
        if type(self.observation_json) is not str or not self.observation_json:
            raise ValueError('Player target inputs require canonical observation JSON')
        if type(self.references) is not tuple:
            raise ValueError('Original player references require an immutable ordered vector')
        ids, refs = [], []
        for row in self.references:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError('Original player reference requires its physical identity and handle')
            _int(row[0], 'original player physical reference', 1)
            if type(row[1]) is not str:
                raise ValueError('Original player handle requires an exact string')
            ids.append(row[0]); refs.append(row[1])
        if ids != sorted(set(ids)) or len(set(refs)) != len(refs):
            raise ValueError('Original player references require unique ordered identities and handles')
        from .player_target_inputs import decode
        # The value contains a player projection; origin consumers enforce
        # their own active-player requirement (paid origins keep it strict).
        decode(self,require_active_player=False)


@dataclass(frozen=True)
class PaidBodyTargetOrigin:
    """Nonrecursive, immutable original target and physical-authority inputs."""
    turn: int
    action: int
    next_entity_id: int
    next_attachment_id: int
    hand: tuple[int, ...]
    board: tuple[int, ...]
    source_json: str
    entities: tuple[PaidBodyTargetEntityFact, ...]
    original_state_hash: str
    observation: PaidTargetObservation | None = None

    def __post_init__(self):
        if self.observation is not None:
            if type(self.observation) is not PaidTargetObservation:
                raise ValueError('Original player target inputs require their exact typed observation')
            self.observation.__post_init__()
        for name in ('turn', 'next_entity_id', 'next_attachment_id'):
            _int(getattr(self, name), 'original target ' + name, 1)
        _int(self.action, 'original target action', 0)
        if type(self.hand) is not tuple or len(set(self.hand)) != len(self.hand):
            raise ValueError('Original hand requires complete ordered unique identities')
        for entity_id in self.hand: _int(entity_id, 'original hand entity', 1)
        if type(self.board) is not tuple or len(set(self.board)) != len(self.board):
            raise ValueError('Original board requires complete ordered unique identities')
        for entity_id in self.board: _int(entity_id, 'original board entity', 1)
        if type(self.source_json) is not str or not self.source_json:
            raise ValueError('Original physical authority requires canonical Entity JSON')
        if type(self.entities) is not tuple or any(type(e) is not PaidBodyTargetEntityFact for e in self.entities):
            raise ValueError('Original target universe requires exact immutable facts')
        for entity in self.entities: entity.__post_init__()
        ids = tuple(e.id for e in self.entities)
        if ids != tuple(sorted(set(ids))) or any(i >= self.next_entity_id for i in ids):
            raise ValueError('Original target universe requires complete canonical identities')
        tribe_ids = [c.id for fact in self.entities for c in fact.tribe_changes]
        if len(set(tribe_ids)) != len(tribe_ids):
            raise ValueError('Original tribe attachments cannot belong to multiple carriers')
        for fact in self.entities:
            for change in fact.tribe_changes:
                if (change.id >= self.next_attachment_id or change.source_id is not None and change.source_id not in ids
                        or change.expires_turn is not None and change.expires_turn < self.turn):
                    raise ValueError('Original tribe change exceeds its actual allocation or lifetime window')
        if (type(self.original_state_hash) is not str or len(self.original_state_hash) != 64
                or any(c not in '0123456789abcdef' for c in self.original_state_hash)):
            raise ValueError('Original target origin requires its payment boundary digest')


@dataclass(frozen=True)
class PaidBodyTargetReceipt:
    action: PlayCard
    selected: tuple[PlayBodyTarget, ...]
    body_choices: tuple[tuple[int | None, ...], ...]
    body_target_active: tuple[bool, ...]
    root_choices: tuple[int | None, ...]
    original_state_hash: str
    registry_fingerprint: str
    origin: PaidBodyTargetOrigin
    origin_hash: str
    retry_root: PaidBodyTargetReceipt | None = None
    retry_attempt: int = 0
    retry_event_start: int | None = None

    def __post_init__(self):
        _int(self.retry_attempt, 'body target retry attempt', 0)
        if self.retry_root is None:
            if self.retry_attempt != 0 or self.retry_event_start is not None:
                raise ValueError('Body retry lost its original root receipt')
        else:
            if type(self.retry_root) is not PaidBodyTargetReceipt or self.retry_root.retry_root is not None or self.retry_attempt < 1:
                raise ValueError('Body retry requires exactly one original non-retry receipt')
            self.retry_root.__post_init__()
            _int(self.retry_event_start, 'body target retry event cursor', 0)
        if type(self.action) is not PlayCard or self.action.body_target_profile_id is None:
            raise ValueError('Body target receipt requires its exact original vector action')
        self.action.__post_init__()
        if type(self.origin) is not PaidBodyTargetOrigin:
            raise ValueError('Body target receipt lost its complete original target inputs')
        self.origin.__post_init__()
        if self.origin.original_state_hash != self.original_state_hash:
            raise ValueError('Body target origin differs from its original payment boundary')
        if type(self.selected) is not tuple or any(type(v) is not PlayBodyTarget for v in self.selected):
            raise ValueError('Body receipt requires its complete canonical vector')
        if set(self.selected) != set(self.action.body_targets) or len(self.selected) != len(self.action.body_targets):
            raise ValueError('Canonical body vector differs from original submission')
        if type(self.body_choices) is not tuple or type(self.body_target_active) is not tuple or not len(self.selected) == len(self.body_choices) == len(self.body_target_active):
            raise ValueError('Body receipt lost a complete original target requirement')
        for choices, active, selected in zip(self.body_choices, self.body_target_active, self.selected):
            _bool(active, 'body target activation')
            if type(choices) is not tuple or len(set(choices)) != len(choices):
                raise ValueError('Body choices require an ordered unique immutable vector')
            for v in choices: _optional_id(v, 'body target candidate')
            if selected.target_id not in choices or not active and choices != (None,):
                raise ValueError('Body target violates its original complete requirement')
        if type(self.root_choices) is not tuple or len(set(self.root_choices)) != len(self.root_choices) or self.action.target_id not in self.root_choices:
            raise ValueError('Ordinary root target differs from its original choices')
        for v in self.root_choices: _optional_id(v, 'ordinary root candidate')
        for v in (self.original_state_hash, self.registry_fingerprint, self.origin_hash):
            if type(v) is not str or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
                raise ValueError('Body receipt requires exact original digests')


@dataclass(frozen=True)
class HandNeighborFact:
    entity_id: int
    player_id: int
    card_id: str
    zone_epoch: int

    def __post_init__(self):
        _int(self.entity_id,'original hand neighbor',1)
        if type(self.player_id)is not int or self.player_id not in (1,2):raise ValueError('Hand neighbor requires its original controller')
        _name(self.card_id,'original hand neighbor face');_int(self.zone_epoch,'original hand neighbor epoch',0)


@dataclass(frozen=True)
class PlayRecord:
    """Facts frozen before payment/movement; completion never changes provenance."""
    id: int
    source_id: int
    player_id: int
    card_id: str
    kind: CardType
    turn: int
    action: int
    target_id: int | None
    hand_index: int
    hand_size: int
    prior_turn_plays: int
    prior_game_plays: int
    cost: int
    payment: PaymentType
    mana_before: int
    mana_after: int
    mana_crystals: int
    hand_entry_id: int
    hand_entry_turn: int
    manathirst_threshold: int | None = None
    countered: bool = False
    completed: bool = False
    interrupted: bool = False
    corrupt_candidates: tuple[HandProgressCandidate, ...] = ()
    held_spells: HeldSpellProgress | None = None
    card_spell_repeats: tuple[AbilityInstance, ...] = ()
    position: int | None = None
    magnetic_target_id: int | None = None
    hand_derivatives: tuple[HandDerivativeSpec, ...] = ()

    branch_id: str | None = None
    minion_result: str | None = None
    battlecries: tuple[BattlecryPayload, ...] = ()
    combos: tuple[ComboPayload, ...] = ()
    battlecry_acceptance: BattlecryAcceptanceReceipt | None = None
    spell_submission: SpellSubmissionReceipt | None = None
    spell_payload: SpellPayloadReceipt | None = None
    spell_acceptance_closed: bool = False
    combo_submission_receipt_id: int | None = None
    combo_acceptance: ComboAcceptanceReceipt | None = None
    submitted_cost: HandPlayCostReceipt | None = None
    played_face: FrozenPlayedFaceFact | None = None
    paid_hand_close: PaidHandClose | None = None
    paid_hand_interrupt: PaidHandInterruption | None = None
    body_targets: PaidBodyTargetReceipt | None = None
    board_player_id: int | None = None
    hand_neighbors: tuple[HandNeighborFact, ...] | None = None

    def __post_init__(self):
        if self.hand_neighbors is not None:
            if type(self.hand_neighbors)is not tuple or any(type(x)is not HandNeighborFact for x in self.hand_neighbors):
                raise ValueError('Hand play requires immutable original physical neighbors')
            if len(self.hand_neighbors)!=int(self.hand_index>0)+int(self.hand_index<self.hand_size-1):
                raise ValueError('Hand play lost an original adjacent slot')
            for x in self.hand_neighbors:
                x.__post_init__()
                if x.player_id!=self.player_id or x.entity_id==self.source_id:raise ValueError('Hand play borrowed foreign/self neighbors')
            if len({x.entity_id for x in self.hand_neighbors})!=len(self.hand_neighbors):raise ValueError('Duplicate original hand neighbor')
        if self.board_player_id is not None and (
                type(self.board_player_id) is not int or self.board_player_id not in (1, 2) or
                self.kind != CardType.MINION):
            raise ValueError('Only a minion hand record can carry its exact board player')
        if self.body_targets is not None:
            if type(self.body_targets) is not PaidBodyTargetReceipt or self.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO):
                raise ValueError('Body targets require their exact paid physical receipt')
            self.body_targets.__post_init__()
            a = self.body_targets.action
            if (a.entity_id, a.player_id, a.target_id, a.position, a.branch_id, a.board_player_id) != (self.source_id, self.player_id, self.target_id, self.position, self.branch_id, self.board_player_id):
                raise ValueError('Body receipt borrowed another paid action')
        if type(self.played_face) is not FrozenPlayedFaceFact:
            raise ValueError('Hand play requires its payment-before frozen face')
        self.played_face.__post_init__()
        if ((self.played_face.play_id, self.played_face.source_id, self.played_face.player_id,
             self.played_face.card_id, self.played_face.kind) !=
                (self.id, self.source_id, self.player_id, self.card_id, self.kind)):
            raise ValueError('Frozen played face differs from its physical hand root')
        if self.submitted_cost is not None:
            if type(self.submitted_cost) is not HandPlayCostReceipt:
                raise ValueError('Submitted cost requires a physical paid hand receipt')
            self.submitted_cost.__post_init__()
            submitted = self.submitted_cost
            quoted = submitted.quote
            if ((quoted.quote_input.source_id, quoted.quote_input.player_id) != (self.source_id, self.player_id) or
                    (quoted.amount, quoted.payment) != (self.cost, self.payment) or
                    submitted.hand_entry_id != self.hand_entry_id or submitted.turn > self.turn or submitted.action > self.action):
                raise ValueError('Submitted price differs from its physical hand play')
            if submitted.quote_origin == 'current_hand' and (quoted.quote_input.card_id != self.card_id or
                    (submitted.turn, submitted.action) != (self.turn, self.action)):
                raise ValueError('Current-hand submitted price differs from its accepted face or clock')
        for name, cls in (('paid_hand_close', PaidHandClose), ('paid_hand_interrupt', PaidHandInterruption)):
            value = getattr(self, name)
            if value is not None:
                if type(value) is not cls or self.kind == CardType.SPELL or self.submitted_cost is None:
                    raise ValueError('Non-Spell payment progress requires its complete submitted receipt')
                value.__post_init__()
                if value.action < self.action:
                    raise ValueError('Non-Spell payment progress predates its actual hand submission')
        if self.paid_hand_close is not None and (not self.completed or self.interrupted or self.paid_hand_interrupt is not None):
            raise ValueError('Only an uninterrupted completed hand root may close its payment acceptance')
        if self.kind == CardType.SPELL and (self.spell_submission is not None or self.completed and not self.interrupted) and self.submitted_cost is None:
            raise ValueError('Accepted paid Spell requires its submitted cost receipt')
        _optional_id(self.combo_submission_receipt_id, 'Combo submission policy receipt')
        physical_combo = self.kind in (CardType.MINION, CardType.WEAPON, CardType.HERO)
        if not physical_combo and (self.combo_submission_receipt_id is not None or self.combo_acceptance is not None):
            raise ValueError('Only paid physical hand roots carry Combo acceptance receipts')
        if self.combo_acceptance is not None:
            if type(self.combo_acceptance) is not ComboAcceptanceReceipt or self.combo_submission_receipt_id is None:
                raise ValueError('Invalid post-entry Combo acceptance receipt')
            self.combo_acceptance.__post_init__()
            if (self.combo_acceptance.player_id != self.player_id or
                    self.combo_acceptance.recipient.carrier_id != self.source_id or
                    self.combo_acceptance.recipient.kind != self.kind):
                raise ValueError('Accepted Combo recipient differs from its physical play')
        if physical_combo and self.completed and not self.interrupted and (
                self.combo_submission_receipt_id is None or self.combo_acceptance is None):
            raise ValueError('Completed physical hand roots require both Combo window receipts')
        _bool(self.spell_acceptance_closed, 'Spell acceptance closed')
        if self.kind != CardType.SPELL and (self.spell_submission is not None or
                self.spell_payload is not None or self.spell_acceptance_closed):
            raise ValueError('Only hand spells carry Spell acceptance receipts')
        if self.spell_submission is not None:
            if type(self.spell_submission) is not SpellSubmissionReceipt:
                raise ValueError('Invalid Spell submission receipt')
            self.spell_submission.__post_init__()
        if self.spell_payload is not None:
            if type(self.spell_payload) is not SpellPayloadReceipt or self.spell_submission is None or self.countered:
                raise ValueError('Invalid Spell payload acceptance receipt')
            self.spell_payload.__post_init__()
        if self.spell_acceptance_closed and (self.spell_submission is None or not self.completed or self.interrupted):
            raise ValueError('Only a completed submitted Spell can close acceptance')
        if self.battlecry_acceptance is not None:
            if (type(self.battlecry_acceptance) is not BattlecryAcceptanceReceipt or
                    self.kind not in (CardType.MINION, CardType.WEAPON, CardType.HERO) or self.countered or
                    self.kind == CardType.MINION and self.minion_result != 'summoned'):
                raise ValueError('Invalid post-entry Battlecry acceptance receipt')
            self.battlecry_acceptance.__post_init__()
            if (self.battlecry_acceptance.recipient.carrier_id != self.source_id or
                    self.battlecry_acceptance.recipient.kind != self.kind):
                raise ValueError('Accepted Battlecry recipient differs from its physical play')
        if type(self.card_spell_repeats) is not tuple or self.card_spell_repeats and self.kind!=CardType.SPELL:
            raise ValueError('Only spells capture card spell repeat attachments')
        for a in self.card_spell_repeats:
            if type(a) is not AbilityInstance or a.kind!='card_spell_repeat':
                raise ValueError('Invalid captured card spell repeat attachment')
            a.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.card_spell_repeats,self.card_spell_repeats[1:])):
            raise ValueError('Card spell repeat captures require ordered unique identities')
        validate_combo_payloads(self.combos)
        if self.combos and self.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO):
            raise ValueError('Played Combo declaration requires a physical card')
        if (type(self.battlecries) is not tuple or
                any(type(b) is not BattlecryPayload for b in self.battlecries) or
                len({b.ability_id for b in self.battlecries}) != len(self.battlecries) or
                self.battlecries and self.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO)):
            raise ValueError('Invalid captured played Battlecries')
        for payload in self.battlecries: payload.__post_init__()
        if self.minion_result is not None and (self.kind != CardType.MINION or self.minion_result not in ("summoned", "magnetized", "countered", "board_full")):
            raise ValueError("Invalid minion play result")
        if self.minion_result == "countered" and not self.countered or self.countered and self.minion_result not in (None, "countered"):
            raise ValueError("Minion result disagrees with counter flag")
        if self.kind == CardType.MINION and self.completed and self.minion_result is None:
            raise ValueError("Completed minion play requires an entry result")
        if self.branch_id is not None: _name(self.branch_id, 'captured branch')
        if (type(self.hand_derivatives) is not tuple or
                any(type(s) is not HandDerivativeSpec for s in self.hand_derivatives) or
                len({s.keyword for s in self.hand_derivatives}) != len(self.hand_derivatives)):
            raise ValueError('Invalid captured hand derivative declarations')
        for spec in self.hand_derivatives:
            spec.__post_init__()
            if self.kind != (CardType.SPELL if spec.keyword == Keyword.TWINSPELL else CardType.MINION):
                raise ValueError('Hand derivative and played card kind differ')
        _optional_id(self.magnetic_target_id, 'magnetic target')
        if self.position is not None:
            _int(self.position, 'play position', 0)
            if self.kind not in (CardType.MINION,CardType.LOCATION):
                raise ValueError('This played card has no board position')
        if self.magnetic_target_id is not None and (self.position is None or self.kind != CardType.MINION or
                self.target_id is not None and self.body_targets is None or self.magnetic_target_id == self.source_id):
            raise ValueError('Invalid magnetic play branch')
        for name in ('mana_before', 'mana_after', 'mana_crystals', 'hand_entry_turn'):
            _int(getattr(self, name), name, 0)
        _int(self.hand_entry_id, 'play hand entry', 1)
        if self.manathirst_threshold is not None:
            _int(self.manathirst_threshold, 'manathirst threshold', 1)
        if (self.hand_entry_turn > self.turn or
                self.mana_after != self.mana_before - (self.cost if self.payment == PaymentType.MANA else 0)):
            raise ValueError('Invalid frozen play conditions')
        if (type(self.corrupt_candidates) is not tuple or
                any(type(c) is not HandProgressCandidate for c in self.corrupt_candidates) or
                len({c.ability_id for c in self.corrupt_candidates}) != len(self.corrupt_candidates)):
            raise ValueError('Invalid captured Corrupt candidates')
        if self.held_spells is not None:
            if type(self.held_spells) is not HeldSpellProgress:raise ValueError('Invalid frozen held-spell condition')
            self.held_spells.__post_init__()
        for candidate in self.corrupt_candidates:
            candidate.__post_init__()
            if candidate.player_id != self.player_id or candidate.source_id == self.source_id:
                raise ValueError('Invalid Corrupt candidate ownership or self reference')
        for name in ('id', 'source_id', 'player_id', 'turn', 'action', 'hand_size'):
            _int(getattr(self, name), name, 1)
        for name in ('hand_index', 'prior_turn_plays', 'prior_game_plays', 'cost'):
            _int(getattr(self, name), name, 0)
        _name(self.card_id, 'played card')
        _optional_id(self.target_id, 'original play target')
        if self.player_id not in (1, 2) or not isinstance(self.kind, CardType) or not isinstance(self.payment, PaymentType):
            raise ValueError('Invalid play record type or player')
        if self.hand_index >= self.hand_size or self.prior_turn_plays > self.prior_game_plays:
            raise ValueError('Invalid pre-play hand position or counts')
        for name in ('countered', 'completed', 'interrupted'):
            _bool(getattr(self, name), name)
        if self.completed and self.interrupted or self.countered and self.kind not in (CardType.SPELL, CardType.MINION):
            raise ValueError('Invalid play outcome')

    @property
    def combo(self):
        return self.prior_turn_plays > 0

    @property
    def finale(self):
        return self.mana_after == 0

    @property
    def quickdraw(self):
        return self.hand_entry_turn == self.turn

    @property
    def manathirst(self):
        return self.manathirst_threshold is not None and self.mana_crystals >= self.manathirst_threshold

    @property
    def outcast(self):
        return self.hand_index in (0, self.hand_size - 1)


@dataclass(frozen=True)
class HeroPowerRepeatContributor:
    carrier_id: int
    card_id: str
    player_id: int
    ability: AbilityInstance

    @property
    def key(self): return self.carrier_id, self.ability.id

    @property
    def spec(self): return self.ability.hero_power_repeat

    def __post_init__(self):
        _int(self.carrier_id, 'hero power repeat source', 1)
        _name(self.card_id, 'hero power repeat source card')
        _int(self.player_id, 'hero power repeat player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid hero power repeat player')
        if type(self.ability) is not AbilityInstance:
            raise ValueError('Expected captured hero power repeat ability')
        self.ability.__post_init__()
        if self.ability.kind != 'hero_power_repeat' or self.ability.consumed:
            raise ValueError('Expected active hero power repeat ability')


@dataclass(frozen=True)
class HeroPowerRepeatPlan:
    repetitions: int = 1
    contributors: tuple[HeroPowerRepeatContributor, ...] = ()

    def __post_init__(self):
        _int(self.repetitions, 'captured hero power repetitions', 1)
        if type(self.contributors) is not tuple:
            raise ValueError('Expected immutable hero power repeat contributors')
        keys = []
        for source in self.contributors:
            if type(source) is not HeroPowerRepeatContributor:
                raise ValueError('Invalid hero power repeat contributor')
            source.__post_init__()
            keys.append(source.key)
        if keys != sorted(set(keys)):
            raise ValueError('Hero power repeat contributors require unique ordered identities')
        if self.repetitions != max((s.spec.repetitions for s in self.contributors), default=1):
            raise ValueError('Hero power repetition count differs from contributors')


def _validate_hero_power_payloads(payloads, *, required=False):
    if type(payloads) is not tuple or required and not payloads:
        raise ValueError('Expected immutable captured hero power payloads')
    ids = []
    for ability in payloads:
        if type(ability) is not AbilityInstance:
            raise ValueError('Expected captured hero power ability')
        ability.__post_init__()
        if ability.kind != 'on_use' or ability.consumed:
            raise ValueError('Expected active hero power on_use ability')
        ids.append(ability.id)
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate hero power payload identity')


@dataclass(frozen=True)
class HeroPowerRecord:
    """A power activation is neither a hand play nor a spell cast."""
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    origin: str
    target_id: int | None
    activator_id: int | None = None
    parent_id: int | None = None
    targeting: str = 'explicit'
    choices: str = 'player'
    cost: int | None = None
    payment: PaymentType | None = None
    uses_before: int = 0
    player_uses_before: int = 0
    completed: bool = False
    interrupted: bool = False
    failure: str | None = None

    branch_id: str | None = None
    payloads: tuple[AbilityInstance, ...] = ()
    repeat_plan: HeroPowerRepeatPlan = field(default_factory=HeroPowerRepeatPlan)

    def __post_init__(self):
        if type(self.repeat_plan) is not HeroPowerRepeatPlan:
            raise ValueError('Expected accepted hero power repeat plan')
        self.repeat_plan.__post_init__()
        _validate_hero_power_payloads(self.payloads)
        if self.failure is not None and (self.payloads or self.repeat_plan.contributors):
            raise ValueError('Failed hero powers cannot accept payloads or repeat sources')
        if self.branch_id is not None: _name(self.branch_id, 'captured branch')
        for key in ('id','source_id','player_id','turn'):
            _int(getattr(self,key),key,1)
        for key in ('action','uses_before','player_uses_before'):
            _int(getattr(self,key),key,0)
        for key in ('target_id','activator_id','parent_id'):
            _optional_id(getattr(self,key),key)
        _name(self.card_id,'power card')
        if self.player_id not in (1,2) or self.origin not in ('manual','effect'):
            raise ValueError('Invalid hero power origin')
        if self.targeting not in ('explicit','random') or self.choices not in ('player','random'):
            raise ValueError('Invalid power execution policy')
        if self.origin == 'manual':
            _int(self.cost,'power cost',0)
            if (type(self.payment) is not PaymentType or self.activator_id is not None or
                    self.parent_id is not None or self.targeting != 'explicit' or self.choices != 'player'):
                raise ValueError('Invalid manual hero power provenance')
        elif self.cost is not None or self.payment is not None:
            raise ValueError('Indirect power activation cannot invent payment')
        for key in ('completed','interrupted'):
            _bool(getattr(self,key),key)
        if (self.completed and self.interrupted or self.failure not in (None,'no_target','invalid_target','passive','disabled') or
                self.failure is not None and (not self.completed or self.origin != 'effect') or
                self.parent_id is not None and self.parent_id >= self.id):
            raise ValueError('Invalid hero power outcome or nesting')


@dataclass(frozen=True)
class HeroPowerPayloadBatch:
    """One accepted root or retained-result group of hero power abilities."""
    id: int  # First capture ID in this batch.
    power_id: int
    payloads: tuple[AbilityInstance, ...]
    outcome_id: int | None = None
    iteration: int = 1
    plan: HeroPowerRepeatPlan = field(default_factory=HeroPowerRepeatPlan)

    @property
    def total(self): return len(self.payloads) * self.plan.repetitions

    def position(self, index):
        """Zero-based queue position -> original ability and one-based repeat."""
        _int(index, 'hero power batch position', 0)
        if index >= self.total:
            raise ValueError('Hero power batch position is out of range')
        ability_index, repeat_index = divmod(index, self.plan.repetitions)
        return self.payloads[ability_index], repeat_index + 1

    def __post_init__(self):
        _int(self.id, 'hero power payload batch', 1)
        _int(self.power_id, 'hero power activation', 1)
        _optional_id(self.outcome_id, 'hero power outcome')
        _int(self.iteration, 'hero power outcome iteration', 1)
        if self.outcome_id is None and self.iteration != 1:
            raise ValueError('Unretained hero power payloads require iteration one')
        if type(self.plan) is not HeroPowerRepeatPlan:
            raise ValueError('Expected captured hero power repeat plan')
        self.plan.__post_init__()
        _validate_hero_power_payloads(self.payloads, required=True)


@dataclass(frozen=True)
class HeroPowerPayloadCapture:
    """Immutable scheduled ability; its root carries target and provenance."""
    id: int
    batch_id: int
    power_id: int
    ability: AbilityInstance
    outcome_id: int | None = None
    iteration: int = 1
    repeat_index: int = 1

    def __post_init__(self):
        for key in ('id', 'batch_id', 'power_id', 'iteration', 'repeat_index'):
            _int(getattr(self, key), f'hero power payload {key}', 1)
        _optional_id(self.outcome_id, 'hero power outcome')
        if self.id < self.batch_id or self.outcome_id is None and self.iteration != 1:
            raise ValueError('Invalid hero power payload scope or iteration')
        _validate_hero_power_payloads((self.ability,), required=True)


@dataclass(frozen=True)
class HeroPowerPayloadRecord:
    capture: HeroPowerPayloadCapture
    execution_order: int | None = None
    completed: bool = False
    interrupted: bool = False

    @property
    def id(self): return self.capture.id

    def __post_init__(self):
        if type(self.capture) is not HeroPowerPayloadCapture:
            raise ValueError('Expected hero power payload capture')
        self.capture.__post_init__()
        _optional_id(self.execution_order, 'hero power payload execution order')
        _bool(self.completed, 'hero power payload completed')
        _bool(self.interrupted, 'hero power payload interrupted')
        if self.completed and (self.execution_order is None or self.interrupted):
            raise ValueError('Invalid hero power payload completion')


@dataclass(frozen=True)
class HeroPowerReference:
    """Captured physical installation; position is not an entity identity."""
    entity_id: int
    player_id: int
    card_id: str
    zone_epoch: int
    entered_order: int

    def __post_init__(self):
        _int(self.entity_id, 'power entity ID', 1)
        _int(self.player_id, 'power controller', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid power controller')
        _name(self.card_id, 'power card ID')
        _int(self.zone_epoch, 'power zone epoch', 0)
        _int(self.entered_order, 'power installation order', 1)

    @classmethod
    def capture(cls, entity):
        if entity.zone != Zone.HERO_POWER or entity.kind != CardType.HERO_POWER:
            raise ValueError('Power references require an installed hero power')
        return cls(entity.id, entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order)


@dataclass(frozen=True)
class SpellCastRecord:
    """One spell execution attempt, independent of payment and hand plays."""
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    origin: str
    target_id: int | None = None
    caster_id: int | None = None
    play_id: int | None = None
    iteration: int = 1
    from_zone: Zone | None = None
    choices: str = 'player'
    combo: bool = False
    outcast: bool = False
    finale: bool = False
    quickdraw: bool = False
    manathirst: bool = False
    payload_started: bool = False
    completed: bool = False
    interrupted: bool = False
    failure: str | None = None
    draw_id: int | None = None
    recast_id: int | None = None

    branch_id: str | None = None
    owner_turn_id: int | None = None
    recorded_event: int = 0
    target_selection: object | None = None
    spell_damage_effects: tuple[PlayerEffect, ...] = ()
    local_spell_damage: tuple[AbilityInstance, ...] = ()
    native_spell_value: AbilityInstance | None = None

    target_origin: object | None = None

    def __post_init__(self):
        from .allocation_facts import SourceAllocationFact
        if self.target_origin is not None:
            if type(self.target_origin)is not SourceAllocationFact:
                raise ValueError('Spell target requires its typed original allocation')
            self.target_origin.__post_init__()
            if self.target_origin.entity_id!=self.target_id:
                raise ValueError('Spell target allocation borrowed another physical target')
        if (self.target_id is None)!=(self.target_origin is None):
            raise ValueError('Spell target identity and original allocation must agree')
        from .stored_spell_damage import validate_local_ability
        if self.native_spell_value is not None:
            if type(self.native_spell_value)is not AbilityInstance or self.native_spell_value.kind!='spell_base_value':
                raise ValueError('Native cast value requires its complete original physical ability')
            self.native_spell_value.__post_init__()
            if not self.payload_started or self.failure is not None or self.native_spell_value.spell_base_value.card_id!=self.card_id:
                raise ValueError('Native cast value differs from its accepted original face')
        if type(self.local_spell_damage) is not tuple:
            raise ValueError('Local cast Spell Damage requires immutable complete abilities')
        if self.local_spell_damage and (not self.payload_started or self.failure is not None):
            raise ValueError('Failed or unaccepted casts cannot claim local Spell Damage')
        for ability in self.local_spell_damage:validate_local_ability(ability)
        if any(a.id >= b.id for a,b in zip(self.local_spell_damage,self.local_spell_damage[1:])):
            raise ValueError('Local cast Spell Damage requires original unique attachment order')
        if type(self.spell_damage_effects) is not tuple or any(type(e) is not PlayerEffect for e in self.spell_damage_effects):
            raise ValueError('Scoped cast Spell Damage requires complete immutable player effects')
        if self.spell_damage_effects and (not self.payload_started or self.failure is not None):
            raise ValueError('Failed or unaccepted casts cannot claim next-spell effects')
        for effect in self.spell_damage_effects:
            effect.__post_init__()
            if effect.created_turn != self.turn:
                raise ValueError('Claimed next-spell effect belongs to another actual turn')
        if any(a.id >= b.id or a.entered_order >= b.entered_order for a,b in zip(self.spell_damage_effects,self.spell_damage_effects[1:])):
            raise ValueError('Claimed next-spell effects require original unique acquisition order')
        _optional_id(self.owner_turn_id, 'cast owner-turn ID')
        _int(self.recorded_event, 'cast allocation event cursor', 0)
        if self.branch_id is not None: _name(self.branch_id, 'captured branch')
        for name in ('id', 'source_id', 'player_id', 'turn', 'iteration'):
            _int(getattr(self, name), name, 1)
        _int(self.action, 'cast action', 0)
        _name(self.card_id, 'cast card')
        for name in ('target_id', 'caster_id', 'play_id', 'draw_id', 'recast_id'):
            _optional_id(getattr(self, name), name)
        if self.player_id not in (1, 2) or self.origin not in ('hand', 'repeat', 'effect', 'draw', 'history'):
            raise ValueError('Invalid spell cast source')
        if self.choices not in ('player', 'random'):
            raise ValueError('Invalid spell choice policy')
        if self.from_zone is not None and (type(self.from_zone) is not Zone or self.from_zone not in (Zone.HAND, Zone.DECK)):
            raise ValueError('Invalid spell origin zone')
        automatic = self.origin in ('effect', 'draw', 'history')
        if self.target_selection is not None:
            from .automatic_targets import AutomaticTargetSelection
            if type(self.target_selection) is not AutomaticTargetSelection or not automatic:
                raise ValueError('Only automatic casts may carry a concrete typed target selection')
            self.target_selection.__post_init__()
            selected = self.target_selection
            if (selected.partition.source_id != self.source_id or selected.partition.definition_id != self.card_id
                    or selected.partition.source_controller != self.player_id or selected.target_id != self.target_id
                    or selected.failure != self.failure):
                raise ValueError('Cast target differs from its complete accepted automatic selection')
        if automatic != (self.play_id is None):
            raise ValueError('Hand/repeat casts require a play, effect casts cannot invent one')
        if (self.origin == 'repeat') != (self.iteration > 1):
            raise ValueError('Invalid cast iteration')
        if not automatic and (self.from_zone != Zone.HAND or self.caster_id is not None or self.choices != 'player'):
            raise ValueError('Invalid played spell provenance')
        for name in ('combo', 'outcast', 'finale', 'quickdraw', 'manathirst', 'payload_started', 'completed', 'interrupted'):
            _bool(getattr(self, name), name)
        if self.failure not in (None, 'countered', 'no_target', 'invalid_target'):
            raise ValueError('Invalid cast failure')
        if self.completed and self.interrupted or self.failure is not None and not self.completed:
            raise ValueError('Invalid spell cast outcome')
        if self.failure is not None and self.payload_started or self.completed and self.failure is None and not self.payload_started:
            raise ValueError('Invalid spell payload phase')
        if automatic and self.failure == 'countered' or not automatic and self.failure not in (None, 'countered'):
            raise ValueError('Spell failure does not match its origin')
        if not automatic and self.failure is None and not self.payload_started:
            raise ValueError('A recorded played spell must have entered its payload')
        if (self.origin == 'draw') != (self.draw_id is not None) or self.origin == 'draw' and self.from_zone != Zone.DECK:
            raise ValueError('Drawn spell requires its deck draw provenance')
        if ((self.origin == 'history') != (self.recast_id is not None) or
                self.origin == 'history' and (self.recast_id >= self.id or self.from_zone is not None)):
            raise ValueError('Historical casting requires an earlier cast and a new entity')


@dataclass(frozen=True)
class CastWhenDrawnSpec:
    replacement: bool = True
    after_draw: str | None = None
    choices: str = 'random'

    def __post_init__(self):
        _bool(self.replacement, 'replacement draw')
        if self.after_draw is not None: _name(self.after_draw, 'after draw behavior')
        if self.choices not in ('random', 'player'):
            raise ValueError('Invalid drawn spell choice policy')


@dataclass(frozen=True)
class DrawRecord:
    id: int
    player_id: int
    turn: int
    action: int
    outcome: str
    entity_id: int | None = None
    card_id: str | None = None
    source_id: int | None = None
    parent_id: int | None = None
    replacement_id: int | None = None
    cast_id: int | None = None
    spec: CastWhenDrawnSpec | None = None
    phase: str = 'drawing'
    interrupted: bool = False

    def __post_init__(self):
        for name in ('id', 'player_id', 'turn'): _int(getattr(self,name), name, 1)
        _int(self.action, 'draw action', 0)
        for name in ('entity_id', 'source_id', 'parent_id', 'replacement_id', 'cast_id'):
            _optional_id(getattr(self,name), name)
        if self.card_id is not None: _name(self.card_id, 'drawn card')
        if self.player_id not in (1,2) or self.outcome not in ('hand','burned','cast','fatigue'):
            raise ValueError('Invalid draw outcome or player')
        if self.outcome == 'fatigue':
            if self.entity_id is not None or self.card_id is not None: raise ValueError('Fatigue cannot name a drawn card')
        elif self.entity_id is None or self.card_id is None: raise ValueError('Physical draw requires a card')
        if self.phase not in ('drawing','pending_cast','casting','pending_replacement','replacing','after_draw','done'):
            raise ValueError('Invalid draw phase')
        if self.outcome == 'cast':
            if type(self.spec) is not CastWhenDrawnSpec or self.phase == 'drawing': raise ValueError('Draw-cast requires its declaration')
            self.spec.__post_init__()
            if (self.phase == 'pending_cast') != (self.cast_id is None): raise ValueError('Invalid draw cast phase')
            if not self.spec.replacement and (self.replacement_id is not None or self.phase in ('pending_replacement','replacing')):
                raise ValueError('Unexpected replacement draw')
        elif self.spec is not None or self.cast_id is not None or self.replacement_id is not None or self.phase not in ('drawing','done'):
            raise ValueError('Ordinary draws cannot contain spell continuation data')
        if self.parent_id is not None and self.parent_id >= self.id or self.replacement_id is not None and self.replacement_id <= self.id:
            raise ValueError('Invalid replacement draw ordering')
        _bool(self.interrupted,'interrupted draw')
        if self.completed and self.interrupted: raise ValueError('Completed draw cannot be interrupted')

    @property
    def completed(self):
        return self.phase == 'done'


@dataclass(frozen=True)
class AppendageSpec:
    card_id: str
    side: str = 'right'

    def __post_init__(self):
        _name(self.card_id, 'appendage card')
        if self.side not in ('left', 'right'):
            raise ValueError('Appendage side must be left or right')


@dataclass(frozen=True)
class ExcavationRecord:
    id: int
    player_id: int
    source_id: int | None
    hero_class: CardClass
    profile_id: str
    profile_version: str
    target_id: str
    mode: str
    pool_id: str
    pool_version: str
    count_before: int
    cycle: int
    tier: int
    maximum: int
    card_id: str
    reward_id: int
    burned: bool
    turn: int
    action: int

    def __post_init__(self):
        for field in ('id','player_id','cycle','tier','maximum','reward_id','turn'):
            _int(getattr(self,field), 'Excavation '+field, 1)
        for field in ('count_before','action'): _int(getattr(self,field), 'Excavation '+field, 0)
        for field in ('profile_id','profile_version','target_id','pool_id','pool_version','card_id'):
            _name(getattr(self,field), 'Excavation '+field)
        _optional_id(self.source_id, 'Excavation source'); _bool(self.burned, 'burned treasure')
        if (self.player_id not in (1,2) or type(self.hero_class) is not CardClass or self.hero_class == CardClass.NEUTRAL or
                self.maximum not in (3,4) or not 1 <= self.tier <= self.maximum or
                self.mode not in ('experimental','standard','wild')):
            raise ValueError('Invalid Excavation class, progress or mode')


@dataclass(frozen=True)
class JadeGolemRecord:
    id: int
    player_id: int
    source_id: int | None
    family_id: str
    family_version: str
    count_before: int
    size: int
    card_id: str
    entity_id: int | None
    turn: int
    action: int

    def __post_init__(self):
        for key in ('id', 'player_id', 'size', 'turn'):
            _int(getattr(self, key), 'Jade ' + key, 1)
        for key in ('count_before', 'action'):
            _int(getattr(self, key), 'Jade ' + key, 0)
        for key in ('family_id', 'family_version', 'card_id'):
            _name(getattr(self, key), 'Jade ' + key)
        _optional_id(self.source_id, 'Jade source')
        _optional_id(self.entity_id, 'Jade generated physical body')
        if self.player_id not in (1, 2) or self.size > 30:
            raise ValueError('Invalid Jade player or size')


@dataclass(frozen=True)
class GalakrondMain:
    entity_id: int
    hero_class: CardClass

    def __post_init__(self):
        _int(self.entity_id, 'main Galakrond', 1)
        if type(self.hero_class) is not CardClass or self.hero_class not in (
                CardClass.PRIEST, CardClass.ROGUE, CardClass.SHAMAN, CardClass.WARLOCK, CardClass.WARRIOR):
            raise ValueError('Invalid main Galakrond class')


@dataclass(frozen=True)
class InvokeRecord:
    id: int
    player_id: int
    source_id: int | None
    profile_version: str
    count_before: int
    main_id: int | None
    hero_class: CardClass | None
    main_zone: Zone | None
    main_epoch: int | None
    card_before: str | None
    card_after: str | None
    progress_before: int | None
    progress_after: int | None
    turn: int
    action: int

    def __post_init__(self):
        for key in ('id', 'player_id', 'turn'):
            _int(getattr(self, key), 'Invoke ' + key, 1)
        for key in ('count_before', 'action'):
            _int(getattr(self, key), 'Invoke ' + key, 0)
        _name(self.profile_version, 'Invoke profile version')
        _optional_id(self.source_id, 'Invoke source')
        _optional_id(self.main_id, 'Invoke main')
        if self.player_id not in (1, 2):
            raise ValueError('Invalid Invoke player')
        dependent = (self.hero_class, self.main_zone, self.main_epoch, self.card_before,
                     self.card_after, self.progress_before, self.progress_after)
        if self.main_id is None:
            if any(value is not None for value in dependent):
                raise ValueError('No-Galakrond Invoke cannot carry a gift or upgrade')
        else:
            GalakrondMain(self.main_id, self.hero_class)
            if type(self.main_zone) is not Zone or self.main_zone not in (Zone.HAND, Zone.DECK, Zone.HERO):
                raise ValueError('Invalid captured Galakrond zone')
            for key in ('main_epoch', 'progress_before', 'progress_after'):
                _int(getattr(self, key), 'Invoke ' + key, 0)
            for key in ('card_before', 'card_after'):
                _name(getattr(self, key), 'Invoke ' + key)
            if self.progress_before > 4 or self.progress_after > 4:
                raise ValueError('Invalid captured Galakrond progress')


@dataclass(frozen=True)
class ImbueRecord:
    id: int
    player_id: int
    source_id: int | None
    hero_class: CardClass
    profile_id: str
    profile_version: str
    count_before: int
    applied_before: int
    old_power_id: int | None
    power_id: int | None
    power_card_id: str | None
    turn: int
    action: int

    def __post_init__(self):
        for field in ('id', 'player_id', 'turn'):
            _int(getattr(self, field), 'Imbue ' + field, 1)
        for field in ('count_before', 'applied_before', 'action'):
            _int(getattr(self, field), 'Imbue ' + field, 0)
        for field in ('profile_id', 'profile_version'):
            _name(getattr(self, field), 'Imbue ' + field)
        for field in ('source_id', 'old_power_id', 'power_id'):
            _optional_id(getattr(self, field), 'Imbue ' + field)
        if self.power_card_id is not None:
            _name(self.power_card_id, 'Imbued power card')
        if (self.player_id not in (1, 2) or type(self.hero_class) is not CardClass or
                self.hero_class == CardClass.NEUTRAL or self.applied_before > self.count_before or
                (self.power_card_id is None) != (self.power_id is None)):
            raise ValueError('Invalid Imbue class, progress or power')


@dataclass(frozen=True)
class HeraldRecord:
    id: int
    player_id: int
    source_id: int | None
    hero_class: CardClass
    soldier_card_id: str
    soldier_id: int | None
    count_before: int
    rank: int
    turn: int
    action: int

    def __post_init__(self):
        for name in ('id', 'player_id', 'turn'):
            _int(getattr(self, name), name, 1)
        for name in ('count_before', 'rank', 'action'):
            _int(getattr(self, name), name, 0)
        _optional_id(self.source_id, 'Herald source')
        _optional_id(self.soldier_id, 'Herald Soldier')
        _name(self.soldier_card_id, 'Herald Soldier card')
        if self.player_id not in (1, 2) or self.rank > 2 or not isinstance(self.hero_class, CardClass):
            raise ValueError('Invalid Herald record')


@dataclass(frozen=True)
class ColossalRecord:
    id: int
    entity_id: int
    card_id: str
    player_id: int
    turn: int
    action: int
    entered_order: int
    zone_epoch: int
    reason: str
    limbs: tuple[int | None, ...]
    attempted: int = 0
    completed: bool = False
    canceled: bool = False
    origin_id: int | None = None
    copy_mode: str | None = None
    death_id: int | None = None
    play_id: int | None = None

    def __post_init__(self):
        for name in ('id','entity_id','player_id','turn','entered_order'):
            _int(getattr(self,name),name,1)
        for name in ('action','zone_epoch','attempted'):
            _int(getattr(self,name),name,0)
        _name(self.card_id,'colossal card')
        for name in ('origin_id','death_id','play_id'):_optional_id(getattr(self,name),name)
        if (self.reason == 'play') != (self.play_id is not None):
            raise ValueError('Only paid Colossal entry requires its exact play origin')
        _bool(self.completed,'colossal completed');_bool(self.canceled,'colossal canceled')
        if self.player_id not in (1,2) or self.reason not in ('play','summon','copy','reborn','resurrect','transform','stored'):
            raise ValueError('Invalid colossal entry')
        if type(self.limbs) is not tuple or not self.limbs or self.attempted>len(self.limbs):
            raise ValueError('Invalid colossal progress')
        for item in self.limbs:_optional_id(item,'appendage entity')
        ids=[i for i in self.limbs if i is not None]
        if len(set(ids))!=len(ids) or self.entity_id in ids or any(i is not None for i in self.limbs[self.attempted:]):
            raise ValueError('Invalid appendage identities')
        if (self.canceled and not self.completed or self.completed and not self.canceled and self.attempted!=len(self.limbs) or
                (self.reason=='copy')!=(self.copy_mode is not None) or self.copy_mode not in (None,'base','current') or
                (self.reason in ('copy','reborn','resurrect'))!=(self.origin_id is not None) or
                (self.reason in ('reborn','resurrect'))!=(self.death_id is not None)):
            raise ValueError('Invalid colossal outcome or origin')


@dataclass(frozen=True)
class MagneticRecord:
    id: int
    play_id: int
    source_id: int
    target_id: int
    player_id: int
    card_id: str
    host_card_id: str
    attack: int
    health: int
    enchantment_id: int
    ability_ids: tuple[int, ...]
    host_tribe_changes: tuple[Enchantment, ...]

    def __post_init__(self):
        for name in ('id', 'play_id', 'source_id', 'target_id', 'player_id', 'enchantment_id'):
            _int(getattr(self,name),name,1)
        _int(self.attack, 'magnetic attack', 0)
        _int(self.health, 'magnetic health', 1)
        _name(self.card_id, 'magnetic source card')
        _name(self.host_card_id, 'magnetic host card')
        if self.player_id not in (1,2) or self.source_id==self.target_id:
            raise ValueError('Invalid magnetic identities')
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids))!=len(self.ability_ids):
            raise ValueError('Invalid magnetic attachment IDs')
        for ability_id in self.ability_ids:
            _int(ability_id, 'magnetic ability ID', 1)
        if self.enchantment_id in self.ability_ids:
            raise ValueError('Duplicate magnetic attachment ID')
        _tribe_changes(self.host_tribe_changes)
        if any(c.id >= self.enchantment_id for c in self.host_tribe_changes):
            raise ValueError('Magnetic host tribe changes must precede the merge allocation')


def validate_combat_relation(value):
    if type(value) is not str or value not in ('opponent', 'friendly_minions', 'any_minions'):
        raise ValueError('Unsupported combat relation')


@dataclass(frozen=True)
class ActionWindow:
    id: int
    kind: str
    player_id: int
    source_id: int
    target_id: int | None = None
    forced: bool = False
    countered: bool = False
    target_phase: bool = False
    play_id: int | None = None
    spellburst_candidates: tuple[TriggerCandidate, ...] = ()
    counter_phase: bool = False
    combat_relation: str = 'opponent'
    attack_source_presence: BoardPresenceReference | None = None

    def __post_init__(self):
        validate_combat_relation(self.combat_relation)
        if self.attack_source_presence is not None:
            if (self.kind != 'attack' or type(self.attack_source_presence) is not BoardPresenceReference or
                    self.attack_source_presence.entity_id != self.source_id):
                raise ValueError('Attack presence must reference its original minion source')
            self.attack_source_presence.__post_init__()
        if self.combat_relation != 'opponent' and (self.kind != 'attack' or not self.forced):
            raise ValueError('Friendly combat requires a forced attack window')
        for name in ('id', 'player_id', 'source_id'):
            _int(getattr(self, name), name, 1)
        if self.player_id not in (1, 2) or self.kind not in ('spell', 'minion', 'attack'):
            raise ValueError('Invalid action window')
        _optional_id(self.target_id, 'window target')
        _optional_id(self.play_id, 'window play')
        if (self.kind in ('spell', 'minion')) != (self.play_id is not None):
            raise ValueError('Card windows require a play record')
        if type(self.spellburst_candidates) is not tuple or any(type(c) is not TriggerCandidate for c in self.spellburst_candidates):
            raise ValueError('Invalid Spellburst candidates')
        if self.kind != 'spell' and self.spellburst_candidates:
            raise ValueError('Only spell windows carry Spellburst candidates')
        if len({c.ability_id for c in self.spellburst_candidates}) != len(self.spellburst_candidates):
            raise ValueError('Duplicate Spellburst candidate')
        for candidate in self.spellburst_candidates:
            candidate.__post_init__()
        _bool(self.forced, 'forced attack')
        _bool(self.countered, 'countered card')
        _bool(self.counter_phase, 'minion counter phase')
        if self.kind != 'minion' and self.counter_phase:
            raise ValueError('Only minions enter the minion counter phase')
        _bool(self.target_phase, 'spell target phase')
        if (self.kind != 'attack' and self.forced) or (self.kind == 'attack' and (self.countered or self.target_id is None)):
            raise ValueError('Invalid action window flags')
        if self.kind != 'spell' and self.target_phase:
            raise ValueError('Attack cannot enter spell target phase')


@dataclass(frozen=True)
class PlayerAuraSpec:
    """Continuous additive stats on the recipient's active board minions."""
    attack: int = 0
    health: int = 0
    card_ids: tuple[str, ...] = ()

    def __post_init__(self):
        _int(self.attack, 'player aura attack')
        _int(self.health, 'player aura health', 0)
        if type(self.card_ids) is not tuple or len(set(self.card_ids)) != len(self.card_ids):
            raise ValueError('Player aura card IDs must be a unique immutable tuple')
        for card_id in self.card_ids:
            _name(card_id, 'player aura card ID')


@dataclass(frozen=True)
class SummonProducerProfile:
    """Logical unit and acceptance policy, independent of the selected card face."""
    id: str
    unit_id: str
    mode: str = 'random_board_batch'
    source_origins: tuple[str, ...] = ('card_effect', 'spell_cast')
    source_types: tuple[CardType, ...] = (CardType.SPELL, CardType.MINION, CardType.WEAPON, CardType.HERO, CardType.LOCATION)
    zero_base_eligible: bool = False

    def __post_init__(self):
        _name(self.id, 'logical summon profile'); _name(self.unit_id, 'logical summon unit')
        if self.mode not in ('random_board_batch', 'single_random_board', 'discover_board', 'choice_board', 'ordered_board_group'):
            raise ValueError('Unknown logical summon producer mode')
        if (type(self.source_origins) is not tuple or not self.source_origins or
                any(type(x) is not str or x not in ('card_effect', 'spell_cast', 'hero_power') for x in self.source_origins) or
                len(set(self.source_origins)) != len(self.source_origins)):
            raise ValueError('Explicit unique logical producer origins required')
        if (type(self.source_types) is not tuple or not self.source_types or
                any(type(x) is not CardType for x in self.source_types) or len(set(self.source_types)) != len(self.source_types)):
            raise ValueError('Explicit unique logical producer source types required')
        if type(self.zero_base_eligible) is not bool:
            raise ValueError('Explicit logical zero-base policy required')


@dataclass(frozen=True)
class ProducerQuantitySpec:
    unit_id: str
    additional: int = 1

    def __post_init__(self):
        _name(self.unit_id, 'additional producer logical unit')
        _int(self.additional, 'additional independent producer count', 0)


@dataclass(frozen=True)
class PlayerKeywordAuraSpec:
    """Known whole-game tribal Rush, independent of a physical source."""
    keyword: Keyword
    tribes_any: tuple[str, ...]

    def __post_init__(self):
        if type(self.keyword) is not Keyword or self.keyword != Keyword.RUSH:
            raise ValueError('Player keyword aura currently supports tribal Rush')
        TribeChangeSpec('set', self.tribes_any).__post_init__()
        if not self.tribes_any:
            raise ValueError('Player keyword aura requires an explicit tribe selector')


@dataclass(frozen=True)
class PlayerEffectSpec:
    """Public, source-independent rule definition, frozen with the registry."""
    id: str
    card_id: str
    kind: str = 'persistent'
    duration: int | None = None
    tick_event: str | None = None
    on_expire: str | None = None
    triggers: tuple[TriggerSpec, ...] = ()
    spell_damage: int = 0
    auras: tuple[PlayerAuraSpec, ...] = ()
    deathrattle_repeats: tuple[DeathrattleRepeatSpec, ...] = ()
    end_turn_repeats: tuple[EndTurnRepeatSpec, ...] = ()
    producer_quantities: tuple[ProducerQuantitySpec, ...] = ()
    keyword_auras: tuple[PlayerKeywordAuraSpec, ...] = ()
    target_policy: str | None = None
    allowed_card_types: tuple[CardType, ...] = ()
    next_turn_end: bool = False

    def __post_init__(self):
        if type(self.next_turn_end) is not bool:
            raise ValueError('Next owner-end player effect requires a boolean clock policy')
        if self.next_turn_end and (self.kind != 'objective' or self.duration != 2 or self.tick_event != 'turn_ended'):
            raise ValueError('Next owner-end policy requires its two-boundary objective declaration')
        if self.kind=='next_kindred'and any((self.duration,self.tick_event,self.on_expire,self.triggers,self.spell_damage,self.auras,
                self.deathrattle_repeats,self.end_turn_repeats,self.producer_quantities,self.keyword_auras,self.target_policy,self.allowed_card_types)):
            raise ValueError('Next-Kindred instances are one independent native repeat source')
        if self.kind == 'next_spell_damage':
            _int(self.spell_damage, 'next-spell damage amount', 1)
            if any((self.triggers,self.auras,self.deathrattle_repeats,self.end_turn_repeats,
                    self.producer_quantities,self.keyword_auras,self.target_policy,self.allowed_card_types)):
                raise ValueError('Next-spell damage cannot combine other player effect text')
        if (type(self.allowed_card_types) is not tuple or
                any(type(kind) is not CardType or kind not in (CardType.MINION,CardType.SPELL,
                    CardType.WEAPON,CardType.HERO,CardType.LOCATION) for kind in self.allowed_card_types) or
                len(set(self.allowed_card_types)) != len(self.allowed_card_types)):
            raise ValueError('Manual card type permissions require unique immutable playable card types')
        if self.kind == 'turn_rule':
            if self.allowed_card_types:
                if self.target_policy is not None:
                    raise ValueError('Turn play permissions cannot combine a target policy')
            elif type(self.target_policy) is not str or self.target_policy != 'spells_no_heroes':
                raise ValueError('Turn rules require a supported explicit target or manual play policy')
            if any((self.triggers,self.spell_damage,self.auras,self.deathrattle_repeats,self.end_turn_repeats,
                    self.producer_quantities,self.keyword_auras)):
                raise ValueError('Turn rules cannot combine other player effect text')
        elif self.target_policy is not None or self.allowed_card_types:
            raise ValueError('Target and manual play policies require an independent current-turn rule')
        if type(self.keyword_auras) is not tuple or any(type(a) is not PlayerKeywordAuraSpec for a in self.keyword_auras):
            raise ValueError('Player keyword auras require immutable typed declarations')
        for aura in self.keyword_auras:
            aura.__post_init__()
        if self.keyword_auras and self.kind != 'persistent':
            raise ValueError('Player keyword auras currently require a whole-game effect')
        if type(self.producer_quantities) is not tuple or any(type(s) is not ProducerQuantitySpec for s in self.producer_quantities):
            raise ValueError('Player producer quantities require immutable declarations')
        for declaration in self.producer_quantities:
            declaration.__post_init__()
        _name(self.id, 'player effect ID')
        _name(self.card_id, 'player effect card ID')
        if self.kind not in ('persistent', 'objective', 'sigil', 'turn_rule', 'next_spell_damage','next_kindred'):
            raise ValueError('Unsupported player effect kind')
        if self.kind in ('persistent', 'turn_rule', 'next_spell_damage','next_kindred'):
            if self.duration is not None or self.tick_event is not None or self.on_expire is not None:
                raise ValueError('Whole-game effects have no countdown or expiry')
        else:
            _int(self.duration, 'player effect duration', 1)
            if self.tick_event not in ('turn_started', 'turn_ended'):
                raise ValueError('Timed player effects require an owner turn boundary')
        if self.on_expire is not None:
            _name(self.on_expire, 'expiry behavior')
        _int(self.spell_damage, 'player spell damage', 0)
        if type(self.triggers) is not tuple or any(type(t) is not TriggerSpec for t in self.triggers):
            raise ValueError('Player effect triggers must be an immutable specification tuple')
        for trigger in self.triggers:
            trigger.__post_init__()
        if 'engine.choose_one' in (self.on_expire, *(trigger.behavior_id for trigger in self.triggers)):
            raise ValueError('Player effect future text cannot dispatch an immediate Choose One branch')
        if type(self.auras) is not tuple or any(type(a) is not PlayerAuraSpec for a in self.auras):
            raise ValueError('Player effect auras must be an immutable specification tuple')
        for aura in self.auras:
            aura.__post_init__()
        if type(self.deathrattle_repeats) is not tuple or any(type(s) is not DeathrattleRepeatSpec for s in self.deathrattle_repeats):
            raise ValueError('Player Deathrattle repeats require immutable specifications')
        for spec in self.deathrattle_repeats:
            spec.__post_init__()
            if spec.scope!='friendly': raise ValueError('Player Deathrattle effects cannot declare self carrier scope')
            if spec.match is not None and spec.match.source_eligibility is not None:
                raise ValueError('Player Deathrattle effects cannot require a physical board carrier')
        if type(self.end_turn_repeats) is not tuple or any(type(s) is not EndTurnRepeatSpec for s in self.end_turn_repeats):
            raise ValueError('Player end-turn repeats require immutable specifications')
        for spec in self.end_turn_repeats:
            spec.__post_init__()
            if spec.match is not None and spec.match.source_eligibility is not None:
                raise ValueError('Player end-turn effects cannot require a physical board carrier')


@dataclass(frozen=True)
class PlayerEffect:
    id: int
    spec_id: str
    source_id: int
    source_card_id: str
    created_turn: int
    entered_order: int
    remaining_turns: int | None = None
    source_allocation: tuple[tuple[str, int | str | CardType | Zone], ...] | None = None
    source_player_id: int | None = None

    def __post_init__(self):
        for name in ('id', 'source_id', 'created_turn', 'entered_order'):
            _int(getattr(self, name), name, 1)
        _name(self.spec_id, 'player effect specification')
        _name(self.source_card_id, 'original source card ID')
        if self.remaining_turns is not None:
            _int(self.remaining_turns, 'remaining owner turns', 1)
        if self.source_allocation is not None:
            from .allocation_facts import allocation_from_payload
            fact=allocation_from_payload(self.source_allocation)
            if (fact.entity_id,fact.card_id,fact.next_order)!=(self.source_id,self.source_card_id,self.entered_order):
                raise ValueError('Player effect source capture changed its original identity or creation order')
            if type(self.source_player_id)is not int or self.source_player_id not in (1,2):
                raise ValueError('Captured player effect source requires its original beneficiary')
        elif self.source_player_id is not None:
            raise ValueError('Player effect source player requires its complete allocation capture')


@dataclass(frozen=True)
class EndTurnRepeatContributor:
    carrier_id: int
    card_id: str
    player_id: int
    ability: AbilityInstance | None = None
    player_effect: PlayerEffect | None = None
    spec: EndTurnRepeatSpec | None = None
    spec_index: int | None = None

    @property
    def key(self) -> tuple:
        return (('ability', self.carrier_id, self.ability.id) if self.ability is not None
                else ('player_effect', self.player_id, self.player_effect.id, self.spec_index))

    def __post_init__(self):
        _int(self.carrier_id, 'end-turn repeat source', 1)
        _name(self.card_id, 'end-turn repeat source card')
        _int(self.player_id, 'end-turn repeat player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid end-turn repeat player')
        if self.ability is not None:
            if type(self.ability) is not AbilityInstance:
                raise ValueError('End-turn repeat contributor requires AbilityInstance')
            self.ability.__post_init__()
            if self.ability.kind != 'end_turn_repeat' or self.ability.consumed:
                raise ValueError('End-turn repeat contributor requires an active repeat ability')
            if self.player_effect is not None or self.spec_index is not None:
                raise ValueError('Ability repeat contributor cannot carry a player effect')
            if self.spec is None:
                object.__setattr__(self, 'spec', self.ability.end_turn_repeat)
            if self.spec != self.ability.end_turn_repeat:
                raise ValueError('End-turn contributor specification differs from its ability')
        else:
            if type(self.player_effect) is not PlayerEffect:
                raise ValueError('End-turn repeat contributor requires PlayerEffect')
            self.player_effect.__post_init__()
            _int(self.spec_index, 'end-turn repeat specification index', 0)
            if self.carrier_id != self.player_effect.source_id or self.card_id != self.player_effect.source_card_id:
                raise ValueError('End-turn contributor disagrees with its player effect identity')
        if type(self.spec) is not EndTurnRepeatSpec:
            raise ValueError('End-turn repeat contributor requires EndTurnRepeatSpec')
        self.spec.__post_init__()
        if (self.player_effect is not None and self.spec.match is not None and
                self.spec.match.source_eligibility is not None):
            raise ValueError('Player end-turn contributor cannot require a physical board carrier')


@dataclass(frozen=True)
class EndTurnRepeatPlan:
    repetitions: int = 1
    contributors: tuple[EndTurnRepeatContributor, ...] = ()

    def __post_init__(self):
        _int(self.repetitions, 'captured end-turn repetitions', 1)
        if type(self.contributors) is not tuple:
            raise ValueError('End-turn repeat contributors must be an immutable tuple')
        keys = []
        for source in self.contributors:
            if type(source) is not EndTurnRepeatContributor:
                raise ValueError('Invalid end-turn repeat contributor')
            source.__post_init__()
            keys.append(source.key)
        if keys != sorted(set(keys)):
            raise ValueError('End-turn repeat contributors require unique ordered identities')
        if self.repetitions != max((source.spec.repetitions for source in self.contributors), default=1):
            raise ValueError('End-turn repetition count differs from contributors')


@dataclass(frozen=True)
class EndTurnSelector:
    """Explicit owners and physical carrier kinds for one acceptance query."""

    mode: str
    player_ids: tuple[int, ...]
    carrier_kinds: tuple[str, ...]
    entity_ids: tuple[int, ...] = ()
    player_effect_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in ('owner', 'selected'):
            raise ValueError('Unsupported end-turn selector mode')
        if type(self.player_ids) is not tuple or not self.player_ids:
            raise ValueError('End-turn selector requires an immutable nonempty owner tuple')
        for player_id in self.player_ids:
            _int(player_id, 'end-turn selector player', 1)
            if player_id not in (1, 2):
                raise ValueError('Invalid end-turn selector player')
        if len(set(self.player_ids)) != len(self.player_ids):
            raise ValueError('Duplicate end-turn selector player')
        kinds = ('minion', 'weapon', 'hero_power', 'location', 'hero', 'player_effect')
        if (type(self.carrier_kinds) is not tuple or not self.carrier_kinds or
                any(type(kind) is not str or kind not in kinds for kind in self.carrier_kinds)):
            raise ValueError('End-turn selector requires immutable supported carrier kinds')
        if len(set(self.carrier_kinds)) != len(self.carrier_kinds):
            raise ValueError('Duplicate end-turn selector carrier kind')
        for name in ('entity_ids', 'player_effect_ids'):
            values = getattr(self, name)
            if type(values) is not tuple:
                raise ValueError('End-turn selected IDs must be immutable tuples')
            for value in values:
                _int(value, 'end-turn selected ID', 1)
            if len(set(values)) != len(values):
                raise ValueError('Duplicate end-turn selected ID')
        if self.mode == 'owner' and (self.entity_ids or self.player_effect_ids):
            raise ValueError('Owner end-turn selection cannot include explicit IDs')


@dataclass(frozen=True)
class EndTurnRequest:
    selector: EndTurnSelector
    profile_id: str = 'end_turn.effect'

    def __post_init__(self):
        if type(self.selector) is not EndTurnSelector:
            raise ValueError('End-turn request requires EndTurnSelector')
        self.selector.__post_init__()
        _name(self.profile_id, 'end-turn activation profile')


@dataclass(frozen=True)
class EndTurnActivationProfile:
    """Registry-owned qualification policy, never a caller-supplied guard flag."""

    id: str
    kind: str = 'effect'
    turn_scope: str = 'ignore'
    target_policy: str = 'none'
    cause_events: tuple[str, ...] = ()

    def __post_init__(self):
        _name(self.id, 'end-turn activation profile ID')
        if type(self.kind) is not str or self.kind not in ('effect', 'phase'):
            raise ValueError('Unsupported end-turn activation profile kind')
        if type(self.turn_scope) is not str or self.turn_scope not in ('ignore', 'respect'):
            raise ValueError('Unsupported end-turn activation turn scope')
        if type(self.target_policy) is not str or self.target_policy not in ('none', 'cause'):
            raise ValueError('Unsupported end-turn activation target policy')
        if type(self.cause_events) is not tuple:
            raise ValueError('End-turn activation cause events must be immutable')
        for kind in self.cause_events:
            _name(kind, 'end-turn activation cause event')
        if len(set(self.cause_events)) != len(self.cause_events):
            raise ValueError('Duplicate end-turn activation cause event')
        if self.kind == 'phase' and not self.cause_events:
            raise ValueError('Phase end-turn activation requires a cause event policy')


@dataclass(frozen=True)
class EndTurnCandidateProfile:
    """Structural carrier qualification, independent of execution conditions."""

    id: str
    presence: str = 'has_body'
    basis: str = 'active'
    dormant: str = 'exclude'
    live_only: bool = True
    consumed: str = 'exclude'

    def __post_init__(self):
        _name(self.id, 'end-turn candidate profile ID')
        for name, choices in (
                ('presence', ('any', 'has_body', 'lacks_body')),
                ('basis', ('current', 'printed', 'active')),
                ('dormant', ('exclude', 'include', 'only')),
                ('consumed', ('exclude', 'include'))):
            value = getattr(self, name)
            if type(value) is not str or value not in choices:
                raise ValueError('Unsupported end-turn candidate ' + name)
        if type(self.live_only) is not bool:
            raise ValueError('End-turn candidate live_only must be boolean')
        if self.basis == 'active' and self.consumed != 'exclude':
            raise ValueError('Active end-turn candidates cannot include consumed abilities')
        if self.basis == 'printed' and self.consumed != 'include':
            raise ValueError('Printed end-turn candidates do not inspect consumption')


@dataclass(frozen=True)
class EndTurnProducerRequest:
    selector: EndTurnSelector
    candidate_profile_id: str = 'end_turn.candidates'
    activation_profile_id: str = 'end_turn.effect'

    def __post_init__(self):
        if type(self.selector) is not EndTurnSelector:
            raise ValueError('End-turn producer request requires EndTurnSelector')
        self.selector.__post_init__()
        _name(self.candidate_profile_id, 'end-turn candidate profile')
        _name(self.activation_profile_id, 'end-turn producer activation profile')


@dataclass(frozen=True)
class EndTurnCarrier:
    """One physical entity or player-effect instance, counted once in a pool."""

    kind: str
    source_id: int
    player_id: int
    card_id: str
    entered_order: int
    zone_epoch: int
    player_effect: PlayerEffect | None = None

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in (
                'minion', 'weapon', 'hero_power', 'location', 'hero', 'player_effect'):
            raise ValueError('Unsupported end-turn carrier kind')
        _int(self.source_id, 'end-turn carrier source', 1)
        _int(self.player_id, 'end-turn carrier player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid end-turn carrier player')
        _name(self.card_id, 'end-turn carrier card')
        _int(self.entered_order, 'end-turn carrier entry order', 1)
        _int(self.zone_epoch, 'end-turn carrier zone epoch', 0)
        if self.kind == 'player_effect':
            if type(self.player_effect) is not PlayerEffect:
                raise ValueError('End-turn player-effect carrier requires its full instance')
            self.player_effect.__post_init__()
            if (self.source_id != self.player_effect.source_id or
                    self.card_id != self.player_effect.source_card_id or
                    self.entered_order != self.player_effect.entered_order):
                raise ValueError('End-turn carrier disagrees with its player effect identity')
        elif self.player_effect is not None:
            raise ValueError('End-turn physical carrier cannot carry a player effect')

    @property
    def key(self) -> tuple:
        return (('player_effect', self.player_effect.id) if self.player_effect is not None
                else ('entity', self.source_id))


def validate_end_turn_rng(value: tuple) -> None:
    """Validate an immutable Python MT19937 getstate() v3 witness."""
    if type(value) is not tuple or len(value) != 3:
        raise ValueError('End-turn RNG state requires an immutable version/state/cache tuple')
    version, words, cache = value
    if type(version) is not int or version != 3:
        raise ValueError('End-turn RNG state requires MT19937 version 3')
    if type(words) is not tuple or len(words) != 625:
        raise ValueError('End-turn RNG state requires 624 words and an index')
    if any(type(word) is not int or not 0 <= word <= 2 ** 32 - 1 for word in words[:-1]):
        raise ValueError('Invalid end-turn RNG state word')
    if type(words[-1]) is not int or not 0 <= words[-1] <= 624:
        raise ValueError('Invalid end-turn RNG state index')
    if cache is not None and (type(cache) is not float or not isfinite(cache)):
        raise ValueError('End-turn RNG Gaussian cache requires a finite float or None')


@dataclass(frozen=True)
class EndTurnSelection:
    request: EndTurnProducerRequest
    candidates: tuple[EndTurnCarrier, ...]
    selected: EndTurnCarrier | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.request) is not EndTurnProducerRequest:
            raise ValueError('End-turn selection requires its original producer request')
        self.request.__post_init__()
        if type(self.candidates) is not tuple:
            raise ValueError('End-turn selection candidates must be an immutable tuple')
        keys = []
        for candidate in self.candidates:
            if type(candidate) is not EndTurnCarrier:
                raise ValueError('End-turn selection requires typed carriers')
            candidate.__post_init__()
            keys.append(candidate.key)
        if len(set(keys)) != len(keys):
            raise ValueError('Duplicate end-turn selection carrier')
        validate_end_turn_rng(self.rng_before)
        validate_end_turn_rng(self.rng_after)
        if self.candidates:
            if type(self.selected) is not EndTurnCarrier:
                raise ValueError('Nonempty end-turn candidate pool requires a selected carrier')
            self.selected.__post_init__()
            if self.selected not in self.candidates:
                raise ValueError('Selected end-turn carrier is not in the complete pool')
        elif self.selected is not None or self.rng_before != self.rng_after:
            raise ValueError('Empty end-turn candidate pool cannot select or consume RNG')


@dataclass(frozen=True)
class EndTurnActivation:
    """An invocation's issuer and real origin, independent of subject ownership."""

    kind: str
    issuer_id: int
    issuer_card_id: str
    issuer_player_id: int
    action: int
    event_cursor: int
    issuer_zone_epoch: int
    issuer_entered_order: int
    request: EndTurnRequest | None = None
    parent_id: int | None = None
    parent_batch_id: int | None = None
    selection: EndTurnSelection | None = None
    producer_mode: str = 'direct'

    def __post_init__(self):
        if type(self.kind) is not str or self.kind not in ('natural', 'effect', 'phase'):
            raise ValueError('Unsupported end-turn activation kind')
        if type(self.producer_mode) is not str or self.producer_mode not in ('direct', 'random_one'):
            raise ValueError('Unsupported end-turn producer mode')
        if (self.producer_mode == 'random_one') != (self.selection is not None):
            raise ValueError('Random end-turn origin requires its complete selection witness')
        _int(self.issuer_id, 'end-turn activation issuer', 1)
        _name(self.issuer_card_id, 'end-turn activation issuer card')
        _int(self.issuer_player_id, 'end-turn activation issuer player', 1)
        if self.issuer_player_id not in (1, 2):
            raise ValueError('Invalid end-turn activation issuer player')
        for name in ('action', 'event_cursor', 'issuer_zone_epoch', 'issuer_entered_order'):
            _int(getattr(self, name), 'end-turn activation ' + name, 0)
        _optional_id(self.parent_id, 'parent end-turn invocation')
        _optional_id(self.parent_batch_id, 'parent end-turn batch')
        if self.parent_id is not None and self.parent_batch_id is None:
            raise ValueError('Parent end-turn invocation requires its batch reference')
        if self.kind == 'natural':
            if self.request is not None:
                raise ValueError('Natural end-turn activation cannot carry an effect request')
            if self.parent_id is not None or self.parent_batch_id is not None:
                raise ValueError('Natural end-turn activation cannot have a parent')
            if self.selection is not None:
                raise ValueError('Natural end-turn activation cannot carry a producer selection')
        else:
            if type(self.request) is not EndTurnRequest:
                raise ValueError('Effect and phase end-turn activation require EndTurnRequest')
            self.request.__post_init__()
            if self.selection is not None:
                if type(self.selection) is not EndTurnSelection:
                    raise ValueError('End-turn activation requires a typed producer selection')
                self.selection.__post_init__()


@dataclass(frozen=True)
class EndTurnSubject:
    """One classified ability or player-effect trigger at acceptance."""

    source_id: int
    player_id: int
    card_id: str
    entered_order: int
    zone_epoch: int
    ability: AbilityInstance | None = None
    player_effect: PlayerEffect | None = None
    trigger: TriggerSpec | None = None
    trigger_index: int | None = None

    def __post_init__(self):
        _int(self.source_id, 'end-turn source', 1)
        _int(self.player_id, 'end-turn player', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid end-turn player')
        _name(self.card_id, 'end-turn card')
        _int(self.entered_order, 'end-turn entry order', 1)
        _int(self.zone_epoch, 'end-turn zone epoch', 0)
        if self.ability is not None:
            if type(self.ability) is not AbilityInstance:
                raise ValueError('End-turn entity subject requires AbilityInstance')
            self.ability.__post_init__()
            if any(value is not None for value in (self.player_effect, self.trigger, self.trigger_index)):
                raise ValueError('End-turn entity subject cannot carry a player effect')
        else:
            if type(self.player_effect) is not PlayerEffect or type(self.trigger) is not TriggerSpec:
                raise ValueError('End-turn player subject requires its effect and trigger')
            self.player_effect.__post_init__()
            self.trigger.__post_init__()
            _int(self.trigger_index, 'end-turn trigger index', 0)
            if (self.source_id != self.player_effect.source_id or
                    self.card_id != self.player_effect.source_card_id or
                    self.entered_order != self.player_effect.entered_order):
                raise ValueError('End-turn player subject disagrees with its effect identity')
        if type(self.spec) is not EndTurnSpec:
            raise ValueError('End-turn subjects require explicit classification')
        self.spec.__post_init__()

    @property
    def spec(self) -> EndTurnSpec | None:
        return self.ability.end_turn_spec if self.ability is not None else self.trigger.end_turn

    @property
    def behavior_id(self) -> str:
        if self.ability is None:
            return self.trigger.behavior_id
        return (self.ability.limited_trigger.behavior_id if self.ability.kind == 'limited_trigger'
                else self.ability.behavior_id)

    @property
    def key(self) -> tuple:
        return (('ability', self.source_id, self.ability.id) if self.ability is not None
                else ('player_effect', self.player_effect.id, self.trigger_index))


@dataclass(frozen=True)
class EndTurnBatch:
    id: int
    first_id: int
    event: Event | None
    turn: int
    subjects: tuple[EndTurnSubject, ...]
    completed: bool = False
    interrupted: bool = False
    plans: tuple[EndTurnRepeatPlan, ...] = ()
    activation: EndTurnActivation = field(kw_only=True)

    @property
    def total(self) -> int:
        return sum(plan.repetitions for plan in self.plans)

    def position(self, index: int) -> tuple[int, int]:
        """Zero-based flat capture position -> subject and repeat indices."""
        _int(index, 'end-turn batch position', 0)
        for subject_index, plan in enumerate(self.plans):
            if index < plan.repetitions:
                return subject_index, index
            index -= plan.repetitions
        raise ValueError('End-turn batch position exceeds its planned captures')

    def __post_init__(self):
        _int(self.id, 'end-turn batch ID', 1)
        _int(self.first_id, 'first end-turn capture ID', 1)
        _int(self.turn, 'end-turn turn', 1)
        if type(self.activation) is not EndTurnActivation:
            raise ValueError('End-turn batch requires EndTurnActivation')
        self.activation.__post_init__()
        if self.event is not None:
            if type(self.event) is not Event:
                raise ValueError('End-turn cause requires Event')
            event = self.event
            _int(event.sequence, 'end-turn cause sequence', 1)
            _int(event.action, 'end-turn cause action', 0)
            _name(event.kind, 'end-turn cause kind')
            _int(event.amount, 'end-turn cause amount')
            for name in ('source_id', 'target_id', 'player_id'):
                _optional_id(getattr(event, name), 'end-turn cause ' + name)
            if event.player_id is not None and event.player_id not in (1, 2):
                raise ValueError('Invalid end-turn cause player')
            if (type(event.data) is not tuple or
                    any(type(pair) is not tuple or len(pair) != 2 for pair in event.data)):
                raise ValueError('End-turn cause data must be immutable pairs')
            for key, _ in event.data:
                _name(key, 'end-turn cause data key')
            if len({key for key, _ in event.data}) != len(event.data):
                raise ValueError('Duplicate end-turn cause data key')
            if event.action > self.activation.action or event.sequence > self.activation.event_cursor:
                raise ValueError('End-turn cause follows its activation window')
        if self.activation.kind == 'natural':
            event = self.event
            if (event is None or event.kind != 'turn_ended' or event.player_id not in (1, 2) or
                    event.source_id is not None or event.target_id is not None or
                    event.amount != 0 or event.data or event.player_id != self.activation.issuer_player_id or
                    event.action != self.activation.action or event.sequence != self.activation.event_cursor):
                raise ValueError('Natural end-turn batch requires its unmodified turn_ended event')
        elif self.activation.kind == 'phase' and self.event is None:
            raise ValueError('Phase end-turn batch requires its real cause event')
        if type(self.subjects) is not tuple or any(type(s) is not EndTurnSubject for s in self.subjects):
            raise ValueError('End-turn subjects must be an immutable tuple')
        for subject in self.subjects:
            subject.__post_init__()
        if len({subject.key for subject in self.subjects}) != len(self.subjects):
            raise ValueError('Duplicate end-turn subject identity')
        if type(self.plans) is not tuple:
            raise ValueError('End-turn plans must be an immutable tuple')
        if not self.plans and self.subjects:
            object.__setattr__(self, 'plans', tuple(EndTurnRepeatPlan() for _ in self.subjects))
        if len(self.plans) != len(self.subjects) or any(type(plan) is not EndTurnRepeatPlan for plan in self.plans):
            raise ValueError('End-turn subjects require exactly one plan each')
        for plan in self.plans:
            plan.__post_init__()
        _bool(self.completed, 'end-turn batch completion')
        _bool(self.interrupted, 'end-turn batch interruption')
        if self.completed and self.interrupted:
            raise ValueError('End-turn batch cannot complete and interrupt')


@dataclass(frozen=True)
class EndTurnCapture:
    id: int
    batch_id: int
    index: int
    subject: EndTurnSubject
    repeat_index: int = 0
    plan: EndTurnRepeatPlan = field(default_factory=EndTurnRepeatPlan)

    def __post_init__(self):
        _int(self.id, 'end-turn capture ID', 1)
        _int(self.batch_id, 'end-turn capture batch ID', 1)
        _int(self.index, 'end-turn capture index', 0)
        if type(self.subject) is not EndTurnSubject:
            raise ValueError('End-turn capture requires EndTurnSubject')
        self.subject.__post_init__()
        _int(self.repeat_index, 'end-turn repeat index', 0)
        if type(self.plan) is not EndTurnRepeatPlan:
            raise ValueError('End-turn capture requires EndTurnRepeatPlan')
        self.plan.__post_init__()
        if self.repeat_index >= self.plan.repetitions or self.id <= self.repeat_index:
            raise ValueError('End-turn capture has an invalid repeat position')


@dataclass(frozen=True)
class EndTurnRecord:
    capture: EndTurnCapture
    execution_order: int | None = None
    completed: bool = False
    interrupted: bool = False
    skipped: bool = False
    guard_passed: bool = False
    guard_id: int | None = None
    guard_event: Event | None = None

    @property
    def id(self):
        return self.capture.id

    def __post_init__(self):
        if type(self.capture) is not EndTurnCapture:
            raise ValueError('End-turn record requires EndTurnCapture')
        self.capture.__post_init__()
        if self.guard_id is None:
            object.__setattr__(self, 'guard_id', self.capture.id - self.capture.repeat_index)
        _int(self.guard_id, 'end-turn guard receipt ID', 1)
        if self.guard_id != self.capture.id - self.capture.repeat_index:
            raise ValueError('End-turn position must reference its first guard receipt')
        _optional_id(self.execution_order, 'end-turn execution order')
        for name in ('completed', 'interrupted', 'skipped', 'guard_passed'):
            _bool(getattr(self, name), 'end-turn ' + name)
        if self.completed and (self.execution_order is None or self.interrupted or self.skipped):
            raise ValueError('Invalid end-turn completion')
        if self.skipped and (self.execution_order is not None or self.completed or self.interrupted or self.guard_passed):
            raise ValueError('Skipped end-turn subject cannot execute, complete, interrupt or pass its guard')
        ability = self.capture.subject.ability
        finite = ability is not None and ability.kind == 'limited_trigger'
        if finite and self.guard_passed and self.guard_event is None:
            raise ValueError('Passed finite end-turn guard requires its actual event receipt')
        if self.guard_event is not None:
            if not finite or not self.guard_passed or self.skipped:
                raise ValueError('Only a passed finite end-turn guard carries an event receipt')
            if type(self.guard_event) is not Event:
                raise ValueError('End-turn guard receipt requires Event')
            event = self.guard_event
            _int(event.sequence, 'end-turn guard event sequence', 1)
            _int(event.action, 'end-turn guard event action', 0)
            _int(event.source_id, 'end-turn guard event source', 1)
            _int(event.player_id, 'end-turn guard event player', 1)
            _int(event.amount, 'end-turn guard event amount', 0)
            if event.kind != 'limited_trigger_used' or event.player_id not in (1, 2) or event.target_id is not None:
                raise ValueError('Invalid finite end-turn guard event')
            if (type(event.data) is not tuple or
                    any(type(pair) is not tuple or len(pair) != 2 for pair in event.data)):
                raise ValueError('End-turn guard event data must be immutable pairs')
            keys = []
            def immutable_value(value):
                return type(value) in (str, int, bool, type(None)) or (
                    type(value) is tuple and all(immutable_value(item) for item in value))
            for key, value in event.data:
                _name(key, 'end-turn guard event data key')
                if not immutable_value(value):
                    raise ValueError('End-turn guard event data requires immutable JSON values')
                keys.append(key)
            if len(set(keys)) != len(keys):
                raise ValueError('Duplicate end-turn guard event data key')


@dataclass(frozen=True)
class ShatterSpec:
    left_card_id: str
    right_card_id: str

    def __post_init__(self):
        _name(self.left_card_id, 'left fragment')
        _name(self.right_card_id, 'right fragment')
        if self.left_card_id == self.right_card_id:
            raise ValueError('Shatter requires two distinct fragments')


@dataclass(frozen=True)
class HandRepeatSpec:
    """Printed repeat-this-turn behavior; Echo additionally floors copy costs."""
    echo: bool = True

    def __post_init__(self):
        _bool(self.echo, 'Echo marker')


@dataclass(frozen=True)
class HandLifetime:
    source_id: int | None
    created_turn: int
    expires_turn: int
    minimum_cost: int = 0

    def __post_init__(self):
        _optional_id(self.source_id, 'temporary card source')
        _int(self.created_turn, 'temporary card creation turn', 1)
        _int(self.expires_turn, 'temporary card expiry turn', self.created_turn)
        _int(self.minimum_cost, 'temporary card cost floor', 0)


@dataclass(frozen=True)
class RewindSpec:
    """Optional retries and a persistent remaining-budget face (R-091/R-092)."""
    retries: int = 1
    next_card_id: str | None = None

    def __post_init__(self):
        _int(self.retries, 'Rewind retries', 1)
        if self.next_card_id is not None:
            _name(self.next_card_id, 'Rewind next form')


@dataclass(frozen=True)
class ComboPayload:
    ability_id: int
    behavior_id: str
    card_id: str

    def __post_init__(self):
        _int(self.ability_id, 'Combo ability', 1)
        _name(self.behavior_id, 'Combo behavior')
        _name(self.card_id, 'Combo declaration card')


@dataclass(frozen=True)
class ComboRecord:
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    target_id: int | None
    play_id: int | None
    payload: ComboPayload
    batch_id: int | None = 1
    repeat_index: int = 1
    outcome_id: int | None = None
    iteration: int = 1
    completed: bool = False
    interrupted: bool = False
    physical_child_id: int | None = None
    failure: str | None = None

    def __post_init__(self):
        if self.failure is not None and (type(self.failure) is not str or self.failure not in ('invalid_target','no_target') or
                self.failure == 'no_target' and self.physical_child_id is None):
            raise ValueError('Invalid Combo target outcome')
        for key in ('id','source_id','player_id','iteration','repeat_index'):
            _int(getattr(self,key),'Combo '+key,1)
        if self.physical_child_id is None:
            _int(self.play_id, 'Combo paid play', 1); _int(self.batch_id, 'Combo paid batch', 1)
        else:
            _int(self.physical_child_id, 'Combo actual generated child', 1)
            if self.play_id is not None or self.batch_id is not None:
                raise ValueError('Generated Combo cannot fabricate paid identities')
        if self.player_id not in (1,2): raise ValueError('Invalid Combo player')
        for key in ('turn','action'): _int(getattr(self,key),'Combo '+key,0)
        _name(self.card_id,'Combo carrier card')
        _optional_id(self.target_id,'Combo target'); _optional_id(self.outcome_id,'Combo outcome')
        if type(self.payload) is not ComboPayload: raise ValueError('Expected ComboPayload')
        self.payload.__post_init__()
        for key in ('completed','interrupted'): _bool(getattr(self,key),'Combo '+key)
        if self.completed and self.interrupted or self.outcome_id is None and self.iteration != 1:
            raise ValueError('Invalid Combo progress or retained iteration')


@dataclass(frozen=True)
class BattlecryPayload:
    ability_id: int
    behavior_id: str
    card_id: str

    def __post_init__(self):
        _int(self.ability_id, 'Battlecry ability', 1)
        _name(self.behavior_id, 'Battlecry behavior')
        _name(self.card_id, 'Battlecry declaration card')


@dataclass(frozen=True)
class BattlecryRecord:
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    target_id: int | None
    play_id: int | None
    payload: BattlecryPayload
    batch_id: int | None
    repeat_index: int = 1
    outcome_id: int | None = None
    iteration: int = 1
    origin: str = 'hand'
    completed: bool = False
    interrupted: bool = False
    caster_id: int | None = None
    history_id: int | None = None
    parent_id: int | None = None
    choices: str = 'player'
    failure: str | None = None
    payload_started: bool = True
    history_play_id: int | None = None
    history_player_id: int | None = None
    controller_policy: str = 'captured'
    exclude_source_target: bool = False
    physical_child_id: int | None = None
    indirect_body_id: int | None = None
    historical_body_id: int | None = None

    def __post_init__(self):
        for key in ('id','source_id','iteration','repeat_index'):
            _int(getattr(self,key), 'Battlecry '+key, 1)
        for key in ('play_id','batch_id','caster_id','history_id','parent_id','history_play_id','physical_child_id','indirect_body_id','historical_body_id'):
            _optional_id(getattr(self,key), 'Battlecry '+key)
        for key in ('turn','action'): _int(getattr(self,key), 'Battlecry '+key, 0)
        if type(self.player_id) is not int or self.player_id not in (1,2):
            raise ValueError('Invalid Battlecry player')
        if self.history_player_id is not None and (type(self.history_player_id) is not int or self.history_player_id not in (1,2)):
            raise ValueError('Invalid Battlecry history owner')
        if (self.origin in ('history','played_history')) != (self.history_player_id is not None):
            raise ValueError('Battlecry history origin requires its owner')
        if (self.controller_policy not in ('captured','current') or
                self.controller_policy == 'current' and self.origin != 'played_history' or
                self.controller_policy == 'captured' and self.history_player_id not in (None,self.player_id)):
            raise ValueError('Battlecry execution and history ownership policy differ')
        _bool(self.exclude_source_target, 'Battlecry source target exclusion')
        if self.indirect_body_id is not None and (self.origin != 'effect' or self.physical_child_id is not None
                or self.exclude_source_target or self.controller_policy != 'captured'):
            raise ValueError('Bound indirect Battlecry requires its own effect origin')
        if self.historical_body_id is not None and (self.origin not in ('history','played_history')
                or self.physical_child_id is not None or self.indirect_body_id is not None):
            raise ValueError('Bound historical Battlecry requires its own history origin')
        if self.exclude_source_target and (self.origin == 'hand' or self.target_id == self.source_id):
            raise ValueError('Invalid Battlecry source target exclusion')
        _name(self.card_id, 'Battlecry card')
        _optional_id(self.target_id, 'Battlecry target')
        _optional_id(self.outcome_id, 'Battlecry outcome')
        if type(self.payload) is not BattlecryPayload:
            raise ValueError('Battlecry requires a captured payload')
        self.payload.__post_init__()
        _bool(self.completed,'completed Battlecry'); _bool(self.interrupted,'interrupted Battlecry')
        _bool(self.payload_started, 'started Battlecry payload')
        if (self.origin not in ('hand','effect','history','played_history') or self.choices not in ('player','random') or
                self.failure not in (None,'no_target','invalid_target') or
                self.failure is not None and self.payload_started or
                self.completed and not self.payload_started and self.failure is None or
                self.outcome_id is None and self.iteration != 1 or
                self.completed and self.interrupted):
            raise ValueError('Invalid Battlecry origin or progress')
        if self.origin == 'hand':
            if (self.play_id is None or self.batch_id is None or self.choices != 'player' or
                    any(v is not None for v in (self.caster_id,self.history_id,self.parent_id,self.history_play_id,self.physical_child_id))):
                raise ValueError('Invalid hand Battlecry provenance')
        else:
            if (any(v is not None for v in (self.play_id,self.batch_id)) or
                    (self.origin == 'history') != (self.history_id is not None) or
                    (self.origin == 'played_history') != (self.history_play_id is not None)):
                raise ValueError('Invalid indirect Battlecry provenance')
            if self.physical_child_id is None:
                if self.outcome_id is not None or self.repeat_index != 1 or self.iteration != 1:
                    raise ValueError('Ordinary indirect Battlecry cannot borrow retained results')
            elif (self.origin != 'effect' or self.history_id is not None or self.history_play_id is not None
                    or self.history_player_id is not None or self.controller_policy != 'captured'):
                raise ValueError('Generated Battlecry requires its own actual physical origin')


@dataclass(frozen=True)
class BattlecryBatchRecord:
    id: int
    play_id: int
    player_id: int
    payloads: tuple[BattlecryPayload, ...]
    plan: BattlecryRepeatPlan
    outcome_id: int | None = None
    iteration: int = 1  # Enclosing retained Rewind outcome, never repeat index.
    completed: int = 0
    running: bool = False
    finished: bool = False
    interrupted: bool = False

    @property
    def total(self):
        return len(self.payloads) * self.plan.repetitions

    def __post_init__(self):
        for key in ('id','play_id','iteration'): _int(getattr(self,key), 'Battlecry batch '+key, 1)
        if type(self.player_id) is not int or self.player_id not in (1,2): raise ValueError('Invalid Battlecry batch player')
        _optional_id(self.outcome_id, 'Battlecry batch outcome')
        if self.outcome_id is None and self.iteration != 1: raise ValueError('Battlecry batch has no enclosing outcome')
        if (type(self.payloads) is not tuple or not self.payloads or
                any(type(b) is not BattlecryPayload for b in self.payloads)):
            raise ValueError('Battlecry batch requires captured payloads')
        for payload in self.payloads: payload.__post_init__()
        if len({b.ability_id for b in self.payloads}) != len(self.payloads): raise ValueError('Duplicate Battlecry batch ability')
        if type(self.plan) is not BattlecryRepeatPlan: raise ValueError('Battlecry batch requires repeat plan')
        self.plan.__post_init__()
        _int(self.completed, 'completed Battlecry batch activations', 0)
        for key in ('running','finished','interrupted'): _bool(getattr(self,key), 'Battlecry batch '+key)
        if (self.completed > self.total or self.running and self.completed == self.total or
                self.finished and self.completed != self.total or self.finished and self.interrupted or
                (self.finished or self.interrupted) and self.running):
            raise ValueError('Invalid Battlecry batch progress')


@dataclass(frozen=True)
class ComboBatchRecord:
    id: int
    play_id: int
    player_id: int
    payloads: tuple[ComboPayload, ...]
    plan: ComboRepeatPlan
    outcome_id: int | None = None
    iteration: int = 1  # Enclosing retained Rewind outcome, never repeat index.
    completed: int = 0
    running: bool = False
    finished: bool = False
    interrupted: bool = False

    @property
    def total(self):
        return len(self.payloads) * self.plan.repetitions

    def __post_init__(self):
        for key in ('id','play_id','iteration'): _int(getattr(self,key), 'Combo batch '+key, 1)
        if type(self.player_id) is not int or self.player_id not in (1,2): raise ValueError('Invalid Combo batch player')
        _optional_id(self.outcome_id, 'Combo batch outcome')
        if self.outcome_id is None and self.iteration != 1: raise ValueError('Combo batch has no enclosing outcome')
        if (type(self.payloads) is not tuple or not self.payloads or
                any(type(b) is not ComboPayload for b in self.payloads)):
            raise ValueError('Combo batch requires captured payloads')
        for payload in self.payloads: payload.__post_init__()
        if len({b.ability_id for b in self.payloads}) != len(self.payloads): raise ValueError('Duplicate Combo batch ability')
        if type(self.plan) is not ComboRepeatPlan: raise ValueError('Combo batch requires repeat plan')
        self.plan.__post_init__()
        _int(self.completed, 'completed Combo batch activations', 0)
        for key in ('running','finished','interrupted'): _bool(getattr(self,key), 'Combo batch '+key)
        if (self.completed > self.total or self.running and self.completed == self.total or
                self.finished and self.completed != self.total or self.finished and self.interrupted or
                (self.finished or self.interrupted) and self.running):
            raise ValueError('Invalid Combo batch progress')


@dataclass(frozen=True)
class RewindOutcomeRecord:
    """Captured, cumulative payload outcomes; neither extra plays nor casts."""
    id: int
    source_id: int
    player_id: int
    card_id: str
    turn: int
    action: int
    target_id: int | None
    behavior_ids: tuple[str, ...]
    contributors: tuple[int, ...]
    total: int
    play_id: int | None = None
    cast_id: int | None = None
    power_id: int | None = None
    completed: int = 0
    running: bool = False
    finished: bool = False
    interrupted: bool = False
    battlecries: tuple[BattlecryPayload, ...] = ()
    combos: tuple[ComboPayload, ...] = ()
    battlecry_plan: BattlecryRepeatPlan | None = None
    combo_plan: ComboRepeatPlan | None = None
    physical_child_id: int | None = None

    def __post_init__(self):
        validate_combo_payloads(self.combos)
        if self.combos and ((self.play_id is None and self.physical_child_id is None) or self.cast_id is not None or self.power_id is not None):
            raise ValueError('Retained Combos require a real non-spell play or physical child')
        if self.combo_plan is not None:
            if type(self.combo_plan) is not ComboRepeatPlan or not self.combos:raise ValueError('Invalid retained Combo plan')
            self.combo_plan.__post_init__()
        if bool(self.battlecries) != (self.battlecry_plan is not None):
            raise ValueError('Retained Battlecries and repetition plan must agree')
        if self.battlecry_plan is not None:
            if type(self.battlecry_plan) is not BattlecryRepeatPlan: raise ValueError('Invalid retained Battlecry plan')
            self.battlecry_plan.__post_init__()
        if type(self.battlecries) is not tuple or any(type(b) is not BattlecryPayload for b in self.battlecries):
            raise ValueError('Retained Battlecries require an immutable payload tuple')
        for payload in self.battlecries: payload.__post_init__()
        if len({b.ability_id for b in self.battlecries}) != len(self.battlecries):
            raise ValueError('Duplicate retained Battlecry ability')
        if self.battlecries and ((self.play_id is None and self.physical_child_id is None) or self.cast_id is not None or self.power_id is not None):
            raise ValueError('Retained Battlecries require a real non-spell play or physical child')
        for key in ('id', 'source_id', 'player_id'):
            _int(getattr(self, key), 'retained outcome '+key, 1)
        if self.player_id not in (1, 2): raise ValueError('Invalid outcome player')
        for key in ('turn', 'action', 'completed'):
            _int(getattr(self, key), 'retained outcome '+key, 0)
        for key in ('target_id', 'play_id', 'cast_id', 'power_id', 'physical_child_id'):
            _optional_id(getattr(self, key), 'retained outcome '+key)
        _name(self.card_id, 'retained outcome card')
        _int(self.total, 'retained outcome count', 2)
        for key in ('running', 'finished', 'interrupted'):
            _bool(getattr(self, key), 'retained outcome '+key)
        if (self.completed > self.total or self.running and self.completed == self.total or
                self.finished and self.completed != self.total or self.finished and self.interrupted or
                (self.finished or self.interrupted) and self.running or
                self.play_id is None and self.cast_id is None and self.power_id is None and self.physical_child_id is None or
                self.physical_child_id is not None and any(x is not None for x in (self.play_id, self.cast_id, self.power_id)) or
                self.power_id is not None and (self.play_id is not None or self.cast_id is not None)):
            raise ValueError('Invalid retained outcome progress')
        if type(self.behavior_ids) is not tuple:
            raise ValueError('Retained behaviors require immutable IDs')
        for behavior in self.behavior_ids: _name(behavior, 'retained behavior')
        if (type(self.contributors) is not tuple or not self.contributors or
                len(set(self.contributors)) != len(self.contributors)):
            raise ValueError('Retained outcomes require unique contributors')
        for entity_id in self.contributors: _int(entity_id, 'retention contributor', 1)


@dataclass(frozen=True)
class HealthFloorRow:
    """Original matched immutable row and physical carrier, not a live HP quote."""
    ability: AbilityInstance
    carrier_id: int
    card_id: str
    kind: CardType
    controller: int
    zone: Zone
    zone_epoch: int
    entered_order: int

    def __post_init__(self):
        if type(self.ability) is not AbilityInstance:
            raise ValueError('Health floor row requires original typed ability')
        self.ability.__post_init__()
        if (self.ability.kind != 'health_rule' or self.ability.consumed or
                self.ability.health_rule.operation != HealthOp.FLOOR):
            raise ValueError('Health floor row is not an accepted FLOOR ability')
        _int(self.carrier_id, 'floor carrier', 1); _name(self.card_id, 'floor carrier face')
        _int(self.zone_epoch, 'floor carrier epoch', 0)
        _int(self.entered_order, 'floor carrier order', 0)
        if type(self.controller) is not int or self.controller not in (1, 2):
            raise ValueError('Invalid floor carrier controller')
        if type(self.kind) is not CardType or type(self.zone) is not Zone or (
                (self.kind, self.zone) not in ((CardType.HERO, Zone.HERO),
                (CardType.MINION, Zone.BOARD), (CardType.WEAPON, Zone.WEAPON))):
            raise ValueError('Unsupported health floor carrier')


@dataclass(frozen=True)
class HealthFloorPlan:
    """Frozen row eligibility; settlement reads current HP independently per packet.

    Allocation bounds prove bounded internal consistency, not unsigned origin or
    complete candidate eligibility. No whole batch GameState is retained.
    """
    rows: tuple[HealthFloorRow, ...]
    floor: int
    turn: int
    next_entity_id: int
    next_attachment_id: int
    next_order: int
    source_id: int | None
    source_controller: int | None
    damage_kind: DamageKind
    school: SpellSchool | None
    target_id: int
    target_card_id: str
    target_kind: CardType
    target_controller: int
    target_zone_epoch: int
    target_entered_order: int

    def __post_init__(self):
        for name in ('floor', 'turn', 'next_entity_id', 'next_attachment_id', 'next_order', 'target_id'):
            _int(getattr(self, name), name, 1)
        for name in ('target_zone_epoch', 'target_entered_order'):
            _int(getattr(self, name), name, 0)
        _name(self.target_card_id, 'floor target face'); _optional_id(self.source_id, 'floor source')
        if type(self.target_controller) is not int or self.target_controller not in (1, 2):
            raise ValueError('Invalid floor target controller')
        if self.source_id is None:
            if self.source_controller is not None: raise ValueError('Source-less floor has source controller')
        elif type(self.source_controller) is not int or self.source_controller not in (1, 2):
            raise ValueError('Invalid floor source controller')
        if (type(self.target_kind) is not CardType or self.target_kind not in (CardType.HERO, CardType.MINION) or
                type(self.damage_kind) is not DamageKind or
                (self.school is not None and type(self.school) is not SpellSchool)):
            raise ValueError('Invalid floor packet kinds')
        if (self.target_id >= self.next_entity_id or self.target_entered_order >= self.next_order or
                (self.source_id is not None and self.source_id >= self.next_entity_id)):
            raise ValueError('Floor packet refers to a future allocation')
        if type(self.rows) is not tuple or not self.rows or any(type(row) is not HealthFloorRow for row in self.rows):
            raise ValueError('Floor plan requires nonempty typed immutable rows')
        ids = tuple(row.ability.id for row in self.rows)
        if ids != tuple(sorted(set(ids))): raise ValueError('Floor rows require unique allocation order')
        for row in self.rows:
            row.__post_init__(); a=row.ability; rule=a.health_rule
            if (a.id >= self.next_attachment_id or row.carrier_id >= self.next_entity_id or
                    row.entered_order >= self.next_order or
                    (a.source_id is not None and a.source_id >= self.next_entity_id) or
                    (a.expires_turn is not None and a.expires_turn < self.turn)):
                raise ValueError('Floor row exceeds its original allocation or lifetime')
            from .health_rules import relation_matches
            if (self.target_kind not in rule.target_kinds or
                    (rule.damage_kinds and self.damage_kind not in rule.damage_kinds) or
                    (rule.schools and self.school not in rule.schools) or
                    not relation_matches(rule.source_relation, self.source_id, self.source_controller, row.carrier_id, row.controller) or
                    not relation_matches(rule.target_relation, self.target_id, self.target_controller, row.carrier_id, row.controller)):
                raise ValueError('Floor row disagrees with accepted packet matching')
        if self.floor != max(row.ability.health_rule.amount for row in self.rows):
            raise ValueError('Floor limit disagrees with original matched rows')


@dataclass(frozen=True)
class InteractableSpec:
    """One recurring, zero-mana own-hand investment action on an inert carrier."""
    behavior_id: str

    def __post_init__(self):
        _name(self.behavior_id, 'interactable behavior')


@dataclass(frozen=True)
class CardDefinition:
    id: str
    name: str
    kind: CardType
    cost: int = 0
    attack: int = 0
    health: int = 0
    keywords: tuple[Keyword, ...] = ()
    on_play: str | None = None
    battlecry: str | None = None
    combo: str | None = None
    deathrattle: str | None = None
    triggers: tuple[TriggerSpec, ...] = ()
    auras: tuple[AuraSpec, ...] = ()
    requires_target: bool = False
    target_rule: str = "any_entity"
    spell_damage: int = 0
    targeting: TargetSpec | None = None
    durability: int = 0
    on_use: str | None = None
    uses_per_turn: int = 1
    use_rule: str = "always"
    requires_board_space: bool = False
    cost_auras: tuple[CostAuraSpec, ...] = ()
    keyword_auras: tuple[KeywordAuraSpec, ...] = ()
    battlecry_repeats: tuple[BattlecryRepeatSpec, ...] = ()
    deathrattle_repeats: tuple[DeathrattleRepeatSpec, ...] = ()
    combo_repeats: tuple[ComboRepeatSpec, ...] = ()
    spell_repeats: tuple[SpellRepeatSpec, ...] = ()
    health_loss_replacements: tuple[HealthLossReplacementSpec, ...] = ()
    health_loss_floors: tuple[HealthLossFloorSpec, ...] = ()
    summon_quantities: tuple[SummonQuantitySpec,...] = ()
    weapon_wear_policies: tuple[WeaponWearSpec, ...] = ()
    deck_sacrifice: DeckSacrificeSpec | None = None
    corpse_value: int | None = None
    spell_school: SpellSchool | None = None
    health_rules: tuple[HealthRule, ...] = ()
    metadata: CardMetadata | None = None
    opening_hooks: tuple[OpeningHook, ...] = ()
    initial_hero_power: str | None = None
    hand_actions: tuple[HandActionSpec, ...] = ()
    # Body templates are selected explicitly by class, never by a generation pool.
    starship_for: tuple[CardClass, ...] = ()
    on_launch: str | None = None
    # Protocols and similar UI options describe a branch, not a physical card.
    choice_only: bool = False
    hero_card: bool = False
    hero_armor: int = 0
    keep_hero_class: bool = False
    additional_power_policy: str = 'preserve'
    dormant_turns: int | None = 0
    dormant_board_full: bool = False
    native_deathrattle: NativeDeathrattleSpec | None = None
    on_awaken: str | None = None
    dormant_triggers: tuple[TriggerSpec, ...] = ()
    activated_abilities: tuple[ActivatedAbilitySpec, ...] = ()
    quest: QuestSpec | None = None
    ongoing_effect_id: str | None = None
    secret: SecretSpec | None = None
    # Built-in pre-play predicate controlling whether the declared target exists.
    target_condition: str | None = None
    manathirst: int | None = None
    magnetic_tribes: tuple[str, ...] = ()
    colossal: tuple[AppendageSpec, ...] = ()
    herald_scaling: bool = False
    herald_soldier_for: CardClass | None = None
    limited_triggers: tuple[LimitedTriggerSpec, ...] = ()
    hand_progress: HandProgressSpec | None = None
    defining_hand_source: HandProgressSpec | None = None
    shatter: ShatterSpec | None = None
    hand_repeat: HandRepeatSpec | None = None
    hand_derivatives: tuple[HandDerivativeSpec, ...] = ()
    cast_when_drawn: CastWhenDrawnSpec | None = None
    rewind: RewindSpec | None = None
    retain_rewind_outcomes: bool = False
    passive_hero_power: bool = False
    choose_one: ChooseOneSpec | None = None
    choose_both: bool = False
    timed_keywords: tuple[TimedKeywordSpec, ...] = ()
    hero_power_repeats: tuple[HeroPowerRepeatSpec, ...] = ()
    end_turn_repeats: tuple[EndTurnRepeatSpec, ...] = ()
    intrinsic_costs: tuple[IntrinsicCostSpec, ...] = ()
    attack_policies: tuple[AttackPolicySpec, ...] = ()
    stat_relations: tuple[StatRelationSpec, ...] = ()
    disguised: bool = False
    interactable: InteractableSpec | None = None
    board_minion_cost: BoardMinionCostSpec | None = None
    hand_count_cost: HandCountCostSpec | None = None
    hero_missing_health_cost: HeroMissingHealthCostSpec | None = None
    player_spell_count_cost: PlayerSpellCountCostSpec | None = None
    player_hero_power_count_cost: PlayerHeroPowerCountCostSpec | None = None
    player_spell_mana_cost: PlayerSpellManaCostSpec | None = None
    minion_death_cost: MinionDeathCostSpec | None = None
    player_overload_cost: PlayerOverloadCostSpec | None = None
    player_played_class_cost: PlayerPlayedClassCostSpec | None = None
    hero_health_change_cost: HeroHealthChangeCostSpec | None = None
    player_draw_count_cost: PlayerDrawCountCostSpec | None = None
    player_weapon_attack_cost: PlayerWeaponAttackCostSpec | None = None
    player_armor_cost: PlayerArmorCostSpec | None = None
    player_summon_count_cost: PlayerSummonCountCostSpec | None = None
    player_elemental_streak_cost: PlayerElementalStreakCostSpec | None = None
    player_corpse_spend_cost: PlayerCorpseSpendCostSpec | None = None
    hero_damage_taken_cost: HeroDamageTakenCostSpec | None = None
    player_spell_damage_cost: PlayerSpellDamageCostSpec | None = None
    player_character_attack_cost: PlayerCharacterAttackCostSpec | None = None
    spell_damage_schools: tuple[SpellSchool, ...] = ()
    cleave: bool = False
    on_discard: str | None = None
    cost_payment: PaymentType = PaymentType.MANA
    pay_health_if_hero_healed: bool = False
    # Permanent portals share dormancy gates but cannot be awakened.
    permanent_dormancy: bool = False
    # A physical hand/deck card may exist without permission to play it manually.
    manual_playable: bool = True
    # A manual hand play may require current equipment without selecting it.
    requires_weapon: bool = False
    hero_power_use_aura: HeroPowerUseAuraSpec | None = None
    on_destroyed: str | None = None
    stored_deathrattle: bool = False
    reborn_policy: str | None = None
    hand_mirror: HandMirrorSpec | None = None
    native_condition: NativeSourceCondition | None = None

    @property
    def hand_playable(self) -> bool:
        """Structural eligibility for a physical card, independent of play permission."""
        return not self.choice_only and self.interactable is None and (self.kind in (
            CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION)
            or (self.kind == CardType.HERO and self.hero_card))


@dataclass(frozen=True)
class DormancyState:
    """A board-only lifecycle instance, independent of removable abilities."""
    id: int
    remaining_turns: int | None
    started_turn: int
    permanent: bool = False

    def __post_init__(self):
        _int(self.id, 'dormancy ID', 1)
        _int(self.started_turn, 'dormancy started_turn', 1)
        _bool(self.permanent, 'permanent dormancy')
        if self.permanent and self.remaining_turns is not None:
            raise ValueError('Permanent dormancy cannot have a countdown')
        if self.remaining_turns is not None:
            _int(self.remaining_turns, 'dormancy remaining_turns', 1)


@dataclass
class Entity:
    id: int
    card_id: str
    owner: int
    controller: int
    zone: Zone
    base_attack: int = 0
    base_health: int = 0
    base_cost: int = 0
    herald_rank: int | None = None
    galakrond_invocations: int | None = None
    damage: int = 0
    armor: int = 0
    attack_bonus: int = 0
    health_bonus: int = 0
    cost_modifier: int = 0
    aura_attack: int = 0
    keywords: set[Keyword] = field(default_factory=set)
    attacks_this_turn: int = 0
    old_god_free_used: bool = False
    summoned_turn: int = 0
    entered_order: int = 0
    # Reuses the entry's existing order allocation; controller/face changes preserve it.
    board_presence_id: int | None = None
    doomed: bool = False
    death_cause: DeathCause | None = None
    enchantments: list[Enchantment] = field(default_factory=list)
    abilities: list[AbilityInstance] = field(default_factory=list)
    silenced: bool = False
    origin_entity_id: int | None = None
    # Explicit replacement transformations invalidate original-deck credit.
    # This physical-recipient provenance is not copied from another entity.
    face_replaced: bool = False
    aura_health: int = 0
    frozen_until_owner_turn: int | None = None
    durability: int = 0
    weapon_attack: int = 0
    weapon_keywords: set[Keyword] = field(default_factory=set)
    aura_keywords: set[Keyword] = field(default_factory=set)
    hand_aura_keywords: set[Keyword] = field(default_factory=set)
    conditional_keywords: set[Keyword] = field(default_factory=set)
    conditional_attack: int = 0
    conditional_health: int = 0
    uses_this_turn: int = 0
    use_limit: int = 1
    corpse_value: int = 0
    components: tuple[str, ...] = ()
    starship_building: bool = False
    kind: CardType = CardType.MINION
    location_cooldown: int = 0
    dormancy: DormancyState | None = None
    quest_progress: QuestProgress | None = None
    secret_instance_id: int | None = None
    # Invalidates old stored-card references after movement or a face change.
    zone_epoch: int = 0
    hand_entry_id: int | None = None
    hand_lifetime: HandLifetime | None = None
    choose_branch: ChooseBranchSelection | None = None
    preparation: HandPreparation | None = None
    jade_size: int | None = None
    interactable_object: bool = False

    @property
    def is_character(self) -> bool:
        return not self.interactable_object and self.kind in (CardType.HERO, CardType.MINION)

    @property
    def active(self) -> bool:
        """Participation in ordinary effects; zone eligibility is checked separately."""
        return not self.interactable_object and not self.starship_building and self.dormancy is None

    @property
    def frozen(self) -> bool:
        return self.frozen_until_owner_turn is not None

    @property
    def attack(self) -> int:
        from .stats import derived_attack
        ordinary = self.base_attack + self.attack_bonus + self.aura_attack
        return derived_attack(self, ordinary)

    @property
    def max_health(self) -> int:
        return self.base_health + self.health_bonus + self.aura_health + self.conditional_health

    @property
    def health(self) -> int:
        return self.max_health - self.damage

    @property
    def cost(self) -> int:
        floor = self.hand_lifetime.minimum_cost if self.hand_lifetime is not None and self.zone == Zone.HAND else 0
        return max(floor, self.base_cost + self.cost_modifier)


@dataclass
class PlayerState:
    id: int
    hero_id: int
    deck: list[int] = field(default_factory=list)
    hand: list[int] = field(default_factory=list)
    board: list[int] = field(default_factory=list)
    graveyard: list[int] = field(default_factory=list)
    setaside: list[int] = field(default_factory=list)
    pending_plays: list[int] = field(default_factory=list)
    quests: list[int] = field(default_factory=list)
    secrets: list[int] = field(default_factory=list)
    max_mana: int = 0
    mana: int = 0
    fatigue: int = 0
    weapon_id: int | None = None
    hero_power_id: int | None = None
    hero_power_uses_this_turn: int = 0
    mana_cap: int = 10
    mana_spent: int = 0
    temporary_mana: int = 0
    overload_owed: int = 0
    overload_locked: int = 0
    resources: dict[Resource, int] = field(default_factory=lambda: {Resource.CORPSES: 0})
    cost_modifiers: list[CostModifier] = field(default_factory=list)
    player_effects: list[PlayerEffect] = field(default_factory=list)
    battlecry_modifiers: list[BattlecryRepeatModifier] = field(default_factory=list)
    combo_modifiers: list[ComboRepeatModifier] = field(default_factory=list)
    spell_modifiers: list[SpellRepeatModifier] = field(default_factory=list)
    choose_both_modifiers: list = field(default_factory=list)
    deck_class: CardClass | None = None
    runes: Runes | None = None
    original_deck: tuple[str, ...] = ()
    sideboards: tuple['SideboardState', ...] = ()
    void_cards: tuple['VoidCard', ...] = ()
    hero_class: CardClass | None = None

    additional_hero_power_ids: list[int] = field(default_factory=list)
    hand_cap: int | None = None

    @property
    def hero_power_ids(self) -> tuple[int, ...]:
        """Installed physical powers, primary first; no duplicate state cache."""
        return (() if self.hero_power_id is None else (self.hero_power_id,)) + tuple(self.additional_hero_power_ids)


@dataclass(frozen=True)
class StarshipLaunchRecord:
    id: int
    player_id: int
    entity_id: int
    card_id: str
    components: tuple[str, ...]
    turn: int
    action: int

    def __post_init__(self):
        for name in ('id', 'entity_id', 'turn'):
            _int(getattr(self, name), f'launch {name}', 1)
        _int(self.action, 'launch action', 0)
        _int(self.player_id, 'launch player_id', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Invalid launch controller')
        _name(self.card_id, 'launch card ID')
        _components(self.components)
        if not self.components:
            raise ValueError('A launched Starship must have components')


@dataclass(frozen=True)
class CardPreview:
    """Frozen visible attributes, without a trackable hidden-zone identity."""
    cost: int
    attack: int
    health: int
    max_health: int
    durability: int
    keywords: tuple[Keyword, ...] = ()

    def __post_init__(self):
        for field in ('cost', 'attack', 'max_health', 'durability'):
            _int(getattr(self, field), 'preview ' + field, 0)
        _int(self.health, 'preview health')
        if (type(self.keywords) is not tuple or any(type(k) is not Keyword for k in self.keywords) or
                tuple(sorted(set(self.keywords), key=lambda k: k.value)) != self.keywords):
            raise ValueError('Preview keywords require a sorted unique tuple')

    @classmethod
    def capture(cls, entity):
        return cls(entity.cost, entity.attack, entity.health, entity.max_health,
                   entity.durability, tuple(sorted(entity.keywords, key=lambda k: k.value)))


@dataclass(frozen=True)
class ChoiceItem:
    id: str
    label: str
    card_id: str | None = None
    entity_id: int | None = None
    preview: CardPreview | None = None

    def __post_init__(self):
        _name(self.id, 'choice option ID')
        _name(self.label, 'choice label')
        if self.card_id is not None:
            _name(self.card_id, 'choice card_id')
        _optional_id(self.entity_id, 'choice entity_id')
        if self.preview is not None:
            if type(self.preview) is not CardPreview or self.card_id is None:
                raise ValueError('A choice preview requires a card identity')
            self.preview.__post_init__()


class ChoicePurpose(StrEnum):
    EFFECT = 'effect'
    MULLIGAN = 'mulligan'
    REWIND = 'rewind'
    DREDGE = 'dredge'
    POOL_DISCOVERY = 'pool_discovery'
    ASSEMBLE = 'assemble'


@dataclass(frozen=True)
class PendingChoice:
    id: int
    player_id: int
    source_id: int | None
    prompt: str
    options: tuple[ChoiceItem, ...]
    min_count: int = 1
    max_count: int = 1
    purpose: ChoicePurpose = ChoicePurpose.EFFECT
    repeat_key: str | None = None

    def __post_init__(self):
        if self.repeat_key is not None:
            _name(self.repeat_key, 'repeat choice key')
            if self.source_id is None or self.purpose != ChoicePurpose.EFFECT:
                raise ValueError('Repeated branch choices require an effect source')
        if not isinstance(self.purpose, ChoicePurpose):
            raise ValueError('Invalid choice purpose')
        _int(self.id, 'choice ID', 1)
        _int(self.player_id, 'choice player_id', 1)
        if self.player_id not in (1, 2):
            raise ValueError('Choice player must be 1 or 2')
        _optional_id(self.source_id, 'choice source_id')
        _name(self.prompt, 'choice prompt')
        if not isinstance(self.options, tuple) or any(not isinstance(o, ChoiceItem) for o in self.options):
            raise ValueError('Choice options must be an immutable tuple of ChoiceItem')
        for item in self.options:
            item.__post_init__()
        if len({o.id for o in self.options}) != len(self.options):
            raise ValueError('Duplicate choice option ID')
        _int(self.min_count, 'choice min_count', 0)
        _int(self.max_count, 'choice max_count', 0)
        if not self.min_count <= self.max_count <= len(self.options):
            raise ValueError('Invalid choice cardinality')


@dataclass(frozen=True)
class ChoiceResult:
    choice: PendingChoice
    selected_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.choice, PendingChoice):
            raise ValueError('ChoiceResult requires PendingChoice')
        self.choice.__post_init__()
        if (not isinstance(self.selected_ids, tuple) or any(not isinstance(i, str) for i in self.selected_ids) or
                len(set(self.selected_ids)) != len(self.selected_ids)):
            raise ValueError('Selected options must be a unique string tuple')
        available = {o.id for o in self.choice.options}
        if set(self.selected_ids) - available or not self.choice.min_count <= len(self.selected_ids) <= self.choice.max_count:
            raise ValueError('Invalid selected options')
        if self.selected_ids != tuple(o.id for o in self.choice.options if o.id in self.selected_ids):
            raise ValueError('Choice results must follow offered option order')

    @property
    def selected(self):
        return tuple(o for o in self.choice.options if o.id in self.selected_ids)


@dataclass(frozen=True)
class StartingHandCard:
    """A frozen face and acquisition at the final opening boundary."""
    entity_id: int
    card_id: str
    zone_epoch: int
    hand_entry_id: int

    def __post_init__(self):
        _int(self.entity_id, 'starting hand entity', 1)
        _name(self.card_id, 'starting hand face')
        _int(self.zone_epoch, 'starting hand epoch', 0)
        _int(self.hand_entry_id, 'starting hand acquisition', 1)


@dataclass(frozen=True)
class OpeningState:
    first_player: int
    stage: str = 'dealing'
    offered: tuple[tuple[int, ...], tuple[int, ...]] = ((), ())
    selected: tuple[tuple[int, ...], tuple[int, ...]] = ((), ())
    completed: tuple[int, ...] = ()
    original_entities: tuple[tuple[int, ...], tuple[int, ...]] = ((), ())
    starting_hands: tuple[tuple[StartingHandCard, ...], tuple[StartingHandCard, ...]] | None = None

    def __post_init__(self):
        _int(self.first_player, 'first_player')
        if self.first_player not in (1, 2) or self.stage not in ('dealing', 'mulligan', 'starting', 'complete'):
            raise ValueError('Invalid opening phase or first player')
        for name in ('offered', 'selected', 'original_entities'):
            groups = getattr(self, name)
            if not isinstance(groups, tuple) or len(groups) != 2:
                raise ValueError('Opening records require two player tuples')
            for group in groups:
                if not isinstance(group, tuple) or len(group) != len(set(group)):
                    raise ValueError('Opening entity lists must be unique tuples')
                for entity_id in group:
                    _int(entity_id, 'opening entity_id', 1)
        if (not isinstance(self.completed, tuple) or self.completed not in
                ((), (self.first_player,), (self.first_player, 3 - self.first_player))):
            raise ValueError('Invalid mulligan completion sequence')
        for player_id in self.completed:
            _int(player_id, 'completed mulligan player', 1)
        for offered, selected, original in zip(self.offered, self.selected, self.original_entities):
            if set(selected) - set(offered):
                raise ValueError('Mulligan selections must reference offered entities')
            if selected != tuple(i for i in offered if i in selected):
                raise ValueError('Mulligan selections must follow offered order')
        if self.stage in ('starting', 'complete') and len(self.completed) != 2:
            raise ValueError('Both mulligans must finish before starting play')
        if self.stage != 'dealing' and any(len(group) != (3 if player_id == self.first_player else 4)
                                          for player_id, group in enumerate(self.offered, 1)):
            raise ValueError('Ordinary opening offers must contain three/four cards')
        if (self.starting_hands is not None) != (self.stage == 'complete'):
            raise ValueError('Final starting hands require the completed opening boundary')
        if self.starting_hands is not None:
            if type(self.starting_hands) is not tuple or len(self.starting_hands) != 2:
                raise ValueError('Final starting hands require two immutable groups')
            seen = set()
            for group in self.starting_hands:
                if type(group) is not tuple:
                    raise ValueError('Final starting hand must be an immutable tuple')
                for card in group:
                    if type(card) is not StartingHandCard:
                        raise ValueError('Typed starting hand card required')
                    card.__post_init__()
                    if card.entity_id in seen:
                        raise ValueError('Duplicate physical starting hand card')
                    seen.add(card.entity_id)


@dataclass(frozen=True)
class DeathrattleRepeatContributor:
    carrier_id: int
    card_id: str
    player_id: int
    ability: AbilityInstance

    @property
    def key(self): return self.ability.id,0

    @property
    def spec(self): return self.ability.deathrattle_repeat

    def __post_init__(self):
        _int(self.carrier_id,'Deathrattle repeat source',1);_name(self.card_id,'Deathrattle repeat source card')
        _int(self.player_id,'Deathrattle repeat player',1)
        if self.player_id not in (1,2): raise ValueError('Invalid Deathrattle repeat player')
        if type(self.ability) is not AbilityInstance: raise ValueError('Expected captured repeat ability')
        self.ability.__post_init__()
        if self.ability.kind!='deathrattle_repeat' or self.ability.consumed: raise ValueError('Expected active repeat ability')


@dataclass(frozen=True)
class DeathrattlePlayerContributor:
    player_id: int
    instance: PlayerEffect
    spec_index: int
    spec: DeathrattleRepeatSpec

    @property
    def key(self): return self.instance.id,self.spec_index

    def __post_init__(self):
        _int(self.player_id,'Deathrattle policy player',1)
        if self.player_id not in (1,2): raise ValueError('Invalid Deathrattle policy player')
        if type(self.instance) is not PlayerEffect: raise ValueError('Expected captured player effect instance')
        self.instance.__post_init__();_int(self.spec_index,'Deathrattle policy specification index',0)
        if type(self.spec) is not DeathrattleRepeatSpec: raise ValueError('Expected captured player repeat specification')
        self.spec.__post_init__()
        if self.spec.scope != 'friendly':
            raise ValueError('Captured player Deathrattle policy cannot require a physical self carrier')
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Captured player Deathrattle policy cannot require a physical board carrier')


@dataclass(frozen=True)
class DeathrattleRepeatPlan:
    repetitions: int = 1
    contributors: tuple[DeathrattleRepeatContributor | DeathrattlePlayerContributor, ...] = ()

    def __post_init__(self):
        _int(self.repetitions,'captured Deathrattle repetitions',1)
        if type(self.contributors) is not tuple: raise ValueError('Expected immutable repeat contributors')
        ids=[]
        for source in self.contributors:
            if type(source) not in (DeathrattleRepeatContributor,DeathrattlePlayerContributor): raise ValueError('Invalid Deathrattle repeat contributor')
            source.__post_init__();ids.append(source.key)
        if ids!=sorted(set(ids)): raise ValueError('Deathrattle repeat contributors require unique ordered identities')
        if self.repetitions!=max((s.spec.repetitions for s in self.contributors),default=1):
            raise ValueError('Deathrattle repetition count differs from contributors')


@dataclass(frozen=True)
class DeathrattlePayloadPlan:
    ability: AbilityInstance
    plan: DeathrattleRepeatPlan

    def __post_init__(self):
        if type(self.ability) is not AbilityInstance: raise ValueError('Expected Deathrattle payload ability')
        self.ability.__post_init__()
        if self.ability.kind!='deathrattle' or self.ability.consumed: raise ValueError('Expected active Deathrattle payload')
        if type(self.plan) is not DeathrattleRepeatPlan: raise ValueError('Expected payload repeat plan')
        self.plan.__post_init__()


@dataclass(frozen=True)
class DeathrattleBatch:
    id: int  # First capture ID, retaining the existing group identity.
    payloads: tuple[DeathrattlePayloadPlan, ...]
    trigger_count: int = 1

    @property
    def abilities(self): return tuple(p.ability for p in self.payloads)

    @property
    def plan(self):
        """Uniform-plan convenience for existing trusted-host queries."""
        first=self.payloads[0].plan
        if any(p.plan!=first for p in self.payloads):
            raise ValueError('Mixed Deathrattle plans require querying individual payloads')
        return first

    @property
    def per_trigger(self): return sum(p.plan.repetitions for p in self.payloads)

    @property
    def total(self): return self.trigger_count*self.per_trigger

    def position(self, index):
        """Zero-based queue position -> frozen ability and two one-based axes."""
        _int(index,'Deathrattle batch position',0)
        if index>=self.total: raise ValueError('Deathrattle batch position is out of range')
        trigger_index,within=divmod(index,self.per_trigger)
        for payload in self.payloads:
            if within<payload.plan.repetitions: return payload.ability,trigger_index+1,within+1
            within-=payload.plan.repetitions
        raise ValueError('Invalid Deathrattle batch position')

    def __post_init__(self):
        _int(self.id,'Deathrattle batch',1)
        _int(self.trigger_count,'Deathrattle trigger count',1)
        if type(self.payloads) is not tuple or not self.payloads: raise ValueError('Expected captured Deathrattle payload plans')
        ids=[]
        for payload in self.payloads:
            if type(payload) is not DeathrattlePayloadPlan: raise ValueError('Invalid Deathrattle payload plan')
            payload.__post_init__();ids.append(payload.ability.id)
        if len(set(ids))!=len(ids): raise ValueError('Duplicate Deathrattle payload identity')


@dataclass(frozen=True)
class DeathrattleCapture:
    """Immutable scheduled invocation; execution state belongs to its record."""
    id: int
    group_id: int
    carrier_id: int
    player_id: int
    card_id: str
    kind: CardType
    ability: AbilityInstance
    origin: str
    death_id: int | None
    trigger_source_id: int | None
    trigger_source_card_id: str | None
    turn: int
    action: int
    repeat_index: int = 1
    trigger_index: int = 1

    def __post_init__(self):
        _int(self.repeat_index,'Deathrattle repeat index',1)
        _int(self.trigger_index,'Deathrattle trigger index',1)
        for name in ('id', 'group_id', 'carrier_id', 'turn'): _int(getattr(self,name),name,1)
        if self.group_id>self.id: raise ValueError('Deathrattle group cannot follow its invocation')
        _int(self.action,'Deathrattle action',0)
        _int(self.player_id,'Deathrattle player',1)
        if self.player_id not in (1,2): raise ValueError('Invalid Deathrattle player')
        _name(self.card_id,'Deathrattle carrier card')
        if type(self.kind) is not CardType or self.kind not in (CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO):
            raise ValueError('Invalid Deathrattle carrier kind')
        if type(self.ability) is not AbilityInstance: raise ValueError('Expected captured Deathrattle ability')
        self.ability.__post_init__()
        if self.ability.kind!='deathrattle' or self.ability.consumed: raise ValueError('Expected active Deathrattle ability')
        if self.origin not in ('death','effect','stored'): raise ValueError('Unknown Deathrattle origin')
        _optional_id(self.death_id,'Deathrattle death')
        _optional_id(self.trigger_source_id,'Deathrattle trigger source')
        if (self.origin=='death') != (self.death_id is not None): raise ValueError('Deathrattle death/origin disagree')
        if (self.trigger_source_id is None) != (self.trigger_source_card_id is None): raise ValueError('Trigger source identity disagrees')
        if self.trigger_source_card_id is not None: _name(self.trigger_source_card_id,'Deathrattle trigger card')
        if self.origin=='death' and self.trigger_source_id is not None: raise ValueError('Natural Deathrattle has no effect trigger source')
        if self.origin=='death' and self.trigger_index!=1: raise ValueError('Natural Deathrattle has one trigger round')
        if self.origin in ('effect','stored') and self.kind!=CardType.MINION: raise ValueError('Current effect trigger requires a minion')


@dataclass(frozen=True)
class DeathrattleRecord:
    capture: DeathrattleCapture
    execution_order: int | None = None
    completed: bool = False
    interrupted: bool = False
    source_attack: int | None = None

    @property
    def id(self): return self.capture.id

    def __post_init__(self):
        if type(self.capture) is not DeathrattleCapture: raise ValueError('Expected Deathrattle capture')
        self.capture.__post_init__()
        _optional_id(self.execution_order,'Deathrattle execution order')
        if self.execution_order is None:
            if self.source_attack is not None:raise ValueError('Unstarted Deathrattle cannot claim an execution Attack')
        else:_int(self.source_attack,'Deathrattle actual execution Attack',0)
        if type(self.completed) is not bool or type(self.interrupted) is not bool: raise ValueError('Invalid Deathrattle status')
        if self.completed and (self.execution_order is None or self.interrupted): raise ValueError('Invalid Deathrattle completion')


@dataclass(frozen=True)
class CharacterAttackCombatFact:
    player_id: int
    source_card_id: str
    source_zone_epoch: int
    source_entered_order: int
    target_id: int
    target_player_id: int
    target_card_id: str
    weapon_id: int | None
    action: int
    event_cursor: int

    def __post_init__(self):
        for player in (self.player_id, self.target_player_id):
            if type(player) is not int or player not in (1, 2):
                raise ValueError('Character combat requires actual original players')
        for name in ('source_card_id', 'target_card_id'):
            _name(getattr(self, name), 'character combat ' + name)
        for name in ('source_entered_order', 'target_id'):
            _int(getattr(self, name), 'character combat ' + name, 1)
        for name in ('source_zone_epoch', 'action', 'event_cursor'):
            _int(getattr(self, name), 'character combat ' + name, 0)
        _optional_id(self.weapon_id, 'character combat original weapon')


@dataclass(frozen=True)
class CharacterAttackTerminalFact:
    status: str
    reason: str
    action: int
    event_cursor: int

    def __post_init__(self):
        if type(self.status) is not str or self.status not in ('completed', 'cancelled', 'interrupted'):
            raise ValueError('Unsupported original character attack terminal')
        _name(self.reason, 'character attack terminal reason')
        _int(self.action, 'character attack terminal action', 0)
        _int(self.event_cursor, 'character attack terminal event cursor', 0)


@dataclass(frozen=True)
class CharacterAttackRecord:
    declaration: ActionWindow
    source_card_id: str
    source_kind: CardType
    source_zone_epoch: int
    source_entered_order: int
    turn: int
    owner_turn_id: int | None
    root_action_number: int
    declaration_action: int
    declaration_event_cursor: int
    delivery: ActionWindow | None = None
    delivery_action: int | None = None
    delivery_event_cursor: int | None = None
    combat: CharacterAttackCombatFact | None = None
    terminal: CharacterAttackTerminalFact | None = None

    def __post_init__(self):
        from .character_attacks import validate_record
        validate_record(self)


@dataclass(frozen=True)
class HeroAttackIdentity:
    record_id: int
    window_id: int
    player_id: int
    physical_hero_id: int
    hero_card_id: str
    zone_epoch: int
    declared_target_id: int
    turn: int
    owner_turn_id: int
    root_action_number: int

    def __post_init__(self):
        for name in ('record_id', 'window_id', 'physical_hero_id', 'declared_target_id',
                     'turn', 'owner_turn_id', 'root_action_number'):
            _int(getattr(self, name), 'hero attack ' + name, 1)
        _int(self.zone_epoch, 'hero attack zone epoch', 0)
        _int(self.player_id, 'hero attack player', 1)
        if self.player_id not in (1, 2) or self.record_id != self.window_id:
            raise ValueError('Invalid hero attack original identity')
        _name(self.hero_card_id, 'hero attack original card')


@dataclass(frozen=True)
class HeroAttackDeclarationFact:
    identity: HeroAttackIdentity
    action_number: int
    event_cursor: int

    def __post_init__(self):
        if type(self.identity) is not HeroAttackIdentity:
            raise ValueError('Expected exact hero attack identity')
        self.identity.__post_init__()
        _int(self.action_number, 'hero attack action', 1)
        _int(self.event_cursor, 'hero attack cursor', 0)


@dataclass(frozen=True)
class HeroAttackDeliveryReceipt(HeroAttackDeclarationFact):
    target_id: int
    forced: bool = False
    combat_relation: str = 'opponent'

    def __post_init__(self):
        super().__post_init__()
        _int(self.target_id, 'hero attack delivery target', 1)
        if type(self.forced) is not bool or self.forced or self.combat_relation != 'opponent':
            raise ValueError('Only voluntary opponent hero attacks are supported')


@dataclass(frozen=True)
class HeroAttackReference:
    identity: HeroAttackIdentity
    delivery: HeroAttackDeliveryReceipt

    def __post_init__(self):
        if type(self.identity) is not HeroAttackIdentity or type(self.delivery) is not HeroAttackDeliveryReceipt:
            raise ValueError('Expected exact hero attack delivery reference')
        self.identity.__post_init__(); self.delivery.__post_init__()
        if self.delivery.identity != self.identity:
            raise ValueError('Hero attack delivery reference identity mismatch')


@dataclass(frozen=True)
class HeroAttackCombatFact(HeroAttackDeclarationFact):
    delivery: HeroAttackDeliveryReceipt
    attacker_controller: int
    attacker_card_id: str
    defender_id: int
    defender_controller: int
    defender_card_id: str
    weapon_id: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if type(self.delivery) is not HeroAttackDeliveryReceipt or self.delivery.identity != self.identity:
            raise ValueError('Hero combat has a foreign delivery identity')
        self.delivery.__post_init__()
        for name in ('attacker_controller', 'defender_controller'):
            _int(getattr(self,name), 'hero combat controller', 1)
            if getattr(self,name) not in (1,2): raise ValueError('Invalid hero combat controller')
        _int(self.defender_id, 'hero combat defender', 1)
        _name(self.attacker_card_id, 'accepted hero face'); _name(self.defender_card_id, 'accepted defender face')
        if self.weapon_id is not None: _int(self.weapon_id, 'hero combat weapon', 1)


@dataclass(frozen=True)
class HeroAttackTerminalFact(HeroAttackDeclarationFact):
    outcome: str
    reason: str
    stage: str

    def __post_init__(self):
        super().__post_init__()
        reasons = {'completed': ('intrinsic_finish',),
                   'cancelled': ('combatant_left_play', 'combatants_became_friendly', 'attacker_frozen'),
                   'interrupted': ('game_terminal',)}
        if self.outcome not in reasons or self.reason not in reasons[self.outcome]:
            raise ValueError('Unknown hero attack terminal outcome/reason')
        if self.stage not in ('declared', 'delivery_pending', 'combat_accepted'):
            raise ValueError('Unknown hero attack terminal stage')


@dataclass(frozen=True)
class HeroAttackRecord:
    wear_acceptance: WeaponWearInputs | None = field(default=None,kw_only=True)
    wear_receipt: WeaponWearReceipt | None = field(default=None,kw_only=True)
    declaration: HeroAttackDeclarationFact
    delivery: HeroAttackDeliveryReceipt | None = None
    combat: HeroAttackCombatFact | None = None
    terminal: HeroAttackTerminalFact | None = None
    origin: str = 'voluntary'

    def __post_init__(self):
        if type(self.declaration) is not HeroAttackDeclarationFact or self.origin != 'voluntary':
            raise ValueError('Unsupported hero attack record origin/declaration')
        self.declaration.__post_init__()
        for name, kind in (('delivery', HeroAttackDeliveryReceipt), ('combat', HeroAttackCombatFact),
                           ('terminal', HeroAttackTerminalFact)):
            value = getattr(self,name)
            if value is not None:
                if type(value) is not kind or value.identity != self.declaration.identity:
                    raise ValueError('Foreign hero attack phase identity')
                value.__post_init__()
        if self.wear_acceptance is not None:
            if type(self.wear_acceptance)is not WeaponWearInputs:raise ValueError('Expected original wear inputs')
            self.wear_acceptance.__post_init__()
        if self.wear_receipt is not None:
            if type(self.wear_receipt)is not WeaponWearReceipt or self.wear_acceptance is None:raise ValueError('Expected original wear receipt')
            self.wear_receipt.__post_init__()
        if self.combat is not None and (self.delivery is None or self.combat.delivery != self.delivery):
            raise ValueError('Hero attack combat has no original delivery')
        if self.terminal is not None:
            t = self.terminal
            if t.outcome == 'completed' and (self.combat is None or t.stage != 'combat_accepted'):
                raise ValueError('Hero completion requires original accepted combat')
            if t.outcome == 'cancelled' and (self.delivery is None or self.combat is not None or t.stage != 'delivery_pending'):
                raise ValueError('Hero cancellation requires pending original delivery')
            if t.outcome == 'interrupted' and (self.combat is not None or t.stage != ('declared' if self.delivery is None else 'delivery_pending')):
                raise ValueError('Invalid hero attack interruption stage')


@dataclass(frozen=True)
class HeroAttackQuery:
    phase: str = 'completed'
    origins: tuple[str, ...] = ('voluntary',)
    window: str = 'match'

    def __post_init__(self):
        if self.phase not in ('declared', 'combat_accepted', 'completed', 'cancelled', 'interrupted'):
            raise ValueError('Unsupported hero attack query phase')
        if type(self.origins) is not tuple or self.origins != ('voluntary',):
            raise ValueError('Unsupported hero attack query origin')
        if self.window not in ('match', 'owner_turn', 'actual_interval'):
            raise ValueError('Unsupported hero attack query window')


def _empty_whole_card_replay_ledger():
    from .whole_card_replay_state import empty_ledger
    return empty_ledger()


@dataclass(frozen=True)
class TurnSchedule:
    """Finite queued turns, the suspended natural successor, and skipped slots."""

    pending: tuple[int, ...] = ()
    resume_player_id: int | None = None
    skip_counts: tuple[int, int] = (0, 0)

    def __post_init__(self):
        if type(self.pending) is not tuple or any(type(p) is not int or p not in (1, 2) for p in self.pending):
            raise ValueError('Queued turns require an immutable tuple of player IDs')
        if self.resume_player_id is not None and (type(self.resume_player_id) is not int or self.resume_player_id not in (1, 2)):
            raise ValueError('Invalid natural turn successor')
        if self.pending and self.resume_player_id is None:
            raise ValueError('Queued turns require a natural successor')
        if type(self.skip_counts) is not tuple or len(self.skip_counts) != 2:
            raise ValueError('Skipped turns require two immutable counters')
        for count in self.skip_counts:
            _int(count, 'skipped turn count', 0)


@dataclass
class GameState:
    players: dict[int, PlayerState]
    entities: dict[int, Entity]
    active_player: int = 1
    board_id: int | None = None
    turn: int = 1
    turn_schedule: TurnSchedule = field(default_factory=TurnSchedule)
    next_entity_id: int = 1
    next_order: int = 1
    status: str = "playing"
    winner: int | None = None
    action_number: int = 0
    next_attachment_id: int = 1
    next_death_id: int = 1
    next_death_batch: int = 1
    death_history: list[DeathRecord] = field(default_factory=list)
    next_overload_id: int = 1
    overload_history: list[OverloadRecord] = field(default_factory=list)
    next_hero_health_change_id: int = 1
    hero_health_change_history: list[HeroHealthChangeRecord] = field(default_factory=list)
    next_healing_id: int = 1
    healing_history: list[HealingRecord] = field(default_factory=list)
    next_damage_id: int = 1
    damage_history: list[DamageRecord] = field(default_factory=list)
    deathrattle_history: list[DeathrattleRecord] = field(default_factory=list)
    deathrattle_batches: list[DeathrattleBatch] = field(default_factory=list)
    next_deathrattle_id: int = 1
    resurrection_history: list[ResurrectionRecord] = field(default_factory=list)
    next_choice_id: int = 1
    pending_choice: PendingChoice | None = None
    opening: OpeningState | None = None
    starship_history: list[StarshipLaunchRecord] = field(default_factory=list)
    next_resource_operation_id: int = 1
    resource_operations: list = field(default_factory=list)
    corpse_spend_history: list[CorpseSpendRecord] = field(default_factory=list)
    mana_consumption_history: list[ManaConsumptionRecord] = field(default_factory=list)
    next_card_summon_id: int = 1
    card_summon_history: list = field(default_factory=list)
    next_successful_summon_id: int = 1
    successful_summon_history: list = field(default_factory=list)
    next_pool_summon_id: int = 1
    pool_summon_history: list = field(default_factory=list)
    next_ordered_group_id: int = 1
    ordered_group_history: list = field(default_factory=list)
    next_discovery_summon_id: int = 1
    discovery_summon_history: list = field(default_factory=list)
    hand_choice_followups: list = field(default_factory=list)
    temporary_hands: list = field(default_factory=list)
    hand_deadlines: list = field(default_factory=list)
    interactable_history: list = field(default_factory=list)
    next_recruit_summon_id: int = 1
    recruit_summon_history: list = field(default_factory=list)
    next_resurrection_summon_id: int = 1
    resurrection_summon_history: list = field(default_factory=list)
    resurrection_quantity_bodies: list = field(default_factory=list)
    next_split_damage_root_id: int = 1
    split_damage_history: list = field(default_factory=list)
    next_hero_lethal_id: int = 1
    hero_lethal_roots: list = field(default_factory=list)
    hero_lethal_history: list = field(default_factory=list)
    active_hero_lethal_root_id: int | None = None
    next_window_id: int = 1
    action_windows: list[ActionWindow] = field(default_factory=list)
    hero_attack_history: list[HeroAttackRecord] = field(default_factory=list)
    character_attack_history: list[CharacterAttackRecord] = field(default_factory=list)
    play_history: list[PlayRecord] = field(default_factory=list)
    owner_turn_history: list[OwnerTurnRecord] = field(default_factory=list)
    cost_use_history: list[CostUseReceipt] = field(default_factory=list)
    kindred_history: list[KindredRecord] = field(default_factory=list)
    cast_history: list[SpellCastRecord] = field(default_factory=list)
    hero_power_history: list[HeroPowerRecord] = field(default_factory=list)
    hero_power_payload_batches: list[HeroPowerPayloadBatch] = field(default_factory=list)
    hero_power_payload_history: list[HeroPowerPayloadRecord] = field(default_factory=list)
    battlecry_batches: list[BattlecryBatchRecord] = field(default_factory=list)
    battlecry_history: list[BattlecryRecord] = field(default_factory=list)
    indirect_body_sequences: list[object] = field(default_factory=list)
    historical_body_invocations: list[object] = field(default_factory=list)
    combo_history: list[ComboRecord] = field(default_factory=list)
    combo_batches: list[ComboBatchRecord] = field(default_factory=list)
    combo_policy_receipts: list[ComboPolicyReceipt] = field(default_factory=list)
    spell_policy_receipts: list[SpellPolicyReceipt] = field(default_factory=list)
    draw_history: list[DrawRecord] = field(default_factory=list)
    hand_entries: list[HandEntryRecord] = field(default_factory=list)
    deck_shuffle_history: list = field(default_factory=list)
    discard_history: list = field(default_factory=list)
    next_discard_id: int = 1
    magnetic_history: list[MagneticRecord] = field(default_factory=list)
    colossal_history: list[ColossalRecord] = field(default_factory=list)
    herald_history: list[HeraldRecord] = field(default_factory=list)
    excavation_history: list[ExcavationRecord] = field(default_factory=list)
    imbue_history: list[ImbueRecord] = field(default_factory=list)
    invoke_history: list[InvokeRecord] = field(default_factory=list)
    jade_history: list[JadeGolemRecord] = field(default_factory=list)
    cthun_history: list[CthunGrowthRecord] = field(default_factory=list)
    galakrond_mains: dict[int, GalakrondMain | None] = field(default_factory=lambda: {1: None, 2: None})
    spell_repeats: list[SpellRepeatRecord] = field(default_factory=list)
    rewind_outcomes: list[RewindOutcomeRecord] = field(default_factory=list)
    end_turn_batches: list[EndTurnBatch] = field(default_factory=list)
    end_turn_history: list[EndTurnRecord] = field(default_factory=list)
    # Concrete immutable WholeCardReplayLedger; module-owned validation avoids import cycles.
    whole_card_replay_ledger: object = field(default_factory=_empty_whole_card_replay_ledger)
    choose_policy_receipts: list = field(default_factory=list)
    # Actual family uses across independent paid and generated acceptances.
    battlecry_policy_uses: list = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    sequence: int
    action: int
    kind: str
    source_id: int | None = None
    target_id: int | None = None
    player_id: int | None = None
    amount: int = 0
    data: tuple[tuple[str, object], ...] = ()


def _int(value: object, name: str, minimum: int | None = None) -> None:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise ValueError(f"{name} must be an integer{suffix}")


def _optional_id(value: object, name: str) -> None:
    if value is not None:
        _int(value, name, 1)


def _spell_damage_school_selector(value):
    if (type(value) is not tuple or any(type(s) is not SpellSchool for s in value) or
            len(set(value)) != len(value)):
        raise ValueError('Spell damage schools require a unique immutable SpellSchool tuple')


def _bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be boolean")


def _name(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def _tribe_changes(values):
    if (type(values) is not tuple or any(type(c) is not Enchantment or c.tribe_change is None for c in values)):
        raise ValueError('Tribe changes require complete immutable identity enchantments')
    for change in values:
        change.__post_init__()
    ids = [c.id for c in values]
    if ids != sorted(set(ids)):
        raise ValueError('Tribe changes require unique acquisition order')


def _components(values):
    if type(values) is not tuple:
        raise ValueError('Starship components must be an immutable tuple')
    for value in values:
        _name(value, 'component card ID')


def validate_invariants(state: GameState, registry: Registry) -> None:
    """Raise ValueError for structural corruption, even during effect resolution.

    This deliberately does not require board entities to be alive: the engine
    owns death-processing boundaries.  Zone membership follows the controller;
    ownership can differ after a future control-changing effect.
    """

    if not isinstance(state, GameState):
        raise ValueError("state must be a GameState")
    if not isinstance(state.players, dict) or set(state.players) != {1, 2}:
        raise ValueError("a match must have exactly players 1 and 2")
    if any(type(key) is not int for key in state.players):
        raise ValueError("player IDs must be integers")
    if not isinstance(state.entities, dict):
        raise ValueError("entities must be a dictionary")
    _int(state.active_player, "active_player")
    if state.active_player not in state.players:
        raise ValueError("active_player must identify a player")
    _int(state.turn, "turn", 1)
    from .game_boards import validate_board_id
    validate_board_id(state.board_id)
    if type(state.turn_schedule) is not TurnSchedule:
        raise ValueError('Expected exact turn schedule')
    state.turn_schedule.__post_init__()
    _int(state.next_entity_id, "next_entity_id", 1)
    _int(state.next_order, "next_order", 1)
    _int(state.next_choice_id, 'next_choice_id', 1)
    _int(state.next_window_id, 'next_window_id', 1)
    from .overload_history import validate_state as validate_overload_state
    validate_overload_state(state)
    from .hero_health_history import validate_state as validate_hero_health_changes
    validate_hero_health_changes(state, registry)
    from .healing_history import validate_state as validate_healing_history
    validate_healing_history(state, registry)
    from .damage_history import validate_state as validate_damage_history
    validate_damage_history(state, registry)
    from .deck_shuffles import validate_state as validate_shuffle_state
    validate_shuffle_state(state, registry)
    from .discard_history import validate_state as validate_discard_state
    validate_discard_state(state, registry)
    from .successful_summons import validate_state as validate_successful_summons
    validate_successful_summons(state, registry)
    from .resource_operations import validate_state as validate_resource_operations
    validate_resource_operations(state, registry)
    from .resources import validate_corpse_spend_history
    validate_corpse_spend_history(state, registry)
    from .resources import validate_mana_consumption_history
    validate_mana_consumption_history(state, registry)
    from .random_split_damage import validate_state as validate_split_damage_state
    validate_split_damage_state(state, registry)
    from .hero_lethal_windows import validate_state as validate_hero_lethal_state
    validate_hero_lethal_state(state, registry)
    if type(state.action_windows) is not list or any(type(w) is not ActionWindow for w in state.action_windows):
        raise ValueError('Invalid action window stack')
    previous_window = 0
    for window in state.action_windows:
        window.__post_init__()
        from .limited_triggers import validate_candidates
        validate_candidates(state,window.spellburst_candidates,window.player_id)
        if (not previous_window < window.id < state.next_window_id or window.source_id not in state.entities or
                (window.target_id is not None and window.target_id not in state.entities)):
            raise ValueError('Invalid action window order or entity reference')
        if window.kind == 'spell' and registry.card(state.entities[window.source_id].card_id).kind != CardType.SPELL:
            raise ValueError('Spell window requires a spell source')
        if window.kind == 'minion' and (state.entities[window.source_id].kind != CardType.MINION or state.entities[window.source_id].zone != Zone.PLAY):
            raise ValueError('Minion window requires a pending minion source')
        if window.kind == 'attack':
            if not all(state.entities[i].is_character for i in (window.source_id, window.target_id)):
                raise ValueError('Attack window requires characters')
            minion_source = state.entities[window.source_id].kind == CardType.MINION
            if minion_source != (window.attack_source_presence is not None):
                raise ValueError('Minion attack window requires its original board presence')
            if window.attack_source_presence is not None and window.attack_source_presence.presence_id >= state.next_order:
                raise ValueError('Attack source presence has not been allocated')
        previous_window = window.id
    if state.pending_choice is not None:
        if not isinstance(state.pending_choice, PendingChoice):
            raise ValueError('pending_choice must be PendingChoice or None')
        state.pending_choice.__post_init__()
        if state.status != 'playing' or state.pending_choice.id >= state.next_choice_id:
            raise ValueError('Invalid pending choice state/counter')
        for item in state.pending_choice.options:
            if item.card_id is not None:
                registry.card(item.card_id)
            if item.entity_id is not None and item.entity_id not in state.entities:
                raise ValueError('Choice refers to a missing entity')
        if state.pending_choice.source_id is not None and state.pending_choice.source_id not in state.entities:
            raise ValueError('Choice source does not exist')
        if state.pending_choice.purpose == ChoicePurpose.MULLIGAN and (
                type(state.opening) is not OpeningState or state.opening.stage != 'mulligan'):
            raise ValueError('A mulligan choice requires the mulligan opening phase')
    if state.opening is not None:
        if type(state.opening) is not OpeningState:
            raise ValueError('opening must be OpeningState or None')
        state.opening.__post_init__()
        all_original = [i for group in state.opening.original_entities for i in group]
        if len(set(all_original)) != len(all_original):
            raise ValueError('Original deck entity identities must be distinct')
        for player_id, group in enumerate(state.opening.original_entities, 1):
            for entity_id in group:
                if entity_id not in state.entities or state.entities[entity_id].owner != player_id:
                    raise ValueError('Original deck entity has wrong owner or is missing')
        if any(entity_id not in state.entities for group in state.opening.offered for entity_id in group):
            raise ValueError('An offered opening entity is missing')
    for name in ("next_attachment_id", "next_death_id", "next_death_batch", "next_deathrattle_id"):
        _int(getattr(state, name), name, 1)
    _int(state.action_number, "action_number", 0)
    if state.status not in {"playing", "finished", "draw"}:
        raise ValueError("status must be playing, finished, or draw")
    if state.status == "finished" and state.winner is None:
        raise ValueError("a finished match must name a winning player")
    if state.winner is not None:
        _int(state.winner, "winner")
        if state.winner not in state.players or state.status != "finished":
            raise ValueError("only a finished match may name a winning player")

    locations: dict[int, tuple[int, Zone]] = {}

    def locate(entity_id: int, player_id: int, zone: Zone) -> None:
        _int(entity_id, f"{zone} entity ID", 1)
        if entity_id in locations:
            raise ValueError(f"entity {entity_id} occurs in more than one zone slot")
        entity = state.entities.get(entity_id)
        if entity is None:
            raise ValueError(f"zone {zone} references missing entity {entity_id}")
        if not isinstance(entity, Entity):
            raise ValueError(f"entity {entity_id} must be an Entity")
        if entity.zone != zone or entity.controller != player_id:
            raise ValueError(f"entity {entity_id} disagrees with its zone/controller")
        definition = registry.card(entity.card_id)
        if definition.choice_only:
            raise ValueError('Choice-only definitions cannot have physical entities')
        kind = definition.kind
        if zone == Zone.HERO and kind != CardType.HERO:
            raise ValueError(f"hero slot {entity_id} must contain a hero")
        if (zone == Zone.HERO and entity.entered_order < 1 and
                any(a.kind == 'trigger' for a in entity.abilities)):
            raise ValueError('Hero trigger carriers require their actual installation order')
        if kind == CardType.HERO and zone not in (Zone.HERO, Zone.GRAVEYARD) and not (
                definition.hero_card and zone in (Zone.HAND, Zone.DECK, Zone.SETASIDE)):
            raise ValueError(f"hero entity {entity_id} must remain in its hero slot")
        if zone == Zone.PLAY and kind != CardType.MINION:
            raise ValueError("Only pending minions use the play zone")
        if zone == Zone.BOARD and kind not in (CardType.MINION, CardType.LOCATION):
            raise ValueError(f"board entity {entity_id} must be a minion or location")
        for special, expected in ((Zone.WEAPON, CardType.WEAPON), (Zone.HERO_POWER, CardType.HERO_POWER)):
            if zone == special and kind != expected:
                raise ValueError(f'{special} slot requires {expected}')
        if kind == CardType.HERO_POWER and zone not in (Zone.HERO_POWER, Zone.GRAVEYARD):
            raise ValueError('Hero powers cannot enter normal card zones')
        if kind == CardType.HERO_POWER and state.entities[entity_id].entered_order < 1:
            raise ValueError('Hero powers require an installation order')
        locations[entity_id] = (player_id, zone)

    for player_id, player in state.players.items():
        if not isinstance(player, PlayerState) or type(player.id) is not int or player.id != player_id:
            raise ValueError(f"player key {player_id} disagrees with player state")
        if player.hero_class is not None and (not isinstance(player.hero_class, CardClass)or player.hero_class==CardClass.DREAM):
            raise ValueError('Invalid current hero class')
        if player.deck_class is not None and (not isinstance(player.deck_class, CardClass) or player.deck_class not in PLAYABLE_CARD_CLASSES):
            raise ValueError('Invalid starting deck class')
        if player.runes is not None:
            from .tourists import requires_runes
            if type(player.runes) is not Runes or not requires_runes(player.deck_class, player.original_deck, registry):
                raise ValueError('Rune loadout needs original Death Knight construction access')
            player.runes.__post_init__()
        if not isinstance(player.original_deck, tuple):
            raise ValueError('Original deck must be an immutable tuple')
        for card_id in player.original_deck:
            registry.card(card_id)
        from .sideboards import validate_player as validate_sideboard_player
        validate_sideboard_player(player, registry)
        from .void_decks import validate_player as validate_void_player
        validate_void_player(state, player, registry)
        for name in ("max_mana", "mana", "fatigue", "hero_power_uses_this_turn", "mana_cap",
                     "mana_spent", "temporary_mana", "overload_owed", "overload_locked"):
            _int(getattr(player, name), f"player {player_id} {name}", 0)
        if (not isinstance(player.resources, dict) or set(player.resources) != set(Resource) or
                any(not isinstance(k, Resource) for k in player.resources)):
            raise ValueError('Player resources must use exactly the known Resource keys')
        for amount in player.resources.values():
            _int(amount, 'resource amount', 0)
        locate(player.hero_id, player_id, Zone.HERO)
        hero_definition = registry.card(state.entities[player.hero_id].card_id)
        if not hero_definition.keep_hero_class:
            classes = hero_definition.metadata.classes if hero_definition.metadata is not None else ()
            expected_class = classes[0] if len(classes) == 1 else None
            if player.hero_class != expected_class:
                raise ValueError('Current hero class disagrees with its definition')
        for field, zone in (('weapon_id', Zone.WEAPON), ('hero_power_id', Zone.HERO_POWER)):
            _optional_id(getattr(player, field), field)
            if getattr(player, field) is not None:
                locate(getattr(player, field), player_id, zone)
        for name, zone in (("deck", Zone.DECK), ("hand", Zone.HAND),
                           ("board", Zone.BOARD), ("graveyard", Zone.GRAVEYARD), ("setaside", Zone.SETASIDE), ("pending_plays", Zone.PLAY), ("quests", Zone.QUEST), ("secrets", Zone.SECRET),
                           ("additional_hero_power_ids", Zone.HERO_POWER)):
            members = getattr(player, name)
            if not isinstance(members, list):
                raise ValueError(f"player {player_id} {name} must be a list")
            for entity_id in members:
                locate(entity_id, player_id, zone)
        if sum(state.entities[i].starship_building for i in player.board) > 1:
            raise ValueError('A player may build only one Starship at a time')

    current_attachment_ids: set[int] = set()
    all_attachment_ids: set[int] = set()
    occupied_orders = {e.entered_order for e in state.entities.values() if e.entered_order > 0}
    current_board_presence_ids: set[int] = set()

    def validate_attachment(attachment: AbilityInstance | Enchantment | CostModifier) -> None:
        attachment.__post_init__()
        if isinstance(attachment, (Enchantment, AbilityInstance)) and attachment.cthun_ritual is not None:
            from .cthun import validate_stamp
            validate_stamp(state, registry, attachment)
        if isinstance(attachment, AbilityInstance):
            from .printed_attack_permits import validate_attachment as validate_printed_permit_attachment
            validate_printed_permit_attachment(state, registry, attachment)
        if isinstance(attachment, AbilityInstance) and attachment.attack_source_binding is not None:
            from .board_presence import validate_attack_source_binding
            validate_attack_source_binding(state, attachment.attack_source_binding)
        if isinstance(attachment, AbilityInstance) and attachment.spell_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.spell_repeat,
                                        allow_source=attachment.kind == 'spell_repeat')
            from .repeat_matching import validate_repeat_cost_declaration
            validate_repeat_cost_declaration(registry, attachment.spell_repeat)
        if isinstance(attachment, AbilityInstance) and attachment.battlecry_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.battlecry_repeat)
        if isinstance(attachment, AbilityInstance) and attachment.combo_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.combo_repeat)
        if isinstance(attachment, AbilityInstance) and attachment.deathrattle_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.deathrattle_repeat)
        if isinstance(attachment, AbilityInstance) and attachment.hero_power_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.hero_power_repeat)
        if isinstance(attachment, AbilityInstance) and attachment.end_turn_repeat is not None:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.end_turn_repeat)
        if type(attachment) is BattlecryRepeatModifier:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.spec, allow_source=False)
        if type(attachment) is ComboRepeatModifier:
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(registry, attachment.spec, allow_source=False)
        if isinstance(attachment,AbilityInstance):
            from .deathrattles import validate_ability as validate_deathrattle_ability
            validate_deathrattle_ability(state,registry,attachment)
        if isinstance(attachment,(AbilityInstance,Enchantment)) and attachment.magnetic_id is not None:
            if attachment.magnetic_id > len(state.magnetic_history):
                raise ValueError('Unknown magnetic attachment group')
            if not attachment.remove_on_silence or (isinstance(attachment, AbilityInstance) and attachment.origin!='granted'):
                raise ValueError('Magnetic attachments must be removable grants')
            if isinstance(attachment, AbilityInstance):
                from .magnetic import transferable_ability
                if not transferable_ability(attachment):
                    raise ValueError('Magnetic attachment cannot contain an entry-only ability')
            record = state.magnetic_history[attachment.magnetic_id - 1]
            if type(record) is not MagneticRecord or attachment.source_id != record.source_id:
                raise ValueError('Magnetic attachment has the wrong source')
            if isinstance(attachment, Enchantment) and (
                    attachment.attack != record.attack or attachment.health != record.health or
                    attachment.expires_turn is not None or attachment.label != 'magnetic'):
                raise ValueError('Magnetic numeric attachment disagrees with its frozen contribution')
        if attachment.source_id is not None and attachment.source_id not in state.entities:
            raise ValueError(f"attachment {attachment.id} refers to a missing source")
        if isinstance(attachment, AbilityInstance) and attachment.behavior_id is not None:
            registry.behavior(attachment.behavior_id)
            if attachment.kind == 'combo' and registry.card(attachment.combo_card_id).combo != attachment.behavior_id:
                raise ValueError('Combo ability differs from its declaration card')
            if attachment.kind == 'battlecry' and registry.card(attachment.battlecry_card_id).battlecry != attachment.behavior_id:
                raise ValueError('Battlecry ability differs from its declaration card')
        if isinstance(attachment, AbilityInstance) and attachment.activation is not None:
            registry.validate_activation(attachment.activation)
        if isinstance(attachment, AbilityInstance) and attachment.limited_trigger is not None:
            registry.validate_limited_trigger(attachment.limited_trigger)
        if isinstance(attachment, AbilityInstance) and attachment.hand_progress is not None:
            registry.validate_hand_progress(attachment.hand_progress)
            from .held_spells import validate_ability as validate_held_spell_ability
            validate_held_spell_ability(state,registry,attachment)
            from .hand_progress import validate_cast_progress
            validate_cast_progress(state, attachment)
            for key in attachment.progress_keys:
                prefix, number = key.split(':'); number = int(number)
                if prefix == 'play' and number > len(state.play_history) or prefix == 'death' and number >= state.next_death_id:
                    raise ValueError('Progress references a missing play or death')
        all_attachment_ids.add(attachment.id)

    from .choose_policies import ChooseBothModifier
    for player in state.players.values():
        if type(player.choose_both_modifiers) is not list or any(type(m) is not ChooseBothModifier for m in player.choose_both_modifiers):
            raise ValueError('Player Choose Both policies require exact modifier instances')
        for modifier in player.choose_both_modifiers:
            validate_attachment(modifier)
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            if modifier.player_id != player.id or modifier.created_turn > state.turn or modifier.id in current_attachment_ids:
                raise ValueError('Invalid Choose Both policy owner, creation or duplicate identity')
            current_attachment_ids.add(modifier.id)
        if any(a.id >= b.id for a, b in zip(player.choose_both_modifiers, player.choose_both_modifiers[1:])):
            raise ValueError('Choose Both policies require acquisition order')
        if type(player.spell_modifiers) is not list or any(type(m) is not SpellRepeatModifier for m in player.spell_modifiers):
            raise ValueError('Player Spell modifiers must contain modifier instances')
        for modifier in player.spell_modifiers:
            from .repeat_matching import validate_repeat_cost_declaration
            validate_repeat_cost_declaration(registry, modifier.spec)
            validate_attachment(modifier)
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            if modifier.created_turn > state.turn or modifier.id in current_attachment_ids:
                raise ValueError('Invalid Spell modifier creation or duplicate ID')
            current_attachment_ids.add(modifier.id)
        if any(a.id >= b.id for a,b in zip(player.spell_modifiers,player.spell_modifiers[1:])):
            raise ValueError('Spell modifiers must preserve acquisition order')
        if type(player.battlecry_modifiers) is not list or any(type(m) is not BattlecryRepeatModifier for m in player.battlecry_modifiers):
            raise ValueError('Player Battlecry modifiers must contain modifier instances')
        for modifier in player.battlecry_modifiers:
            validate_attachment(modifier)
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            if modifier.created_turn > state.turn or modifier.id in current_attachment_ids:
                raise ValueError('Invalid Battlecry modifier creation or duplicate ID')
            current_attachment_ids.add(modifier.id)
        if any(a.id >= b.id for a,b in zip(player.battlecry_modifiers,player.battlecry_modifiers[1:])):
            raise ValueError('Battlecry modifiers must preserve acquisition order')
        if type(player.combo_modifiers) is not list or any(type(m) is not ComboRepeatModifier for m in player.combo_modifiers):
            raise ValueError('Player Combo modifiers must contain modifier instances')
        for modifier in player.combo_modifiers:
            validate_attachment(modifier)
            if modifier.source_card_id is not None: registry.card(modifier.source_card_id)
            if modifier.created_turn > state.turn or modifier.id in current_attachment_ids:
                raise ValueError('Invalid Combo modifier creation or duplicate ID')
            current_attachment_ids.add(modifier.id)
        if any(a.id >= b.id for a,b in zip(player.combo_modifiers,player.combo_modifiers[1:])):
            raise ValueError('Combo modifiers must preserve acquisition order')
        if type(player.player_effects) is not list or any(type(e) is not PlayerEffect for e in player.player_effects):
            raise ValueError('Player effects must contain PlayerEffect instances')
        for effect in player.player_effects:
            effect.__post_init__()
            spec = registry.player_effect(effect.spec_id)
            spec.__post_init__()
            if spec.kind in ('turn_rule','next_spell_damage') and effect.created_turn != state.turn:
                raise ValueError('Current-turn target rule cannot survive into another actual turn')
            from .repeat_source_conditions import validate_source_declaration
            for repeat in spec.end_turn_repeats:
                validate_source_declaration(registry, repeat, allow_source=False)
            registry.card(effect.source_card_id)
            if (effect.source_id not in state.entities or effect.created_turn > state.turn or
                    effect.entered_order >= state.next_order or
                    (spec.duration is None) != (effect.remaining_turns is None) or
                    (spec.duration is not None and effect.remaining_turns > spec.duration)):
                raise ValueError('Invalid player effect source, order or countdown')
            if effect.source_allocation is not None:
                from .allocation_facts import allocation_from_payload,validate_allocation
                validate_allocation(state,registry,allocation_from_payload(effect.source_allocation))
                if effect.source_player_id!=player.id:raise ValueError('Captured player effect changed its original beneficiary')
            if effect.id in current_attachment_ids:
                raise ValueError('Duplicate player effect instance ID')
            if effect.entered_order in occupied_orders:
                raise ValueError('Duplicate player effect acquisition order')
            occupied_orders.add(effect.entered_order)
            current_attachment_ids.add(effect.id)
            all_attachment_ids.add(effect.id)
        if any(a.id >= b.id or a.entered_order >= b.entered_order
               for a, b in zip(player.player_effects, player.player_effects[1:])):
            raise ValueError('Player effects must preserve acquisition order')
        if not isinstance(player.cost_modifiers, list) or any(not isinstance(m, CostModifier) for m in player.cost_modifiers):
            raise ValueError('Player cost_modifiers must contain CostModifier instances')
        for modifier in player.cost_modifiers:
            validate_attachment(modifier)
            if modifier.id in current_attachment_ids:
                raise ValueError('Duplicate cost modifier ID')
            current_attachment_ids.add(modifier.id)
        if any(a.id >= b.id for a, b in zip(player.cost_modifiers, player.cost_modifiers[1:])):
            raise ValueError('Cost modifiers must preserve acquisition order')

    for entity_id, entity in state.entities.items():
        _int(entity_id, "entity dictionary key", 1)
        if not isinstance(entity, Entity) or type(entity.id) is not int or entity.id != entity_id:
            raise ValueError(f"entity key {entity_id} disagrees with entity state")
        if entity_id not in locations:
            raise ValueError(f"entity {entity_id} is absent from all zone slots")
        for name in ("owner", "controller"):
            value = getattr(entity, name)
            _int(value, f"entity {entity_id} {name}")
            if value not in state.players:
                raise ValueError(f"entity {entity_id} has an invalid {name}")
        if not isinstance(entity.zone, Zone):
            raise ValueError(f"entity {entity_id} must use a Zone enum")
        validate_composition(entity, registry)
        if entity.choose_branch is not None:
            from .choose_branch_state import validate_selection
            validate_selection(registry, entity.choose_branch, card_id=entity.card_id)
        if type(entity.kind) is not CardType or entity.kind != registry.card(entity.card_id).kind:
            raise ValueError('Entity type disagrees with its definition')
        if (entity.zone == Zone.SECRET) != (entity.secret_instance_id is not None):
            raise ValueError('Secret instance belongs only to secret zone')
        if entity.secret_instance_id is not None:
            _int(entity.secret_instance_id, 'secret instance', 1)
            if registry.card(entity.card_id).secret is None or entity.secret_instance_id in current_attachment_ids:
                raise ValueError('Invalid or duplicate secret instance')
            current_attachment_ids.add(entity.secret_instance_id)
            all_attachment_ids.add(entity.secret_instance_id)
        if (entity.zone == Zone.QUEST) != (entity.quest_progress is not None):
            raise ValueError('Quest progress belongs only to the quest zone')
        if entity.quest_progress is not None:
            progress, spec = entity.quest_progress, registry.card(entity.card_id).quest
            if type(progress) is not QuestProgress or spec is None:
                raise ValueError('Invalid quest progress or definition')
            progress.__post_init__()
            if progress.stage >= len(spec.stages):
                raise ValueError('Invalid quest stage')
            goal = spec.stages[progress.stage].goal
            if progress.value > goal or progress.completing != (progress.value == goal) or len(progress.keys) > progress.value:
                raise ValueError('Invalid quest progress total')
            if progress.id in current_attachment_ids:
                raise ValueError('Duplicate quest instance ID')
            current_attachment_ids.add(progress.id)
            all_attachment_ids.add(progress.id)
        _int(entity.location_cooldown, 'location_cooldown', 0)
        if entity.kind != CardType.LOCATION and entity.location_cooldown:
            raise ValueError('Only locations have a location cooldown')
        if entity.kind == CardType.LOCATION and (entity.base_attack or entity.base_health or entity.damage or
                entity.armor or entity.attack_bonus or entity.health_bonus or entity.aura_attack or entity.aura_health or
                entity.frozen or entity.keywords or entity.weapon_attack or entity.attacks_this_turn or entity.silenced):
            raise ValueError('Locations cannot have character combat state')
        permanent_dormancy = registry.card(entity.card_id).permanent_dormancy
        if (entity.zone == Zone.BOARD and permanent_dormancy and
                entity.dormancy is None):
            raise ValueError('Permanent board carrier requires its dormant lifecycle')
        if entity.dormancy is not None:
            if type(entity.dormancy) is not DormancyState:
                raise ValueError('Invalid dormancy state')
            entity.dormancy.__post_init__()
            if entity.dormancy.permanent != permanent_dormancy:
                raise ValueError('Dormancy permanence disagrees with its definition')
            if (entity.kind != CardType.MINION or entity.zone != Zone.BOARD or entity.starship_building or
                    entity.dormancy.started_turn > state.turn or entity.keywords or entity.aura_attack or entity.aura_health):
                raise ValueError('Dormancy requires an inactive board minion')
            if entity.dormancy.id in current_attachment_ids:
                raise ValueError('Duplicate dormancy instance ID')
            current_attachment_ids.add(entity.dormancy.id)
            all_attachment_ids.add(entity.dormancy.id)
        _bool(entity.starship_building, 'starship_building')
        if entity.starship_building and (not entity.components or entity.zone != Zone.BOARD or
                entity.damage or entity.armor or entity.doomed or entity.silenced or entity.enchantments or
                entity.frozen or entity.attacks_this_turn or entity.aura_attack or entity.aura_health):
            raise ValueError('Invalid Starship construction state')
        for name in ("base_attack", "base_health", "base_cost", "damage", "armor",
                     "attacks_this_turn", "summoned_turn", "entered_order", "zone_epoch"):
            _int(getattr(entity, name), f"entity {entity_id} {name}", 0)
        _bool(entity.old_god_free_used, f"entity {entity_id} old_god_free_used")
        if entity.zone == Zone.BOARD and entity.kind == CardType.MINION:
            _int(entity.board_presence_id, 'board presence identity', 1)
            if entity.board_presence_id > entity.entered_order or entity.board_presence_id >= state.next_order:
                raise ValueError('Board presence identity exceeds its original entry allocation')
            if entity.board_presence_id in current_board_presence_ids:
                raise ValueError('Physical board residents must have distinct identities')
            current_board_presence_ids.add(entity.board_presence_id)
        elif entity.board_presence_id is not None:
            raise ValueError('Only a minion on the board carries a residence identity')
        for name in ("attack_bonus", "health_bonus", "cost_modifier", "aura_attack"):
            _int(getattr(entity, name), f"entity {entity_id} {name}")
        if type(entity.doomed) is not bool:
            raise ValueError(f"entity {entity_id} doomed must be boolean")
        from .death_causes import dying
        if dying(entity) and entity.death_cause is None:
            raise ValueError('Fatal entity requires its captured death cause')
        if entity.death_cause is not None:
            from .death_causes import dying, validate_in_state
            if type(entity.death_cause) is not DeathCause:
                raise ValueError('Invalid entity death cause')
            validate_in_state(state, registry, entity.death_cause)
            cause = entity.death_cause
            if (not dying(entity) or cause.target_id != entity.id or cause.target_card_id != entity.card_id
                    or cause.target_zone_epoch != entity.zone_epoch or cause.target_entered_order > entity.entered_order):
                raise ValueError('Entity death cause belongs to a different incarnation or rescued entity')
        if not isinstance(entity.keywords, set) or any(not isinstance(k, Keyword) for k in entity.keywords):
            raise ValueError(f"entity {entity_id} keywords must be a set of Keyword values")
        _bool(entity.silenced, f"entity {entity_id} silenced")
        _int(entity.aura_health, f"entity {entity_id} aura_health", 0)
        _int(entity.durability, 'durability')
        _int(entity.weapon_attack, 'weapon_attack', 0)
        _int(entity.uses_this_turn, 'uses_this_turn', 0)
        _int(entity.use_limit, 'use_limit', 1)
        _int(entity.corpse_value, 'corpse_value', 0)
        if registry.card(entity.card_id).kind != CardType.MINION and entity.corpse_value:
            raise ValueError('Only minions may produce corpses')
        if not isinstance(entity.weapon_keywords, set) or any(not isinstance(k, Keyword) for k in entity.weapon_keywords):
            raise ValueError('weapon_keywords must be a Keyword set')
        if not isinstance(entity.aura_keywords, set) or any(not isinstance(k, Keyword) for k in entity.aura_keywords):
            raise ValueError('aura_keywords must be a Keyword set')
        if not isinstance(entity.hand_aura_keywords, set) or any(not isinstance(k, Keyword) for k in entity.hand_aura_keywords):
            raise ValueError('hand_aura_keywords must be a Keyword set')
        if not isinstance(entity.conditional_keywords, set) or any(not isinstance(k, Keyword) for k in entity.conditional_keywords):
            raise ValueError('conditional_keywords must be a Keyword set')
        _int(entity.conditional_attack, 'conditional_attack', 0)
        if entity.kind not in (CardType.WEAPON, CardType.LOCATION) and entity.durability != 0:
            raise ValueError('Only weapons and locations have durability')
        if entity.kind not in (CardType.HERO_POWER, CardType.LOCATION) and (entity.uses_this_turn or entity.use_limit != 1):
            raise ValueError('Only hero powers and locations have usage state')
        _optional_id(entity.frozen_until_owner_turn, f"entity {entity_id} frozen_until_owner_turn")
        if (entity.active and entity.is_character and entity.zone in (Zone.BOARD, Zone.HERO) and
                entity.frozen and Keyword.CANT_BE_FROZEN in entity.keywords):
            raise ValueError("Freeze-protected character cannot retain a frozen deadline")
        _optional_id(entity.origin_entity_id, f"entity {entity_id} origin_entity_id")
        _bool(entity.face_replaced, f"entity {entity_id} face_replaced")
        if entity.origin_entity_id is not None and entity.origin_entity_id not in state.entities:
            raise ValueError(f"entity {entity_id} refers to a missing origin entity")
        for name, cls in (("abilities", AbilityInstance), ("enchantments", Enchantment)):
            attachments = getattr(entity, name)
            if not isinstance(attachments, list) or any(not isinstance(item, cls) for item in attachments):
                raise ValueError(f"entity {entity_id} {name} must be a list of {cls.__name__}")
            if name == 'abilities':
                from .discard_history import validate_carrier as validate_discard_carrier
                validate_discard_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .zones import validate_destroyed_carrier
                validate_destroyed_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .printed_attack_permits import validate_carrier
                validate_carrier(state, registry, entity.card_id, entity.kind, attachments)
                from .stat_relations import (validate_carrier as validate_stat_relation_carrier,
                                             conditional_attack)
                validate_stat_relation_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                if entity.conditional_attack != conditional_attack(state, entity, registry):
                    raise ValueError('Stale conditional self Attack in its captured state')
                from .keyword_auras import (validate_carrier as validate_conditional_keyword_carrier,
                                            conditional_keywords)
                validate_conditional_keyword_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .deathrattles import validate_prohibition_carrier
                validate_prohibition_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .hero_powers import validate_prohibition_carrier as validate_power_prohibition
                validate_power_prohibition(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .hero_powers import validate_use_aura_carrier
                validate_use_aura_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                if entity.conditional_keywords != conditional_keywords(state, entity):
                    raise ValueError('Stale conditional self keyword cache in its captured state')
                from .stat_auras import validate_carrier as validate_conditional_stat_aura_carrier
                validate_conditional_stat_aura_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .costs import validate_cost_aura_carrier
                validate_cost_aura_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .corpse_gains import validate_carrier as validate_corpse_gain_carrier
                validate_corpse_gain_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .turn_start_draws import validate_carrier as validate_turn_draw_carrier
                validate_turn_draw_carrier(registry,entity.card_id,entity.kind,attachments,entity.components)
                from .native_spell_values import validate_carrier as validate_native_spell_carrier
                validate_native_spell_carrier(state,registry,entity.card_id,entity.kind,attachments)
                from .health_rules import validate_school_spell_damage_carrier
                validate_school_spell_damage_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .native_conditions import validate_carrier as validate_native_condition_carrier
                validate_native_condition_carrier(registry,entity.card_id,entity.kind,attachments,entity.components)
                from .deathrattle_memory import validate_carrier as validate_deathrattle_memory_carrier
                validate_deathrattle_memory_carrier(state,registry,entity.card_id,entity.kind,attachments,entity.components)
                from .dormancy import validate_board_full_carrier
                validate_board_full_carrier(registry,entity.card_id,entity.kind,attachments)
                from .cleave import validate_carrier as validate_cleave_carrier
                validate_cleave_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .health_floors import validate_carrier as validate_floor_carrier
                validate_floor_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
                from .health_loss_floors import validate_carrier as validate_loss_floor_carrier
                validate_loss_floor_carrier(registry, entity.card_id, entity.kind, attachments, entity.components)
            for attachment in attachments:
                validate_attachment(attachment)
                if type(attachment) is Enchantment and attachment.hand_play_lock is not None:
                    from .hand_play_locks import validate_clock
                    validate_clock(state, attachment.hand_play_lock)
                if type(attachment) is Enchantment and attachment.tribe_change is not None and entity.kind != CardType.MINION:
                    raise ValueError('Current tribe change requires a minion carrier')
                if type(attachment) is Enchantment and attachment.control_return_player_id is not None:
                    if (entity.kind != CardType.MINION or entity.zone not in (Zone.BOARD, Zone.GRAVEYARD) or
                            attachment.expires_turn is not None and attachment.expires_turn > state.turn):
                        raise ValueError('Temporary control requires a resident or dead current-turn minion carrier')
                    if attachment.control_return_expiry is not None:
                        from .timed_keywords import validate_deadline
                        validate_deadline(state, attachment.control_return_expiry)
                if isinstance(attachment, AbilityInstance):
                    from .timed_keywords import validate_instance
                    validate_instance(state, entity, attachment)
                    if attachment.health_rule_expiry is not None:
                        from .timed_keywords import validate_deadline
                        if entity.kind!=CardType.HERO:raise ValueError('Owner health deadline requires a hero carrier')
                        validate_deadline(state,attachment.health_rule_expiry)
                elif attachment.owner_turn_expiry is not None:
                    from .timed_keywords import validate_deadline
                    if entity.kind not in (CardType.MINION, CardType.HERO):
                        raise ValueError('Numeric owner expiry requires an existing character buff carrier')
                    validate_deadline(state, attachment.owner_turn_expiry)
                if (isinstance(attachment, AbilityInstance) and attachment.kind == 'attack_policy' and
                        entity.kind not in (CardType.MINION, CardType.HERO, CardType.WEAPON)):
                    raise ValueError('Invalid attack policy carrier')
                if (isinstance(attachment, AbilityInstance) and attachment.kind == 'cost_aura' and
                        entity.kind not in (CardType.MINION, CardType.WEAPON, CardType.LOCATION)):
                    raise ValueError('Invalid cost aura carrier')
                if (isinstance(attachment,AbilityInstance) and attachment.end_turn_spec is not None and
                        entity.kind not in (CardType.MINION,CardType.WEAPON,CardType.LOCATION,CardType.HERO_POWER,CardType.HERO)):
                    raise ValueError('Invalid classified end-turn carrier')
                if (isinstance(attachment, AbilityInstance) and attachment.kind in ('spell_repeat','battlecry_repeat','combo_repeat','deathrattle_repeat','hero_power_repeat','end_turn_repeat') and
                        entity.kind != CardType.MINION):
                    raise ValueError('Invalid spell repeat aura carrier')
                if isinstance(attachment, AbilityInstance) and attachment.kind=='card_spell_repeat' and entity.kind!=CardType.SPELL:
                    raise ValueError('Invalid card spell repeat carrier')
                if (isinstance(attachment, AbilityInstance) and attachment.kind == 'rewind_retention' and
                        entity.kind != CardType.MINION):
                    raise ValueError('Invalid Rewind retention carrier')
                if (isinstance(attachment, AbilityInstance) and attachment.health_loss_replacement is not None and
                        entity.kind != CardType.MINION):
                    raise ValueError('Invalid health loss replacement carrier')
                if isinstance(attachment,AbilityInstance) and attachment.weapon_wear_policy is not None:
                    expected=CardType.WEAPON if attachment.weapon_wear_policy.profile.scope=='self_weapon'else CardType.MINION
                    if entity.kind!=expected:raise ValueError('Invalid wear policy physical carrier')
                    if attachment.weapon_wear_declaration is not None:
                        from .weapon_wear import declared_spec
                        if declared_spec(registry,attachment.weapon_wear_declaration)!=attachment.weapon_wear_policy:raise ValueError('Foreign declared wear row')
                if isinstance(attachment, AbilityInstance) and attachment.limited_trigger is not None:
                    from .limited_triggers import supports_carrier
                    if not supports_carrier(entity.kind,attachment.limited_trigger):
                        raise ValueError('Invalid finite trigger carrier')
                if isinstance(attachment, AbilityInstance) and attachment.counter_policy is not None and entity.kind != CardType.MINION:
                    raise ValueError('Counter policy requires a minion carrier')
                if isinstance(attachment, AbilityInstance) and attachment.reborn_policy is not None and entity.kind != CardType.MINION:
                    raise ValueError('Full-health Reborn requires a minion carrier')
                if isinstance(attachment, AbilityInstance) and attachment.reborn_policy is not None and attachment.origin == 'printed':
                    if (registry.card(entity.card_id).reborn_policy != attachment.reborn_policy or attachment.source_id != entity.id or
                            sum(a.kind=='keyword'and a.keyword==Keyword.REBORN and a.origin=='printed'and a.reborn_policy is not None for a in entity.abilities)>1):
                        raise ValueError('Native Reborn differs from its complete printed declaration')
                if isinstance(attachment, AbilityInstance) and entity.kind == CardType.SPELL and attachment.kind == 'spell_damage':
                    from .stored_spell_damage import validate_local_ability
                    validate_local_ability(attachment)
                if attachment.id in current_attachment_ids:
                    raise ValueError("current attachment IDs must be globally unique")
                current_attachment_ids.add(attachment.id)
            if name == "enchantments" and any(a.id >= b.id for a, b in zip(attachments, attachments[1:])):
                raise ValueError("enchantments must preserve acquisition order")
        activated = [a.activation.id for a in entity.abilities if a.kind == 'activated']
        progress = [a for a in entity.abilities if a.kind == 'hand_progress']
        if any(a.kind == 'limited_trigger' and a.limited_trigger.reset == 'turn' and
               a.trigger_turn != state.turn for a in entity.abilities):
            raise ValueError('Finite trigger budget differs from the actual current turn')
        if len(progress) > 1 or progress and entity.kind not in (CardType.MINION, CardType.SPELL, CardType.WEAPON):
            raise ValueError('Invalid hand progress carrier or duplicate instance')
        from .hand_mirrors import validate_entity as validate_hand_mirror_entity
        validate_hand_mirror_entity(state,registry,entity)
        defining = [a for a in entity.abilities if a.kind == 'defining_hand_source']
        if len(defining) > 1:
            raise ValueError('Duplicate native defining source on a physical card')
        for binding in defining:
            registry.validate_defining_hand_binding(entity, binding)
        if len(activated) != len(set(activated)):
            raise ValueError('Duplicate activated ability key on an entity')
        if any(a.kind == 'keyword' and a.keyword == Keyword.TITAN and not a.consumed for a in entity.abilities):
            if entity.kind != CardType.MINION or len(activated) != 3:
                raise ValueError('Titan requires three finite ability instances')
        if any(a.kind == 'keyword' and a.keyword == Keyword.OLD_GOD and not a.consumed for a in entity.abilities):
            if entity.kind != CardType.MINION or len(activated) != 4 or Keyword.TITAN in entity.keywords:
                raise ValueError('Old God requires four finite ability instances and its independent policy')
    if state.entities and state.next_entity_id <= max(state.entities):
        raise ValueError("next_entity_id must be greater than all existing entity IDs")
    if state.entities and state.next_order <= max(e.entered_order for e in state.entities.values()):
        raise ValueError("next_order must be greater than existing entered_order values")

    if not isinstance(state.death_history, list):
        raise ValueError("death_history must be a list")
    previous_record_id = previous_batch = 0
    batch_turns: dict[int, int] = {}
    batch_entities: set[tuple[int, int]] = set()
    for record in state.death_history:
        if not isinstance(record, DeathRecord):
            raise ValueError("death_history must contain DeathRecord values")
        record.__post_init__()
        from .death_causes import validate_in_state
        validate_in_state(state, registry, record.cause)
        validate_composition(record, registry)
        if record.entity_id not in state.entities:
            raise ValueError("death record refers to a missing entity")
        kind = registry.card(record.card_id).kind
        if kind not in {Zone.BOARD:(CardType.MINION,CardType.LOCATION),Zone.WEAPON:(CardType.WEAPON,),Zone.HERO:(CardType.HERO,)}[record.zone]:
            raise ValueError('Invalid destruction record type')
        if kind == CardType.LOCATION and (record.corpse_value or record.max_health or record.attack or record.damage):
            raise ValueError('Location destruction cannot carry character death stats')
        if registry.card(state.entities[record.entity_id].card_id).kind != kind or registry.card(record.card_id).kind != kind:
            raise ValueError('Death record entity/type does not match its zone')
        if record.id <= previous_record_id or record.batch < previous_batch:
            raise ValueError("death history IDs must increase and batches cannot move backwards")
        if record.id >= state.next_death_id or record.batch >= state.next_death_batch:
            raise ValueError("death counters must be greater than recorded IDs and batches")
        if record.turn > state.turn:
            raise ValueError("death record cannot refer to a future turn")
        if record.batch in batch_turns and batch_turns[record.batch] != record.turn:
            raise ValueError("one death batch cannot span multiple turns")
        if (record.batch, record.entity_id) in batch_entities:
            raise ValueError("an entity cannot die twice in the same death batch")
        batch_turns[record.batch] = record.turn
        batch_entities.add((record.batch, record.entity_id))
        previous_record_id, previous_batch = record.id, record.batch
        from .printed_attack_permits import validate_carrier
        validate_carrier(state, registry, record.card_id, kind, record.abilities)
        from .stat_relations import validate_carrier as validate_stat_relation_carrier
        validate_stat_relation_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .discard_history import validate_carrier as validate_discard_carrier
        validate_discard_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .keyword_auras import validate_carrier as validate_conditional_keyword_carrier
        validate_conditional_keyword_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .deathrattles import validate_prohibition_carrier
        validate_prohibition_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .hero_powers import validate_prohibition_carrier as validate_power_prohibition
        validate_power_prohibition(registry, record.card_id, kind, record.abilities, record.components)
        from .hero_powers import validate_use_aura_carrier
        validate_use_aura_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .stat_auras import validate_carrier as validate_conditional_stat_aura_carrier
        validate_conditional_stat_aura_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .costs import validate_cost_aura_carrier
        validate_cost_aura_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .corpse_gains import validate_carrier as validate_corpse_gain_carrier
        validate_corpse_gain_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .turn_start_draws import validate_carrier as validate_turn_draw_carrier
        validate_turn_draw_carrier(registry,record.card_id,kind,record.abilities,record.components)
        from .native_spell_values import validate_carrier as validate_native_spell_carrier
        validate_native_spell_carrier(state,registry,record.card_id,kind,record.abilities)
        from .health_rules import validate_school_spell_damage_carrier
        validate_school_spell_damage_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .native_conditions import validate_carrier as validate_native_condition_carrier
        validate_native_condition_carrier(registry,record.card_id,kind,record.abilities,record.components)
        from .deathrattle_memory import validate_carrier as validate_deathrattle_memory_carrier
        validate_deathrattle_memory_carrier(state,registry,record.card_id,kind,record.abilities,record.components)
        from .dormancy import validate_board_full_carrier
        validate_board_full_carrier(registry,record.card_id,kind,record.abilities)
        from .cleave import validate_carrier as validate_cleave_carrier
        validate_cleave_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .health_floors import validate_carrier as validate_floor_carrier, validate_result
        validate_floor_carrier(registry, record.card_id, kind, record.abilities, record.components)
        from .health_loss_floors import validate_carrier as validate_loss_floor_carrier
        validate_loss_floor_carrier(registry, record.card_id, kind, record.abilities, record.components)
        if record.cause is not None and record.cause.result:
            from .health_outcomes import result_from_payload
            validate_result(state, registry, result_from_payload(record.cause.result))
        for attachment in (*record.abilities, *record.enchantments):
            validate_attachment(attachment)
            if type(attachment) is Enchantment and attachment.hand_play_lock is not None:
                from .hand_play_locks import validate_clock
                if attachment.hand_play_lock.deadline.created_turn > record.turn:
                    raise ValueError('Frozen hand play lock was created after this death')
                validate_clock(state, attachment.hand_play_lock)
            if type(attachment) is Enchantment and attachment.owner_turn_expiry is not None:
                from .timed_keywords import validate_deadline
                if kind not in (CardType.MINION, CardType.HERO) or attachment.owner_turn_expiry.created_turn > record.turn:
                    raise ValueError('Frozen numeric owner expiry exceeds its character death window')
                validate_deadline(state, attachment.owner_turn_expiry)
            if isinstance(attachment, AbilityInstance) and attachment.reborn_policy is not None and kind != CardType.MINION:
                raise ValueError('Frozen full-health Reborn requires a minion carrier')
            if isinstance(attachment, AbilityInstance) and attachment.reborn_policy is not None and attachment.origin == 'printed':
                if (registry.card(record.card_id).reborn_policy != attachment.reborn_policy or attachment.source_id != record.entity_id or
                        sum(a.kind=='keyword'and a.keyword==Keyword.REBORN and a.origin=='printed'and a.reborn_policy is not None for a in record.abilities)>1):
                    raise ValueError('Frozen native Reborn differs from its printed declaration')
            if type(attachment) is Enchantment and attachment.tribe_change is not None and kind != CardType.MINION:
                raise ValueError('Frozen tribe change requires a minion carrier')
            if type(attachment) is Enchantment and attachment.control_return_player_id is not None and kind != CardType.MINION:
                raise ValueError('Frozen temporary control requires a minion carrier')
            if type(attachment) is Enchantment and attachment.control_return_expiry is not None:
                from .timed_keywords import validate_deadline
                validate_deadline(state, attachment.control_return_expiry)
            if (isinstance(attachment, AbilityInstance) and attachment.kind == 'deathrattle_repeat' and
                    kind != CardType.MINION):
                raise ValueError('Frozen Deathrattle repeat source requires a minion carrier')
            if (isinstance(attachment, AbilityInstance) and attachment.kind == 'hero_power_repeat' and
                    kind != CardType.MINION):
                raise ValueError('Frozen hero power repeat source requires a minion carrier')
            if (isinstance(attachment, AbilityInstance) and attachment.kind == 'end_turn_repeat' and
                    kind != CardType.MINION):
                raise ValueError('Frozen end-turn repeat source requires a minion carrier')
    if all_attachment_ids and state.next_attachment_id <= max(all_attachment_ids):
        raise ValueError("next_attachment_id must exceed current and historical attachment IDs")
    from .owner_turns import validate_history as validate_owner_turn_history
    validate_owner_turn_history(state, registry)
    from .payment_projection import validate_cost_use_history
    validate_cost_use_history(state, registry)
    from .repeat_matching import validate_spell_cost_history
    validate_spell_cost_history(state, registry)
    from .play_history import validate_history
    validate_history(state, registry)
    from .summon_sources import validate_history as validate_resurrections
    from .spell_casts import validate_history as validate_casts
    validate_casts(state, registry)
    from .hero_attack_history import validate_history as validate_hero_attacks
    validate_hero_attacks(state, registry)
    from .character_attacks import validate_history as validate_character_attacks
    validate_character_attacks(state, registry)
    from .draw_casts import validate_history as validate_draws
    validate_draws(state, registry)
    validate_resurrections(state, registry)
    from .spell_repeats import validate_history as validate_spell_repeats
    validate_spell_repeats(state, registry)
    from .spell_acceptance import validate_history as validate_spell_acceptance
    validate_spell_acceptance(state, registry)
    from .spell_modifiers import validate_receipts as validate_spell_receipts
    validate_spell_receipts(state, registry)
    from .choose_policies import validate_history as validate_choose_policies
    validate_choose_policies(state, registry)
    from .rewind_outcomes import validate_history as validate_rewind_outcomes
    validate_rewind_outcomes(state, registry)
    from .hand_history import validate_hand_history
    validate_hand_history(state, registry)
    from .temporary_cards import validate_lifetimes
    validate_lifetimes(state, registry)
    from .magnetic import validate_magnetic_history
    validate_magnetic_history(state, registry)
    from .summon_quantities import validate_history as validate_card_summon_history
    validate_card_summon_history(state,registry)
    from .pool_summons import validate_history as validate_pool_summon_history
    validate_pool_summon_history(state,registry)
    from .ordered_group_batches import validate_history as validate_ordered_group_history
    validate_ordered_group_history(state,registry)
    from .discovery_summons import validate_history as validate_discovery_summon_history
    validate_discovery_summon_history(state,registry)
    from .hand_choice_followups import validate_shape as validate_hand_followups
    validate_hand_followups(state)
    from .temporary_hands import validate_shape as validate_temporary_hands
    validate_temporary_hands(state,registry)
    from .hand_deadlines import validate_shape as validate_hand_deadlines
    validate_hand_deadlines(state,registry)
    from .recruit_summons import validate_history as validate_recruit_summon_history
    validate_recruit_summon_history(state,registry)
    from .resurrection_summons import validate_history as validate_resurrection_summon_history
    validate_resurrection_summon_history(state,registry)
    from .colossal import validate_history as validate_colossal_history
    validate_colossal_history(state, registry)
    from .herald import validate_history as validate_herald_history
    validate_herald_history(state, registry)
    from .excavate import validate_history as validate_excavation_history
    validate_excavation_history(state, registry)
    from .imbue import validate_history as validate_imbue_history
    validate_imbue_history(state, registry)
    from .invoke import validate_state as validate_invoke_state
    validate_invoke_state(state, registry)
    from .jade import validate_state as validate_jade_state
    validate_jade_state(state, registry)
    from .cthun import validate_state as validate_cthun_state
    validate_cthun_state(state, registry)
    from .hero_powers import validate_history as validate_power_history
    validate_power_history(state, registry)
    from .battlecries import validate_history as validate_battlecry_history
    validate_battlecry_history(state, registry)
    from .combos import validate_history as validate_combo_history
    validate_combo_history(state, registry)
    from .deathrattles import validate_history as validate_deathrattle_history
    validate_deathrattle_history(state,registry)
    from .end_turns import validate_history as validate_end_turn_history
    validate_end_turn_history(state, registry)
    from .whole_card_replay_state import validate_history as validate_whole_card_replay_history
    validate_whole_card_replay_history(state, registry)
    from .battlecry_policy_uses import validate_history as validate_battlecry_policy_uses
    validate_battlecry_policy_uses(state, registry)
    if type(state.starship_history) is not list:
        raise ValueError('Starship history must be a list')
    previous_turn, previous_action = 0, 0
    for index, record in enumerate(state.starship_history, 1):
        if type(record) is not StarshipLaunchRecord:
            raise ValueError('Starship history requires immutable launch records')
        record.__post_init__()
        if (record.id != index or record.entity_id not in state.entities or
                not previous_turn <= record.turn <= state.turn or
                not previous_action <= record.action <= state.action_number):
            raise ValueError('Invalid Starship launch history identity or chronology')
        if not registry.card(record.card_id).starship_for:
            raise ValueError('Launch history requires a Starship body')
        if any(registry.card(i).kind != CardType.MINION or registry.card(i).starship_for for i in record.components):
            raise ValueError('Launch history contains invalid components')
        previous_turn, previous_action = record.turn, record.action


    from .interactables import validate_state as validate_interactable_state
    validate_interactable_state(state, registry)
    from .game_boards import validate_state as validate_board_state
    validate_board_state(state, registry)


def validate_composition(entity, registry):
    _components(entity.components)
    definition = registry.card(entity.card_id)
    if bool(definition.starship_for) != bool(entity.components):
        raise ValueError('Starship body and composition disagree')
    parts = [registry.card(i) for i in entity.components]
    if any(p.kind != CardType.MINION or p.starship_for for p in parts):
        raise ValueError('Invalid Starship component definition')
    if parts and (entity.base_attack != sum(p.attack for p in parts) or
                  entity.base_health != sum(p.health for p in parts)):
        raise ValueError('Starship base stats disagree with its components')


def validate_combo_payloads(values):
    if (type(values) is not tuple or any(type(b) is not ComboPayload for b in values) or
            len({b.ability_id for b in values}) != len(values)):
        raise ValueError('Expected unique immutable Combo payloads')
    for value in values: value.__post_init__()


@dataclass(frozen=True)
class KindredProfile:
    card_id: str
    mode: str
    wrapper: str | None = None
    active: str | None = None
    prepare: str | None = None
    inactive: str | None = None

    def __post_init__(self):
        _name(self.card_id,'Kindred definition')
        if self.mode not in('body','cost'):raise ValueError('Unknown native Kindred role')
        for name in('wrapper','active','prepare','inactive'):
            if getattr(self,name)is not None:_name(getattr(self,name),'Kindred '+name)
        if self.mode=='cost'and any((self.wrapper,self.active,self.prepare,self.inactive)):
            raise ValueError('Intrinsic Kindred price has no duplicated ordinary body')
        if self.mode=='body'and(self.wrapper is None or not(self.active or self.prepare)):
            raise ValueError('Native Kindred body requires a real entry and component')


@dataclass(frozen=True)
class KindredActivation:
    card_id: str
    original: object
    condition: PreviousOwnerTurnMatch
    sources: tuple[PlayerEffect, ...]
    repetitions: int
    record_id: int

    def __post_init__(self):
        from .registry import RuleContext
        _int(self.record_id,'Kindred acceptance ID',1)
        _name(self.card_id,'Kindred acceptance definition')
        if type(self.original)is not RuleContext or self.original.kindred is not None:
            raise ValueError('Kindred acceptance requires its independent original caller')
        if type(self.condition)is not PreviousOwnerTurnMatch:raise ValueError('Kindred acceptance lost its complete original relation')
        self.condition.__post_init__()
        if type(self.sources)is not tuple or any(type(x)is not PlayerEffect for x in self.sources):
            raise ValueError('Kindred acceptance requires complete immutable source instances')
        for x in self.sources:x.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.sources,self.sources[1:])):raise ValueError('Kindred acceptance sources lost original order')
        if type(self.repetitions)is not int or self.repetitions!=(2 if self.sources else 1):
            raise ValueError('Kindred count differs from its original max2 source plan')


@dataclass(frozen=True)
class KindredRecord:
    id:int
    card_id:str
    source:object
    player_id:int
    turn:int
    action:int
    event_cursor:int
    boundary:OwnerTurnQueryBoundaryFact
    condition:PreviousOwnerTurnMatch
    sources:tuple[PlayerEffect,...]
    repetitions:int
    plan:tuple[str,...]
    started:tuple[str,...]=()
    stack:tuple[int,...]=()
    finished:tuple[int,...]=()
    completed:bool=False
    interruption:tuple[int,int]|None=None

    def __post_init__(self):
        from .allocation_facts import SourceAllocationFact
        for name in('id','player_id','turn'):_int(getattr(self,name),'Kindred record '+name,1)
        for name in('action','event_cursor'):_int(getattr(self,name),'Kindred record '+name,0)
        if self.player_id not in(1,2)or type(self.source)is not SourceAllocationFact:raise ValueError('Kindred record requires its original player/source')
        self.source.__post_init__();_name(self.card_id,'Kindred record definition')
        if type(self.boundary)is not OwnerTurnQueryBoundaryFact or type(self.condition)is not PreviousOwnerTurnMatch:
            raise ValueError('Kindred record requires its original complete condition window')
        self.boundary.__post_init__();self.condition.__post_init__()
        if(self.boundary.turn,self.boundary.action,self.condition.player_id)!=(self.turn,self.action,self.player_id):
            raise ValueError('Kindred record changed its original condition window')
        if type(self.sources)is not tuple or any(type(x)is not PlayerEffect for x in self.sources):raise ValueError('Kindred record requires complete original sources')
        for x in self.sources:x.__post_init__()
        if any(a.id>=b.id for a,b in zip(self.sources,self.sources[1:]))or type(self.repetitions)is not int or self.repetitions!=(2 if self.sources else 1):raise ValueError('Kindred record changed its max source plan')
        for rows in(self.plan,self.started):
            if type(rows)is not tuple or any(x not in('active','prepare','inactive')for x in rows):raise ValueError('Kindred record has unknown component roles')
        if len(self.plan)>3 or self.started!=self.plan[:len(self.started)]:raise ValueError('Kindred record changed the accepted ordered plan')
        for rows in(self.stack,self.finished):
            if type(rows)is not tuple or len(set(rows))!=len(rows)or any(type(x)is not int or not 0<=x<len(self.started)for x in rows):raise ValueError('Kindred record has invalid execution identities')
        if set(self.stack)&set(self.finished)or set(self.stack)|set(self.finished)!=set(range(len(self.started))):raise ValueError('Kindred record lost an accepted execution identity')
        _bool(self.completed,'Kindred completion')
        if self.completed and(self.started!=self.plan or self.stack or len(self.finished)!=len(self.plan)):raise ValueError('Kindred record completed before its full plan')
        if self.interruption is not None:
            if type(self.interruption)is not tuple or len(self.interruption)!=2 or any(type(x)is not int or x<1 for x in self.interruption):raise ValueError('Kindred interruption requires its actual terminal event/action')
            if self.completed or self.interruption[1]<self.action:raise ValueError('Kindred interruption contradicts its accepted root')

