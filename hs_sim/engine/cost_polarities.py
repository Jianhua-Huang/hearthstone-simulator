"""Native owner-start polarity, carried by the original removable cost aura.

The existing actual owner-start publication drives the change, not a second loop.
Each current copy retains this material; a printed/base installation starts odd.
The cost predicate freezes the pre-external price so its own floor cannot cycle.
"""
from dataclasses import dataclass, replace
from .model import CardType, CostAuraSpec, CostPolarityState, CostSpec, Zone

RELATION='friendly_polarity'
AURA=CostAuraSpec(CostSpec(delta=-2),relation=RELATION)


@dataclass(frozen=True)
class CostPolarityProfile:
    card_id: str


def validate_profile(registry, profile):
    if type(profile) is not CostPolarityProfile:
        raise ValueError('Typed native polarity declaration required')
    card=registry.card(profile.card_id)
    if (card.kind!=CardType.MINION or not card.hand_playable or card.starship_for or card.cost_auras!=(AURA,)):
        raise ValueError('Native polarity requires its ordinary two-cost friendly minion aura')


def initial_fields(registry, definition, spec):
    if spec.relation!=RELATION:return {}
    if registry is None or definition.id not in registry.cost_polarity_profiles or spec!=AURA:
        raise ValueError('Native polarity installation lost its actual registered source')
    return dict(cost_polarity=CostPolarityState(definition.id))


def validate_carrier(registry, card_id, kind, abilities, components=()):
    for a in abilities:
        native=a.kind=='cost_aura' and a.cost_aura.relation==RELATION
        if native != (a.cost_polarity is not None):
            raise ValueError('Native polarity lost its actual independent aura parameter')
        if not native:continue
        a.__post_init__()
        if (kind!=CardType.MINION or components or a.cost_polarity.card_id!=card_id or
                card_id not in registry.cost_polarity_profiles or a.cost_aura!=AURA):
            raise ValueError('Polarity borrowed an undeclared or composite physical carrier')


def started(r, event):
    if event.kind!='turn_started' or not r.registry.cost_polarity_profiles:return
    player=r.state.players.get(event.player_id)
    if player is None:return
    accepted=[]
    for identity in (*player.hand,*player.deck,*player.board):
        e=r.state.entities[identity]
        if e.silenced or (e.zone==Zone.BOARD and (not e.active or e.doomed or e.health<=0)):continue
        for a in e.abilities:
            if a.cost_polarity is not None and not a.consumed:accepted.append((e,a))
    if not accepted:return
    from .owner_turns import current_owner_turn
    owner=current_owner_turn(r.state)
    if (owner.origin!='actual' or owner.publication_event is not None or owner.player_id!=event.player_id or owner.turn!=dict(event.data).get('turn') or
            event.sequence>len(r.game._events) or r.game._events[event.sequence-1]!=event):
        raise ValueError('Native polarity requires the actual current owner start')
    changes=[]
    for e,a in accepted:
        validate_carrier(r.registry,e.card_id,e.kind,e.abilities,e.components)
        phase='even'if a.cost_polarity.phase=='odd'else'odd'
        changes.append((e,a,replace(a,cost_polarity=replace(a.cost_polarity,phase=phase))))
    # All accepted physical parameters advance before any ordinary start observer.
    for e,old,new in changes:e.abilities[e.abilities.index(old)]=new


def validate_basis(registry, contribution, amount=None):
    a=contribution.ability
    if a is None or a.cost_aura.relation!=RELATION:return
    native=a.cost_polarity
    if native is None or native.card_id not in registry.cost_polarity_profiles or a.cost_aura!=AURA:
        raise ValueError('Frozen polarity price lost its native declaration')
    native.__post_init__()
    if amount is not None and contribution.polarity_basis!=amount:
        raise ValueError('Polarity price lost its original pre-external operand')


def matches(registry, contribution):
    validate_basis(registry,contribution)
    return contribution.polarity_basis%2 == (1 if contribution.ability.cost_polarity.phase=='odd'else 0)


def public_polarity(entity):
    if entity.silenced:return None
    rows=[a for a in entity.abilities if a.cost_polarity is not None and not a.consumed]
    if len(rows)>1:raise ValueError('A native physical minion has one polarity')
    return None if not rows else rows[0].cost_polarity.phase


def validate_game(game):
    state,registry=game._state,game.registry
    for e in state.entities.values():
        validate_carrier(registry,e.card_id,e.kind,e.abilities,e.components)
        if e.card_id in registry.cost_polarity_profiles and not e.silenced and e.zone in (Zone.HAND,Zone.DECK,Zone.BOARD):
            rows=[a for a in e.abilities if a.cost_polarity is not None]
            if len(rows)!=1:
                raise ValueError('Native polarity lost its complete physical printed source')
