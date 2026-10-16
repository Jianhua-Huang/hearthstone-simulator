"""Declarative effects emitted by card behaviors and interpreted by the engine.

No effect mutates state itself.  Extension effects may subclass Effect and register
an interpreter; the engine must reject types without a registered interpreter.
"""

from __future__ import annotations
from .model import BoardPresenceReference, ChooseBranchSelection, EquippedWeaponReference

from .card_creation import (CardSpellRepeatGrant, CreatedMinionGrant, validate_declaration,
    validate_branch_declaration, validate_branch_transfer, validate_minion_grant)
from dataclasses import dataclass
from .model import HeroAttackReference
from .model import ChoiceItem, ChoicePurpose, CostScope, CostSpec, CostAuraSpec, DamageKind, HealingKind, HealthRule, Keyword, Resource, StatReference, validate_cost_scope
from .model import SummonStats, validate_summon_stats, CardPreview, HeroPowerReference
from .model import TimedKeywordSpec, EndTurnSpec, TriggerSpec, validate_combat_relation


class Effect:
    """Marker base class for immutable rule instructions."""


@dataclass(frozen=True)
class ForceAttack(Effect):
    attacker_id: int | BoardPresenceReference
    defender_id: int | BoardPresenceReference
    combat_relation: str = 'opponent'

    def __post_init__(self):
        validate_combat_relation(self.combat_relation)
        for label, value in (('attacker_id', self.attacker_id), ('defender_id', self.defender_id)):
            if type(value) is BoardPresenceReference:
                value.__post_init__()
            else:
                _integer(value, label, 1)

    def validate_in_state(self, state):
        """Old residence may be stale; unknown or future residence is invalid."""
        self.__post_init__()
        for value in (self.attacker_id, self.defender_id):
            if type(value) is BoardPresenceReference and (
                    value.entity_id not in state.entities or value.presence_id >= state.next_order):
                raise ValueError('Forced attack borrowed an unknown or future board residence')


@dataclass(frozen=True)
class RandomForceAttack(Effect):
    attacker_ids: tuple[int, ...]
    defender_ids: tuple[int, ...]
    source_id: int | None = None
    combat_relation: str = 'opponent'

    def __post_init__(self):
        validate_combat_relation(self.combat_relation)
        for values in (self.attacker_ids,self.defender_ids):
            if type(values) is not tuple or len(set(values))!=len(values):raise ValueError('Expected distinct combat candidates')
            for value in values:_integer(value,'combat candidate',1)
        _source(self.source_id)


@dataclass(frozen=True)
class RevealHandCard(Effect):
    """Reveal a hand identity to explicit seats without publishing its modifiers."""
    target_id: int
    viewers: tuple[int, ...] = (1, 2)

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        if type(self.viewers) is not tuple or not self.viewers:
            raise ValueError('Reveal viewers must be a nonempty tuple')
        for viewer in self.viewers:
            _player(viewer)
        if len(set(self.viewers)) != len(self.viewers):
            raise ValueError('Reveal viewers must be distinct')


def validate_generated_cost(cost, expires_turn):
    if cost is not None:
        if type(cost) is not CostSpec:
            raise ValueError('Generated cost requires CostSpec')
        cost.__post_init__()
    if expires_turn is not None:
        _integer(expires_turn, 'generated cost expiry', 1)
        if cost is None:
            raise ValueError('Generated cost expiry requires a cost modifier')


@dataclass(frozen=True)
class AddToHand(Effect):
    player_id: int
    card_id: str
    source_id: int | None = None
    revealed_to: tuple[int, ...] = ()
    cost: CostSpec | None = None
    expires_turn: int | None = None

    spell_repeat: CardSpellRepeatGrant | None = None
    choose_branch: ChooseBranchSelection | None = None
    minion_grant: CreatedMinionGrant | None = None

    def __post_init__(self):
        validate_declaration(self.spell_repeat)
        validate_minion_grant(self.minion_grant)
        validate_branch_declaration(self.choose_branch, self.card_id)
        _player(self.player_id)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('card_id must be nonempty')
        _source(self.source_id)
        if type(self.revealed_to) is not tuple:
            raise ValueError('revealed_to must be a tuple of player IDs')
        for viewer in self.revealed_to:
            _player(viewer)
        if len(set(self.revealed_to)) != len(self.revealed_to):
            raise ValueError('revealed_to must contain distinct players')
        validate_generated_cost(self.cost, self.expires_turn)


