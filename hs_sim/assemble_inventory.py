"""Source observations for assembly authoring, never a runtime generation pool.

Keep markers, named tags, numeric tags and proxy text as separate evidence.
Neither implementation availability nor a candidate Standard list establishes
live membership, role compatibility, weights or a Rajh-specific domain.
"""
from collections import Counter
from copy import deepcopy
from html.entities import html5
import re

from .targets import canonical_digest

VERSION = 'assemble-source-inventory-v1'
LOCALES = (('zh_CN', 'text'), ('en_US', 'text_en'))
ENTITY = re.compile(r'&(?:#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);')
PROXY = re.compile(r'~GAMEPLAY_ASPROXY_([A-Za-z0-9_]+)')


def text_observation(text):
    if type(text) is not str:
        raise ValueError('Assembly source text must be its complete original string')
    entities, backslash, markers = [], [], []
    for offset, char in enumerate(text):
        if char != '&': continue
        entity = ENTITY.match(text, offset)
        if entity is not None and (entity.group().startswith('&#') or entity.group()[1:] in html5):
            entities.append(dict(offset=offset, text=entity.group()))
        elif offset and text[offset-1] == '\\':
            # Observe the native backslash adjacency; do not decode or guess a
            # C/Python escape convention for Hearthstone's localized strings.
            backslash.append(offset)
        else:
            markers.append(offset)
    prefix = suffix = None
    status = 'absent' if not markers else 'ambiguous'
    if len(markers) == 1:
        offset, = markers
        prefix, suffix = text[:offset], text[offset+1:]
        status = 'single' if prefix.strip() and suffix.strip() else 'empty_half'
        if prefix+'&'+suffix != text: raise ValueError('Source split lost original text')
    return dict(text=text, marker_offsets=markers, backslash_ampersand_offsets=backslash,
        html_entities=entities, status=status, prefix=prefix, suffix=suffix,
        proxy_directive_ids=PROXY.findall(text))


def _ids(values, label):
    if isinstance(values, (str, bytes)):
        raise ValueError(label+' must be an identity collection, not a string')
    values = tuple(values)
    if (any(type(x) is not str or not x or x.strip() != x for x in values) or
            len(values) != len(set(values))):
        raise ValueError(label+' requires explicit unique source identities')
    return values


def build_source_inventory(catalog, proposed_standard_ids=()):
    """Extract all source signals; retain non-minions and unimplemented rows."""
    proposed = set(_ids(proposed_standard_ids, 'Proposed Standard roots'))
    by_id = {r['id']: r for r in catalog.cards}
    missing = proposed-set(by_id)
    if missing: raise ValueError('Proposed roots are absent from this source: '+', '.join(sorted(missing)))
    observations = []
    prefix_groups = {}
    for raw in sorted(catalog.cards, key=lambda row: row['id']):
        if any(type(k) is not str for k in raw.get('tags', {})):
            raise ValueError('Assembly source tag keys must retain their original strings')
        languages = {locale:text_observation(raw.get(field, '')) for locale, field in LOCALES}
        craft_tags = {k:v for k,v in raw.get('tags', {}).items() if k.startswith('CRAFTABLE_')}
        has_marker = any(x['marker_offsets'] for x in languages.values())
        has_backslash = any(x['backslash_ampersand_offsets'] for x in languages.values())
        has_proxy = any(x['proxy_directive_ids'] for x in languages.values())
        if not (has_marker or craft_tags or has_backslash or has_proxy): continue
        proxy_ids = sorted({cid for x in languages.values() for cid in x['proxy_directive_ids']})
        single = all(x['status'] == 'single' for x in languages.values())
        prefix_key = None
        if single:
            prefixes = {locale:x['prefix'] for locale,x in languages.items()}
            prefix_key = canonical_digest(prefixes)
            group = prefix_groups.setdefault(prefix_key, dict(prefix_sha256=prefix_key,
                complete_original_prefixes=prefixes, source_ids=[]))
            group['source_ids'].append(raw['id'])
        observations.append(dict(id=raw['id'], dbf_id=raw.get('dbf_id'),
            source_record=deepcopy(raw), source_record_sha256=canonical_digest(raw),
            source_type=raw.get('type'), source_collectible=raw.get('collectible'),
            proposed_standard_root=raw['id'] in proposed,
            languages=languages, named_craft_tags=deepcopy(craft_tags),
            unresolved_numeric_tags={k:deepcopy(v) for k,v in raw.get('tags', {}).items() if k.isdigit()},
            source_split_observed=has_marker, both_locales_single_nonempty_split=single,
            craftable_output_tag_enabled=(type(craft_tags.get('CRAFTABLE_OUTPUT_POWER')) is int and
                craft_tags['CRAFTABLE_OUTPUT_POWER'] == 1),
            exact_bilingual_prefix_group=prefix_key,
            literal_proxy_references=[dict(card_id=cid, self_reference=cid==raw['id'],
                raw_record_present=cid in by_id) for cid in proxy_ids],
            ordinary_live_membership='unverified', rajh_live_membership='unverified',
            executable_role='unverified', compatibility='unverified'))
    split = [x for x in observations if x['source_split_observed']]
    declared = [x for x in observations if x['craftable_output_tag_enabled']]
    literal_only = [x for x in observations if not x['source_split_observed'] and
        not x['named_craft_tags'] and not x['literal_proxy_references']]
    counts = dict(source_records=len(catalog.cards), observed_records=len(observations),
        unescaped_split_records=len(split), unescaped_split_minions=sum(x['source_type']=='MINION' for x in split),
        source_output_tag_enabled=len(declared),
        proposed_standard_split_records=sum(x['proposed_standard_root'] for x in split),
        proposed_standard_split_minions=sum(x['proposed_standard_root'] and x['source_type']=='MINION' for x in split),
        both_locales_single_nonempty=sum(x['both_locales_single_nonempty_split'] for x in split),
        literal_backslash_only_records=len(literal_only),
        split_by_type=dict(sorted(Counter(str(x['source_type']) for x in split).items())),
        output_tag_by_type=dict(sorted(Counter(str(x['source_type']) for x in declared).items())),
        exact_bilingual_prefix_groups=len(prefix_groups))
    return dict(schema=1, version=VERSION, counts=counts,
        offset_units='Python Unicode code points in complete original source strings',
        proposed_standard_root_count=len(proposed), records=observations,
        exact_bilingual_prefix_groups=[prefix_groups[k] for k in sorted(prefix_groups)],
        unverified_rules=['Live ordinary and Rajh membership and source roles',
            'Numeric tag meanings, proxy behavior and physical template requirements',
            'Mode/version filtering, weights, half compatibility and CN timing'],
        runtime_pool_installed=False, formal_pool_complete=False, cn_calibrated=False)


