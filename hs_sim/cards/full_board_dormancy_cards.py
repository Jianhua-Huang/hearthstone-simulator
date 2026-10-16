"""The real Ash Worm uses the existing dormant body and awakening executor."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/full-board-dormancy-v1.json'
BATCH_HASH='2a32232bd7e7b8b625f5622c990ca43faed5416c5153cfed5e969699920dd506'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Full-board dormancy lost its complete reviewed source pin')
    return data


def register_full_board_dormancy_cards(registry):
    data=load_batch()
    if len(data['cards'])!=1:raise TargetValidationError('Unreviewed full-board dormancy source set')
    item=data['cards'][0];raw=item['record']
    if raw['id']!='MEND_040'or canonical_digest(raw)!=item['record_sha256']or item['recipe']!=dict(dormant_turns=None,dormant_board_full=True):
        raise TargetValidationError('Unreviewed complete Ash Worm recipe')
    card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        dormant_turns=None,dormant_board_full=True,metadata=replace(metadata_from_record(raw),deck_identity=raw['id']))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
