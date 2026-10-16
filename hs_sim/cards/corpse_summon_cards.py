"""Four actual fixed-token corpse cards, with native no-corpse token faces."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.corpse_summon_rewards import CorpseSummonProfile,ResolveCorpseSummons,profile_for
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/corpse-summon-effects-v1.json'
BATCH_HASH='1729b9e23f164c337c6c46295f5c5b312653330edf7e0bcb8dcbc27216de9533'
BODY='cards.corpse_summon.native'
CHOW='CATA_465';TOMB='CORE_RLK_118';COMMANDER='CORE_RLK_506';ARMY='RLK_060'
DRAKE='CATA_465t';ZOMBIE='RLK_118t3';FOOTMAN='RLK_061t';GHOUL='RLK_008t'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Corpse summon complete source pin changed')
    return data


def register_corpse_summon_cards(registry):
    def body(c):
        profile=profile_for(registry,c)
        if profile.mode=='raise':return(ResolveCorpseSummons(c),)
        request=SummonByCard(c.player_id,(SummonEntryMaterial(profile.token_id),),SummonCause.capture(c))
        return(*(request for _ in range(profile.count)),ResolveCorpseSummons(c))
    registry.register_behavior(BODY,body);data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(CHOW,TOMB,COMMANDER,ARMY)or tuple(x['record']['id']for x in data['dependencies'])!=(DRAKE,ZOMBIE,FOOTMAN,GHOUL):
        raise TargetValidationError('Unreviewed corpse summon batch')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Incomplete corpse summon raw record')
        recipe=row.get('recipe');metadata=replace(metadata_from_record(raw),deck_identity=cid if recipe is None else recipe['deck_identity'])
        keywords=tuple(k for tag,k in(('TAUNT',Keyword.TAUNT),('RUSH',Keyword.RUSH))if raw['tags'].get(tag)==1)
        if raw['type']=='MINION':
            kwargs=dict(attack=raw['attack'],health=raw['health'],corpse_value=0 if raw['tags'].get('2217')==1 else 1)
            if cid==COMMANDER:kwargs['battlecry']=BODY
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],keywords=keywords,metadata=metadata,**kwargs)
        else:
            school=raw['tags'].get('SPELL_SCHOOL')
            if school not in(None,6):raise TargetValidationError('Unknown corpse summon spell school')
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata,on_play=BODY,
                spell_school=SpellSchool.SHADOW if school==6 else None)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for row in data['cards']:
        p=row['recipe'];registry.register_corpse_summon_profile(CorpseSummonProfile(row['record']['id'],p['token_id'],p['mode'],p['count'],p['corpse_cost'],
            Keyword(p['keyword'])if p['keyword']else None))
