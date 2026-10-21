"""Frontline Ironborn rewards each original enemy death in its player's turn."""
import json
from pathlib import Path

from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_996'
BODY='cards.frontline_ironborn.reward'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/frontline-ironborn-v1.json'
BATCH_HASH='8e2f203b9755782045bd027359429b1de70599efb1b12c34f1913b0825f1755f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['cards'])):
        raise TargetValidationError('Frontline Ironborn lost its complete reviewed original face')
    return data


def register_frontline_ironborn_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('RARITY'))!=('MINION',5,3,5,12,4):
        raise TargetValidationError('Frontline Ironborn requires its original neutral Epic 5-cost 3/5 face')
    def reward(c):
        if c.event is None or c.event.kind!='minion_died':return ()
        death_id=dict(c.event.data).get('death_id')
        death=next((row for row in c.state.death_history if type(death_id)is int and row.id==death_id),None)
        if (death is None or (death.entity_id,death.entity_id,death.controller)!=(c.event.source_id,c.event.target_id,c.event.player_id)
                or registry.card(death.card_id).kind!=CardType.MINION or death.zone!=Zone.BOARD):
            raise ResolutionError('Frontline Ironborn lost its original actual minion death')
        interval=next((row for row in c.state.owner_turn_history if row.turn==death.turn),None)
        if interval is None:raise ResolutionError('Frontline Ironborn needs the actual original death turn')
        if death.controller==c.player_id or interval.player_id!=c.player_id:return ()
        source=c.source
        if source.kind!=CardType.MINION or source.zone!=Zone.BOARD or not source.active or source.health<=0 or source.doomed:return ()
        presence=BoardPresenceReference.capture(c.state,c.source_id)
        return(BuffCapturedMinion(presence,2,2,c.source_id),
            GrantRandomBonusEffects(c.source_id,1,c.source_id,presence))
    registry.register_behavior(BODY,reward)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=3,health=5,
        triggers=(TriggerSpec('minion_died',BODY),),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
