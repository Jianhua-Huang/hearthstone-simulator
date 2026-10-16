"""Two real generated-minion recipes use shared creation-time numeric layers."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionStats
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Keyword, Rarity, SpellSchool, SummonStats
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/generated-minion-stat-v1.json'
BATCH_HASH = '4c850bec6381b3297cccdc7df27ec1c8c49056c0800ca71fd173e67703e1c36e'
KAROV = 'JAIL_448'
TRIUMPH = 'CATA_136'
ROOTS = (KAROV, TRIUMPH)
POOL_ID = 'constructed.cards'
PREFIX = 'cards.generated_minion_stat.'
QUERIES = {
    KAROV: PoolQuery(kinds=(CardType.MINION,), collectible=True, rarities=(Rarity.LEGENDARY,)),
    TRIUMPH: PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=8),
}
GRANTS = {
    KAROV: CreatedMinionStats(set_to=SummonStats(1, 1)),
    TRIUMPH: CreatedMinionStats(double=True),
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('JAIL_448e', 'CATA_136e') or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))):
        raise TargetValidationError('Unreviewed complete generated minion stat source')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete generated minion stat raw row')
    return data


def register_generated_minion_stat_cards(registry):
    registry.register_behavior(PREFIX + 'karov', lambda c: (
        GenerateFromPool(c.player_id, POOL_ID, QUERIES[KAROV], count=3, source_id=c.source_id,
                         cost=CostSpec(set_to=1), minion_stats=GRANTS[KAROV]),))
    registry.register_behavior(PREFIX + 'triumph', lambda c: (
        GenerateFromPool(c.player_id, POOL_ID, QUERIES[TRIUMPH], count=5, source_id=c.source_id,
                         destination='deck', minion_stats=GRANTS[TRIUMPH], shuffle_actor_id=c.player_id),))
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        if cid == KAROV:
            if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS')) != ('MINION', 6, 6, 6, 6):
                raise TargetValidationError('Karov requires its complete Priest minion face')
            kwargs = dict(attack=6, health=6, keywords=(Keyword.TAUNT,), deathrattle=PREFIX + 'karov')
        else:
            if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 1, 2, 1):
                raise TargetValidationError('Triumph requires its complete Druid Arcane face')
            kwargs = dict(spell_school=SpellSchool.ARCANE, on_play=PREFIX + 'triumph')
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()), cost=raw['cost'],
                              metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
