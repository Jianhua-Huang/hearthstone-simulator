"""Hamuul composes original-deck school checks, persistent triggers and Imbue."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.deck_conditions import CheckDeckCondition,DeckSpellSchoolCondition
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition,CardType,OpeningHook,PlayerEffectSpec,SpellSchool,TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_casts import cast_record,cast_spells
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_845'
PREFIX='cards.nature_opening_imbue.'
PROGRAM=PREFIX+'every_three'
CONDITION=DeckSpellSchoolCondition(SpellSchool.NATURE)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/nature-opening-imbue-v1.json'
BATCH_HASH='9758fd7377cd2056b4e153c505b0caf6fac8489fdb6c25314e88ee793cef032e'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in data['cards'])!=(CARD,)
            or tuple(r['record']['id']for r in data['evidence_only'])!=('EDR_845e1',)or data['dependencies']):
        raise TargetValidationError('Hamuul complete original source pin changed')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Hamuul original source row changed')
    return data


def register_nature_opening_imbue_card(registry):
    def every_three(c):
        if c.event is None or c.event.kind!='spell_cast_finished' or c.event.player_id!=c.player_id:return ()
        if c.player_effect is None or c.player_effect.spec_id!=PROGRAM:
            raise ResolutionError('Hamuul lost its original persistent opening program')
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if row.player_id!=c.player_id or not row.completed or row.failure is not None:
            raise ResolutionError('Hamuul requires the original successful completed cast')
        count=len(cast_spells(c.state,c.player_id,successful=True))
        return (Imbue(c.player_id,c.source_id),)if count and count%3==0 else ()
    registry.register_behavior(PREFIX+'every_three',every_three)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD,
        triggers=(TriggerSpec('spell_cast_finished',PREFIX+'every_three'),)))
    registry.register_behavior(PREFIX+'start',lambda c:(CheckDeckCondition(c.player_id,CONDITION,
        (AddPlayerEffect(c.player_id,PROGRAM,c.source_id),Imbue(c.player_id,c.source_id))),))
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',5,5,6):
        raise TargetValidationError('Unexpected Hamuul original face')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=5,health=6,
        opening_hooks=(OpeningHook('before_deal',PREFIX+'start'),),metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
