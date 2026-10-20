"""Real low/high-cost and specified-Mage Assemble sources."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardClass, CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_assemble_entry_cards import POOL_ID

MISMATCH, THAW, MAGE_FRAGMENT = 'BE_045', 'BE_257', 'CORE_DRG_107'
ROOTS = COLLECTIBLE_ROOTS = (MISMATCH, THAW)
DEPENDENCIES = ()
PREFIX = 'cards.assemble_source_exceptions.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-source-exceptions-v1.json'
BATCH_HASH = '4f5544defa575bde08d5575d3df8a2e0ffd565b2c33576f4c15d8b4ca140cec3'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(r['record']['id'] for r in data['cards']) != ROOTS or
            tuple(r['record']['id'] for r in data['existing_dependencies']) != (MAGE_FRAGMENT,) or
            any(data[k] for k in ('dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['cards']+data['existing_dependencies'])):
        raise TargetValidationError('Assemble source exceptions require two full roots and one whole Mage fragment')
    return data


def register_assemble_source_exception_cards(registry):
    data = load_batch(); original = registry.card(MAGE_FRAGMENT)
    if canonical_digest(asdict(original)) != data['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Mage fragment changed its complete original definition')
    declaration = data['reviewed_template']
    registry.register_assemble_template(AssembleTemplate(MAGE_FRAGMENT,
        AssemblePrefix(declaration['timing'], tuple(Keyword(k) for k in declaration['keywords'])),
        AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']))))
    policy = data['experimental_source_policy']
    if policy != dict(pool_id=POOL_ID, empty_policy='error', small_policy='error',
            keep_policy='forbid', formal_pool_installed=False, not_cn_calibrated=True):
        raise TargetValidationError('Assemble source exception changed its experimental domain policy')

    def request(c, **kwargs):
        return Assemble(c.player_id, POOL_ID, c.source_id, empty_policy=policy['empty_policy'],
            small_policy=policy['small_policy'], keep_policy=policy['keep_policy'], **kwargs)

    bodies = {
        MISMATCH: lambda c: (request(c, primary_query=PoolQuery(max_cost=3), secondary_min_cost=5),),
        THAW: lambda c: (request(c, primary_query=PoolQuery(class_mode='specified',
            classes=(CardClass.MAGE,), include_neutral=False),
            minion_grant=CreatedMinionGrant(special='hand_turn_end_discount')),),
    }
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in data['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = (dict(attack=raw['attack'], health=raw['health'], keywords=(Keyword.TAUNT,), battlecry=PREFIX+cid)
            if cid == MISMATCH else dict(on_play=PREFIX+cid, spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))))
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
