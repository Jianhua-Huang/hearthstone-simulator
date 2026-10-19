"""Noxious Bribe uses one discovery selection and independent printed deliveries."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT='JAIL_861';BODY='cards.choose_one_bribe.play'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/choose-one-bribe-v1.json'
BATCH_HASH='d0c53f9f8c1a149dae676f6885a83f91e963fd561867e8e866442a3de34e1281'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(ROOT,) or
            tuple(x['record']['id']for x in d['evidence_only'])!=(ROOT+'e',) or d['dependencies'] or
            d['existing_dependencies'] or any(canonical_digest(x['record'])!=x['record_sha256']
                for k in ('cards','evidence_only')for x in d[k])):
        raise TargetValidationError('Noxious Bribe requires its complete original card and enchantment evidence')
    return d


def register_choose_one_bribe_card(registry):
    raw=load_batch()['cards'][0]['record']
    if raw['type']!='SPELL' or raw['cost']!=2 or raw['tags'].get('DISCOVER')!=1:
        raise TargetValidationError('Noxious Bribe changed its original two-mana discovery face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',
        PoolQuery(collectible=True,choose_one=True),source_id=c.source_id,paired_choose_one=True),))
    card=CardDefinition(ROOT,raw['name'],CardType.SPELL,cost=2,on_play=BODY,
        metadata=replace(metadata_from_record(raw),deck_identity=ROOT))
    registry.register_card(card)
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
