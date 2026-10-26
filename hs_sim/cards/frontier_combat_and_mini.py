"""Actual Assemblybot and Rabbit consume shared forced combat and native cleave."""
import json
from pathlib import Path

from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyCharacter
from hs_sim.engine.model import (CardDefinition, CardType, EndTurnSpec,
    HandDerivativeSpec, Keyword, TriggerSpec)
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOTS=('TOY_601','DMF_070')
MINI, BOT='TOY_601t','TOY_601t2'
PREFIX='cards.frontier_combat_and_mini.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/frontier-combat-and-mini-v1.json'
BATCH_HASH='244d6b4047c67c5f17f186c11dd18bbe85c60cf0366bca8ca8c63b7127b1f8a8'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=value['cards']+value['dependencies']
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or
            tuple(x['record']['id']for x in value['cards'])!=ROOTS or
            tuple(x['record']['id']for x in value['dependencies'])!=(MINI,BOT) or
            len(value['official_faces'])!=8 or value['formal_pool_complete']is not False or
            value['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Assemblybot/Rabbit lost their complete original native source scope')
    return value


def register_frontier_combat_and_mini(registry):
    value=load_batch();rows={x['record']['id']:x['record']for x in value['cards']+value['dependencies']}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Assemblybot/Rabbit cannot replace existing native identities')
    registry.register_behavior(PREFIX+'end',lambda c:(SummonByCard(c.player_id,
        (SummonEntryMaterial(BOT,on_summon=PREFIX+'attack'),),SummonCause.capture(c)),))
    registry.register_behavior(PREFIX+'attack',lambda c:(AttackRandomEnemyCharacter(
        original_named_reference(c),c.player_id,c.source_id),))
    for cid,raw in rows.items():
        fields={}
        if cid in ('TOY_601',MINI):
            fields['triggers']=(TriggerSpec('turn_ended',PREFIX+'end',EndTurnSpec('controller')),)
        if cid=='TOY_601':
            fields.update(keywords=(Keyword.MINIATURIZE,),hand_derivatives=(HandDerivativeSpec(Keyword.MINIATURIZE,MINI),))
        elif cid==MINI:fields['keywords']=(Keyword.MINI,)
        elif cid=='DMF_070':fields.update(keywords=(Keyword.RUSH,Keyword.POISONOUS),cleave=True)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
