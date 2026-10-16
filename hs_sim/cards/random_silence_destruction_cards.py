"""Cease to Exist consumes native random spell targets, Silence and Rewind."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword,RewindSpec
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_targets import RandomSpellTarget
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/random-silence-destruction-v1.json'
BATCH_HASH='ea21190944b0778f0fff8d9e115549e8474af53787656159ada6286275c07cd1'
CEASE='TIME_433';BODY='cards.random_silence_destruction.cease'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CEASE,) or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Unreviewed complete silence destruction source')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original silence destruction row')
    return data

def register_random_silence_destruction_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('REWIND'))!=('SPELL',3,6,1)or 'SPELL_SCHOOL'in raw['tags']:
        raise TargetValidationError('Cease requires its current complete printed spell')
    def cease(c):
        refs=tuple(MinionReference.capture(c.state.entities[eid])for eid in minions(c,registry,3-c.player_id))
        return(RandomSpellTarget(refs,c.source_id,'silence_destroy'),)
    registry.register_behavior(BODY,cease)
    card=CardDefinition(CEASE,raw['name'],CardType.SPELL,cost=3,metadata=metadata_from_record(raw),
        keywords=(Keyword.REWIND,),rewind=RewindSpec(),on_play=BODY)
    registry.register_card(card)
    from hs_sim.engine.pools import PoolCard
    registry.register_pool_card(PoolCard.from_definition(card))
