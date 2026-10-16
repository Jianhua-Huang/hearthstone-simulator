"""Immutable creation-time attachments, installed before acquisition events (R-134)."""
from dataclasses import dataclass, fields, is_dataclass

from .construction import integer, name
from .errors import ResolutionError
from .model import (CardType, ChooseBranchSelection, Keyword, SummonStats,
                    validate_reborn_policy, validate_summon_stats)


# Only the basic keyword grants required by known constructed Dark Gifts.
# Other stored grants keep their own existing API; this is not an effect program.
MINION_CREATION_KEYWORDS = frozenset((Keyword.TAUNT, Keyword.DIVINE_SHIELD,
    Keyword.CHARGE, Keyword.WINDFURY, Keyword.REBORN, Keyword.LIFESTEAL, Keyword.ELUSIVE))


@dataclass(frozen=True)
class CreatedMinionGrant:
    attack: int = 0
    health: int = 0
    keywords: tuple[Keyword, ...] = ()
    reborn_policy: str | None = None
    identity: str | None = None
    special: str | None = None

    def __post_init__(self):
        if type(self.attack) is not int or type(self.health) is not int:
            raise ValueError('Created minion stats require integers')
        if (type(self.keywords) is not tuple or
                any(type(k) is not Keyword or k not in MINION_CREATION_KEYWORDS for k in self.keywords) or
                len(set(self.keywords)) != len(self.keywords)):
            raise ValueError('Unsupported or duplicate created minion keyword')
        validate_reborn_policy(self.reborn_policy, Keyword.REBORN if Keyword.REBORN in self.keywords else None)
        if self.identity is not None:name(self.identity, 'created minion grant identity')
        if self.special is not None and (type(self.special) is not str or
                self.special not in ('living_nightmare', 'rude_awakening')):
            raise ValueError('Unknown created minion special ability')
        if not (self.attack or self.health or self.keywords or self.special):
            raise ValueError('Created minion grant must change stats or keywords')


def validate_minion_grant(value):
    if value is not None:
        if type(value) is not CreatedMinionGrant:
            raise ValueError('Expected CreatedMinionGrant')
        value.__post_init__()


@dataclass(frozen=True)
class CreatedMinionStats:
    """One numeric recipe for a freshly allocated hand/deck minion."""
    set_to: SummonStats | None = None
    double: bool = False

    def __post_init__(self):
        validate_summon_stats(self.set_to)
        if type(self.double) is not bool or (self.set_to is not None) == self.double:
            raise ValueError('Created minion stats require exactly one replacement or doubling')
        if self.set_to is not None and (self.set_to.attack is None or self.set_to.health is None):
            raise ValueError('Created minion stats require both Attack and Health')


def validate_minion_stats(value):
    if value is not None:
        if type(value) is not CreatedMinionStats:
            raise ValueError('Expected CreatedMinionStats')
        value.__post_init__()


@dataclass(frozen=True)
class DiscoveryMinionGift:
    """A finite creation recipe, not a dynamically granted effect program."""
    id: str
    label: str
    grant: CreatedMinionGrant
    cost_delta: int = 0
    min_attack: int = 0
    destination: str = 'hand'

    def __post_init__(self):
        name(self.id, 'discovery gift ID');name(self.label, 'discovery gift label')
        if type(self.grant) is not CreatedMinionGrant:
            raise ValueError('Unsupported discovery gift body')
        self.grant.__post_init__()
        if self.grant.identity is not None:
            raise ValueError('Discovery gift identity belongs to its enclosing recipe')
        if type(self.cost_delta) is not int or self.cost_delta > 0:
            raise ValueError('Discovery gift cost requires an integer reduction')
        integer(self.min_attack, 'minimum printed gift Attack', 0)
        if type(self.destination) is not str or self.destination not in ('hand','deck_top'):
            raise ValueError('Gift destination must be hand or deck_top')

    def eligible(self, definition):
        if definition.kind != CardType.MINION or definition.attack < self.min_attack:
            return False
        if set(self.grant.keywords).intersection(definition.keywords):
            return False
        if Keyword.CHARGE in self.grant.keywords and definition.attack == 0:
            return False
        return self.grant.special != 'rude_awakening' or definition.battlecry is not None


