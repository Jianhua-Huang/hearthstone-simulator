"""Ignite: one native base and a newly generated successor, never a global buff."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.growing_spell_damage import DamageGrowingSpell,GrowingDamageProfile
from hs_sim.engine.model import CardDefinition,CardType,TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/ignite-native-growth-v1.json'
BATCH_HASH='108ca860e5760b9f8d427062399939434073eccbb961de341460fd828331c331'
POLICY='cn37-local-ignite-native-growth-v1'
CARD='SW_110'
LEAVES=DEPENDENCIES=(CARD,)
COLLECTIBLE_ROOTS=()
BODY='cards.ignite.native_growth'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(data['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES or
            len(data['official_observations'])!=2 or data['display_normalizations']!={CARD:{'@':''}} or
            any(data[k] for k in ('cards','existing_dependencies','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Ignite requires its complete original row and two primary faces')
    path=ROOT/data['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=data['reference_sha256'] or
            CARD not in json.loads(path.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Ignite lost its complete past-Mage source scope')
    return data


def register_ignite_card(registry):
    raw=load_batch()['dependencies'][0]['record']
    if CARD in registry.cards or CARD in registry.pool_cards:raise TargetValidationError('Ignite already registered')
    amount=raw['tags']['TAG_SCRIPT_DATA_NUM_1']
    if type(amount) is not int or amount!=2:raise TargetValidationError('Ignite lost its printed native damage')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=BODY,targeting=TargetSpec(),
        spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
    registry._validate_card(card)
    def cast(c):
        if c.cast is None:raise ValueError('Ignite requires its actual active CAST')
        return (DamageGrowingSpell(c.cast.id),)
    registry.register_behavior(BODY,cast);registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_value_profile(GrowingDamageProfile(CARD,amount))
