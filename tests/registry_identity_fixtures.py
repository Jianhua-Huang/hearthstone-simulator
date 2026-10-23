"""Reviewed representative identity; update only after full identity-delta audit."""

# K219: the complete identity audit preserves all 311 definitions. Changing
# only m5.sandfury_aura.kind from objective to its real aura identity reproduces
# this entire fingerprint; the prior fingerprint is retained in that receipt.
DEFAULT_REPRESENTATIVE_FINGERPRINT = 'b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a'

# Explicit, previously reviewed whole-definition transitions. Historical input
# files keep their original bytes; a current definition must match the complete
# approved successor, so this cannot hide a new behavior or metadata change.
# K108: CATA_155 gains the source's second printed tribe (Dragon/Undead).
# K109: CORE_BOT_576 uses its real native Combo instead of Battlecry.
# K226: EDR_531 grants Armor only after destroying the original target.
# K413: the constructed JAIL_123 selects the constructed spell domain; the
# representative build deliberately retains its original experimental domain.
REVIEWED_DEFINITION_TRANSITIONS = {
    'CATA_155': (
        '340d249a68db8258c9afed3907bc0e2578493ef02169518b86c7a7adebd5f8fd',
        'bd72987b7a6935b1fb5cf41de1f903c1d58d772684bc370815187ea344900d22'),
    'CORE_BOT_576': (
        'e4f79f8e86868d844a3192c4dc4c38d6285caa3e266e1b9503f23b0b54bde0bb',
        '6d1cab16caa28675118758239d2784994cc9e8e21c24e96e8c54614a55583d43'),
    'EDR_531': (
        'f9fe21dc4b383cfa1018a07c78d79857b492b676db07c48ab841ce45e82f9484',
        'ff5206e09662ccdb211c6d189ee202d1161dc6fc4e1e576c905b8ac7c305f447'),
    'JAIL_123': (
        '063295f998dcb220dfc3b6872874f2d6fdec9192671b164bd5f36a9ae4ba1302',
        'af5c5337294a3f4ed6cca61f88a0d1cf472f9601cd8c696eecaa54a7816076c1'),
}


def _older_inert_field_shapes(definition):
    """Yield only schemas preceding two explicitly inert nested defaults.

    These fields were added after the frozen K70-K81 definitions. An absent
    hand-adjacency flag meant False; an absent exact-card selector meant ().
    Nondefault values are never removed. Each complete projected definition
    still has to reproduce the caller's original SHA, so every other field,
    including the rest of each cost declaration, remains protected.
    """
    from copy import deepcopy

    variants = [definition]
    for container, field, inert in (
            ('cost_auras', 'hand_adjacent', False),
            ('intrinsic_costs', 'card_ids', ())):
        for original in tuple(variants):
            projected = deepcopy(original)
            changed = False
            for spec in projected.get(container, ()):
                if field in spec and type(spec[field]) is type(inert) and spec[field] == inert:
                    del spec[field]
                    changed = True
            if changed:
                variants.append(projected)
                yield projected


def historical_definition_digests(registry, historical):
    from dataclasses import asdict
    from hs_sim.targets import canonical_digest

    actual = {}
    for cid, expected in historical.items():
        definition = asdict(registry.card(cid))
        digest = canonical_digest(definition)
        transition = REVIEWED_DEFINITION_TRANSITIONS.get(cid)
        if transition is not None and expected == transition[0]:
            if digest != transition[1]:
                raise AssertionError(f'Current definition differs from reviewed successor: {cid}')
            digest = expected
        elif digest != expected and any(canonical_digest(older) == expected
                for older in _older_inert_field_shapes(definition)):
            digest = expected
        actual[cid] = digest
    return actual
