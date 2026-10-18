"""Tranquil Clearing: a normal Taunt body with a separate voluntary attack clock."""
import json
from pathlib import Path

from hs_sim.engine.attack_policies import GrantAttackPolicy,next_owner_end
from hs_sim.engine.model import AttackPolicySpec,CardDefinition,CardType,Keyword,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='MEND_044'
BODY='cards.owner_end_sleep.clearing'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-owner-end-sleep-v1.json'
BATCH_HASH='21aafba6bb5892a7ec8ff204645350faced9deaacc4566325745b5e0bbf0238b'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(value)!=BATCH_HASH or tuple(x['record']['id']for x in value['cards'])!=(CARD,)or
            value['dependencies']or value['existing_dependencies']or value['skipped']):
        raise TargetValidationError('Tranquil Clearing requires its complete original location and evidence')
    for row in value['cards']+value['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Tranquil Clearing original row changed')
    return value


def register_native_owner_end_sleep_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['health'])!=('LOCATION',2,2):
        raise TargetValidationError('Tranquil Clearing lost its actual location face')
    def body(c):
        reference=MinionReference.capture(c.state.entities[c.target_id])
        deadline=next_owner_end(c.state,c.player_id)
        return(BuffCapturedMinion(reference,0,2,c.source_id),
            GrantCapturedKeyword(reference,Keyword.TAUNT,c.source_id),
            GrantAttackPolicy(reference.entity_id,AttackPolicySpec('cannot_attack'),c.source_id,
                recipient=reference,until_next_turn_end=deadline))
    registry.register_behavior(BODY,body)
    card=CardDefinition(CARD,raw['name'],CardType.LOCATION,cost=raw['cost'],durability=raw['health'],
        on_use=BODY,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
