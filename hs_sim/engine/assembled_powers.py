"""Immutable passive power faces compiled from reviewed assembled minions.

The real template is incomplete without a chosen minion recipe. It is not an
executable blank power and is never inserted into a hand as an intermediate.
"""
from dataclasses import asdict, dataclass, fields
import base64
import binascii
import json

from .assemble_faces import PREFIX as MINION_PREFIX, recipe_from_id
from .model import CardDefinition, CardMetadata, CardType, Keyword, Zone, _name

PREFIX = 'assemble-power:'
VERSION = 'assembled-passive-power-v1'


@dataclass(frozen=True)
class AssembledPowerProfile:
    template_card_id: str
    source_card_id: str
    pool_id: str
    name: str
    metadata: CardMetadata
    reviewed_fragment_ids: tuple[str, ...]
    secondary_projection_ids: tuple[str, ...] = ()
    ignored_prefix_keywords: tuple[Keyword, ...] = ()

    def __post_init__(self):
        for key in ('template_card_id', 'source_card_id', 'pool_id', 'name'):
            _name(getattr(self, key), key)
        if self.template_card_id.startswith((PREFIX, MINION_PREFIX)):
            raise ValueError('Passive power requires a real original template identity')
        if type(self.metadata) is not CardMetadata or self.metadata.collectible:
            raise ValueError('Passive power template requires complete noncollectible metadata')
        self.metadata.__post_init__()
        if (type(self.reviewed_fragment_ids) is not tuple or not self.reviewed_fragment_ids or
                len(set(self.reviewed_fragment_ids)) != len(self.reviewed_fragment_ids)):
            raise ValueError('Passive power needs explicit unique reviewed fragment compatibility')
        for card_id in self.reviewed_fragment_ids:
            _name(card_id, 'reviewed passive assembly fragment')
        if (type(self.secondary_projection_ids) is not tuple or
                len(set(self.secondary_projection_ids)) != len(self.secondary_projection_ids) or
                not set(self.secondary_projection_ids) <= set(self.reviewed_fragment_ids)):
            raise ValueError('Passive projection roles require unique explicitly reviewed source identities')
        if (type(self.ignored_prefix_keywords) is not tuple or
                len(set(self.ignored_prefix_keywords)) != len(self.ignored_prefix_keywords) or
                any(type(k) is not Keyword or k not in (Keyword.ELUSIVE, Keyword.DIVINE_SHIELD)
                    for k in self.ignored_prefix_keywords)):
            raise ValueError('Passive conversion requires its explicit finite minion-keyword policy')


def profile_signature(profile):
    """Unused additive source policies retain the previous registry identity."""
    result = asdict(profile)
    for key in ('secondary_projection_ids', 'ignored_prefix_keywords'):
        if not result[key]:
            result.pop(key)
    return result


@dataclass(frozen=True)
class AssembledPowerRecipe:
    template_card_id: str
    minion_card_id: str
    version: str = VERSION

    def __post_init__(self):
        _name(self.template_card_id, 'passive power template')
        if self.template_card_id.startswith((PREFIX, MINION_PREFIX)) or self.version != VERSION:
            raise ValueError('Unsupported passive power recipe or recursive template')
        recipe_from_id(self.minion_card_id)

    @property
    def card_id(self):
        self.__post_init__()
        body = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        result = PREFIX+base64.urlsafe_b64encode(body).decode().rstrip('=')
        if len(result) > 8192:
            raise ValueError('Passive assembly identity exceeds its bounded recipe size')
        return result


def power_recipe_from_id(card_id):
    if type(card_id) is not str or not card_id.startswith(PREFIX) or len(card_id) > 8192:
        raise ValueError('Invalid passive assembly identity')
    token = card_id[len(PREFIX):]
    try:
        body = base64.b64decode(token+'='*(-len(token)%4), altchars=b'-_', validate=True)
        row = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError('Invalid passive assembly encoding') from exc
    if type(row) is not dict or set(row) != {'template_card_id', 'minion_card_id', 'version'}:
        raise ValueError('Passive assembly requires its complete original recipe')
    recipe = AssembledPowerRecipe(**row)
    if recipe.card_id != card_id:
        raise ValueError('Passive assembly identity is not canonical')
    return recipe


def validate_profile(registry, profile):
    if type(profile) is not AssembledPowerProfile:
        raise ValueError('Typed original passive power template required')
    profile.__post_init__()
    source = registry.card(profile.source_card_id)
    if source.kind != CardType.MINION or source.battlecry is None:
        raise ValueError('Passive assembly requires its original Battlecry minion')
    if profile.template_card_id in registry._cards:
        raise ValueError('Incomplete passive template cannot be registered as an executable blank')
    for cid in profile.reviewed_fragment_ids:
        validate_fragment(registry, profile, cid)