@dataclass(frozen=True)
class InvokeBehavior(Effect):
    """Call registered, pure card behavior against the state at execution time."""
    behavior_id: str
    source_id: int
    player_id: int
    target_id: int | None = None
    play_id: int | None = None

    def __post_init__(self):
        if type(self.behavior_id) is not str or not self.behavior_id.strip():
            raise ValueError('InvokeBehavior requires a behavior ID')
        _integer(self.source_id, 'source_id', 1)
        _player(self.player_id)
        _source(self.target_id)
        _source(self.play_id)


@dataclass(frozen=True)
class SplitDamage(Effect):
    """Non-spell effect damage split into one-point hits, querying each time."""
    player_id: int  # The seat whose characters receive the damage.
    amount: int
    source_id: int | None = None
    include_hero: bool = True
    kind: DamageKind = DamageKind.EFFECT

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount', 0)
        _source(self.source_id)
        if type(self.include_hero) is not bool:
            raise ValueError('include_hero must be boolean')
        if type(self.kind) is not DamageKind or self.kind not in (DamageKind.EFFECT, DamageKind.HERO_POWER, DamageKind.MINION_ABILITY):
            raise ValueError('Split damage supports effect, hero power or minion ability damage')


def _integer(value: object, name: str, minimum: int | None = None) -> None:
    if type(value) is not int or (minimum is not None and value < minimum):
        suffix = "" if minimum is None else f" >= {minimum}"
        raise ValueError(f"{name} must be an integer{suffix}")


def _source(source_id: int | None) -> None:
    if source_id is not None:
        _integer(source_id, "source_id", 1)


def _player(player_id: int) -> None:
    _integer(player_id, "player_id", 1)
    if player_id not in (1, 2):
        raise ValueError("player_id must be 1 or 2")


@dataclass(frozen=True)
class ChoiceOption:
    id: str
    label: str
    effects: tuple[Effect, ...] = ()
    card_id: str | None = None
    entity_id: int | None = None
    preview: 'CardPreview | None' = None

    def __post_init__(self):
        self.item.__post_init__()
        if not isinstance(self.effects, tuple) or any(not isinstance(e, Effect) for e in self.effects):
            raise ValueError('Choice branch must be a tuple of effects')

    @property
    def item(self):
        return ChoiceItem(self.id, self.label, self.card_id, self.entity_id, self.preview)


@dataclass(frozen=True)
class RequestChoice(Effect):
    player_id: int
    options: tuple[ChoiceOption, ...]
    source_id: int | None = None
    prompt: str = 'Choose an option'
    min_count: int = 1
    max_count: int = 1
    on_select: str | None = None
    sample_size: int | None = None
    purpose: ChoicePurpose = ChoicePurpose.EFFECT
    repeat_key: str | None = None

    def __post_init__(self):
        from .model import PendingChoice
        _player(self.player_id)
        _source(self.source_id)
        if not isinstance(self.options, tuple) or any(not isinstance(o, ChoiceOption) for o in self.options):
            raise ValueError('RequestChoice requires an immutable tuple of ChoiceOption')
        for option in self.options:
            option.__post_init__()
        PendingChoice(1, self.player_id, self.source_id, self.prompt, tuple(o.item for o in self.options),
                      self.min_count, self.max_count, self.purpose, self.repeat_key)
        if self.repeat_key is not None and self.sample_size is not None:
            raise ValueError('A repeated branch choice cannot sample its option identities')
        if self.on_select is not None and (not isinstance(self.on_select, str) or not self.on_select.strip()):
            raise ValueError('on_select must be a nonempty behavior ID or None')
        if self.sample_size is not None:
            _integer(self.sample_size, 'sample_size', 1)
            if not self.max_count <= self.sample_size <= len(self.options):
                raise ValueError('Invalid choice sampling size')


@dataclass(frozen=True)
class ModifyCost(Effect):
    target_id: int
    spec: CostSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _cost_attachment(self)


