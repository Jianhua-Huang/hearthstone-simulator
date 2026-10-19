"""Original Dark Gift notifications and one native stored receiver's copy.

Copies keep gift provenance without becoming another original grant. Sweet
Dreams delegates movement to the ordinary physical-card operation.
"""
from dataclasses import dataclass
from types import SimpleNamespace

from .effects import Effect, _integer
from .model import CardType, Event, Zone
from .zones import CardReference


def gift_for_grant(grant):
    from .dark_gifts import DARK_GIFTS
    from dataclasses import replace
    gift = next((g for g in DARK_GIFTS if g.id == grant.identity), None)
    if gift is not None and grant != replace(gift.grant, identity=gift.id):
        raise ValueError('A named Dark Gift must keep its complete original recipe')
    return gift


def validate_ability(ability):
    from .dark_gifts import DARK_GIFTS, LIVING_NIGHTMARE_BEHAVIOR
    from .model import BattlecryRepeatSpec
    gift = next((g for g in DARK_GIFTS if g.id == ability.dark_gift_id), None)
    if gift is None or ability.origin != 'granted' or not ability.remove_on_silence:
        raise ValueError('Dark Gift ability lost its real granted recipe')
    valid = (ability.kind == 'keyword' and ability.keyword in gift.grant.keywords and
             ability.reborn_policy == (gift.grant.reborn_policy if ability.keyword.value == 'reborn' else None))
    valid |= (gift.grant.special == 'living_nightmare' and ability.kind == 'on_play' and
              ability.behavior_id == LIVING_NIGHTMARE_BEHAVIOR)
    valid |= (gift.grant.special == 'rude_awakening' and ability.kind == 'battlecry_repeat' and
              ability.battlecry_repeat == BattlecryRepeatSpec(2, (CardType.MINION,), scope='self'))
    if not valid:
        raise ValueError('Dark Gift provenance cannot label an unrelated ability')


def publish(r, entity, gift, source_id):
    r.emit('dark_gift_granted', source_id=source_id, target_id=entity.id,
           player_id=entity.controller, gift_id=gift.id, recipient_kind=CardType.MINION.value)


def original_gift(state, event):
    from .dark_gifts import DARK_GIFTS
    if type(event) is not Event or event.kind != 'dark_gift_granted':
        raise ValueError('Dark Gift copy requires its original grant event')
    gift_id = dict(event.data).get('gift_id')
    gift = next((g for g in DARK_GIFTS if g.id == gift_id), None)
    target = state.entities.get(event.target_id)
    if (gift is None or target is None or dict(event.data).get('recipient_kind') != CardType.MINION.value or
            event.player_id not in (1, 2)):
        raise ValueError('Dark Gift copy lost its original minion or gift identity')
    return gift


@dataclass(frozen=True)
class CopyReceivedDarkGift(Effect):
    card: CardReference
    event: Event

    def __post_init__(self):
        if type(self.card) is not CardReference or type(self.event) is not Event:
            raise ValueError('Dark Gift echo requires a physical stored card and original event')
        self.card.__post_init__()
        _integer(self.event.sequence, 'original Dark Gift event sequence', 1)
        if self.event.kind != 'dark_gift_granted' or self.event.player_id != self.card.player_id:
            raise ValueError('Dark Gift echo cannot borrow another player or a copy notification')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        gift = original_gift(state, self.event)
        card = registry.card(self.card.card_id)
        spec = card.hand_progress
        if (card.kind != CardType.MINION or spec is None or spec.zones != (Zone.HAND, Zone.DECK) or
                spec.event_kind != self.event.kind or not spec.repeat):
            raise ValueError('Dark Gift echo requires its declared native stored receiver')
        return gift


def keep_gifts_on_own_sweet_dreams(r, entity):
    """32.2 retains only actual gifts, including the gift part of a mixed price.

Creation may combine a source discount with Horrific Claws in one cost row.
Rebuild the fixed gift cost from each original gift marker, never keep the
combined source discount or infer keyword provenance from its current value.
"""
    from .dark_gifts import DARK_GIFTS
    from .lifecycle import reset_to_definition, attachment_id
    from .model import CostSpec, Enchantment
    by_id = {g.id: g for g in DARK_GIFTS}
    prefix = 'created_minion_grant:'
    kept = [e for e in entity.enchantments if e.label.startswith(prefix) and e.label[len(prefix):] in by_id]
    abilities = [a for a in entity.abilities if a.dark_gift_id is not None]
    reset_to_definition(r.state, entity, r.registry.card(entity.card_id), r.registry)
    entity.enchantments.extend(kept)
    entity.abilities.extend(abilities)
    for marker in kept:
        gift = by_id[marker.label[len(prefix):]]
        if gift.cost_delta:
            entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=marker.source_id,
                cost=gift.cost_delta, label='dark_gift_cost:' + gift.id))


def copy_received(r, effect):
    from dataclasses import replace
    from .card_creation import install
    from .lifecycle import attachment_id
    from .model import CostSpec, Enchantment
    from .zones import MoveCard, reference_entity
    gift = effect.validate_in_state(r.state, r.registry)
    if (effect.event.sequence > len(r.game._events) or
            r.game._events[effect.event.sequence - 1] != effect.event):
        raise ValueError('Dark Gift echo requires the actual committed grant witness')
    entity = reference_entity(r, effect.card)
    if entity is None:
        return ()
    if entity.kind != CardType.MINION:
        raise ValueError('Dark Gift echo requires its native minion')
    to_deck = gift.destination == 'deck_top' and entity.zone == Zone.HAND
    if to_deck:
        keep_gifts_on_own_sweet_dreams(r, entity)
    if gift.cost_delta:
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=entity.id,
            cost=gift.cost_delta, label='dark_gift_cost:' + gift.id))
    install(r.state, entity, SimpleNamespace(spell_repeat=None, source_id=entity.id,
        minion_grant=replace(gift.grant, identity=gift.id)), resolver=r, publish_gift=False)
    r.refresh_auras()
    r.emit('dark_gift_copied', source_id=entity.id, target_id=entity.id,
           player_id=entity.controller, gift_id=gift.id, grant_event=effect.event.sequence)
    return (MoveCard(CardReference.capture(entity), entity.controller, Zone.DECK,
                     position='top', source_id=entity.id),) if to_deck else ()


def register(mechanics):
    mechanics.register(CopyReceivedDarkGift, copy_received)
