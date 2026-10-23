"""Native removable corpse gain providers; base death credit stays intrinsic."""
from collections import Counter
from dataclasses import dataclass

from .lifecycle import active_abilities
from .model import AbilityInstance, CardType, Zone, _int, _name


@dataclass(frozen=True)
class CorpseGainProfile:
    card_id: str
    multiplier: int = 2

    def __post_init__(self):
        _name(self.card_id, 'corpse gain declaration')
        _int(self.multiplier, 'corpse gain multiplier', 2)


def validate_profile(registry, profile):
    if type(profile) is not CorpseGainProfile:
        raise ValueError('Corpse gains require their native typed declaration')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    if card.kind != CardType.MINION or card.starship_for or card.choice_only:
        raise ValueError('Native corpse gain provider requires an ordinary minion face')


def validate_ability(registry, ability):
    ability.__post_init__()
    if ability.kind == 'corpse_gain':
        profile = registry.corpse_gain_profiles.get(ability.corpse_gain_card_id)
        if profile is None:
            raise ValueError('Corpse gain ability lost its registered native declaration')
        validate_profile(registry, profile)


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'corpse_gain')
    if not rows:
        return
    if kind != CardType.MINION:
        raise ValueError('Corpse gain source requires its original minion carrier')
    declared=Counter(cid for source in (card_id,*components)for cid in declaration_ids(registry,source))
    installed=Counter()
    for ability in rows:
        validate_ability(registry, ability)
        installed[ability.corpse_gain_card_id] += 1
        if installed[ability.corpse_gain_card_id] > declared[ability.corpse_gain_card_id]:
            raise ValueError('Duplicate or foreign printed corpse gain source')


def declaration_ids(registry,card_id):
    if card_id.startswith('assemble:'):
        from .assemble_corpse_prefixes import assembled_gain_ids
        return assembled_gain_ids(registry,card_id)
    return (card_id,)if card_id in registry.corpse_gain_profiles else ()


def gain_amount(state, registry, player_id, base):
    """Evaluate actual surviving providers at the credit window, once per gain."""
    _int(base, 'base corpse gain', 0)
    amount = base
    if not base:
        return 0
    for entity_id in state.players[player_id].board:
        entity = state.entities[entity_id]
        if (entity.zone != Zone.BOARD or entity.kind != CardType.MINION or
                entity.controller != player_id or entity.silenced or entity.doomed or entity.health <= 0):
            continue
        for ability in active_abilities(entity, 'corpse_gain'):
            validate_ability(registry, ability)
            amount *= registry.corpse_gain_profiles[ability.corpse_gain_card_id].multiplier
    return amount
