"""Niri uses the original paid price and the shared stat/spell repeat machinery."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import DoubleStats,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,RepeatCostFilter,RepeatMatchSpec,SpellRepeatSpec,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .played_minion_keyword_cards import played_minion,original_recipient

CARD='TLC_836';PREFIX='cards.niri.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/one-cost-play-provider-v1.json'
BATCH_HASH='0078f765fd8f490fcf0fb03d4a651a5bb2dc0d72b16680871940deb2385d64b3'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,) or data['dependencies']:
        raise TargetValidationError('Niri complete original source pin changed')
    for row in (*data['cards'],*data['evidence_only']):
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Niri original source changed')
    return data


def register_one_cost_play_provider_card(registry):
    def accept(c):
        row=played_minion(c)
        if row is None:return ()
        if row.submitted_cost is None:raise ValueError('Niri requires the original accepted physical cost')
        if row.submitted_cost.quote.amount!=1:return ()
        return (InvokeBehavior(PREFIX+'double',row.source_id,row.player_id,c.source_id,row.id),)
    def double(c):
        target=original_recipient(c,c.play)
        return (DoubleStats(target.id,attack=True,health=True,source_id=c.target_id),)if target is not None else()
    registry.register_behavior(PREFIX+'accept',accept);registry.register_behavior(PREFIX+'double',double)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',3,2,5):raise TargetValidationError('Unexpected Niri source shape')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=3,attack=2,health=5,
        triggers=(TriggerSpec('card_played',PREFIX+'accept'),),
        spell_repeats=(SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(recipient_cost=RepeatCostFilter('cast_quote',minimum=1,maximum=1))),),
        metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
