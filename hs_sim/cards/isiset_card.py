"""Real Isiset and the fixed-source Colossus; primary token link remains open."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_mana_freeze import SpellManaFreezeProfile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD,TOKEN='BE_259','BE_254'
BODY='cards.isiset.constructs'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/isiset-v1.json'
BATCH_HASH='06bb40895f106604eda7fe7baf76c9f895b548199bd769b005bcb716d81f74bc'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in data['dependencies'])!=(TOKEN,) or
            any(data[k]for k in ('existing_dependencies','evidence_only','skipped')) or
            data['official_faces_verified']!=2 or data['source_limits']['BE_254_primary_face_verified'] is not False or
            data['source_limits']['dependency_assignment_primary_confirmed'] is not False):
        raise TargetValidationError('Isiset requires complete fixed records and its explicit unavailable-token/source-link limits')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Isiset complete original record changed')
    return data


def register_isiset_card(registry):
    data=load_batch();raw=data['cards'][0]['record'];token=data['dependencies'][0]['record']
    if ((raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'))!=('MINION',6,5,5,1) or
            (token['type'],token['cost'],token['attack'],token['health'],token['collectible'],token['tags'].get('TAG_SCRIPT_DATA_NUM_1'))!=('MINION',10,10,10,False,15)):
        raise TargetValidationError('Isiset or the native fifteen-Mana Colossus changed its complete printed face')
    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id!=CARD:
            raise ResolutionError('Isiset requires its original actual Battlecry')
        request=SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c))
        return (request,request)
    registry.register_behavior(BODY,body)
    for definition in (CardDefinition(CARD,raw['name'],CardType.MINION,cost=6,attack=5,health=5,
            metadata=metadata_from_record(raw),battlecry=BODY),
            CardDefinition(TOKEN,token['name'],CardType.MINION,cost=10,attack=10,health=10,
            metadata=metadata_from_record(token))):
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
    registry.register_spell_mana_freeze_profile(SpellManaFreezeProfile(TOKEN,15))
