"""Sharp-Eyed Lookout consumes the original draw and current-turn stored-cost layer."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_sequences import DrawWithTemporaryCostReduction
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_950'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/temporary-draw-discount-v1.json'
BATCH_HASH='0120205a7c35427b844dc94bbc5dcf96e857e3139414ff65a2f332a02aac7cf0'
BEHAVIOR='cards.sharp_eyed_lookout.battlecry'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            data['dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=(CARD+'e',)):
        raise TargetValidationError('Sharp-Eyed Lookout complete source pin changed')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Sharp-Eyed Lookout original row changed')
    return data


def register_temporary_draw_discount_card(registry):
    def battlecry(c):
        if c.battlecry is None:raise ValueError('Lookout requires its actual Battlecry context')
        return (DrawWithTemporaryCostReduction(c.player_id,1,c.source_id,c.state.turn),)
    registry.register_behavior(BEHAVIOR,battlecry)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',3,2,3):raise TargetValidationError('Unexpected Lookout native shape')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=BEHAVIOR,metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
