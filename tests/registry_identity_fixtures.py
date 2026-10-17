"""Reviewed representative identity; update only after full identity-delta audit."""

# K122: independent printed Deathrattle/Choose One pool facts; definitions unchanged.
DEFAULT_REPRESENTATIVE_FINGERPRINT = 'ce7b146fc1157c37aa59bae3e92472d6028c102cebd0e20dfab1a1958df49967'

# Explicit, previously reviewed whole-definition transitions. Historical input
# files keep their original bytes; a current definition must match the complete
# approved successor, so this cannot hide a new behavior or metadata change.
# K108: CATA_155 gains the source's second printed tribe (Dragon/Undead).
# K109: CORE_BOT_576 uses its real native Combo instead of Battlecry.
REVIEWED_DEFINITION_TRANSITIONS = {
    'CATA_155': (
        '340d249a68db8258c9afed3907bc0e2578493ef02169518b86c7a7adebd5f8fd',
        'bd72987b7a6935b1fb5cf41de1f903c1d58d772684bc370815187ea344900d22'),
    'CORE_BOT_576': (
        'e4f79f8e86868d844a3192c4dc4c38d6285caa3e266e1b9503f23b0b54bde0bb',
        '6d1cab16caa28675118758239d2784994cc9e8e21c24e96e8c54614a55583d43'),
}


def historical_definition_digests(registry, historical):
    from dataclasses import asdict
    from hs_sim.targets import canonical_digest

    actual = {cid: canonical_digest(asdict(registry.card(cid))) for cid in historical}
    for cid, (old, approved) in REVIEWED_DEFINITION_TRANSITIONS.items():
        if historical.get(cid) == old:
            if actual[cid] != approved:
                raise AssertionError(f'Current definition differs from reviewed successor: {cid}')
            actual[cid] = old
    return actual