@dataclass(frozen=True)
class CardSpellRepeatGrant:
    casts: int = 2
    expires_turn: int | None = None

    def __post_init__(self):
        integer(self.casts, 'created spell casts', 2)
        if self.expires_turn is not None:
            integer(self.expires_turn, 'created spell repeat expiry')


def validate_declaration(spec):
    if spec is not None:
        if type(spec) is not CardSpellRepeatGrant:
            raise ValueError('Creation spell repetition requires CardSpellRepeatGrant')
        spec.__post_init__()


def validate_branch_declaration(value, card_id):
    if value is not None:
        if type(value) is not ChooseBranchSelection:
            raise ValueError('Created preselection requires ChooseBranchSelection')
        value.__post_init__()
        if value.card_id != card_id:
            raise ValueError('Created preselection belongs to another card face')


def validate_branch_transfer(policy, value, mapping):
    if type(policy) is not str or policy not in ('clear', 'inherit'):
        raise ValueError('Unknown replacement branch policy')
    if policy == 'inherit' and value is not None:
        raise ValueError('Inherited replacement cannot also prescribe another branch')
    if mapping is not None:
        if policy != 'inherit' or type(mapping) is not tuple or not mapping:
            raise ValueError('Branch mapping requires an explicit inherited replacement')
        if any(type(pair) is not tuple or len(pair) != 2 or
                any(type(s) is not str or not s.strip() for s in pair) for pair in mapping):
            raise ValueError('Branch mapping requires immutable pairs of branch IDs')
        if len({a for a,b in mapping}) != len(mapping) or len({b for a,b in mapping}) != len(mapping):
            raise ValueError('Branch mapping cannot duplicate source or target branches')


def validate_combined_shatter(value):
    if type(value)is not bool:raise ValueError('Combined Shatter creation requires a boolean declaration')


def validate_spell_damage_grant(amount, source_id):
    integer(amount, 'created local Spell Damage', 0)
    if amount and source_id is None:
        raise ValueError('Created local Spell Damage requires its original source')


def validate_candidates(effect, definitions):
    combined=getattr(effect,'combined_shatter',False)
    validate_combined_shatter(combined)
    spec = getattr(effect, 'spell_repeat', None)
    validate_declaration(spec)
    selection = getattr(effect, 'choose_branch', None)
    grant = getattr(effect, 'minion_grant', None)
    validate_minion_grant(grant)
    stats = getattr(effect, 'minion_stats', None)
    validate_minion_stats(stats)
    if stats is not None and (grant is not None or spec is not None or selection is not None or
            getattr(effect,'combined_shatter',False) or getattr(effect,'spell_damage',0) or
            effect.source_id is None):
        raise ResolutionError('Created minion numeric recipe requires a separate source-bound declaration')
    spell_damage = getattr(effect, 'spell_damage', 0)
    validate_spell_damage_grant(spell_damage, effect.source_id)
    if spec is None and selection is None and grant is None and stats is None and not spell_damage and not combined: return
    definitions = tuple(definitions)
    if combined and any(d.kind!=CardType.SPELL or d.shatter is None or Keyword.SHATTER not in d.keywords for d in definitions):
        raise ResolutionError('Every combined Shatter creation candidate must be a native whole spell')
    if spell_damage and any(d.kind != CardType.SPELL for d in definitions):
        raise ResolutionError('Created local Spell Damage requires a spell carrier')
    if grant is not None and any(d.kind != CardType.MINION for d in definitions):
        raise ResolutionError('Every created grant carrier must be a minion')
    if stats is not None and any(d.kind != CardType.MINION for d in definitions):
        raise ResolutionError('Every created numeric carrier must be a minion')
    if spec is not None and any(d.kind != CardType.SPELL for d in definitions):
        raise ResolutionError('Every created repeat carrier must be a spell')
    if selection is not None:
        from .choose_branch_state import validate_selection_for_card
        for card in definitions: validate_selection_for_card(card, selection)


def validate_creation(state, effect, definitions=()):
    validate_candidates(effect, definitions)
    spec = getattr(effect, 'spell_repeat', None)
    if (spec is None and getattr(effect, 'minion_grant', None) is None and getattr(effect,'minion_stats',None) is None and
            not getattr(effect, 'spell_damage', 0) and not getattr(effect,'combined_shatter',False)):
        return
    if effect.source_id is not None and effect.source_id not in state.entities:
        raise ResolutionError('Creation attachment source does not exist')
    if spec is not None and spec.expires_turn is not None and spec.expires_turn < state.turn:
        raise ResolutionError('Creation spell repetition has already expired')