@dataclass(frozen=True)
class AddCostModifier(Effect):
    player_id: int
    spec: CostSpec
    uses_remaining: int | None = None
    source_id: int | None = None
    expires_turn: int | None = None
    scope: CostScope = CostScope.CARD
    tribes_any: tuple[str, ...] = ()
    combo_only: bool = False
    temporary_only: bool = False
    maximum_cost: int | None = None
    minion_keyword: Keyword | None = None
    minion_keyword_repetitions: int = 1

    def __post_init__(self):
        _player(self.player_id)
        _cost_attachment(self)
        validate_cost_scope(self.scope, self.spec)
        from .model import CostModifier
        CostModifier(1,self.spec,self.source_id,self.uses_remaining,self.expires_turn,self.scope,self.tribes_any,
            self.combo_only,self.temporary_only,self.maximum_cost,self.minion_keyword,self.minion_keyword_repetitions)
        if self.uses_remaining is not None:
            _integer(self.uses_remaining, 'uses_remaining', 1)


@dataclass(frozen=True)
class GrantCostAura(Effect):
    target_id: int
    spec: CostAuraSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _cost_attachment(self, CostAuraSpec)
        if self.spec.tribes_any or self.spec.first_per_turn or self.spec.every_nth_per_turn is not None:
            raise ValueError('Native filtered cost aura grants are not supported')


def _cost_attachment(effect, expected=CostSpec):
    if type(effect.spec) is not expected:
        raise ValueError('Cost effect requires ' + expected.__name__)
    effect.spec.__post_init__()
    _source(effect.source_id)
    if effect.expires_turn is not None:
        _integer(effect.expires_turn, 'expires_turn', 1)


@dataclass(frozen=True)
class GainTemporaryMana(Effect):
    player_id: int
    amount: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount', 0)


@dataclass(frozen=True)
class SpendMana(Effect):
    player_id: int
    amount: int | None = None
    source_id: int | None = None
    on_result: str | None = None

    def __post_init__(self):
        _player(self.player_id)
        if self.amount is not None: _integer(self.amount,'requested mana consumption',0)
        _source(self.source_id)
        if self.on_result is not None:
            _behavior(self.on_result)
            if self.source_id is None:
                raise ValueError('Mana result callback requires a physical source')


@dataclass(frozen=True)
class RefreshMana(Effect):
    player_id: int
    amount: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount', 0)


@dataclass(frozen=True)
class ChangeManaCrystals(Effect):
    player_id: int
    amount: int
    filled: bool = False

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount')
        if type(self.filled) is not bool:
            raise ValueError('filled must be boolean')


@dataclass(frozen=True)
class SetManaCap(Effect):
    player_id: int
    amount: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount', 0)


@dataclass(frozen=True)
class Overload(Effect):
    player_id: int
    amount: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.amount, 'amount', 0)


@dataclass(frozen=True)
class UnlockOverload(Effect):
    player_id: int
    clear_pending: bool = True

    def __post_init__(self):
        _player(self.player_id)
        if type(self.clear_pending) is not bool:
            raise ValueError('clear_pending must be boolean')


@dataclass(frozen=True)
class GainResource(Effect):
    player_id: int
    resource: Resource
    amount: int

    def __post_init__(self):
        _resource_effect(self)


@dataclass(frozen=True)
class SpendResource(Effect):
    """Check at execution; run exactly one branch using the then-current bank."""
    player_id: int
    resource: Resource
    amount: int
    on_success: tuple[Effect, ...] = ()
    on_failure: tuple[Effect, ...] = ()
    required: bool = False

    def __post_init__(self):
        _resource_effect(self)
        if type(self.required) is not bool:
            raise ValueError('required must be boolean')
        for branch in (self.on_success, self.on_failure):
            if not isinstance(branch, tuple) or any(not isinstance(e, Effect) for e in branch):
                raise ValueError('Resource branches must be immutable tuples of effects')


def _resource_effect(effect):
    _player(effect.player_id)
    if not isinstance(effect.resource, Resource):
        raise ValueError('Unknown Resource')
    _integer(effect.amount, 'amount', 0)


@dataclass(frozen=True)
class Damage(Effect):
    target_id: int
    amount: int
    source_id: int | None = None
    kind: DamageKind = DamageKind.EFFECT
    on_result: str | None = None
    spell_bonus_multiplier: int = 1

    def __post_init__(self) -> None:
        _integer(self.target_id, "target_id", 1)
        _integer(self.amount, "amount", 0)
        _source(self.source_id)
        _damage_kind(self.kind, self.source_id)
        _health_callback(self.on_result, self.source_id)
        _integer(self.spell_bonus_multiplier, "spell_bonus_multiplier", 1)
        if self.spell_bonus_multiplier != 1 and self.kind != DamageKind.SPELL:
            raise ValueError("Only SPELL damage may scale its Spell Damage bonus")


