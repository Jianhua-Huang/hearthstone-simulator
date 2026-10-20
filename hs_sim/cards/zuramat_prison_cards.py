"""Zuramat's actual location, its 5/5 guard and source-bound released minion."""
import json
from dataclasses import asdict
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, Keyword, TargetSpec, TriggerSpec, Zone
from hs_sim.engine.prison_playback import PlayPrisonDiscard, PrisonProfile
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial, PrisonEntryMaterial
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='JAIL_887';RELEASED=CARD+'t2';GUARD=CARD+'t3';PREFIX='cards.zuramat.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/zuramat-prison-v1.json'
BATCH_HASH='ae32ae17fb629a14307d3777172d08546d4fe0e5aa030016a253f22d26882bd8'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)
            or tuple(x['record']['id']for x in data['dependencies'])!=(RELEASED,)
            or tuple(x['record']['id']for x in data['existing_dependencies'])!=(GUARD,)
            or tuple(x['record']['id']for x in data['evidence_only'])!=(RELEASED+'e',)
            or data['skipped']
            or any(canonical_digest(x['record'])!=x['record_sha256'] for group in
                ('cards','dependencies','existing_dependencies','evidence_only') for x in data[group])):
        raise TargetValidationError('Prison requires its complete original location, minions and raw memory evidence')
    return data


def register_zuramat_prison_cards(registry):
    data=load_batch();rows={x['record']['id']:x['record']for x in (*data['cards'],*data['dependencies'])}
    pin=data['existing_dependency_definition_pins'][GUARD]
    if canonical_digest(asdict(registry.card(GUARD)))!=pin['sha256'] or canonical_digest(pin['definition'])!=pin['sha256']:
        raise TargetValidationError('Prison must preserve its complete previously implemented 5/5 guard')
    def use(c):
        if c.target_id is None: raise ValueError('Prison requires an actual hand discard selection')
        reward=SummonByCard(c.player_id,(SummonEntryMaterial(GUARD),),SummonCause.capture(c))
        return (DiscardCard(CardReference.capture(c.state.entities[c.target_id]),c.source_id,on_success=(reward,)),)
    def release(c):
        if c.death is None or c.death.card_id!=CARD:
            raise ValueError('Prison release requires its actual captured location death')
        return (SummonByCard(c.player_id,(PrisonEntryMaterial(RELEASED,prison_death_id=c.death.id),),
            SummonCause.capture(c)),)
    registry.register_behavior(PREFIX+'use',use)
    registry.register_behavior(PREFIX+'release',release)
    registry.register_behavior(PREFIX+'end',lambda c:(PlayPrisonDiscard(c.end_turn.id),)
        if c.end_turn is not None else ())
    registry.register_use_rule(PREFIX+'held',lambda c:bool(c.observation['players'][c.player_id-1]['hand']),visibility='player')
    for cid,raw in rows.items():
        fields={}
        if cid==CARD:
            fields=dict(durability=raw['health'],on_use=PREFIX+'use',deathrattle=PREFIX+'release',
                use_rule=PREFIX+'held',
                targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,CardType.SPELL,
                    CardType.WEAPON,CardType.LOCATION,CardType.HERO),relation='friendly'))
        else:
            fields=dict(attack=raw['attack'],health=raw['health'])
            if cid==GUARD:fields['keywords']=(Keyword.TAUNT,)
            else:fields['triggers']=(TriggerSpec('turn_ended',PREFIX+'end',end_turn=EndTurnSpec()),)
        card=CardDefinition(cid,raw['name'],CardType.LOCATION if cid==CARD else CardType.MINION,
            cost=raw['cost'],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_prison_profile(PrisonProfile(CARD,RELEASED,GUARD,PREFIX+'end'))
