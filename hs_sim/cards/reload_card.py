"""Reload composes ordinary spell discovery and the exact excess-discount loop."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,CostSpec,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='BE_555'
BODY='cards.reload.discover'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/reload-v1.json'
BATCH_HASH='6ac218f1cc2c8b482eb0f6bc245f659e9ed5aa71263f48dedb3bd86343cc2b53'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',include_neutral=False)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,) or
            any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in d['cards'])):
        raise TargetValidationError('Reload lost its complete original root and primary faces')
    return d


def register_reload_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'),raw['tags'].get('SPELL_SCHOOL'),raw['tags'].get('DISCOVER'))!=('SPELL',8,True,3,4,1,1):
        raise TargetValidationError('Reload requires its real eight-cost Hunter Arcane discovery')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',QUERY,
        source_id=c.source_id,cost=CostSpec(delta=-8),excess_discount=True),))
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=8,on_play=BODY,
        spell_school=SpellSchool.ARCANE,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
