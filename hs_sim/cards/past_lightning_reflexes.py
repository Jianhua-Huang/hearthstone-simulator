"""Lightning Reflexes discovers afresh after the original same-turn hand play."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-lightning-reflexes-v1.json'
BATCH_HASH='5e3a2881a2273b1ab1885eddd0ca0f8a6f2833b587302921c3a096176d8c6645'
ROOTS=('TTN_317',)
DEPENDENCIES=()
PREFIX='cards.past_lightning_reflexes.'
QUERY=PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.NATURE,),collectible=True,class_mode='current')

def make_definition(raw):
    if (raw['id']!='TTN_317' or raw['type']!='SPELL' or raw['cost']!=1 or raw['collectible']is not True
            or raw['tags'].get('SPELL_SCHOOL')!=4 or raw['tags'].get('DISCOVER')!=1):
        raise TargetValidationError('Lightning Reflexes requires its complete original Nature discovery spell')
    return CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=1,on_play=PREFIX+'discover',
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw))

def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or tuple(x['record']['id']for x in d['cards'])!=ROOTS
            or d['dependencies'] or [x['record']['id']for x in d['evidence_only']]!=['TTN_317e']
            or [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013'] or len(d['official_observations'])!=4
            or any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Lightning Reflexes lost original roles or claimed its incomplete class source complete')
    for key in('cards','evidence_only','existing_dependencies'):
        for row in d[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Lightning Reflexes lost a complete original row')
    source=(ROOT/d['full_union_source_document']).resolve()
    if not source.is_relative_to(ROOT)or hashlib.sha256(source.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Lightning Reflexes changed its complete original reference')
    return d

def register_past_lightning_reflexes(registry):
    d=load_batch();row=d['cards'][0];card=make_definition(row['record'])
    if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
        raise TargetValidationError('Lightning Reflexes cannot replace or change an original native face')
    registry._validate_card(card)
    if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
        raise TargetValidationError('Lightning Reflexes changed existing complete pool metadata')
    registry.register_behavior(PREFIX+'discover',lambda c:(DiscoverForPlayFollowup(
        DiscoverFromPool(c.player_id,'constructed.cards',QUERY,source_id=c.source_id),'rediscover'),))
    registry.register_card(card)
    if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
