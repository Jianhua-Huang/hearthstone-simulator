"""Fyrakk's native school immunity and sequential printed-mana spell budget."""
import json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealthFlow, HealthLayer,
    HealthOp, HealthRule, SpellSchool)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_mana_budget import CastManaWorth
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'FIR_959'
BODY = 'cards.fyrakk.fire_budget'
POOL_ID = 'constructed.cards'
IMMUNITY = HealthRule(HealthFlow.DAMAGE,HealthOp.SPELL_IMMUNITY,layer=HealthLayer.TARGET,
    target_relation='self',target_kinds=(CardType.MINION,),damage_kinds=(DamageKind.SPELL,),schools=(SpellSchool.FIRE,))
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/mana-budget-v1.json'
BATCH_HASH = '4ae6e3b819b8c7229b6170cbabeb893a2aa5bc73efba6f38bf1d2bb6ec971019'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            any(data[k] for k in ('dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Fyrakk requires its reviewed complete source and Fire dependencies')
    for row in (*data['cards'],*data['existing_dependencies']):
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Original Fyrakk or Fire spell source changed')
    raw=data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags']['CLASS'],
            raw['tags']['RARITY'],raw['tags']['BATTLECRY'])!=('MINION',10,7,7,True,12,5,1):
        raise TargetValidationError('Original ten-cost Legendary Dragon changed')
    if any(x['record']['type']!='SPELL' or x['record']['tags'].get('SPELL_SCHOOL')!=2
            for x in data['existing_dependencies']):
        raise TargetValidationError('Reviewed Fire dependency is not an original Fire spell')
    return data


def register_mana_budget_cards(registry):
    registry.register_behavior(BODY,lambda c:(CastManaWorth(c.player_id,POOL_ID,SpellSchool.FIRE,15,
        c.source_id,c.source.card_id),))
    raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=10,attack=7,health=7,battlecry=BODY,
        health_rules=(IMMUNITY,),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
