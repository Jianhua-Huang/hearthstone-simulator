"""Conductivity delegates complete adjacent spell bodies to the shared interpreter."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec,SpellSchool
from hs_sim.engine.next_spell_bodies import AdjacentSpellBodyProfile
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-conductivity-v2.json'
BATCH_HASH='e3c4f61e7abd6c81f624e5462b5774b7baebde46f033ab15984cbffdf9805ee7'
ROOTS=('YOG_522',)
DEPENDENCIES=()
PREFIX='cards.past_conductivity.'
PROGRAM=PREFIX+'next_adjacent'


def make_definition(raw):
    if (raw['id']!='YOG_522' or raw['type']!='SPELL' or raw['cost']!=2 or raw['collectible']is not True
            or raw['tags'].get('SPELL_SCHOOL')!=4 or raw['tags'].get('CLASS')!=8):
        raise TargetValidationError('Conductivity requires its complete original Shaman Nature spell')
    return CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=2,on_play=PREFIX+'install',
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or tuple(x['record']['id']for x in d['cards'])!=ROOTS
            or d['dependencies'] or [x['record']['id']for x in d['evidence_only']]!=['YOG_522e']
            or [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013'] or len(d['official_observations'])!=4
            or any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Conductivity lost its complete original face/roles or claimed an incomplete source complete')
    for key in('cards','evidence_only','existing_dependencies'):
        for row in d[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Conductivity changed an original full row')
    prior=(ROOT/d['previous_document']).resolve()
    if (d['policy_id']!='cn37-local-conductivity-v2' or not prior.is_relative_to(ROOT) or
            hashlib.sha256(prior.read_bytes()).hexdigest()!=d['previous_document_sha256']):
        raise TargetValidationError('Conductivity lost its preserved original implementation evidence')
    original=json.loads(prior.read_text(encoding='utf8'))
    if any(d[k]!=original[k] for k in ('cards','evidence_only','existing_dependencies','official_observations',
            'original_shaman_member_ids','full_union_source_document','full_union_source_sha256')):
        raise TargetValidationError('Conductivity body extension changed original raw faces, roles or membership')
    source=(ROOT/d['full_union_source_document']).resolve()
    if not source.is_relative_to(ROOT)or hashlib.sha256(source.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Conductivity changed its complete original reference source')
    return d


def register_past_conductivity(registry):
    row=load_batch()['cards'][0];card=make_definition(row['record'])
    if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
        raise TargetValidationError('Conductivity cannot replace or change an original native face')
    registry._validate_card(card)
    if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
        raise TargetValidationError('Conductivity changed existing complete pool metadata')
    registry.register_behavior(PREFIX+'install',lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))
    registry.register_card(card)
    if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,card.id,kind='next_spell_adjacent'))
    registry.register_next_spell_body_profile(AdjacentSpellBodyProfile(PROGRAM,card.id))
