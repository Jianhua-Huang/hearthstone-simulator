"""Detached public descriptions; callers must first authorize the carrier zone.

Positions describe the current visible list, never global attachment identities.
Stored bodies and consumption are displayed even when the carrier is dormant;
this is not an activation plan or a promise that the body will execute.
"""
from .targeting import target_spec


def public_bodies(entity, registry):
    result = []
    for ability in entity.abilities:
        if ability.kind not in ('battlecry', 'combo'):
            continue
        declaration_id = getattr(ability, ability.kind + '_card_id')
        declaration = registry.card(declaration_id)
        from .carved_spells import spell_target_definition
        if ability.carved_spell_id is not None:
            declaration=spell_target_definition(registry,declaration,ability.carved_spell_id)
        if getattr(declaration, ability.kind) != ability.behavior_id:
            raise ValueError('Body description does not match its registered declaration')
        spec = target_spec(declaration)
        target = None if spec is None else {
            'mode': spec.mode.value,
            'zones': [zone.value for zone in spec.zones],
            'kinds': [kind.value for kind in spec.kinds],
            'relation': spec.relation,
            'exclude_source': spec.exclude_source,
            'condition': declaration.target_condition,
            'manathirst': declaration.manathirst if declaration.target_condition == 'manathirst' else None,
        }
        result.append({
            'position': len(result) + 1,
            'family': ability.kind,
            'card_id': declaration_id,
            'origin': ability.origin,
            'consumed': ability.consumed,
            'expires_turn': ability.expires_turn,
            'target': target,
        })
        if ability.carved_spell_id is not None:result[-1]['cast_card_id']=ability.carved_spell_id
    return result
