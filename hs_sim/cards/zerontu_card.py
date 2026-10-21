"""Zer'Ontu delegates its real ordered recruit and numeric gain to the kernel."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.recruit_stat_groups import RecruitAttackGroupForStats
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_790'; BODY='cards.zerontu.recruit_stats'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/zerontu-v1.json'
BATCH_HASH='4f6f5162a4c004c8521e057285c3c993fc8d6269ceee2ec6334a170fcbebdde3'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CARD,)or
            any(d[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards'])):
        raise TargetValidationError('Zerontu lost its full original reviewed minion face')
    return d


def register_zerontu_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'),raw['tags'].get('TAUNT'))!=('MINION',8,3,3,6,5,1,1):
        raise TargetValidationError('Zerontu requires its real Priest legendary 8-cost 3/3 Taunt Battlecry')
    registry.register_behavior(BODY,lambda c:(RecruitAttackGroupForStats(c),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=8,attack=3,health=3,
        keywords=(Keyword.TAUNT,),battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
