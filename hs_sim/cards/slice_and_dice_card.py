"""Actual same-turn whole-card replay followed by a safe ordinary natural end."""
import json
from pathlib import Path

from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.generated_activation_receipts import RETAINED_PROFILE
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.natural_turn_end import RequestNaturalTurnEnd
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='JAIL_500'
BODY='cards.slice_and_dice.replay'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/slice-and-dice-v1.json'
BATCH_HASH='46770a224220e80a5d6bffc81acb9df659d316689566df87843c82759991916b'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Slice and Dice requires its complete original source and primary faces')
    row,=d['cards'];raw=row['record']
    if (canonical_digest(raw)!=row['record_sha256'] or
            (raw['type'],raw['cost'],raw['collectible'],raw['tags']['CLASS'],raw['tags']['RARITY'])!=('SPELL',5,True,7,5) or
            raw['tags'].get('DONT_PICK_FROM_SUBSETS')!=1):
        raise TargetValidationError('Original five-cost Rogue Legendary spell changed')
    return d


def register_slice_and_dice_card(registry):
    def body(c):
        if c.cast is None or (c.cast.card_id,c.cast.source_id,c.cast.player_id)!=(CARD,c.source_id,c.player_id):
            raise UnsupportedDefinitionError('Slice and Dice requires its actual original cast')
        query=WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,
            min_turn=c.cast.turn,max_turn=c.cast.turn,exclude_card_ids=(CARD,))
        return (ReplayWholeCards(c.player_id,c.source_id,query,
            target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE,physical_profile=RETAINED_PROFILE),
            RequestNaturalTurnEnd(c.cast.id))
    registry.register_behavior(BODY,body);raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=5,on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
