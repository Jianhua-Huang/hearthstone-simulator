"""Real fixed shreds and original Treants use the ordinary shared executors."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,CastWhenDrawnSpec,
    DamageKind,Keyword,SpellSchool,TargetSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_attack_groups import AttackSummonedGroup,SummonAttackProfile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions
from .recruit_cards import shuffle

ENTROPY='TIME_026';SHRED='TIME_025t';TREES='TLC_230';TREANT='TLC_230t'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-shred-treant-v1.json'
BATCH_HASH='3949161b44aecea7845b42817ea8bbb387efef9346794b403c9b7c9aa3cf41f9'
PREFIX='cards.shred_treant.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Shred/Treant complete source pin changed')
    if(tuple(row['record']['id']for row in data['cards'])!=(ENTROPY,TREES)or
            tuple(row['record']['id']for row in data['dependencies'])!=(SHRED,TREANT)):
        raise TargetValidationError('Unreviewed Shred/Treant roots or fixed dependencies')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Shred/Treant lost its complete original row')
    return data


def register_native_shred_treant_cards(registry):
    def entropy(c):
        buffs=tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),1,1,c.source_id)
            for i in minions(c,registry,c.player_id))
        return(*buffs,*shuffle(c,SHRED,2))
    def shred(c):
        return(Damage(c.state.players[c.player_id].hero_id,3,c.source_id,DamageKind.SPELL,spell_bonus_multiplier=0),)
    def trees(c):
        if c.cast is None or c.cast.card_id!=TREES or c.cast.source_id!=c.source_id:
            raise ResolutionError('Treants require their original native spell body')
        target=c.state.entities.get(c.target_id)
        if target is None or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return ()
        reference=BoardPresenceReference.capture(c.state,target.id)
        request=SummonByCard(c.player_id,(SummonEntryMaterial(TREANT),),SummonCause.capture(c))
        return(request,request,request,request,AttackSummonedGroup(c,reference))
    for name,body in(('entropy',entropy),('shred',shred),('trees',trees)):
        registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['cost'] is not None:kwargs['cost']=raw['cost']
        elif 'COST'in raw['tags']:raise TargetValidationError('Missing printed cost cannot carry a COST tag')
        if cid==TREANT:
            if(kind,raw['attack'],raw['health'])!=(CardType.MINION,2,2):raise TargetValidationError('Unreviewed exact Treant')
            kwargs.update(attack=raw['attack'],health=raw['health'])
        elif kind!=CardType.SPELL:raise TargetValidationError('Shred/Treant roots require native SPELL definitions')
        elif cid==TREES:
            if raw['tags'].get('SPELL_SCHOOL')!=4:raise TargetValidationError('Treants must retain Nature')
            kwargs.update(on_play=PREFIX+'trees',spell_school=SpellSchool.NATURE,
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        else:
            if 'SPELL_SCHOOL'in raw['tags']:raise TargetValidationError('Do not invent a Shred/Continuity school')
            kwargs['on_play']=PREFIX+('entropy'if cid==ENTROPY else'shred')
            if cid==SHRED:
                if raw['tags'].get('349')!=1:raise TargetValidationError('Shred lost its immune-to-spellpower raw evidence')
                kwargs.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        card=CardDefinition(cid,raw['name'],kind,metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_summon_attack_profile(SummonAttackProfile(TREES,TREANT,4,combat_relation='any_minions'))
