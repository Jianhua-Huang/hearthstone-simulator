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
BATCH_PATH=ROOT/'data/cards/past-conductivity-v1.json'
BATCH_HASH='1e8405522122839091a89ea330438d8c6bf173eb4c733c5ceaa2b22ce4abb351'
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
