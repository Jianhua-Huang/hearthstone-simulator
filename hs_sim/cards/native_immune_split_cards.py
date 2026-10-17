"""Bone Flurry uses the ordinary active SPELL split pipeline with no spell bonus."""
import json
from pathlib import Path
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-immune-split-v1.json'
BATCH_HASH='15abba2e899d27343b01c4ad346457f8c062d4c5c5f0d4f7f95a6666a534b136'
FLURRY='JAIL_445';PREFIX='cards.native_immune_split.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(FLURRY,)
            or any(d[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Native immune split requires its complete reviewed source')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']):
        raise TargetValidationError('Native immune split original full source row changed')
    return d


def register_native_immune_split_cards(registry):
    def wave(c):
        return RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3,spell_bonus_multiplier=0)
    def body(c):return (wave(c),InvokeBehavior(PREFIX+'extra',c.source_id,c.player_id))
    def extra(c):
        return (wave(c),)if any(d.controller==c.player_id and d.turn==c.state.turn
            for d in c.state.death_history)else ()
    registry.register_behavior(PREFIX+'body',body);registry.register_behavior(PREFIX+'extra',extra)
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['tags'].get('349'))!=('SPELL',1):
        raise TargetValidationError('Bone Flurry requires its actual immune-to-spellpower declaration')
    card=CardDefinition(FLURRY,raw['name'],CardType.SPELL,cost=raw['cost'],metadata=metadata_from_record(raw),
        on_play=PREFIX+'body')
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
