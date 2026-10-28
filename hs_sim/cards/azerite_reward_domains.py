"""Full fixed ordinary inventories for the original three Azerite reward bodies."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/azerite-reward-domains-v1.json'
BATCH_HASH = 'd73de83fddec86aa9eea5396d0809a8176774b260b1b0729f5bb640165c7a575'
POLICY = 'cn37-local-azerite-ordinary-reward-domains-v1'
SCORPION, OX, MURLOC = 'WW_001t23', 'WW_001t27', 'DEEP_999t5'
CARDS_POOL = 'representative.generation'
EIGHT_POOL = 'representative.excavate-eight-cost'
TRANSFORM_POOL = 'representative.excavate-transform'
COLLECTIBLE_ROOTS = ()
REFERENCE_PATHS = ('data/cards/candidate-generation-catalog-v1.json',
    'data/cards/launch-candidate-cn37-v1.json', 'data/cards/excavate-shared-treasures-v1.json')


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            d['source_card_ids'] != [SCORPION, OX, MURLOC] or
            d['source_scope_bound'] is not True or len(d['official_observations']) != 6 or
            any(d[k] for k in ('new_definition_ids', 'new_metadata_ids', 'new_standard_roots',
                'real_excavate_profile_bound', 'formal_pool_complete', 'cn_calibrated')) or
            tuple(r['path'] for r in d['references']) != REFERENCE_PATHS):
        raise TargetValidationError('Azerite rewards require complete fixed ordinary sources and local evidence boundaries')
    refs = []
    for ref in d['references']:
        path = ROOT / ref['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != ref['sha256']:
            raise TargetValidationError('Azerite reward changed a full original ordinary or treasure source')
        refs.append(json.loads(path.read_text(encoding='utf8')))
    base, launch, treasures = refs
    raw = {row['record']['id']: row['record'] for row in base['cards'] + launch['additional_cards']}
    roots = tuple(launch['candidate_root_ids'])
    minions = tuple(cid for cid in roots if raw[cid]['type'] == 'MINION')
    eight = tuple(cid for cid in minions if raw[cid]['cost'] == 8)
    if (len(roots) != 1322 or len(minions) != 811 or len(eight) != 44 or
            set(d['ordinary_member_metadata_sha256']) != set(roots)):
        raise TargetValidationError('Azerite reward lost a complete fixed ordinary inventory or metadata identity')
    expected = []
    for pool, source, ids, role in (
            (CARDS_POOL, 'constructed.cards', roots, 'all-ordinary-cards'),
            (EIGHT_POOL, 'constructed.minions', eight, 'printed-eight-collectible-minions'),
            (TRANSFORM_POOL, 'constructed.minions', minions, 'all-ordinary-minion-tiers')):
        expected.append(dict(pool_id=pool, source_pool_id=source, role=role,
            candidate_ids=list(ids), weights=[1] * len(ids), excluded_card_ids=[],
            complete_for_declared_local_inventory=True))
    if d['domains'] != expected:
        raise TargetValidationError('Azerite reward cannot crop, reorder, reweight or exclude its original ordinary domains')
    treasure_rows = {row['record']['id']: row for row in treasures['existing_dependencies']}
    if (tuple(row['record']['id'] for row in d['existing_dependencies']) != (SCORPION, OX, MURLOC) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                row['record'] != treasure_rows[row['record']['id']]['record']
                for row in d['existing_dependencies'])):
        raise TargetValidationError('Azerite reward requires each complete original source body')
    return d


def local_pools(registry, context):
    """Prepare every member before returning any pool; never trim unknown bodies."""
    d = load_batch()
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_metadata_sha256']):
            raise TargetValidationError('Azerite reward requires its complete original adapter and metadata: ' + cid)
    for cid, expected in d['ordinary_member_metadata_sha256'].items():
        registry.card(cid)
        if canonical_digest(asdict(registry.pool_card(cid))) != expected:
            raise TargetValidationError('Azerite reward requires every original ordinary metadata row: ' + cid)
    all_cards, all_minions = d['domains'][0], d['domains'][2]
    sources = {}
    for domain in (all_cards, all_minions):
        source = registry.pool(domain['source_pool_id'], context)
        if (tuple((m.card_id, m.weight) for m in source.members) !=
                tuple(zip(domain['candidate_ids'], domain['weights'])) or
                source.excluded_card_ids or not source.complete):
            raise TargetValidationError('Azerite reward source must retain the full ordered ordinary inventory')
        sources[source.id] = source
    return tuple(PoolDefinition(domain['pool_id'], POLICY + ':' + sources[domain['source_pool_id']].version,
        context.target_id, context.mode,
        tuple(PoolMember(cid, weight) for cid, weight in zip(domain['candidate_ids'], domain['weights'])),
        excluded_card_ids=tuple(domain['excluded_card_ids']), complete=True) for domain in d['domains'])