def _health_callback(behavior_id, source_id):
    if behavior_id is not None:
        _behavior(behavior_id)
        _integer(source_id, 'health result callback source', 1)


@dataclass(frozen=True)
class CombatExchange:
    """One committed attack; its intrinsic wear settles in the damage batch."""
    attacker_id: int
    defender_id: int
    weapon_id: int | None = None
    combat_relation: str = 'opponent'
    hero_attack: 'HeroAttackReference | None' = None
    attack_window_id: int | None = None

    def __post_init__(self):
        validate_combat_relation(self.combat_relation)
        if self.combat_relation != 'opponent' and self.weapon_id is not None:
            raise ValueError('Friendly minion combat cannot carry a weapon')
        _integer(self.attacker_id, 'attacker_id', 1)
        _integer(self.defender_id, 'defender_id', 1)
        _source(self.weapon_id)
        _source(self.attack_window_id)
        if self.hero_attack is not None:
            if type(self.hero_attack) is not HeroAttackReference: raise ValueError("Expected exact hero attack reference")
            self.hero_attack.__post_init__()


@dataclass(frozen=True)
class DamageBatch(Effect):
    """Hits sharing one simultaneous damage/death boundary."""

    hits: tuple[Damage, ...]
    combat: CombatExchange | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.hits, tuple) or any(type(hit) is not Damage for hit in self.hits):
            raise ValueError("hits must be a tuple of Damage effects")
        if self.combat is not None:
            if not isinstance(self.combat, CombatExchange):
                raise ValueError('combat must be a CombatExchange')
            if (not 2 <= len(self.hits) <= 4 or any(h.kind != DamageKind.COMBAT for h in self.hits)
                    or [(h.source_id, h.target_id) for h in self.hits[:2]] != [
                        (self.combat.attacker_id, self.combat.defender_id),
                        (self.combat.defender_id, self.combat.attacker_id)]):
                raise ValueError('Combat exchange requires its two reciprocal hits and at most two cleave hits')
            tail = self.hits[2:]
            if (any(h.source_id != self.combat.attacker_id or h.amount != self.hits[0].amount or
                    h.target_id in (self.combat.attacker_id, self.combat.defender_id) or h.on_result is not None for h in tail)
                    or len({h.target_id for h in tail}) != len(tail)):
                raise ValueError('Cleave hits require distinct additional recipients and the original attack amount')


@dataclass(frozen=True)
class Heal(Effect):
    target_id: int
    amount: int
    source_id: int | None = None
    kind: HealingKind = HealingKind.EFFECT
    on_result: str | None = None

    def __post_init__(self) -> None:
        _integer(self.target_id, "target_id", 1)
        _integer(self.amount, "amount", 0)
        _source(self.source_id)
        if not isinstance(self.kind, HealingKind):
            raise ValueError('Healing kind requires HealingKind')
        if self.kind != HealingKind.EFFECT and self.source_id is None:
            raise ValueError('Spell and hero power healing require a source')
        _health_callback(self.on_result, self.source_id)


@dataclass(frozen=True)
class HealBatch(Effect):
    heals: tuple[Heal, ...]

    def __post_init__(self):
        if not isinstance(self.heals, tuple) or any(type(h) is not Heal for h in self.heals):
            raise ValueError('HealBatch requires a tuple of Heal instructions')


@dataclass(frozen=True)
class GrantHealthRule(Effect):
    target_id: int
    rule: HealthRule
    source_id: int | None = None
    expires_turn: int | None = None
    until_owner_turn_start: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        if not isinstance(self.rule, HealthRule):
            raise ValueError('GrantHealthRule requires HealthRule')
        self.rule.__post_init__()
        if self.until_owner_turn_start is not None:
            _player(self.until_owner_turn_start)
            if self.expires_turn is not None:raise ValueError('Health rule cannot combine global and owner deadlines')


@dataclass(frozen=True)
class Freeze(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _source(self.source_id)


@dataclass(frozen=True)
class Unfreeze(Effect):
    target_id: int

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)


