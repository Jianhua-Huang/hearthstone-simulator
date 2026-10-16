"""Native draw restrictions, retained original copies and named Wisp costs."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import Draw,RefreshMana
from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec,TargetMode,TargetSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record,reviewed_definition_digest

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/draw-retention-limits-v1.json'
BATCH_HASH='704571fc2c5e45bb736cf73e86a4778a8f25b04b48c0aa9bf89c4e7f0cd73e2f'
PREFIX='cards.draw_retention.'
SCRIPTS={'BE_EVENT_100':'old_gods','BE_EVENT_101':'titans','EDR_234':'bounty','EDR_522':'mimicry','TIME_031':'ladder','EDR_804':'divination'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Draw retention cards lost their complete reviewed pin')
    return value


def register_draw_retention_cards(registry):
    data=load_batch();wisps=[]
    for row in data['named_target_evidence']:
        raw=row['record']
        if canonical_digest(raw)!=row['record_sha256']or raw['name_en']!='Wisp'or raw['type']!='MINION':
            raise TargetValidationError('Named Wisp target family lost its complete raw evidence')
        if row['registered_definition_present']and reviewed_definition_digest(registry.card(raw['id']))!=row['definition_sha256']:
            raise TargetValidationError('Existing native Wisp differs from its complete reused definition')
        wisps.append(raw['id'])
    wisps=frozenset(wisps)
    gallery=data['gallery_links'][0]['gallery_record']
    if gallery['id']!=114012 or 116450 not in gallery['child_ids']or 'EDR_851t'not in wisps:
        raise TargetValidationError('Divination lost its named CN Wisp child link')
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'wisp','v1'),lambda c:c.target['card_id']in wisps)
    def arrival(c,kind,refresh):
        return (DrawMatching(c.player_id,PoolQuery(kinds=(kind,)),'skip',count=2,source_id=c.source_id),
            RefreshMana(c.player_id,refresh),AddPlayerEffect(c.player_id,PREFIX+kind.value+'_only',c.source_id))
    bodies=dict(old_gods=lambda c:arrival(c,CardType.MINION,5),titans=lambda c:arrival(c,CardType.SPELL,6),
        bounty=lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*2,DrawGroupReward('lock_all',2)),),
        mimicry=lambda c:(DrawPhysicalGroup(3-c.player_id,c.source_id,(DrawGroupSlot(),)*2,DrawGroupReward('copy_other')),),
        ladder=lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PoolQuery(),different_costs=True),)*3),),
        divination=lambda c:(DestroyCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),c.source_id,
            (Draw(c.player_id,3,c.source_id),)),))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];school=raw['tags'].get('SPELL_SCHOOL');kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(raw['id'])!=recipe['script']:
            raise TargetValidationError('Draw retention recipe differs from its complete reviewed spell face')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unknown draw retention spell school')
        if raw['id']=='EDR_804':kwargs.update(target_rule=PREFIX+'wisp',targeting=TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for kind,cid in ((CardType.MINION,'BE_EVENT_100'),(CardType.SPELL,'BE_EVENT_101')):
        registry.register_player_effect(PlayerEffectSpec(PREFIX+kind.value+'_only',cid,kind='turn_rule',allowed_card_types=(kind,)))
