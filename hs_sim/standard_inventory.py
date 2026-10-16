"""Conservative Standard candidate and static-reference inventory, not legality."""

from collections import Counter

from hs_sim.card_effects import effect_groups, trigger_groups
from hs_sim.targets import canonical_digest


ROOT_TYPES = frozenset(('MINION', 'SPELL', 'WEAPON', 'HERO', 'LOCATION'))
REFERENCE_TAGS = ('COLLECTION_RELATED_CARD_DATABASE_ID', 'DISPLAY_CARD_ON_MOUSEOVER')


def build_standard_inventory(catalog, policy, implemented_ids=()):
    """Keep every source row, including unimplemented and uncertain candidates."""
    if policy.get('formal_pool_complete') is not False or policy.get('mode') != 'STANDARD':
        raise ValueError('Candidate inventory cannot certify a formal pool')
    sets = policy['candidate_set_ids']
    if type(sets) is not list or len(set(sets)) != len(sets) or any(type(s) is not int or s < 1 for s in sets):
        raise ValueError('Candidate series require unique explicit positive IDs')
    overrides = policy['early_available_ids']
    if type(overrides) is not list or len(set(overrides)) != len(overrides):
        raise ValueError('Early exceptions require unique explicit card IDs')
    by_id = {r['id']: r for r in catalog.cards}
    by_dbf = {r['dbf_id']: r for r in catalog.cards if r.get('dbf_id') is not None}
    excluded = policy.get('excluded_ids', [])
    if (type(excluded) is not list or
            any(type(cid) is not str or not cid or cid.strip() != cid for cid in excluded) or
            len(set(excluded)) != len(excluded)):
        raise ValueError('Candidate exclusions require unique explicit card IDs')
    for cid in excluded:
        if (cid not in by_id or by_id[cid].get('collectible') is not True or
                by_id[cid].get('type') not in ROOT_TYPES or cid in overrides):
            raise ValueError('Excluded root must exist and cannot also be an early exception')
    for cid in overrides:
        if cid not in by_id or by_id[cid].get('collectible') is not True or by_id[cid].get('type') not in ROOT_TYPES:
            raise ValueError('Early exception must resolve to an eligible source root')
    registered = set(implemented_ids)
    rows, counts, roots = [], Counter(), []
    for raw in sorted(catalog.cards, key=lambda r: r['id']):
        root_type = raw.get('type') in ROOT_TYPES and raw.get('collectible') is True
        exception = raw['id'] in overrides
        candidate = root_type and (raw.get('card_set_id') in sets or exception) and raw['id'] not in excluded
        refs = [dict(r, evidence='xml_card_tag') for r in raw.get('xml_card_references', ())]
        refs += [dict(tag='RELATED_CARDS', dbf_id=value, evidence='relationship_hint')
                 for value in raw.get('related_dbf_ids', ())]
        refs += [dict(tag=tag, dbf_id=raw['tags'][tag], evidence='display_or_collection_hint')
                 for tag in REFERENCE_TAGS if tag in raw.get('tags', {})]
        for ref in refs:
            target = by_dbf.get(ref['dbf_id'])
            ref['resolved_card_id'] = target['id'] if target is not None else None
        row = dict(id=raw['id'], name=raw.get('name'), dbf_id=raw.get('dbf_id'),
            source_set_id=raw.get('card_set_id'), type=raw.get('type'),
            source_record_sha256=canonical_digest(raw), standard_candidate=candidate,
            membership_review_required=True, registered_definition_present=raw['id'] in registered,
            effect_groups=list(effect_groups(raw)), trigger_groups=list(trigger_groups(raw)),
            reference_hints=refs, reachability_complete=False)
        if candidate:
            row['candidate_reason'] = 'early_available_exception' if exception else 'current_series_candidate'
            roots.append(raw['id'])
            counts[raw.get('card_set_id')] += 1
        elif raw['id'] in excluded:
            row['candidate_reason'] = 'explicitly_excluded_root'
        else:
            row['candidate_reason'] = 'outside_selected_series_or_root_type'
        rows.append(row)
    by_row = {row['id']: row for row in rows}
    # This only follows evidenced static hints. Dynamic generated results and
    # script-defined dependencies stay explicitly open; no unsupported row drops.
    seen, pending = set(roots), list(roots)
    missing = []
    while pending:
        cid = pending.pop()
        for ref in by_row[cid]['reference_hints']:
            target = ref['resolved_card_id']
            if target is None:
                missing.append(dict(source_id=cid, **ref))
            elif target not in seen:
                seen.add(target)
                pending.append(target)
    return dict(mode='STANDARD', formal_pool_complete=False, reachability_complete=False,
        source_record_count=len(rows), candidate_root_count=len(roots),
        candidate_counts_by_set={str(k): v for k, v in sorted(counts.items())},
        registered_candidate_root_count=sum(by_row[cid]['registered_definition_present'] for cid in roots),
        candidate_root_ids=roots, static_dependency_hint_ids=sorted(seen-set(roots)),
        unresolved_static_hints=missing, policy=policy, records=rows,
        limits=['Series membership and collectibles are candidates, not full format legality.',
                'Event timing, bans, hotfixes and generation exclusions need independent review.',
                'Registered definitions do not prove full effects, testing or CN calibration.',
                'Static relationships do not exhaust dynamically reachable content.'])