@dataclass(frozen=True)
class Summon(Effect):
    player_id: int
    card_id: str
    position: int | None = None
    stats: SummonStats | None = None

    def __post_init__(self) -> None:
        _player(self.player_id)
        validate_summon_stats(self.stats)
        if not isinstance(self.card_id, str) or not self.card_id.strip():
            raise ValueError("card_id must be a nonempty string")
        if self.position is not None:
            _integer(self.position, "position", 0)


@dataclass(frozen=True)
class Draw(Effect):
    player_id: int
    count: int = 1
    source_id: int | None = None

    def __post_init__(self) -> None:
        _player(self.player_id)
        _integer(self.count, "count", 0)
        _source(self.source_id)


@dataclass(frozen=True)
class DrawToHandLimit(Effect):
    player_id: int

    def __post_init__(self):
        _player(self.player_id)


@dataclass(frozen=True)
class Buff(Effect):
    target_id: int
    attack: int = 0
    health: int = 0
    source_id: int | None = None
    expires_turn: int | None = None
    until_owner_turn_start: int | None = None

    def __post_init__(self) -> None:
        _integer(self.target_id, "target_id", 1)
        _integer(self.attack, "attack")
        _integer(self.health, "health")
        _source(self.source_id)
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'expires_turn', 1)
        if self.until_owner_turn_start is not None:
            _player(self.until_owner_turn_start)
            if self.expires_turn is not None:
                raise ValueError('Buff cannot combine global and owner-turn expiry')


@dataclass(frozen=True)
class RandomBuff(Effect):
    """Choose one live board minion once, then use the ordinary stat layer."""
    candidate_ids: tuple[int, ...]
    attack: int = 0
    health: int = 0
    source_id: int | None = None

    def __post_init__(self):
        if type(self.candidate_ids)is not tuple:raise ValueError('Random buff candidates require an immutable tuple')
        for identity in self.candidate_ids:_integer(identity,'random buff minion',1)
        if len(set(self.candidate_ids))!=len(self.candidate_ids):raise ValueError('Random buff candidates must be unique')
        _integer(self.attack,'random buff attack');_integer(self.health,'random buff health');_source(self.source_id)


@dataclass(frozen=True)
class SetStats(Effect):
    """Set either local stat; setting health also clears accumulated damage.

    References read visible values at execution, simultaneously before writes.
    Ongoing auras apply after the ordered local enchantments.
    """
    target_id: int
    attack: int | StatReference | None = None
    health: int | StatReference | None = None
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        if self.attack is None and self.health is None:
            raise ValueError('SetStats requires at least one stat')
        for name in ('attack', 'health'):
            value = getattr(self, name)
            if value is not None and not isinstance(value, StatReference):
                _integer(value, name, 0)


@dataclass(frozen=True)
class SwapStats(Effect):
    """Set attack to current remaining health and health to current attack."""
    target_id: int
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)


@dataclass(frozen=True)
class DoubleStats(Effect):
    """Add a frozen copy of the selected visible attack / remaining health."""
    target_id: int
    attack: bool = False
    health: bool = False
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        if type(self.attack) is not bool or type(self.health) is not bool:
            raise ValueError('DoubleStats selectors must be booleans')
        if not self.attack and not self.health:
            raise ValueError('DoubleStats requires at least one stat')


@dataclass(frozen=True)
class Destroy(Effect):
    target_id: int
    source_id: int | None = None

    def __post_init__(self) -> None:
        _integer(self.target_id, "target_id", 1)
        _source(self.source_id)


@dataclass(frozen=True)
class DestroyBatch(Effect):
    """Mark captured board minions/locations before one ordinary death checkpoint."""
    target_ids: tuple[int, ...]
    source_id: int | None = None

    def __post_init__(self):
        if type(self.target_ids) is not tuple:
            raise ValueError('Batch destruction requires unique immutable target IDs')
        for target_id in self.target_ids:
            _integer(target_id, 'batch destruction target', 1)
        if len(set(self.target_ids)) != len(self.target_ids):
            raise ValueError('Batch destruction requires unique immutable target IDs')
        _source(self.source_id)


@dataclass(frozen=True)
class GainArmor(Effect):
    player_id: int
    amount: int

    def __post_init__(self) -> None:
        _player(self.player_id)
        _integer(self.amount, "amount", 0)


