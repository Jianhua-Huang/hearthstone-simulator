"""Four real owner-clock spells and the exact officially linked Naga."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import ChangeControl,ReturnToHand
from hs_sim.engine.model import CardDefinition,CardType,Keyword,PlayerEffectSpec,SpellSchool,TargetSpec,Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/temporal-effect-cards-v1.json'
BATCH_HASH='dfd11269b70850acbdbea7f650f29fe71210b379d556fd2bc04ddb673802794a'
PREFIX='cards.temporal_effect.'
DAZE='CATA_215';CHAINS='CATA_496';CEREMONY='DINO_405';SEAS='CATA_528';NAGA='CATA_528t'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Temporal spell full source pin changed')
    return data


def register_temporal_effect_cards(registry):
    def transfer_space(c):
        board=next(p['board']for p in c.observation['players']if p['id']==c.player_id)
        return len(board)<c.observation['limits']['max_board']
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'transfer_space','v1'),transfer_space)
    bodies={
        'daze':lambda c:(ReturnToHand(c.target_id,to_owner=True,lock_next_owner_turn=True,source_id=c.source_id),),
        'chains':lambda c:(ChangeControl(c.target_id,c.player_id,source_id=c.source_id,
            until_previous_controller_turn_end=True,cannot_attack_this_turn=True),),
        'ceremony_expire':lambda c:(BuffMinionsInZones(c.player_id,2,2,MinionScope(zones=(Zone.BOARD,)),c.source_id),),
        'seas_expire':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(NAGA),),SummonCause.capture(c)),),
    }
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'ceremony',CEREMONY,kind='objective',
        duration=2,tick_event='turn_ended',on_expire=PREFIX+'ceremony_expire',next_turn_end=True))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'seas',SEAS,kind='sigil',
        duration=1,tick_event='turn_started',on_expire=PREFIX+'seas_expire'))
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(DAZE,CHAINS,CEREMONY,SEAS)or len(data['dependencies'])!=1:
        raise TargetValidationError('Unreviewed temporal spell batch')
    for row in data['cards']+data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete temporal spell raw face')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];metadata=replace(metadata_from_record(raw),deck_identity=cid)
        if cid==NAGA:
            if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TAUNT'),raw['tags'].get('CARDRACE'))!=('MINION',3,3,3,1,92):
                raise TargetValidationError('Unknown fixed Naga face')
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=3,attack=3,health=3,keywords=(Keyword.TAUNT,),metadata=metadata)
        else:
            recipe=row['recipe'];expected={6:'shadow',7:'fel'}.get(raw['tags'].get('SPELL_SCHOOL'))
            if raw['type']!='SPELL'or recipe['spell_school']!=expected:raise TargetValidationError('Unknown temporal spell school')
            kwargs={}
            if 'script'in recipe:
                kwargs.update(on_play=PREFIX+recipe['script'],targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'))
                if cid==CHAINS:kwargs['target_rule']=PREFIX+'transfer_space'
            else:kwargs['ongoing_effect_id']=PREFIX+recipe['ongoing']
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata,
                spell_school=SpellSchool(expected)if expected else None,**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
