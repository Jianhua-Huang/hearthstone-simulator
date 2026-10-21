"""Efflorescence draws a different physical spell and marks only Nature spells."""
import json
from pathlib import Path

from hs_sim.engine.card_spell_repeats import DrawMatchingSpellRepeat
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_801'
BODY='cards.efflorescence.draw'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/efflorescence-v1.json'
BATCH_HASH='dfac67da791f544ea87262ce31fc38d998f05ed61cce3b12c1afdf0da77e8810'
QUERY=PoolQuery(kinds=(CardType.SPELL,),exclude_card_ids=(CARD,))


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['cards'])):
        raise TargetValidationError('Efflorescence lost its complete reviewed original face')
    return data


def register_efflorescence_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,True,2,4):
        raise TargetValidationError('Efflorescence requires its original two-cost Druid Nature spell')
    def body(c):
        if c.cast is None or (c.cast.source_id,c.cast.card_id)!=(c.source_id,CARD):
            raise ValueError('Efflorescence requires its actual physical CAST')
        return(DrawMatchingSpellRepeat(c.player_id,QUERY,c.source_id,SpellSchool.NATURE),)
    registry.register_behavior(BODY,body)
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,spell_school=SpellSchool.NATURE,
        on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