@dataclass(frozen=True)
class LoseArmor(Effect):
    player_id: int
    amount: int | None = None
    source_id: int | None = None
    on_result: str | None = None

    def __post_init__(self):
        _player(self.player_id)
        if self.amount is not None: _integer(self.amount,'requested armor loss',0)
        _source(self.source_id)
        if self.on_result is not None:
            _behavior(self.on_result)
            if self.source_id is None:
                raise ValueError('Armor result callback requires a physical source')


@dataclass(frozen=True)
class EquipWeapon(Effect):
    player_id: int
    card_id: str

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)


@dataclass(frozen=True)
class TransferWeapon(Effect):
    weapon: EquippedWeaponReference
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        if type(self.weapon) is not EquippedWeaponReference:
            raise ValueError('Weapon transfer requires a captured equipped reference')
        self.weapon.__post_init__()
        _player(self.player_id)
        _source(self.source_id)


@dataclass(frozen=True)
class ModifyWeapon(Effect):
    target_id: int
    attack: int = 0
    durability: int = 0
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.attack, 'attack')
        _integer(self.durability, 'durability')
        _source(self.source_id)


@dataclass(frozen=True)
class ReplaceHeroPower(Effect):
    player_id: int
    card_id: str
    power: HeroPowerReference | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None
    source_id: int | None = None
    choose_branch: ChooseBranchSelection | None = None
    branch_policy: str = 'clear'
    branch_map: tuple[tuple[str, str], ...] | None = None

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        validate_power_reference(self.power, self.player_id)
        validate_generated_cost(self.cost, self.expires_turn)
        _source(self.source_id)
        validate_branch_declaration(self.choose_branch, self.card_id)
        validate_branch_transfer(self.branch_policy, self.choose_branch, self.branch_map)


@dataclass(frozen=True)
class RefreshHeroPower(Effect):
    player_id: int
    power: HeroPowerReference | None = None

    def __post_init__(self):
        _player(self.player_id)
        validate_power_reference(self.power, self.player_id)


@dataclass(frozen=True)
class SetHeroPowerUses(Effect):
    player_id: int
    limit: int
    power: HeroPowerReference | None = None

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.limit, 'limit', 1)
        validate_power_reference(self.power, self.player_id)


def validate_power_reference(power, player_id):
    if power is not None:
        if type(power) is not HeroPowerReference:
            raise ValueError('Expected a captured HeroPowerReference')
        power.__post_init__()
        if power.player_id != player_id:
            raise ValueError('Power reference belongs to a different player')


def validate_additional_power_policy(policy):
    if type(policy) is not str or policy not in ('preserve', 'remove'):
        raise ValueError('Unknown additional hero power replacement policy')


@dataclass(frozen=True)
class ReplaceHero(Effect):
    player_id: int
    card_id: str
    armor: int = 0
    hero_power_card_id: str | None = None
    health: int | None = None
    additional_power_policy: str = 'preserve'

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        _integer(self.armor, 'armor', 0)
        if self.hero_power_card_id is not None:
            _behavior(self.hero_power_card_id)
        if self.health is not None:
            _integer(self.health, 'health', 1)
        validate_additional_power_policy(self.additional_power_policy)


@dataclass(frozen=True)
class RandomDestroy(Effect):
    candidate_ids: tuple[int, ...]
    source_id: int | None = None

    def __post_init__(self):
        if type(self.candidate_ids) is not tuple:
            raise ValueError('candidate_ids must be a tuple')
        for entity_id in self.candidate_ids:
            _integer(entity_id, 'candidate_id', 1)
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError('Duplicate random candidates')
        _source(self.source_id)


@dataclass(frozen=True)
class RandomReturnToHand(Effect):
    candidate_ids: tuple[int, ...]
    source_id: int | None = None

    def __post_init__(self):
        RandomDestroy(self.candidate_ids, self.source_id)


@dataclass(frozen=True)
class RandomDamage(Effect):
    candidate_ids: tuple[int, ...]
    amount: int
    source_id: int | None = None
    kind: DamageKind = DamageKind.EFFECT
    on_result: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_ids, tuple):
            raise ValueError("candidate_ids must be a tuple")
        for candidate_id in self.candidate_ids:
            _integer(candidate_id, "candidate_id", 1)
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate_ids must not contain duplicates")
        _integer(self.amount, "amount", 0)
        _source(self.source_id)
        _damage_kind(self.kind, self.source_id)
        _health_callback(self.on_result, self.source_id)


