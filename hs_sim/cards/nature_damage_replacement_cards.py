"""Flux Revenant and Stormrook share their original Nature damage replacements."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,HealthOp,Keyword
from hs_sim.engine.nature_damage_replacements import RULES
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOTS=('TIME_214','TIME_217')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/nature-damage-replacements-v1.json'
BATCH_HASH='c587bd6307af1d20c345573dfc535f22859ea36ae94e602f52e1f3f364f5f532'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']:
        raise TargetValidationError('Native Nature replacement complete source pin changed')
    for row in (*data['cards'],*data['evidence_only']):
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Native Nature replacement original row changed')
    return data


def register_nature_damage_replacement_cards(registry):
    for row,op,stats in zip(load_batch()['cards'],(HealthOp.NATURE_GROWTH,HealthOp.NATURE_SUMMON),((2,1,4),(5,5,5))):
        raw=row['record'];cid=raw['id']
        if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',*stats):
            raise TargetValidationError('Unexpected native Nature replacement source shape')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            health_rules=(RULES[op],),keywords=(Keyword.TAUNT,)if cid=='TIME_214'else(),
            metadata=replace(metadata_from_record(raw),deck_identity=cid))
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
