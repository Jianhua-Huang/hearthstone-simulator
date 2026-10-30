"""Five real numeric/resource spells and their exact fixed Golem dependency."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,Buff,Damage,DamageBatch,Destroy,SetStats
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.mana_summon_rewards import SpendManaForSummonedPair
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_target_conditions import UnplayedCopyTargetProfile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/numeric-resource-effects-v1.json'
BATCH_HASH='099cd554c05dfe6b96eca84a2d4bd83b6e4734faf15d2846163a8daa94cdbc76'
PREFIX='cards.numeric_resource.'
FOREST='CATA_138';URSOL='EDR_252';TRIUMPH='CATA_557';BRIBE='CATA_EVENT_402';MOSS='CATA_135';GOLEM='CATA_135t';COIN='GAME_005'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Numeric/resource full source pin changed')
    return data


def register_numeric_resource_cards(registry):
    def forest(c):
        count=sum(c.state.entities[i].kind==CardType.MINION and registry.card(c.state.entities[i].card_id).interactable is None
            for i in c.state.players[c.player_id].board)
        return(Buff(c.target_id,count,count,c.source_id),)
    def ursol(c):
        amount=3 if c.state.entities[c.target_id].controller==c.player_id else 1
        return(SetStats(c.target_id,amount,amount,c.source_id),)
    def triumph(c):
        if c.cast is None:raise UnsupportedDefinitionError('Triumph requires its actual accepted spell target window')
        # The finite native profile already accepted required-target versus
        # no-target text. Do not acquire a different branch during reactions.
        if c.target_id is None:
            return(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.SPELL)for i in characters(c,registry,3-c.player_id))),)
        return(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),)
    def moss(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(GOLEM),),SummonCause.capture(c))
        return(request,request,SpendManaForSummonedPair(c,GOLEM))
    def bribe(c):
        return(Destroy(c.target_id,c.source_id),AddToHand(3-c.player_id,COIN,c.source_id),
            *((AddToHand(c.player_id,COIN,c.source_id),)if c.spell_conditions.combo else()))
    bodies=dict(forest=forest,ursol=ursol,triumph=triumph,moss=moss,
        bribe=bribe)
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    data=load_batch();rows=data['cards']+data['dependencies']
    if tuple(x['record']['id']for x in data['cards'])!=(FOREST,URSOL,TRIUMPH,BRIBE,MOSS)or len(data['dependencies'])!=1:
        raise TargetValidationError('Unreviewed numeric/resource batch')
    for row in rows:
        raw=row['record']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Incomplete numeric/resource raw face')
        metadata=replace(metadata_from_record(raw),deck_identity=raw['id'])
        if raw['id']==GOLEM:
            if(raw['cost'],raw['attack'],raw['health'],raw['type'])!=(1,1,2,'MINION'):raise TargetValidationError('Unknown Moss Golem face')
            card=CardDefinition(GOLEM,raw['name'],CardType.MINION,cost=1,attack=1,health=2,metadata=metadata)
        else:
            recipe=row['recipe'];cid=raw['id'];kwargs={}
            if raw['type']!='SPELL' or recipe['spell_school']!=('nature'if raw['tags'].get('SPELL_SCHOOL')==4 else None):
                raise TargetValidationError('Unknown numeric/resource spell school')
            if cid==FOREST:kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
            elif cid in(URSOL,BRIBE):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
            elif cid==TRIUMPH:kwargs['requires_target']=True
            if cid==BRIBE:kwargs.update(keywords=(Keyword.COMBO,))
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata,on_play=PREFIX+recipe['script'],
                spell_school=SpellSchool(recipe['spell_school'])if recipe['spell_school']else None,**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    coin=data['reused_dependencies'][0]
    from dataclasses import asdict
    if coin['record']['id']!=COIN or canonical_digest(coin['record'])!=coin['record_sha256']or canonical_digest(asdict(registry.card(COIN)))!=coin['definition_digest']:
        raise TargetValidationError('Original Coin dependency changed')
    registry.register_spell_target_profile(UnplayedCopyTargetProfile(TRIUMPH))