def passive_minion(card, ignored_keywords=()):
    """Refuse every declaration that this conversion would otherwise discard."""
    blank = CardDefinition(card.id, card.name, CardType.MINION)
    allowed = {'id', 'name', 'kind', 'cost', 'attack', 'health', 'metadata', 'triggers', 'keywords'}
    if (card.kind != CardType.MINION or not card.triggers or not set(card.keywords) <= set(ignored_keywords) or
            any(getattr(card, f.name) != getattr(blank, f.name)
                for f in fields(CardDefinition) if f.name not in allowed)):
        raise ValueError('Passive assembly contains unsupported native minion text or keywords')


def validate_fragment(registry, profile, card_id):
    if card_id not in profile.reviewed_fragment_ids:
        raise ValueError('Eligible passive assembly source lacks reviewed power-context compatibility: ' + card_id)
    if card_id in profile.secondary_projection_ids:
        from .assemble_faces import AssembleProjection, text_source
        projection = text_source(registry, card_id)
        if type(projection) is not AssembleProjection or projection.source_kind is not CardType.WEAPON:
            raise ValueError('Passive secondary role requires its original reviewed weapon-text projection')
        if projection.prefix.keywords or projection.prefix.spell_damage or projection.prefix.hand_actions:
            raise ValueError('Passive weapon projection contains unsupported non-trigger text')
    else:
        if card_id not in registry.assemble_templates:
            raise ValueError('Passive fragment compatibility needs its reviewed whole text halves')
        passive_minion(registry.card(card_id), profile.ignored_prefix_keywords)


def validate_extension(registry, original, extended):
    validate_profile(registry, extended)
    if (any(getattr(original, key) != getattr(extended, key) for key in
            ('template_card_id', 'source_card_id', 'pool_id', 'name', 'metadata')) or
            extended.reviewed_fragment_ids[:len(original.reviewed_fragment_ids)] != original.reviewed_fragment_ids or
            not set(original.secondary_projection_ids) <= set(extended.secondary_projection_ids) or
            not set(original.ignored_prefix_keywords) <= set(extended.ignored_prefix_keywords)):
        raise ValueError('Passive source extension cannot change or remove existing template compatibility')


def active_power_source(context):
    """An actual approved passive carrier, not an arbitrary zero-health body."""
    source = context.source
    if (source.kind is not CardType.HERO_POWER or source.zone is not Zone.HERO_POWER or
            not source.active or source.doomed or
            context.state.players[source.controller].hero_power_id != source.id or
            not source.card_id.startswith(PREFIX)):
        return False
    # Ordinary RuleContext.trigger is intentionally None. The existing
    # CheckHeroPowerTrigger validates its captured listener ID; installation
    # and the immutable wrapper validate the complete registered power face.
    power_recipe_from_id(source.card_id)
    return context.event is not None and any(a.kind == 'trigger' and not a.consumed and
        a.event == context.event.kind for a in source.abilities)


def request_profile(registry, state, spec):
    profile = registry.assembled_power_profiles.get(spec.passive_power_template_id)
    if profile is None:
        raise ValueError('Unknown original passive assembly template')
    validate_profile(registry, profile)
    source = state.entities.get(spec.source_id)
    # An accepted historical Battlecry may legally execute on another carrier.
    # The trusted card adapter supplies this declared profile; source_id binds
    # the physical cause and cannot be treated as an original-print identity.
    if source is None or spec.pool_id != profile.pool_id:
        raise ValueError('Passive assembly changed its original source or curated pool')
    return profile


def power_id(registry, template_card_id, minion_card_id):
    result = AssembledPowerRecipe(template_card_id, minion_card_id).card_id
    registry.card(result)
    return result


def resolve_face(registry, card_id):
    from .registry import UnsupportedDefinitionError
    try:
        recipe = power_recipe_from_id(card_id)
        profile = registry.assembled_power_profiles[recipe.template_card_id]
        validate_profile(registry, profile)
        minion_recipe = recipe_from_id(recipe.minion_card_id)
        if not {minion_recipe.primary_card_id, minion_recipe.secondary_card_id} <= set(profile.reviewed_fragment_ids):
            raise ValueError('Passive assembly lacks review of its native power carrier context')
        minion = registry.card(recipe.minion_card_id)
        passive_minion(minion, profile.ignored_prefix_keywords)
        card = CardDefinition(card_id, profile.name, CardType.HERO_POWER,
            passive_hero_power=True, triggers=minion.triggers, metadata=profile.metadata)
        registry._validate_card(card)
        return card
    except (ValueError, TypeError, KeyError) as exc:
        raise UnsupportedDefinitionError('Unsupported assembled passive power: '+str(exc)) from exc


def validate_profiles(registry):
    for key, profile in registry.assembled_power_profiles.items():
        if key != profile.template_card_id:
            raise ValueError('Passive power template changed its original identity')
        validate_profile(registry, profile)
    if any(cid.startswith(PREFIX) for cid in registry._cards):
        raise ValueError('Passive assembly identities cannot contain registered substitutes')
