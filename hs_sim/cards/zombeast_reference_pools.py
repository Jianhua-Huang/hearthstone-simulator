"""Bind independent local role inventories, then validate their native coverage."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_blueprint, validate_part_shape
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest
from .candidate_generation_catalog import candidate_pool_rows, KEYWORD_TAGS
from .storm_gates_card import TEMPLATE, FIRST, SECOND, CARD as QUEST
from .past_scourge_tamer_card import CARD as TAMER


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/zombeast-pool-bindings-v1.json'
BATCH_HASH = 'c15e98af23381e95605412754cc5afce959dbb76c39cd72078888b53db9d090e'
REFERENCE_PATH = ROOT / 'data/cards/zombeast-local-reference-v1.json'
REFERENCE_HASH = '6fa31f30bbe48a8297b45d182117fa2f5b9df95902d92dfe39979a6de6aea3e1'
POLICY = 'cn37-local-zombeast-role-bindings-v1'
EXCLUDED = 'GIL_607t'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != REFERENCE_HASH or
            data['schema'] != 1 or data['kind'] != 'bound-local-zombeast-role-reference' or
            data['policy_id'] != POLICY or data['reference_document'] != REFERENCE_PATH.relative_to(ROOT).as_posix() or
            data['reference_canonical_sha256'] != REFERENCE_HASH or
            data['source_callers'] != [TAMER, QUEST] or data['source_equivalence_confirmed'] is not False or
            data['unit_local_weights'] is not True or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False or data['full_role_partition_certified'] is not False):
        raise TargetValidationError('Zombeast binding requires the independent local role reference and explicit uncertainties')
    roles = data['roles']
    if len(roles) != 2:
        raise TargetValidationError('Zombeast binding requires two separate original role inventories')
    eligible = []
    for role, pid, field, count, exclusions in zip(roles, (FIRST, SECOND),
            ('first_reference_ids', 'second_reference_ids'), (34, 38), ([], [EXCLUDED])):
        ids = role['member_ids']
        if (role['pool_id'] != pid or role['reference_field'] != field or ids != reference[field] or
                len(ids) != count or len(set(ids)) != count or role['excluded_card_ids'] != exclusions or
                type(role['member_weight']) is not int or role['member_weight'] != 1 or
                role['complete_for_declared_inventory'] is not True):
            raise TargetValidationError('Zombeast role identities, weights or explicit exclusions changed')
        eligible.extend(cid for cid in ids if cid not in exclusions)
    if ([row['card_id'] for row in data['native_card_pins']] != eligible or
            [row['card_id'] for row in data['producer_pins']] != [TAMER, QUEST, TEMPLATE] or
            reference['second_exclusions'][0]['card_id'] != EXCLUDED or
            [row['card_id'] for row in data['metadata_only']] != [EXCLUDED]):
        raise TargetValidationError('Zombeast native validation pins cannot define or crop candidate membership')
    return data, reference


def local_pools(registry, context):
    data, reference = load_batch()
    # Membership is fixed above, before any executable lookup. Missing coverage
    # is an error, never a reason to remove a member or change its weight.
    for pin in data['native_card_pins'] + data['producer_pins']:
        cid = pin['card_id']; card = registry.card(cid)
        if (canonical_digest(asdict(card)) != pin['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != pin['pool_card_sha256']):
            raise TargetValidationError('Zombeast binding lost a complete native face: ' + cid)
    for pin in data['native_card_pins']:
        cid = pin['card_id']; card = registry.card(cid)
        if cid not in registry.crafted_minion_parts:
            raise TargetValidationError('Zombeast member lacks its native donation adapter: ' + cid)
        validate_part_shape(registry, card)
        if (card.cost > 5 or
                PoolCard.from_definition(card).filter_signature() != registry.pool_card(cid).filter_signature()):
            raise TargetValidationError('Zombeast member lost its printed role facts: ' + cid)
    blueprint = registry.crafted_minion_blueprints[TEMPLATE]
    validate_blueprint(registry, blueprint)
    if canonical_digest(asdict(blueprint)) != data['blueprint_sha256']:
        raise TargetValidationError('Zombeast binding lost its original Beast/Beast template')
    pin, = data['metadata_only']
    row = next(r for r in reference['outer_records'] if r['record']['id'] == EXCLUDED)
    tags = (*KEYWORD_TAGS, 'ECHO')
    if (pin['source_record_sha256'] != row['record_sha256'] or
            canonical_digest(row['record']) != row['record_sha256'] or pin['keyword_tags'] != list(tags)):
        raise TargetValidationError('Excluded Echo member lost its complete raw keyword evidence')
    metadata, = candidate_pool_rows(batch=dict(cards=[row], printed_keyword_overrides={}),
        zero_costs={}, zero_attacks={}, keyword_tags=tags)
    if (canonical_digest(asdict(metadata)) != pin['pool_card_sha256'] or
            EXCLUDED in registry.pool_cards and registry.pool_card(EXCLUDED) != metadata):
        raise TargetValidationError('Excluded Echo member lost its independent printed metadata')
    pools = tuple(PoolDefinition(role['pool_id'], POLICY, context.target_id, context.mode,
        tuple(PoolMember(cid, role['member_weight']) for cid in role['member_ids']),
        excluded_card_ids=tuple(role['excluded_card_ids']), complete=True) for role in data['roles'])
    # Finish every validation before adding the sole metadata-only identity.
    # Excluded members need inventory metadata, not a fake executable adapter.
    if EXCLUDED not in registry.pool_cards:
        registry.register_pool_card(metadata)
    return pools
