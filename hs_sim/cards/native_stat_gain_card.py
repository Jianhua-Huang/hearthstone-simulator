"""Dalaran Champion declares one removable native extra-stat source."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.native_stat_gains import NativeStatGainProfile
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import canonical_digest,TargetValidationError
from .metadata import metadata_from_record

CARD='JAIL_330'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-stat-gain-v1.json'
BATCH_HASH='ff61cad28004c6b54fbe7621af331e937cc9b4160d724a7d6455e3506576d495'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in d['evidence_only'])!=('JAIL_330e',) or
            any(d[k]for k in ('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Champion requires its complete original stat-gain source')
    for x in (*d['cards'],*d['evidence_only']):
        if canonical_digest(x['record'])!=x['record_sha256']:raise TargetValidationError('Champion full raw source changed')
    return d


def register_native_stat_gain_card(registry):
    raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.DIVINE_SHIELD,Keyword.TAUNT),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_native_stat_gain_profile(NativeStatGainProfile(CARD))
