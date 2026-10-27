"""A monotonic native face change in hand/deck from actual owner launch history."""
from dataclasses import dataclass

from .model import CardType, Zone

ACQUISITIONS = frozenset(('starship_launched','card_created','card_added_to_hand','card_moved_to_hand',
    'card_drawn','card_returned','card_added_to_deck','stored_card_transformed','hand_card_upgraded'))


@dataclass(frozen=True)
class StoredLaunchFormProfile:
    card_id: str
    form_card_id: str

    def __post_init__(self):
        if (type(self.card_id) is not str or not self.card_id or type(self.form_card_id) is not str or
                not self.form_card_id or self.card_id == self.form_card_id):
            raise ValueError('Stored launch form requires its two distinct native identities')


def validate_profile(registry, profile):
    if type(profile) is not StoredLaunchFormProfile: raise ValueError('Typed stored launch form required')
    profile.__post_init__(); root = registry.card(profile.card_id); form = registry.card(profile.form_card_id)
    if (root.kind != CardType.MINION or form.kind != CardType.MINION or root.starship_for or form.starship_for or
            not root.hand_playable or not form.hand_playable or
            (root.cost,root.attack,root.health,root.metadata.classes,root.metadata.tribes) !=
            (form.cost,form.attack,form.health,form.metadata.classes,form.metadata.tribes)):
        raise ValueError('Stored launch form must retain its complete native printed body and type')
    if profile.form_card_id in registry.stored_launch_form_profiles:
        raise ValueError('Stored launch forms are terminal, not a speculative transformation chain')


def candidates(state, registry):
    launched = {row.player_id for row in state.starship_history}
    for pid in (state.active_player,3-state.active_player):
        if pid not in launched: continue
        for zone in (Zone.HAND,Zone.DECK):
            for eid in tuple(getattr(state.players[pid],zone.value)):
                entity = state.entities[eid]
                if entity.card_id in registry.stored_launch_form_profiles and not entity.silenced:
                    yield entity,registry.stored_launch_form_profiles[entity.card_id]


def synchronize(r, event):
    if (not r.registry.stored_launch_form_profiles or event.kind not in ACQUISITIONS or
            getattr(r,'_synchronizing_stored_launch_forms',False) or not r.state.starship_history): return
    from .hand_upgrades import upgrade_face
    from .cross_zone import announce_stored_transform
    rows = tuple(candidates(r.state,r.registry))
    # Complete the entire native change before the first notification captures
    # a view. Ordinary owner-private transform events keep deck/hand isolation.
    r._synchronizing_stored_launch_forms = True
    try:
        for entity,profile in rows: upgrade_face(r,entity,profile.form_card_id)
        for entity,profile in rows: announce_stored_transform(r,entity,profile.card_id,source_id=entity.id)
    finally:
        r._synchronizing_stored_launch_forms = False


def validate_game(game):
    if game.registry.stored_launch_form_profiles and any(candidates(game._state,game.registry)):
        raise ValueError('Stored native form ignored its actual original owner launch history')
