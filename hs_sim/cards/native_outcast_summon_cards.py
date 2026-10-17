"""Horn of Feasting binds its post-summon reward to the original deliveries."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_keyword_groups import GrantOutcastSummonedGroup, OutcastSummonProfile
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-outcast-summon-v1.json'
BATCH_HASH='ce773b8deab42e2011fa84a19cc1ba5de5ae74544c48b2713e6998dfd55a4519'
HORN,RAPTOR,ENCHANT='DINO_136','DINO_136t','DINO_136e'
BODY='cards.native_outcast_summon.horn'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(HORN,)or
            tuple(x['record']['id']for x in data['dependencies'])!=(RAPTOR,)or
            tuple(x['record']['id']for x in data['evidence_only'])!=(ENCHANT,)or
            any(data[k]for k in('existing_dependencies','skipped'))):
        raise TargetValidationError('Horn of Feasting requires its complete fixed source/dependency')
    for row in data['cards']+data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original Horn/Raptor row')
    return data


def register_native_outcast_summon_cards(registry):
    def horn(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(RAPTOR),),SummonCause.capture(c))
        return(request,request,request,GrantOutcastSummonedGroup(c))
    registry.register_behavior(BODY,horn);data=load_batch()
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if cid==HORN:
            if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('OUTCAST'))!=('SPELL',4,14,1):
                raise TargetValidationError('Horn lost its actual Demon Hunter Outcast spell')
            kwargs.update(on_play=BODY,keywords=(Keyword.OUTCAST,))
        else:
            if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('RUSH'),raw['collectible'])!=('MINION',2,2,1,1,False):
                raise TargetValidationError('Horn lost its explicit real Rush Raptor')
            kwargs.update(attack=2,health=1,keywords=(Keyword.RUSH,))
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_outcast_summon_profile(OutcastSummonProfile(HORN,RAPTOR,3))
