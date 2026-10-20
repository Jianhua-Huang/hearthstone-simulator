"""Two actual Osk Battlecry forms; the rotating hand root is separate."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.model import CardDefinition, CardType, Keyword, TargetMode, TargetSpec, Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DRAW='TLC_452t18'; COPY='TLC_452t19'; ROOT='TLC_452'
PREFIX='cards.osk.draw_copy.'; RULE=PREFIX+'non_titan'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/titanographer-draw-copy-v1.json'
BATCH_HASH='db977b4926a350f9359d3c8def26fa4da0bb57e996e59ce71934771c56d3f22f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=(*data['cards'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(DRAW,COPY,ROOT) or
            any(data[k]for k in ('dependencies','existing_dependencies','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Osk draw/copy requires its complete reviewed forms and original root')
    for row in data['cards']:
        raw=row['record']
        if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'))!=('MINION',6,6,6,1):
            raise TargetValidationError('Osk draw/copy printed Battlecry form changed')
    return data


def register_titanographer_draw_copy_cards(registry):
    registry.register_player_target_rule(PlayerTargetRuleSpec(RULE,'v1'),
        lambda c:c.target is not None and Keyword.TITAN.value not in c.target.get('keywords',()))
    registry.register_behavior(PREFIX+'draw',lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,
        (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),)*2,DrawGroupReward('set_stats_cost_all',2)),))
    registry.register_behavior(PREFIX+'copy',lambda c:() if c.target_id is None else (
        CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c),minion_grant=CreatedMinionGrant(2,2)),))
    for row in load_batch()['cards']:
        raw=row['record']; copying=raw['id']==COPY
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=6,attack=6,health=6,
            metadata=metadata_from_record(raw),battlecry=PREFIX+('copy'if copying else'draw'),
            targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,))if copying else None,
            target_rule=RULE if copying else 'any_character')
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
