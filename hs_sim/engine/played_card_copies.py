"""Printed non-minion hand copies of committed physical hand-play faces.

The existing immutable face is the identity proof, not the entity's later face,
zone or controller. Minions retain their existing richer intrinsic recipe.
Allocation, copy attribution, hand notification and overflow use CopyCard.
"""
from .model import CardType, Entity, FrozenPlayedFaceFact, Zone


def original_entity(state, registry, face):
    if type(face) is not FrozenPlayedFaceFact:
        raise ValueError('Played card copy requires the original frozen hand face')
    from .owner_turns import validate_face
    validate_face(face, registry)
    if face.kind not in (CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO):
        raise ValueError('Played minions require their complete intrinsic copy material')
    if not 1 <= face.play_id <= len(state.play_history):
        raise ValueError('Played card copy lost its committed physical hand root')
    row = state.play_history[face.play_id - 1]
    if row.played_face != face or (row.id, row.source_id, row.player_id, row.card_id, row.kind) != (
            face.play_id, face.source_id, face.player_id, face.card_id, face.kind):
        raise ValueError('Played card copy borrowed another committed hand face')
    original = state.entities.get(face.source_id)
    if original is None or original.owner not in (1, 2):
        raise ValueError('Played card copy lost its original physical owner')
    # A logical printed source for the shared writer, not an allocation/zone fact.
    source = Entity(face.source_id, face.card_id, original.owner, face.player_id,
                    Zone.HAND, kind=face.kind)
    if face.kind == CardType.WEAPON and row.submitted_cost is not None:
        from .carved_spells import weapon_material
        quoted = row.submitted_cost.quote.quote_input
        if weapon_material(quoted) is not None:
            if quoted.card_id != face.card_id:
                raise ValueError('Played carved weapon lost its original submitted face')
            source.base_cost = quoted.base_cost
            source.abilities = list(quoted.abilities)
    return source
