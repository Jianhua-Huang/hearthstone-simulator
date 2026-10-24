"""Repair Bot uses actual immutable Magnetic recipes; Skulker is evidence only."""
import json
from pathlib import Path

from hs_sim.engine.magnetic import ReturnMagnetizedMechs
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

REPAIR='TTN_906'
DEPENDENCIES=(REPAIR,)
COLLECTIBLE_ROOTS=()
BODY='cards.past_stored_carrier_materials.repair'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-stored-carrier-materials-v1.json'
BATCH_HASH='876a82a99e6a692a58e18a0ec784b2742274d239dc476512a7295e203d69198a'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['evidence_only'])!=('DEEP_012',) or
            any(d[k]for k in('cards','existing_dependencies','choice_only','skipped',
                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in(*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Stored carrier material lost its full original source scope')
    return d


def register_past_stored_carrier_materials_cards(registry):
    def body(c):
        return(ReturnMagnetizedMechs.capture(c),)
    registry.register_behavior(BODY,body)
    raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('CARDRACE'),raw['tags'].get('DEATHRATTLE'))!=('MINION',1,1,3,5,17,1):
        raise TargetValidationError('Repair Bot requires its actual Paladin Mech Deathrattle face')
    card=CardDefinition(REPAIR,raw['name'],CardType.MINION,cost=1,attack=1,health=3,
        deathrattle=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
