"""Real Kindred tutor and native held-card bonus rotation; no generated pool."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.bonus_effects import RotatePrintedHandBonuses
from hs_sim.engine.model import CardDefinition,CardType,HandProgressSpec,Keyword
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/kindred-hand-bonus-native-v1.json'
BATCH_HASH='0b952f0db96df6b07422aae1838635d9967de547a61b23ce7467fda5574eb6eb'
TWISTED='CATA_206';TORGA='TLC_102';PREFIX='cards.kindred_hand_bonus.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Kindred tutor/native hand bonus complete source pin changed')
    return data


def register_kindred_hand_bonus_cards(registry):
    registry.register_trigger_condition(PREFIX+'own_start',lambda c:c.event is not None and c.event.player_id==c.player_id)
    registry.register_behavior(PREFIX+'rotate',lambda c:(RotatePrintedHandBonuses(CardReference.capture(c.source),c.source_id),))
    slot=DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,CardType.SPELL)))
    registry.register_behavior(PREFIX+'torga',lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(slot,slot),kindred_pair=True),))
    data=load_batch()
    if tuple(row['record']['id']for row in data['cards'])!=(TWISTED,TORGA)or data['dependencies']:
        raise TargetValidationError('Unreviewed native Kindred/hand-bonus root set')
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']:
            raise TargetValidationError('Incomplete native Kindred/hand-bonus face')
        kwargs={}
        if cid==TWISTED:
            if(raw['tags'].get('TAUNT'),raw['tags'].get('ELUSIVE'),raw['tags'].get('DYNAMIC_KEYWORD1'),raw['tags'].get('DYNAMIC_KEYWORD2'))!=(1,1,1211,190):
                raise TargetValidationError('Native initial bonus pair differs from the complete dynamic-keyword declarations')
            kwargs.update(keywords=(Keyword.TAUNT,Keyword.ELUSIVE),hand_progress=HandProgressSpec('event',1,
                on_complete=PREFIX+'rotate',repeat=True,event='turn_started',condition_id=PREFIX+'own_start'))
        else:kwargs['battlecry']=PREFIX+'torga'
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
