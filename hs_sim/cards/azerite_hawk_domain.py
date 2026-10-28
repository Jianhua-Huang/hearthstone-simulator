"""Complete local Hawk domain; preserve the original experimental sample."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.model import CardType, Keyword
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/azerite-hawk-domain-v1.json'
BATCH_HASH = '8344bf2e4e46732e1452da088cdcc4d52297d5c5d556d6b424687ad531cf4200'
HAWK = 'WW_001t24'
POOL = 'representative.excavate-titans'
POLICY = 'cn37-local-azerite-hawk-full-titans-v1'
COLLECTIBLE_ROOTS = ()


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            d['source_card_id'] != HAWK or d['pool_id'] != POOL or
            len(d['existing_dependencies']) != 13 or len(d['official_observations']) != 2 or
            d['source_scope_bound'] is not True or
            any(d[k] for k in ('new_definition_ids', 'new_metadata_ids', 'new_standard_roots',
                'real_excavate_profile_bound', 'formal_pool_complete', 'cn_calibrated')) or
            tuple(r['path'] for r in d['references']) != (
                'data/cards/titan-reference-khaz-argus-v1.json', 'data/cards/excavate-shared-treasures-v1.json') or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in d['existing_dependencies'])):
        raise TargetValidationError('Hawk requires the full original source and explicit locally bound Titan domain')
    for ref in d['references']:
        if hashlib.sha256((ROOT / ref['path']).read_bytes()).hexdigest() != ref['sha256']:
            raise TargetValidationError('Hawk changed a complete original Titan or treasure reference')
    reference = json.loads((ROOT / d['references'][0]['path']).read_text(encoding='utf8'))['inventory']
    expected = dict(reference, runtime_bound=True)
    if (d['inventory'] != expected or len(reference['candidate_ids']) != 12 or
            tuple(r['record']['id'] for r in d['existing_dependencies']) != (HAWK, *reference['candidate_ids'])):
        raise TargetValidationError('Hawk cannot trim, reorder or reweight the complete original Titan reference')
    return d


def local_pool(registry, context):
    """Pure declaration preparation; validate every member before installation."""
    d = load_batch()
    for row in d['existing_dependencies']:
        cid = row['record']['id']; card = registry.card(cid)
        if (canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_metadata_sha256']):
            raise TargetValidationError('Hawk requires each complete original native definition and metadata: ' + cid)
        if cid != HAWK and (card.kind != CardType.MINION or Keyword.TITAN not in card.keywords or
                len(card.activated_abilities) != 3 or not card.metadata.collectible):
            raise TargetValidationError('Hawk requires real collectible Titan bodies and their native skills')
    inventory = d['inventory']
    return PoolDefinition(POOL, POLICY, context.target_id, context.mode,
        tuple(PoolMember(cid, weight) for cid, weight in zip(inventory['candidate_ids'], inventory['weights'])),
        excluded_card_ids=tuple(inventory['excluded_card_ids']), complete=True)
