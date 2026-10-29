"""The complete known faction lists over ordinary choices and generation."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.generation_scopes import GenerationScope, pool_digest
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Rarity
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolDefinition, PoolMember, PoolQuery, resolve_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
CARD = 'WON_113'
CHOICES = ('WON_113a', 'WON_113b')
POLICY = 'cn37-local-complete-known-champions-source-v1'
BODY = 'cards.champions_of_azeroth.choose'
BATCH_PATH = ROOT / 'data/cards/champions-of-azeroth-v1.json'
BATCH_HASH = '873dd8a4027a79a07ed3b98f594d9cadab68d068482ee1c3273bbd275d740684'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, rarities=(Rarity.LEGENDARY,))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            [v['record']['id'] for v in d['cards']] != [CARD] or
            tuple(v['record']['id'] for v in d['dependencies']) != CHOICES or
            len(d['existing_dependencies']) != 13 or len(d['official_observations']) != 22 or
            d['metadata_ids'] != ['LOE_077'] or canonical_digest(d['query']) != canonical_digest(asdict(QUERY)) or
            any(d[k] for k in ('evidence_only', 'new_standard_roots', 'membership_uses_executable_coverage',
                'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Champions require complete original faces, lists and explicit local policies')
    for row in (*d['cards'], *d['dependencies'], *d['existing_dependencies']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Champions lost a complete original record')
    if ([(v['role'], v['choice_card_id'], len(v['member_ids'])) for v in d['domains']] !=
            [('alliance', CHOICES[0], 5), ('horde', CHOICES[1], 5)] or
            d['parent_child_ids'] != [2760, 890, 1080, 2949, 9, 338, 1721, 420, 86383, 62176, 1730, 318]):
        raise TargetValidationError('Champions changed original source identities or faction roles')
    members = [cid for v in d['domains'] for cid in v['member_ids']]
    if (len(set(members)) != 10 or members != [v['record']['id'] for v in d['existing_dependencies'][:10]] or
            any(v['weight'] != 1 or len(v['actual_ids']) != 5 or
                set(v['actual_ids']) != set(v['member_ids']) or
                (v['generated_count'], v['replacement'], v['cost_delta']) != (2, True, -2) or
                not v['complete_for_declared_inventory'] or v['formal_pool_complete'] for v in d['domains'])):
        raise TargetValidationError('Champions cannot prune, duplicate or reweight an original faction list')
    return d


def metadata_additions(registry, d):
    result = []
    for row in d['existing_dependencies']:
        raw = row['record']; cid = raw['id']; card = registry.card(cid)
        if (canonical_digest(asdict(card)) != row['definition_sha256'] or card.metadata != metadata_from_record(raw)):
            raise TargetValidationError('Champions lost a complete unchanged native dependency: ' + cid)
        printed = PoolCard.from_definition(card)
        if canonical_digest(asdict(printed)) != row['pool_card_sha256']:
            raise TargetValidationError('Champion printed metadata disagrees with its complete native face')
        if cid in registry.pool_cards:
            if registry.pool_card(cid) != printed:
                raise TargetValidationError('Champion cannot overwrite different existing generation metadata')
        elif cid in d['metadata_ids']:
            result.append(printed)
        else:
            raise TargetValidationError('Champion lost required existing generation metadata: ' + cid)
    return tuple(result)


def register_champions_of_azeroth(registry):
    d = load_batch(); additions = metadata_additions(registry, d); cards = []
    for row in (*d['cards'], *d['dependencies']):
        raw = row['record']; cid = raw['id']
        if raw['type'] != 'SPELL' or raw['cost'] != 4 or raw['collectible'] != (cid == CARD):
            raise TargetValidationError('Champion source or choice-only face changed')
        fields = {'on_play': BODY} if cid == CARD else {'choice_only': True}
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=4, metadata=metadata_from_record(raw), **fields)
        if (canonical_digest(asdict(card)) != row['definition_sha256'] or cid in registry.cards or cid in registry.pool_cards):
            raise TargetValidationError('Champion source cannot replace a different native identity')
        cards.append(card)

    def choose(c):
        labels = {v['record']['id']: v['record']['name'] for v in d['dependencies']}
        options = tuple(ChoiceOption(v['choice_card_id'], labels[v['choice_card_id']],
            (GenerateFromPool(c.player_id, v['pool_id'], QUERY, count=2, replacement=True,
                source_id=c.source_id, cost=CostSpec(delta=-2)),), card_id=v['choice_card_id']) for v in d['domains'])
        return (RequestChoice(c.player_id, options, c.source_id, prompt='选择联盟或部落'),)

    registry.register_behavior(BODY, choose)
    for card in cards:
        registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(cards[0]))
    for row in additions:
        registry.register_pool_card(row)


def validate_native(registry, d):
    if metadata_additions(registry, d):
        raise TargetValidationError('Champion source requires all declared metadata before pool binding')
    for row in (*d['cards'], *d['dependencies']):
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Champion source lost a complete native source or choice-only face')


def local_pools(registry, context):
    d = load_batch(); validate_native(registry, d)
    return tuple(PoolDefinition(v['pool_id'], POLICY + ':' + v['role'], context.target_id, context.mode,
        tuple(PoolMember(cid, 1) for cid in v['member_ids']), complete=True) for v in d['domains'])


def register_scopes(registry, context):
    d = load_batch(); validate_native(registry, d)
    for domain, expected in zip(d['domains'], local_pools(registry, context)):
        pool = registry.pool(domain['pool_id'], context)
        if pool.members != expected.members or not pool.complete or pool.excluded_card_ids:
            raise TargetValidationError('Champion source lost a complete original ordered faction list')
        registry.register_generation_scope(GenerationScope(POLICY + ':' + domain['role'] + ':' + context.target_id,
            pool.id, context.target_id, context.mode, CARD, None, QUERY, pool_digest(pool)))
        actual = resolve_candidates(registry, context, pool.id, QUERY, source_card_id=CARD, exclude_source_by_rule=True)
        if [asdict(v) for v in actual] != [asdict(PoolMember(cid, 1)) for cid in domain['actual_ids']]:
            raise TargetValidationError('Champion source changed the complete actual faction candidates or weights')
