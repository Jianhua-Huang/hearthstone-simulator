"""Sha'kar queries actual deaths and installs the shared persistent predicate."""
import json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, Keyword, PlayerEffectSpec,
    PlayerKeywordConditionAuraSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_sources import DeathQuery, death_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_565'
BODY='cards.broodqueen_shakar.install'
PROGRAM='cards.broodqueen_shakar.rush_charge'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/broodqueen-shakar-v1.json'
BATCH_HASH='cbf28281a589a7fe39d7157111c9abfa26617138025a18731cf3c1ce2529d048'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(row['record']['id']for row in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in data['cards'])):
        raise TargetValidationError('Sha\'kar lost her complete original source and progress forms')
    return data


def register_broodqueen_shakar_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('CARDRACE'),
            raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'),raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'))!=('MINION',5,3,5,14,20,5,1,5):
        raise TargetValidationError('Sha\'kar requires her actual legendary Demon Hunter Beast 5-cost 3/5, threshold5')
    def install(c):
        deaths=death_candidates(c.state,registry,c.player_id,
            DeathQuery(min_turn=c.state.turn,max_turn=c.state.turn),c.source_id)
        return(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),)if len(deaths)>=5 else()
    registry.register_behavior(BODY,install)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=3,health=5,battlecry=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD,
        keyword_auras=(PlayerKeywordConditionAuraSpec(Keyword.CHARGE,Keyword.RUSH),)))
