"""Independently classified local pack printings; no shop or rarity simulation."""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from hs_sim.engine.model import CardType
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/standard-pack-printings-v1.json'
BATCH_HASH = '34cd825c3b5b4b82ee6c716c14c9da9985c6bbc1efa323e240108223525e0051'
CARD = 'CORE_WON_145'
POOL_ID = 'constructed.standard_pack'
POLICY = 'cn37-local-standard-pack-printings-v1'
EXPANSION_SETS = (1946, 1952, 1957, 1980, 1988, 1994)
KINDS = (CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            (data['policy_id'], data['pool_id'], data['source_card_id']) != (POLICY, POOL_ID, CARD) or
            tuple(data['expansion_set_ids']) != EXPANSION_SETS or
            [r['record']['id'] for r in data['cards']] != [CARD] or
            len(data['existing_dependencies']) != 1321 or data['dependencies'] or
            data['evidence_only'] or data['skipped'] or len(data['official_faces']) != 2 or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False):
        raise TargetValidationError('Standard pack requires its full independently classified local inventory')
    universe = data['universe']; path = (ROOT / universe['path']).resolve()
    if (not path.is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != universe['sha256'] or
            json.loads(path.read_text(encoding='utf-8'))['candidate_root_ids'] != universe['root_ids']):
        raise TargetValidationError('Standard pack lost its original complete launch universe')
    records = data['cards'] + data['existing_dependencies']
    rows = {r['record']['id']: r for r in records}
    ids = universe['root_ids']
    if (len(ids) != len(set(ids)) or len(rows) != len(records) or set(ids) != set(rows) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in records)):
        raise TargetValidationError('Standard pack source rows were cropped, duplicated or changed')
    members = [cid for cid in ids if rows[cid]['record']['card_set_id'] in EXPANSION_SETS]
    assessments = data['assessments']
    excluded = sorted(r['card_id'] for r in assessments if r['role'] in (
        'normal-login-grant', 'normal-track-grant', 'normal-promotional-grant', 'explicit-not-in-expansion-pack'))
    if (len(assessments) != len(ids) or [r['card_id'] for r in assessments] != ids or
            members != data['member_ids'] or len(members) != 1012 or
            excluded != data['excluded_card_ids'] or len(excluded) != 15 or
            not set(excluded) <= set(members) or
            [cid for cid in members if cid not in excluded] != data['eligible_card_ids'] or
            len(data['eligible_card_ids']) != 997 or
            [cid for cid in members if cid.startswith(('MEND_', 'CAP_'))] != data['class_set_member_ids']):
        raise TargetValidationError('Standard pack changed its original set or explicit print qualification')
    for assessment in assessments:
        row = rows[assessment['card_id']]
        if (assessment['record_sha256'] != row['record_sha256'] or
                assessment['card_set_id'] != row['record']['card_set_id']):
            raise TargetValidationError('Standard pack classification borrowed another printing')
    return data


def local_pool(registry, context):
    """Keep all 1012 source printings, including the fifteen declared exclusions.

    Eligibility never follows implementation coverage. Every root's original
    full row and existing native definition is checked before exposing a pool.
    Evidence caches are provenance only; runtime needs checked-in data alone.
    """
    data = load_batch()
    rows = {r['record']['id']: r for r in data['cards'] + data['existing_dependencies']}
    for assessment in data['assessments']:
        cid = assessment['card_id']; card = registry.card(cid); raw = rows[cid]['record']
        if canonical_digest(asdict(card)) != assessment['definition_sha256']:
            raise TargetValidationError('Standard pack native definition changed: ' + cid)
        # The complete native digest above pins reviewed Core aliases and the
        # normal None -> physical-ID fallback. Raw CARD_SET is not an alias map.
        printed = replace(metadata_from_record(raw), deck_identity=card.metadata.deck_identity)
        if (card.kind not in KINDS or not card.hand_playable or card.choice_only or
                card.metadata.collectible is not True or card.metadata != printed or
                registry.pool_card(cid) != PoolCard.from_definition(card)):
            raise TargetValidationError('Standard pack printing lost its native metadata or role: ' + cid)
    return PoolDefinition(POOL_ID, POLICY, context.target_id, context.mode,
        tuple(PoolMember(cid, 1) for cid in data['member_ids']),
        excluded_card_ids=tuple(data['excluded_card_ids']), complete=True)
