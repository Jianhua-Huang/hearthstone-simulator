"""Persistent grants to captured hand/deck cards, separate from live hand auras."""
from dataclasses import dataclass

from .effects import Effect
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import AbilityInstance, CardType, Keyword, _optional_id, validate_reborn_policy
from .zones import CardReference, reference_entity, reference_value, source_exists


STORED_KEYWORDS = frozenset((Keyword.TAUNT, Keyword.DIVINE_SHIELD, Keyword.CHARGE,
    Keyword.RUSH, Keyword.WINDFURY, Keyword.MEGA_WINDFURY, Keyword.POISONOUS, Keyword.IMMUNE, Keyword.REBORN,
    Keyword.LIFESTEAL, Keyword.STEALTH, Keyword.ELUSIVE, Keyword.ECHO))


@dataclass(frozen=True)
class GrantStoredKeyword(Effect):
    card: CardReference
    keyword: Keyword
    source_id: int | None = None
    expires_turn: int | None = None
    reborn_policy: str | None = None

    def __post_init__(self):
        validate_reborn_policy(self.reborn_policy, self.keyword)
        reference_value(self.card)
        if type(self.keyword) is not Keyword or self.keyword not in STORED_KEYWORDS:
            raise ValueError('Unsupported stored-card keyword grant')
        _optional_id(self.source_id, 'stored keyword source')
        _optional_id(self.expires_turn, 'stored keyword expiry')


def grant_stored_keyword(r, effect):
    effect.__post_init__()
    source_exists(r, effect.source_id)
    entity = reference_entity(r, effect.card)
    if entity is None:
        return
    if entity.kind != CardType.MINION and not (entity.kind == CardType.SPELL and effect.keyword == Keyword.ECHO):
        raise ResolutionError('Stored keywords require a minion, or Echo on a spell')
    if effect.expires_turn is not None and effect.expires_turn < r.state.turn:
        raise ResolutionError('Stored keyword grant already expired')
    entity.abilities.append(AbilityInstance(attachment_id(r.state), 'keyword', keyword=effect.keyword,
        source_id=effect.source_id, expires_turn=effect.expires_turn, reborn_policy=effect.reborn_policy))
    refresh_entity(entity)
    r.emit('stored_keyword_granted', source_id=effect.source_id, target_id=entity.id,
           player_id=entity.controller)


def register(mechanics):
    mechanics.register(GrantStoredKeyword, grant_stored_keyword)
