"""Echoes of the Past uses original casts and the ordinary corpse branch."""
import json
from pathlib import Path

from hs_sim.engine.effects import SpendResource
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Resource, SpellSchool
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-corpse-spell-summon-v1.json'
BATCH_HASH = '2d2cdafcdaf00b34bd583528ab61c76a324e58c86611c393b81329e57840a1e9'
ECHO = 'END_005'
POOL_ID = 'constructed.cards'
BODY = 'cards.native_corpse_spell_summon.echo'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=4, max_cost=4)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (ECHO,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Echoes requires its complete reviewed source recipe')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Echoes original source row changed')
    return data


def body(context):
    if (context.cast is None or context.cast.card_id != ECHO or
            (context.cast.source_id, context.cast.player_id) != (context.source_id, context.player_id)):
        raise UnsupportedDefinitionError('Echoes requires its original active spell cast')
    one = SummonFromPool(context.player_id, POOL_ID, QUERY, source_id=context.source_id,
                         cause=SummonCause.capture(context))
    spend = SpendResource(context.player_id, Resource.CORPSES, 4, on_success=(one,), requires_board_space=True)
    return (one, spend) + ((one,) if context.cast.outcast else ())


def register_native_corpse_spell_summon_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('MULTIPLE_CLASSES'), raw['tags'].get('OUTCAST'),
            raw['tags'].get('SPELL_SCHOOL'), raw['tags'].get('CORPSE_SPENDER')) != ('SPELL', 5, 8193, 1, 6, 1):
        raise TargetValidationError('Echoes lost its Death Knight/Demon Hunter Shadow Outcast face')
    registry.register_behavior(BODY, body)
    card = CardDefinition(ECHO, raw['name'], CardType.SPELL, cost=5, metadata=metadata_from_record(raw),
                          keywords=(Keyword.OUTCAST,), spell_school=SpellSchool.SHADOW, on_play=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