def audit_registered_support(inventory, catalog, registered_ids=(), reviewed_template_ids=(), generation_families=None):
    """One-time support evidence kept separate from the immutable source facts."""
    if inventory.get('version') != VERSION or inventory.get('formal_pool_complete') is not False:
        raise ValueError('Support audit requires an uncertified source inventory')
    registered = set(_ids(registered_ids, 'Registered definitions'))
    reviewed = set(_ids(reviewed_template_ids, 'Reviewed templates'))
    by_id = {r['id']:r for r in catalog.cards}
    observed = {r['id']:r for r in inventory['records']}
    if len(observed) != len(inventory['records']):
        raise ValueError('Source observations contain duplicate identities')
    for cid, row in observed.items():
        raw = by_id.get(cid)
        if (raw is None or row['source_record'] != raw or
                row['source_record_sha256'] != canonical_digest(raw) or row['source_type'] != raw.get('type')):
            raise ValueError('Source observations differ from their complete catalog: '+cid)
    split = {cid for cid,row in observed.items() if row['source_split_observed']}
    families = {} if generation_families is None else generation_families
    for family, members in families.items():
        if type(family) is not str or not family: raise ValueError('Generation family identity is invalid')
        _ids(members, 'Generation exclusion family')
    rows = [dict(id=cid, source_type=row['source_type'],
        source_split_observed=row['source_split_observed'],
        registered_definition_present=cid in registered, reviewed_template_present=cid in reviewed,
        live_membership_verified=False) for cid,row in sorted(observed.items())]
    unmatched = []
    for cid in sorted(reviewed-split):
        raw = by_id.get(cid)
        same_name = [other for other in sorted(split) if raw is not None and raw.get('name_en') and
            by_id[other].get('name_en')==raw['name_en']]
        links = [dict(id=key, source_ids=list(members), meaning='registered generation-exclusion family; not pool alias proof')
            for key,members in sorted(families.items()) if cid in members]
        unmatched.append(dict(id=cid, source_record=deepcopy(raw),
            source_record_sha256=None if raw is None else canonical_digest(raw),
            source_record_missing=raw is None, marked_same_english_name_ids=same_name,
            declared_generation_exclusion_families=links, live_membership_verified=False))
    return dict(schema=1, inventory_version=VERSION, observed_source_rows=rows,
        reviewed_template_count=len(reviewed), reviewed_templates_with_source_split=len(reviewed&split),
        reviewed_templates_without_source_split=unmatched,
        source_split_rows_without_registered_definition=sorted(split-registered),
        source_split_rows_without_reviewed_template=sorted(split-reviewed),
        registration_is_not_effect_or_membership_verification=True,
        formal_pool_complete=False, cn_calibrated=False)