def install(state, entity, effect):
    """The caller owns the newly allocated entity, including a burned result.

    Like creation costs, this emits no intermediate acquisition/attachment event.
    The first card_created observer receives the complete card.
    """
    if getattr(effect,'combined_shatter',False):
        from .lifecycle import consume_keyword
        consume_keyword(entity,Keyword.SHATTER)
    spec = effect.spell_repeat
    if spec is not None:
        from .card_spell_repeats import attach
        attach(state, entity, spec.casts, effect.source_id, spec.expires_turn)
    selection = getattr(effect, 'choose_branch', None)
    if selection is not None: entity.choose_branch = selection
    spell_damage = getattr(effect, 'spell_damage', 0)
    if spell_damage:
        from .stored_spell_damage import attach_local_bonus
        attach_local_bonus(state, entity, spell_damage, effect.source_id)
    stats = getattr(effect, 'minion_stats', None)
    if stats is not None:
        from .lifecycle import attachment_id, refresh_entity
        from .model import Enchantment
        if stats.set_to is not None:
            numeric = dict(set_attack=stats.set_to.attack, set_health=stats.set_to.health)
        else:
            # Freeze actual fresh undamaged values once, as DoubleStats does.
            numeric = dict(attack=entity.attack, health=entity.health)
        entity.enchantments.append(Enchantment(attachment_id(state), source_id=effect.source_id,
            label='created_minion_stats', **numeric))
        refresh_entity(entity)
    grant = getattr(effect, 'minion_grant', None)
    if grant is not None:
        # The generated physical entity is already known, including a burned
        # result. Install everything before the first acquisition event.
        from .lifecycle import attachment_id, refresh_entity
        from .model import AbilityInstance, Enchantment
        if grant.attack or grant.health or grant.identity is not None:
            entity.enchantments.append(Enchantment(attachment_id(state), source_id=effect.source_id,
                attack=grant.attack, health=grant.health,
                label='created_minion_grant' if grant.identity is None else 'created_minion_grant:'+grant.identity))
        for keyword in grant.keywords:
            entity.abilities.append(AbilityInstance(attachment_id(state), 'keyword', source_id=effect.source_id,
                keyword=keyword, reborn_policy=grant.reborn_policy if keyword == Keyword.REBORN else None))
        if grant.special == 'living_nightmare':
            from .dark_gifts import LIVING_NIGHTMARE_BEHAVIOR
            entity.abilities.append(AbilityInstance(attachment_id(state), 'on_play',
                source_id=effect.source_id, behavior_id=LIVING_NIGHTMARE_BEHAVIOR))
        elif grant.special == 'rude_awakening':
            from .model import BattlecryRepeatSpec
            entity.abilities.append(AbilityInstance(attachment_id(state), 'battlecry_repeat',
                source_id=effect.source_id,
                battlecry_repeat=BattlecryRepeatSpec(2, (CardType.MINION,), scope='self')))
        refresh_entity(entity)


def validate_boundary(game):
    """Check declarations nested in suspended branches, including deferred delivery."""
    from .effects import AddToHand
    from .zones import AddToDeck
    from .pools import DiscoverFromPool, GenerateFromPool
    from .effects import ReplaceHeroPower
    from .hero_powers import AddHeroPower, installation_definition
    from types import SimpleNamespace
    def visit(value):
        if type(value) in (AddToHand, AddToDeck, DiscoverFromPool, GenerateFromPool):
            definitions = (game.registry.card(value.card_id),) if type(value) in (AddToHand, AddToDeck) else ()
            validate_creation(game._state, value, definitions)
        if type(value) in (AddHeroPower, ReplaceHeroPower) and (value.choose_branch is not None or
                getattr(value, 'branch_policy', 'clear') != 'clear' or getattr(value, 'branch_map', None) is not None):
            installation_definition(SimpleNamespace(state=game._state, registry=game.registry), value)
        if is_dataclass(value):
            for field in fields(value):
                visit(getattr(value, field.name))
        elif type(value) is tuple:
            for item in value:
                visit(item)
    if game._frame is not None:
        visit(game._frame)
