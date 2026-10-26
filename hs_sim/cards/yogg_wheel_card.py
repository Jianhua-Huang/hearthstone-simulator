"""The six actual Wheel outcomes compose ordinary typed public operations."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.destruction_resources import DestroyMinionsForStats
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,CostSpec,Keyword,Zone
from hs_sim.engine.pools import FillBoardFromPool,FillHandFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.random_control import TakeRandomEnemyMinions
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.spell_history import CastFromPool,personal_hand_spell_count
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.terminal_spell_loops import CastSpellUntilHeroDies
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .original_yogg_native import CAP

CARD='DMF_004'
OUTCOMES=tuple(CARD+'t'+str(n)for n in range(1,7))
PYRO='EX1_279'
PREFIX='cards.yogg_wheel.'
SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True)
MINIONS=PoolQuery(kinds=(CardType.MINION,),collectible=True)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/yogg-wheel-v1.json'
BATCH_HASH='74e3e51b126921a056e926a4f09f2bbf773c87e50fcd3b63b36edbafb09c2480'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows=[*data['cards'],*data['choice_only'],*data['existing_dependencies'],*data['evidence_only']]
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in data['choice_only'])!=OUTCOMES or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=(PYRO,) or
            tuple(x['record']['id']for x in data['evidence_only'])!=(CARD+'t1e',CARD+'t5e') or
            data['dependencies'] or data['skipped'] or len(data['official_faces'])!=2 or
            tuple(data['weights'][cid]for cid in OUTCOMES)!=(19,19,19,19,19,5) or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in rows)):
        raise TargetValidationError('Yogg Wheel requires all six original outcomes and explicit complete local weights')
    return data


def register_yogg_wheel_card(registry):
    data=load_batch();raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['PLAYER_TAG_THRESHOLD_VALUE'])!=('MINION',10,7,5,10):
        raise TargetValidationError('Yogg Wheel lost its original face or ten-spell threshold')
    if any(cid in registry.cards for cid in (CARD,*OUTCOMES)):
        raise TargetValidationError('Yogg Wheel cannot overwrite a reviewed native identity')
    if canonical_digest(asdict(registry.card(PYRO)))!=data['existing_dependencies'][0]['definition_sha256']:
        raise TargetValidationError('Wheel requires the complete existing native Pyroblast definition')
    names={row['record']['id']:row['record']['name']for row in data['choice_only']}
    def rush(c):
        from hs_sim.engine.cross_zone import MinionScope,minion_references
        return tuple(GrantCapturedKeyword(ref,Keyword.RUSH,c.source_id)
            for ref in minion_references(c.state,registry,c.player_id,MinionScope((Zone.BOARD,)),c.source_id))
    def spin(c):
        if (c.battlecry is None or not c.battlecry.payload_started or c.battlecry.failure is not None or
                (c.battlecry.source_id,c.battlecry.player_id)!=(c.source_id,c.player_id)):
            raise ResolutionError('Wheel requires its original accepted minion Battlecry')
        count=personal_hand_spell_count(c.state,registry,c.player_id,c.source_id)
        if count<10:return()
        presence=BoardPresenceReference.capture(c.state,c.source_id)if c.source.zone==Zone.BOARD else None
        cause=SummonCause.capture(c)
        effects=(
            (CastFromPool(c.player_id,'constructed.cards',SPELLS,count=min(CAP,count),source_id=c.source_id),),
            (FillHandFromPool(GenerateFromPool(c.player_id,'constructed.cards',SPELLS,source_id=c.source_id,
                cost=CostSpec(set_to=0),expires_turn=c.state.turn)),),
            (FillBoardFromPool(c.player_id,'constructed.cards',MINIONS,c.source_id,cause),
                FillBoardFromPool(3-c.player_id,'constructed.cards',MINIONS,c.source_id,cause),
                InvokeBehavior(PREFIX+'rush',c.source_id,c.player_id)),
            (TakeRandomEnemyMinions(c.player_id,c.source_id),),
            (DestroyMinionsForStats(c.player_id,c.source_id,presence),),
            (CastSpellUntilHeroDies(c.player_id,PYRO,c.source_id),),
        )
        options=tuple(ChoiceOption(cid,names[cid],work,card_id=cid)for cid,work in zip(OUTCOMES,effects))
        return(ChooseRandomEffects(c.player_id,c.source_id,options,tuple(data['weights'][cid]for cid in OUTCOMES)),)
    registry.register_behavior(PREFIX+'rush',rush);registry.register_behavior(PREFIX+'spin',spin)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=PREFIX+'spin',metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for row in data['choice_only']:
        raw=row['record']
        if(raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('HIDE_COST'))!=('SPELL',None,False,1):
            raise TargetValidationError('Wheel outcome labels require original hidden-cost noncollectible spell faces')
        registry.register_card(CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=0,choice_only=True,
            metadata=metadata_from_record(raw)))
