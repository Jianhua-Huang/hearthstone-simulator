"""Two native consumers of the complete host-bound Dark Gift discovery."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS,DARK_GIFT_VERSION
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardClass,CardDefinition,CardType,DamageKind,SpellSchool,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p37-v1.json'
BATCH_HASH='73a370ba90fd64ce3744cb28225e05518c479ce18622afe972b6fd0491d57864'
RIDER='EDR_456';SUFFUSION='FIR_939';ROOTS=(RIDER,SUFFUSION);DEPENDENCIES=();EXISTING_DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p37.'
QUERIES={RIDER:PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',tribes_any=('dragon',)),
 SUFFUSION:PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='specified',classes=(CardClass.WARRIOR,),include_neutral=False)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))or data['gift_version']!=DARK_GIFT_VERSION or data['gift_recipes_sha256']!=canonical_digest([asdict(g)for g in DARK_GIFTS])or tuple(x['record']['id']for x in data['existing_gift_sources'])!=tuple(g.id for g in DARK_GIFTS)):raise TargetValidationError('P37 complete reviewed source or gift inventory changed')
    for row in data['cards']+data['existing_gift_sources']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P37 original row')
    return data

def register_simple_followup_p37_cards(registry):
    def rider(c):
        if not any(has_any_tribe(registry,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand):return ()
        return(DiscoverDarkGift(c.player_id,POOL_ID,QUERIES[RIDER],c.source_id),)
    def suffusion(c):return(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),DiscoverDarkGift(c.player_id,POOL_ID,QUERIES[SUFFUSION],c.source_id))
    registry.register_behavior(PREFIX+RIDER,rider);registry.register_behavior(PREFIX+SUFFUSION,suffusion)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int:raise TargetValidationError('P37 requires complete collectible faces')
        if cid==RIDER:
            if raw['type']!='MINION'or any(type(raw[k])is not int for k in('attack','health'))or raw['tags'].get('SPELL_SCHOOL')is not None:raise TargetValidationError('P37 native Demon face changed')
            kwargs.update(attack=raw['attack'],health=raw['health'],battlecry=PREFIX+cid)
        elif raw['type']=='SPELL'and raw['tags'].get('SPELL_SCHOOL')==2:kwargs.update(on_play=PREFIX+cid,spell_school=SpellSchool.FIRE,targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))
        else:raise TargetValidationError('P37 native Fire spell face changed')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
