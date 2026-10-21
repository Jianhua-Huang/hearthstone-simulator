"""Finite native weapon Lifesteal recipients in the original health batch."""
from dataclasses import dataclass

from .model import CardType, DamageKind, Keyword, Zone, _name


@dataclass(frozen=True)
class LifestealRecipientProfile:
    card_id: str
    recipients: str = 'both_heroes'

    def __post_init__(self):
        _name(self.card_id, 'native Lifesteal recipient source')
        if type(self.recipients) is not str or self.recipients != 'both_heroes':
            raise ValueError('Unsupported native Lifesteal recipient policy')


def validate_profile(registry, profile):
    if type(profile) is not LifestealRecipientProfile:
        raise ValueError('Typed native Lifesteal recipient declaration required')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if card.kind != CardType.WEAPON or Keyword.LIFESTEAL not in card.keywords:
        raise ValueError('Native two-hero Lifesteal requires its original Lifesteal weapon')


def targets(state, registry, packet):
    """Read the batch-start source, without depending on its later survival.

    Weapon keywords on a hero only contribute to its COMBAT damage. Ordinary
    spell, minion, hero-power and other hero damage retain their own recipients.
    Both restorations retain the actual source's healing kind and controller.
    """
    owner = packet.source_controller
    ordinary = (state.players[owner].hero_id,)
    if not registry.lifesteal_recipient_profiles: return ordinary
    source = state.entities.get(packet.source_id)
    if source is not None and source.kind == CardType.HERO and packet.damage_kind == DamageKind.COMBAT:
        source = state.entities.get(state.players[owner].weapon_id)
        if source is not None and (source.zone != Zone.WEAPON or source.controller != owner):
            raise ValueError('Native Lifesteal lost its original equipped weapon')
    if source is None or source.kind != CardType.WEAPON: return ordinary
    profile = registry.lifesteal_recipient_profiles.get(source.card_id)
    if profile is None: return ordinary
    validate_profile(registry, profile)
    return (*ordinary, state.players[3-owner].hero_id)
