"""Immutable passive power faces compiled from reviewed assembled minions.

The real template is incomplete without a chosen minion recipe. It is not an
executable blank power and is never inserted into a hand as an intermediate.
"""
from dataclasses import asdict, dataclass, fields
import base64
import binascii
import json

from .assemble_faces import PREFIX as MINION_PREFIX, recipe_from_id
from .model import CardDefinition, CardMetadata, CardType, _name

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
        if cid not in registry.assemble_templates:
            raise ValueError('Passive fragment compatibility needs its reviewed whole text halves')
        passive_minion(registry.card(cid))


def passive_minion(card):
    """Refuse every declaration that this conversion would otherwise discard."""
    blank = CardDefinition(card.id, card.name, CardType.MINION)
    allowed = {'id', 'name', 'kind', 'cost', 'attack', 'health', 'metadata', 'triggers'}
    if (card.kind != CardType.MINION or not card.triggers or
            any(getattr(card, f.name) != getattr(blank, f.name)
                for f in fields(CardDefinition) if f.name not in allowed)):
        raise ValueError('Passive assembly contains unsupported native minion text or keywords')


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
        passive_minion(minion)
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
