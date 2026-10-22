"""Real Assemble entries over the existing immutable face and offer machinery.

Reviewed fragments do not establish official curated-pool membership. A host
must supply the separate complete domain; no ordinary-pool fallback is added.
"""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

FETCHER, NURTURER, CARETAKER, SHAPER, FLESH = 'BE_044', 'BE_262', 'BE_851', 'BE_229', 'BE_571'
ROOTS = COLLECTIBLE_ROOTS = (FETCHER, NURTURER, CARETAKER, SHAPER, FLESH)
DEPENDENCIES = ()
FRAGMENT_SOURCES = ('CORE_UNG_809', 'CORE_EX1_096', 'CORE_GIL_622', 'CORE_UNG_084',
    'CORE_EX1_110', 'BE_855', 'BE_856', 'BE_859', 'BE_152')
POOL_ID = 'constructed.assemble'
PREFIX = 'cards.native_assemble_entries.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-assemble-entries-v2.json'
BATCH_HASH = 'e80a179dc7d7988feaf6a63d487ae0b94ad8b3a74fa318d067fc0d5217c2ca42'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != FRAGMENT_SOURCES or
            tuple(t['card_id'] for t in data['reviewed_templates']) != FRAGMENT_SOURCES or
            any(data[k] for k in ('dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256']
                for r in data['cards']+data['existing_dependencies'])):
        raise TargetValidationError('Native Assemble entries require five full roots and nine pinned original fragments')
    return data


def register_native_assemble_entry_cards(registry):
    data = load_batch()
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        original = registry.card(row['record']['id'])
        if canonical_digest(asdict(original)) != row['definition_sha256']:
            raise TargetValidationError('Assemble fragment changed its complete original native definition')
        timing = declaration['timing']
        end_turn = original.triggers[0].end_turn if timing == 'end_turn' else None
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(timing, tuple(Keyword(k) for k in declaration['keywords']), end_turn),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']),
                original.requires_target, original.targeting, original.target_rule)))

    policy = data['experimental_source_policy']
    if policy != dict(pool_id=POOL_ID, empty_policy='error', small_policy='error',
            keep_policy='forbid', formal_pool_installed=False, not_cn_calibrated=True):
        raise TargetValidationError('Unreviewed Assemble source policy or formal-pool claim')

    def request(c, query=PoolQuery(), trait='any'):
        return Assemble(c.player_id, POOL_ID, source_id=c.source_id, primary_query=query,
            primary_trait=trait, empty_policy=policy['empty_policy'],
            small_policy=policy['small_policy'], keep_policy=policy['keep_policy'])

    bodies = {
        FETCHER: lambda c: (request(c, PoolQuery(min_cost=4, max_cost=4)),),
        NURTURER: lambda c: (request(c, PoolQuery(min_cost=1, max_cost=1)),),
        CARETAKER: lambda c: (request(c, PoolQuery(tribes_any=('beast',))),),
        SHAPER: lambda c: (request(c, trait='end_turn'),),
        FLESH: lambda c: (request(c, trait='deathrattle'),
            BuffMinionsInZones(c.player_id, 2, 2, MinionScope((Zone.HAND,)), c.source_id)),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = (dict(attack=raw['attack'], health=raw['health'], battlecry=PREFIX+cid)
            if kind == CardType.MINION else
            dict(spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), on_play=PREFIX+cid))
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
