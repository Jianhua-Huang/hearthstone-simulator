"""Explicit experimental metadata; no official card-pool claims."""
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy, DeckSpec,
                           MatchSetup, Rarity, Registry, Runes)
from hs_sim.engine.effects import Damage, GainArmor, GainTemporaryMana


def metadata(card_class=CardClass.NEUTRAL, **kwargs):
    return CardMetadata(kwargs.pop('collectible', True), (card_class,), kwargs.pop('rarity', Rarity.COMMON), **kwargs)


def registry():
    r = Registry('opening-fixtures-v1')
    r.register_behavior('power', lambda c: [Damage(c.state.players[3 - c.player_id].hero_id, 1, c.source_id)])
    r.register_behavior('coin', lambda c: [GainTemporaryMana(c.player_id, 1)])
    for card_class in (CardClass.MAGE, CardClass.WARRIOR, CardClass.DEATH_KNIGHT):
        r.register_card(CardDefinition(card_class.value + '.power', 'Power', CardType.HERO_POWER, cost=2,
            on_use='power', metadata=metadata(card_class, collectible=False)))
        r.register_card(CardDefinition(card_class.value + '.hero', 'Hero', CardType.HERO, health=30,
            initial_hero_power=card_class.value + '.power', metadata=metadata(card_class, collectible=False)))
    r.register_card(CardDefinition('coin', 'Coin', CardType.SPELL, on_play='coin', metadata=metadata(collectible=False)))
    for i in range(1, 41):
        r.register_card(CardDefinition(f'card.{i}', f'Card {i}', CardType.MINION, cost=1, attack=4, health=4,
                                       metadata=metadata()))
    return r


def deck(card_class=CardClass.MAGE, cards=None, runes=None):
    return DeckSpec(card_class.value + '.hero', card_class.value + '.power', card_class,
                    tuple(f'card.{i}' for i in range(1, 31)) if cards is None else cards, runes)


def policy(r, **kwargs):
    return DeckPolicy('test-pool-v1', 'synthetic-test-target', 'experimental', tuple(r.cards), **kwargs)


def setup(r, first=1, seed=71, decks=None, **policy_fields):
    return MatchSetup(decks or (deck(), deck(CardClass.WARRIOR)), policy(r, **policy_fields), 'coin', seed, first)
