"""Raid Boss Onyxia consumes native Whelp presence and six ordinary summons."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword, KeywordAuraSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, WHELP='ONY_004','ONY_001t'
BODY='cards.native_onyxia_whelp.summon'
IMMUNITY=KeywordAuraSpec(Keyword.IMMUNE,target='self',condition='controller_controls_whelp')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-onyxia-whelp-v1.json'
BATCH_HASH='14f220093edabe80e1d35a46d55b6a8c10ff9f9fa5194ef3db9d84c62ba2148a'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or value['dependencies'] or
            tuple(x['record']['id']for x in value['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in value['existing_dependencies'])!=(WHELP,) or
            len(value['official_faces'])!=4 or value['formal_pool_complete']is not False or
            value['cn_calibrated']is not False or any(canonical_digest(x['record'])!=x['record_sha256']
                for x in value['cards']+value['existing_dependencies'])):
        raise TargetValidationError('Raid Boss Onyxia lost its complete original source and Whelp')
    return value


def register_native_onyxia_whelp(registry):
    value=load_batch();raw=value['cards'][0]['record'];dependency=value['existing_dependencies'][0]['record']
    if CARD in registry.cards or WHELP not in registry.cards:
        raise TargetValidationError('Raid Boss Onyxia cannot overwrite or omit original native identities')
    old=registry.card(WHELP)
    if (old.cost,old.attack,old.health,old.metadata,old.keywords)!=(dependency['cost'],dependency['attack'],
            dependency['health'],metadata_from_record(dependency),(Keyword.RUSH,)):
        raise TargetValidationError('Raid Boss Onyxia requires the unchanged complete native Whelp')
    registry.register_behavior(BODY,lambda c:tuple(SummonByCard(c.player_id,
        (SummonEntryMaterial(WHELP),),SummonCause.capture(c))for _ in range(6)))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),keywords=(Keyword.RUSH,),keyword_auras=(IMMUNITY,),battlecry=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
