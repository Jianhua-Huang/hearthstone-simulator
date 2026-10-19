"""The Living Plague declares its native damage replacement; Blight is reused."""
import json
from pathlib import Path
from hs_sim.engine.blight_damage_replacement import BLIGHT,RULE
from hs_sim.engine.deck_generation import MAX_GENERATED_DECK_SIZE
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='JAIL_443'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-blight-replacement-v1.json'
BATCH_HASH='8fe5bdcda558c6c6f5d3a140dee517b6838700fb1e067d70edea38c7abc32752'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in d['existing_dependencies'])!=(BLIGHT,) or
            any(d[k] for k in ('dependencies','evidence_only','skipped')) or d['policy']['capacity']!=MAX_GENERATED_DECK_SIZE):
        raise TargetValidationError('Living Plague requires its complete original source and existing Blight')
    for x in (*d['cards'],*d['existing_dependencies']):
        if canonical_digest(x['record'])!=x['record_sha256']:raise TargetValidationError('Living Plague complete source pin changed')
    from .recruit_cards import load_batch as load_recruits
    previous=next(x for x in load_recruits()['cards'] if x['record']['id']==BLIGHT)
    if previous['record']!=d['existing_dependencies'][0]['record']:
        raise TargetValidationError('Existing full Blight source differs from its preserved complete record')
    return d


def register_native_blight_replacement_cards(registry):
    raw=load_batch()['cards'][0]['record'];token=registry.card(BLIGHT)
    if token.kind!=CardType.SPELL or token.cost!=1 or token.cast_when_drawn is None:
        raise UnsupportedDefinitionError('Living Plague requires the existing actual Blight draw-cast adapter')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.CHARGE,),health_rules=(RULE,),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
