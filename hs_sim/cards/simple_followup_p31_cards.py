"""Ordinary targeted spells followed by explicit-format discovery or generation."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,Freeze,Heal
from hs_sim.engine.model import CardClass,CardDefinition,CardType,DamageKind,HealingKind,SpellSchool,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p31-v1.json'
BATCH_HASH='c04cbd923f0bb0ec24485ae63bac169d82fbaa20d98fc77a9acd2d99be243039'
ORB='CORE_BAR_541';ADVANCE='CORE_CATA_009';SNAP='JAIL_125';PHOTO='EDR_848'
ROOTS=(ORB,ADVANCE,SNAP,PHOTO);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p31.'
IDENTITIES={ORB:'BAR_541',ADVANCE:ADVANCE,SNAP:SNAP,PHOTO:PHOTO}
QUERIES={ORB:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),
 ADVANCE:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),
 SNAP:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FROST,)),
 PHOTO:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.DRUID,),include_neutral=False)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P31 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('BAR_541',)or data['skipped']or data['reviewed_display_normalizations']!={PHOTO:{'#6':'6'}}):raise TargetValidationError('Unreviewed P31 recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P31 original row')
    return data

def register_simple_followup_p31_cards(registry):
    def orb(c):return(Damage(c.target_id,2,c.source_id,kind=DamageKind.SPELL),DiscoverFromPool(c.player_id,POOL_ID,QUERIES[ORB],source_id=c.source_id))
    def advance(c):return(Freeze(c.target_id,c.source_id),DiscoverFromPool(c.player_id,POOL_ID,QUERIES[ADVANCE],source_id=c.source_id))
    def snap(c):return(Freeze(c.target_id,c.source_id),GenerateFromPool(c.player_id,POOL_ID,QUERIES[SNAP],source_id=c.source_id))
    def photo(c):return(Heal(c.target_id,6,c.source_id,kind=HealingKind.SPELL),GenerateFromPool(c.player_id,POOL_ID,QUERIES[PHOTO],count=3,source_id=c.source_id))
    bodies={ORB:orb,ADVANCE:advance,SNAP:snap,PHOTO:photo}
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];school=raw['tags'].get('SPELL_SCHOOL')
        if raw['type']!='SPELL'or raw['collectible']is not True or type(raw['cost'])is not int or school not in SCHOOLS:raise TargetValidationError('P31 requires complete reviewed spell faces')
        registry.register_behavior(PREFIX+cid,bodies[cid]);card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,spell_school=SCHOOLS[school],
            targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='enemy'if cid==SNAP else'any'),
            metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
