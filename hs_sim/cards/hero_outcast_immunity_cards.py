"""Doomsday Prepper uses the original Outcast flag and shared hero expiry."""
import json
from pathlib import Path
from hs_sim.engine.effects import GrantKeyword
from hs_sim.engine.model import CardDefinition, CardType, Keyword, TimedKeywordSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/hero-outcast-immunity-v1.json'
BATCH_HASH='11bfa48773a84ba00414d3fd1fdc29695ba4613910b99c9e9cfe10adbff15985'
PREPPER='TIME_021'
BODY='cards.hero_outcast_immunity.play'
IMMUNITY=TimedKeywordSpec(Keyword.IMMUNE)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in data['cards'])!=(PREPPER,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Doomsday Prepper requires its complete reviewed source')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Doomsday Prepper original row is incomplete')
    return data


def body(context):
    if context.spell_conditions is None:
        raise ValueError('Doomsday Prepper requires original accepted Outcast conditions')
    if not context.spell_conditions.outcast:return()
    return(GrantKeyword(context.state.players[context.player_id].hero_id,Keyword.IMMUNE,
        context.source_id,duration=IMMUNITY),)


def register_hero_outcast_immunity_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('OUTCAST'),raw['tags'].get('IMMUNE'),raw['tags'].get('BATTLECRY'))!=('MINION',5,5,4,14,1,None,None):
        raise TargetValidationError('Doomsday Prepper lost its actual native Outcast minion face')
    registry.register_behavior(BODY,body)
    card=CardDefinition(PREPPER,raw['name'],CardType.MINION,cost=5,attack=5,health=4,
        metadata=metadata_from_record(raw),keywords=(Keyword.OUTCAST,),on_play=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
