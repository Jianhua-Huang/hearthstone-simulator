"""Reviewed ordinary keyword dependencies of an uncompleted past-minion source."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p77-v1.json'
BATCH_HASH = 'e68b9b0f5a176f4dfd70858eab332ec3f6d02966ecb8ae5034f6b5f227a95e41'
MASTER, CREEPER, FENCER, KNIGHT, PLAGUE, WORM, RECYCLER, HORSE, SPIDER, TROGG, ANNOY, ASSASSIN = (
    'CFM_666', 'CS1_069', 'DAL_085', 'FP1_008', 'ICC_032', 'ICC_905',
    'BOT_050', 'GIL_545', 'GIL_562', 'LOOT_315', 'OG_145', 'ULD_274')
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = ROOTS = (MASTER, CREEPER, FENCER, KNIGHT, PLAGUE, WORM, RECYCLER, HORSE, SPIDER, TROGG, ANNOY, ASSASSIN)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['cards'] or d['existing_dependencies'] or d['skipped']
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES):
        raise TargetValidationError('P77 complete reviewed scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256'] for key in ('dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P77 complete original record changed')
    return d


def register_simple_followup_p77_cards(registry):
    for item in load_batch()['dependencies']:
        raw, recipe = item['record'], item['recipe']
        if (raw['type'] != 'MINION' or raw['collectible'] is not True
                or any(type(recipe[k]) is not int or raw[k] != recipe[k] for k in ('cost', 'attack', 'health'))):
            raise TargetValidationError('P77 printed minion recipe changed')
        definition = CardDefinition(raw['id'], raw['name'], CardType.MINION,
            cost=recipe['cost'], attack=recipe['attack'], health=recipe['health'],
            keywords=tuple(Keyword(k) for k in recipe['keywords']), metadata=metadata_from_record(raw))
        registry.register_card(definition)
        if definition.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(definition))