@dataclass(frozen=True)
class RandomDamageBatch(Effect):
    candidate_ids: tuple[int, ...]
    count: int
    amount: int
    source_id: int | None = None
    kind: DamageKind = DamageKind.EFFECT

    def __post_init__(self):
        RandomDamage(self.candidate_ids,self.amount,self.source_id,self.kind).__post_init__()
        _integer(self.count,'distinct random damage targets',1)


def _damage_kind(kind, source_id):
    if not isinstance(kind, DamageKind):
        raise ValueError('damage kind must be a DamageKind')
    if kind in (DamageKind.SPELL, DamageKind.COMBAT, DamageKind.HERO_POWER) and source_id is None:
        raise ValueError('This damage kind requires a source')
    if kind == DamageKind.FATIGUE and source_id is not None:
        raise ValueError('Fatigue damage has no source')


@dataclass(frozen=True)
class GrantSpellDamage(Effect):
    target_id: int
    amount: int
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        _integer(self.amount, 'spell damage amount', 1)


def _grant(target_id, source_id, expires_turn):
    _integer(target_id, 'target_id', 1)
    _source(source_id)
    if expires_turn is not None:
        _integer(expires_turn, 'expires_turn', 1)


def _behavior(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('behavior_id must be a nonempty string')


@dataclass(frozen=True)
class Silence(Effect):
    target_id: int
    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)


@dataclass(frozen=True)
class GrantKeyword(Effect):
    target_id: int
    keyword: Keyword
    source_id: int | None = None
    expires_turn: int | None = None
    duration: 'TimedKeywordSpec | None' = None
    reborn_policy: str | None = None
    def __post_init__(self):
        from .model import validate_reborn_policy
        validate_reborn_policy(self.reborn_policy, self.keyword)
        _grant(self.target_id, self.source_id, self.expires_turn)
        if not isinstance(self.keyword, Keyword):
            raise ValueError('keyword must be a Keyword')
        if self.keyword in (Keyword.DEATHRATTLE_SUPPRESSOR, Keyword.HERO_POWER_SUPPRESSOR):
            raise ValueError('Global prohibition currently requires a native minion source')
        if self.duration is not None:
            if type(self.duration) is not TimedKeywordSpec:
                raise ValueError('Expected TimedKeywordSpec')
            self.duration.__post_init__()
            if self.duration.keyword != self.keyword or self.expires_turn is not None:
                raise ValueError('Timed grants require a matching keyword and one expiry policy')


@dataclass(frozen=True)
class TriggerDeathrattles(Effect):
    target_id: int
    source_id: int | None = None
    times: int = 1

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        if self.source_id is not None: _integer(self.source_id, 'source_id', 1)
        _integer(self.times, 'Deathrattle trigger count', 1)


@dataclass(frozen=True)
class GrantDeathrattle(Effect):
    target_id: int
    behavior_id: str
    source_id: int | None = None
    expires_turn: int | None = None
    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        _behavior(self.behavior_id)


@dataclass(frozen=True)
class GrantTrigger(Effect):
    target_id: int
    event: str
    behavior_id: str
    source_id: int | None = None
    expires_turn: int | None = None
    end_turn: EndTurnSpec | None = None
    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        _behavior(self.behavior_id)
        if not isinstance(self.event, str) or not self.event.strip():
            raise ValueError('event must be a nonempty string')
        TriggerSpec(self.event,self.behavior_id,self.end_turn).__post_init__()


@dataclass(frozen=True)
class GrantAura(Effect):
    target_id: int
    attack: int = 0
    include_self: bool = False
    source_id: int | None = None
    expires_turn: int | None = None
    health: int = 0
    adjacent_only: bool = False
    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        _integer(self.attack, 'attack')
        _integer(self.health, 'health', 0)
        if type(self.include_self) is not bool:
            raise ValueError('include_self must be bool')
        if type(self.adjacent_only) is not bool or self.adjacent_only and self.include_self:
            raise ValueError('Adjacent aura requires a boolean and excludes its source')


