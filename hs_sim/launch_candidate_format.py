"""Post-launch source inventory with an explicitly experimental ban snapshot.

The global ban observation is not a CN legality certificate. Unknown executable
cards stay in the inventory and fail when a deck or qualifying query needs them.
The historical pre-launch factory and its saved matches remain unchanged.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from .candidate_format import CandidateFormat, POOL_ID, MINION_POOL_ID, load_source_facts
from .cards import build_registry
from .cards.candidate_generation_catalog import (
    BATCH_HASH as BASE_HASH, KEYWORD_TAGS, _same_printed_query_fields,
    candidate_pool_rows, load_batch as load_base,
)
from .engine.construction import DeckPolicy
from .engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from .targets import TargetValidationError, canonical_digest


BATCH_PATH = Path(__file__).resolve().parents[1] / 'data/cards/launch-candidate-cn37-v1.json'
BATCH_HASH = '0238115c36021efe33f72761d6a6c2c30e6e3c190fb8bd497ba28410e5b4b821'
FORMAT_VERSION = 'cn37-launch-candidate-global-ban-observation-20261023-v1'
OBSERVED_BANS = ('DINO_402', 'TIME_030', 'TLC_817')
LAUNCH_KEYWORDS = KEYWORD_TAGS + ('OLD_GOD',)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Unreviewed post-launch candidate inventory or ban observation')
    base = load_base()
    roots = tuple(data['candidate_root_ids'])
    added = tuple(row['record']['id'] for row in data['additional_cards'])
    if (data['base_catalog_sha256'] != BASE_HASH or len(roots) != 1322 or len(set(roots)) != 1322 or
            roots != tuple(sorted(roots)) or len(added) != 134 or len(set(added)) != 134 or
            set(base['candidate_root_ids']) & set(added) or
            set(base['candidate_root_ids']) | set(added) != set(roots) or
            tuple(data['keyword_tags']) != LAUNCH_KEYWORDS or
            data['printed_keyword_overrides'] != {'BE_171': ['taunt'], 'BE_702': ['combo']} or
            tuple(data['experimental_deck_bans']) != OBSERVED_BANS or
            data['cn_bans_verified'] is not False or data['formal_pool_complete'] is not False):
        raise TargetValidationError('Post-launch candidate inventory lost its full source or evidence boundary')
    for item in data['additional_cards']:
        raw = item['record']
        if (canonical_digest(raw) != item['record_sha256'] or raw['card_set_id'] != 1994 or
                raw['collectible'] is not True):
            raise TargetValidationError('Post-launch candidate requires its entire original collectible record')
    by_id = {item['record']['id']: item['record'] for item in data['additional_cards']}
    for key, field, numeric in (('zero_cost_evidence', 'cost', 'manaCost'),
            ('zero_attack_evidence', 'attack', 'attack')):
        identities = [item['record']['id'] for item in data[key]]
        required = {cid for cid, raw in by_id.items() if raw[field] is None and
            (field == 'cost' or raw['type'] == 'MINION')}
        if len(identities) != len(set(identities)) or set(identities) != required:
            raise TargetValidationError('Post-launch numeric evidence lost an exact source identity')
        for item in data[key]:
            raw = item['record']
            faces = item['official_observations']
            if (by_id.get(raw['id']) != raw or raw[field] is not None or
                    canonical_digest(raw) != item['record_sha256'] or
                    len(faces) != 2 or {f['locale'] for f in faces} != {'zh_CN', 'en_US'} or any(
                        f['face']['id'] != raw['dbf_id'] or type(f['face'].get(numeric)) is not int or
                        f['face'][numeric] != 0 for f in faces)):
                raise TargetValidationError('Post-launch missing numeric field requires both complete primary faces')
    evidence = data['keyword_override_evidence']
    if (len(evidence) != 2 or {item['record']['id'] for item in evidence} !=
            set(data['printed_keyword_overrides'])):
        raise TargetValidationError('Post-launch printed keyword evidence lost its exact source')
    for item in evidence:
        raw = item['record']
        faces = item['official_observations']
        if (by_id.get(raw['id']) != raw or canonical_digest(raw) != item['record_sha256'] or
                item['keywords'] != data['printed_keyword_overrides'][raw['id']] or
                len(faces) != 2 or {f['locale'] for f in faces} != {'zh_CN', 'en_US'} or
                any(f['face']['id'] != raw['dbf_id'] for f in faces)):
            raise TargetValidationError('Post-launch keyword override requires both full primary faces')
    source = data['global_ban_evidence']
    if canonical_digest(source['first_post']) != source['first_post_sha256']:
        raise TargetValidationError('Post-launch ban observation changed its complete original post')
    return data


def register_launch_pool_metadata(registry, data=None):
    """Prevalidate every new source row; do not create executable placeholders."""
    data = load_batch() if data is None else data
    zero = {row['record']['id']: row for row in data['zero_cost_evidence']}
    zero_attack = {row['record']['id']: row for row in data['zero_attack_evidence']}
    compiled = candidate_pool_rows(batch={'cards': data['additional_cards'],
        'printed_keyword_overrides': data['printed_keyword_overrides']},
        zero_costs=zero, zero_attacks=zero_attack, keyword_tags=LAUNCH_KEYWORDS)
    pending = []
    for expected in compiled:
        cid = expected.card_id
        actual = expected
        if cid in registry.cards:
            actual = PoolCard.from_definition(registry.card(cid))
            if not _same_printed_query_fields(expected, actual):
                raise TargetValidationError('Post-launch executable differs from independent printed inventory: ' + cid)
        if cid in registry.pool_cards:
            if registry.pool_card(cid) != actual:
                raise TargetValidationError('Post-launch existing metadata conflicts with its full source: ' + cid)
        else:
            pending.append(actual)
    for row in pending:
        registry.register_pool_card(row)


@dataclass(frozen=True)
class LaunchCandidateFormat(CandidateFormat):
    effective_until: str | None
    expansion_launched_at: str
    ban_observed_at: str
    cn_bans_verified: bool

    @property
    def unimplemented_root_card_ids(self):
        return tuple(cid for cid in self.root_card_ids if cid not in self.registry.cards)


def build_cn37_launch_candidate_format():
    data = load_batch()
    facts = load_source_facts()
    if (data['region'] != facts['region'] or data['patch'] != facts['official_patch'] or
            data['client_version'] != facts['frozen_source']['client_version'] or
            data['source_sha256'] != facts['normalized_source_sha256'] or
            data['expansion_launched_at'] != facts['preloaded_expansion']['formal_launch']):
        raise TargetValidationError('Post-launch candidate phase changed its frozen CN37 source')
    base = load_base()
    roots = tuple(data['candidate_root_ids'])
    records = {row['record']['id']: row['record'] for row in base['cards'] + data['additional_cards']}
    minions = tuple(cid for cid in roots if records[cid]['type'] == 'MINION')
    registry = build_registry()
    register_launch_pool_metadata(registry, data)
    companions = {cid for spec in registry.fabled.values() if spec.source_card_id in roots
        for cid in spec.companion_card_ids}
    allowed = tuple(sorted(set(roots) | companions))
    domains = ((POOL_ID, roots), (MINION_POOL_ID, minions))
    binding = canonical_digest(dict(format=FORMAT_VERSION, batch=BATCH_HASH, content=registry.version,
        allowed=allowed, bans=data['experimental_deck_bans'], domains=domains))
    target_id = FORMAT_VERSION + '-' + binding[:16]
    policy = DeckPolicy(target_id + '.deck', target_id, 'experimental', allowed,
        banned_card_ids=tuple(data['experimental_deck_bans']), pool_complete=False)
    context = GenerationContext(target_id, 'experimental')
    for pool_id, members in domains:
        registry.register_pool(PoolDefinition(pool_id, 'source-pinned-' + binding, target_id,
            'experimental', tuple(PoolMember(cid) for cid in members), complete=True))
    registry.validate()
    return LaunchCandidateFormat(registry, target_id, binding, roots, policy, context,
        data['ban_observed_at'], None, data['client_version'], data['expansion_launched_at'],
        data['ban_observed_at'], False)
