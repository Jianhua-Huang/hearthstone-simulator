"""Scion of Insight composes genuine grouped discovery and captured keywords."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pool_offers import ChooseFromPools, PoolOfferGroup
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_298'
BODY = 'cards.scion-insight.battlecry'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/scion-insight-v1.json'
BATCH_HASH = 'fa37982ebef887d0bbc8a80629c0b05f04b3647c94692907a96ef26a7d041587'
POOL = 'constructed.cards'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            any(data[k]for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256'] or
            data['official_faces_verified']!=2):
        raise TargetValidationError('Scion of Insight requires its complete source and two full primary faces')
    return data


def register_scion_insight_card(registry):
    raw=load_batch()['cards'][0]['record'];meta=metadata_from_record(raw)
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'),
            raw['tags'].get('DISCOVER'),meta.runes.total)!=('MINION',2,2,2,1,1,0):
        raise TargetValidationError('Scion of Insight lost its actual runeless two-Mana 2/2 face')
    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id!=CARD or c.source.kind!=CardType.MINION:
            raise ResolutionError('Scion of Insight requires its original physical Battlecry')
        if c.source.zone!=Zone.BOARD or not c.source.active or c.source.health<=0 or c.source.doomed:return ()
        return (ChooseFromPools(c.player_id,tuple(PoolOfferGroup(POOL,PoolQuery(collectible=True,runes_any=(rune,)))
            for rune in ('blood','frost','unholy')),c.source_id,rune_recipient=MinionReference.capture(c.source)),)
    registry.register_behavior(BODY,body)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=2,attack=2,health=2,metadata=meta,battlecry=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