@dataclass(frozen=True)
class RemoveEnchantment(Effect):
    target_id: int
    enchantment_id: int
    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.enchantment_id, 'enchantment_id', 1)


@dataclass(frozen=True)
class ReturnToHand(Effect):
    target_id: int
    to_owner: bool = False
    cost: CostSpec | None = None
    discard: object | None = None
    lock_next_owner_turn: bool = False
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        if type(self.to_owner) is not bool:
            raise ValueError('to_owner must be boolean')
        if type(self.lock_next_owner_turn) is not bool:
            raise ValueError('Returned-card play restriction requires a boolean')
        _source(self.source_id)
        if self.lock_next_owner_turn:
            _integer(self.source_id, 'returned-card lock source', 1)
            if self.discard is not None:
                raise ValueError('Returned-card lock requires an actual board-to-hand arrival')
        elif self.source_id is not None:
            raise ValueError('Ordinary return keeps its original source-free request')
        if self.cost is not None:
            if type(self.cost) is not CostSpec:
                raise ValueError('Return cost requires CostSpec')
            self.cost.__post_init__()
        if self.discard is not None:
            from .discard_history import material_value
            material_value(self.discard)
            if self.target_id != self.discard.entity_id or self.to_owner or self.cost is not None:
                raise ValueError('Retained discard return requires its original target and controller')


@dataclass(frozen=True)
class Transform(Effect):
    target_id: int
    card_id: str
    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        if not isinstance(self.card_id, str) or not self.card_id.strip():
            raise ValueError('card_id must be nonempty')


@dataclass(frozen=True)
class CopyMinion(Effect):
    target_id: int | BoardPresenceReference
    player_id: int
    position: int | None = None
    mode: str = 'current'
    cause: object = None
    stats: SummonStats | None = None
    allow_dormant: bool = False
    on_summon: str | None = None
    def __post_init__(self):
        if self.on_summon is not None:
            _behavior(self.on_summon)
            if self.cause is None: raise ValueError('Copy followup requires original card attribution')
        if type(self.allow_dormant) is not bool:
            raise ValueError('Dormant copy permission requires bool')
        validate_summon_stats(self.stats)
        if self.cause is not None:
            from .summon_quantities import SummonCause
            if type(self.cause)is not SummonCause:raise ValueError('Typed card copy cause required')
            self.cause.__post_init__()
        if type(self.target_id) is BoardPresenceReference:
            self.target_id.__post_init__()
        else:
            _integer(self.target_id, 'target_id', 1)
        _player(self.player_id)
        if self.position is not None:
            _integer(self.position, 'position', 0)
        if self.mode not in ('current', 'base'):
            raise ValueError('copy mode must be current or base')

    def validate_in_state(self, state):
        self.__post_init__()
        if type(self.target_id) is BoardPresenceReference and (
                self.target_id.entity_id not in state.entities or self.target_id.presence_id >= state.next_order):
            raise ValueError('Copy borrowed an unknown or future board residence')


@dataclass(frozen=True)
class FillBoardWithCopies(Effect):
    """Request current copies for the actual remaining board capacity."""
    target_id: int
    player_id: int

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _player(self.player_id)


@dataclass(frozen=True)
class ChangeControl(Effect):
    target_id: int
    player_id: int
    until_end_of_turn: bool = False
    source_id: int | None = None
    until_previous_controller_turn_end: bool = False
    cannot_attack_this_turn: bool = False
    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _player(self.player_id)
        if type(self.until_end_of_turn) is not bool:
            raise ValueError('Temporary control requires a boolean duration flag')
        if type(self.until_previous_controller_turn_end) is not bool or type(self.cannot_attack_this_turn) is not bool:
            raise ValueError('Owner-end control and attack restriction require boolean flags')
        if self.until_end_of_turn and self.until_previous_controller_turn_end:
            raise ValueError('Temporary control requires one original deadline policy')
        _source(self.source_id)
        if self.until_end_of_turn or self.until_previous_controller_turn_end:
            _integer(self.source_id, 'temporary control source', 1)
        elif self.source_id is not None or self.cannot_attack_this_turn:
            raise ValueError('Permanent control keeps its original source-free operation')


@dataclass(frozen=True)
class ShuffleIntoDeck(Effect):
    target_id: int
    player_id: int | None = None
    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        if self.player_id is not None:
            _player(self.player_id)
