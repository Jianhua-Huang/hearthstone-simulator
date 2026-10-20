"""Anomalize delegates the real cost bands and stat permutation to shared code."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.scrambled_summons import SummonAndScramble
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TIME_859'
BODY='cards.anomalize.summon_scramble'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/anomalize-v1.json'
BATCH_HASH='a4c904a66fbaf59c875c128dede01805c8a06ce92e43cfb2206e6d21473c3baa'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=data['cards']+data['evidence_only']
    if (canonical_digest(data)!=BATCH_HASH or [r['record']['id']for r in rows]!=[CARD,CARD+'e'] or
            any(data[k]for k in('dependencies','existing_dependencies','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Anomalize requires its complete original spell and evidence')
    raw=data['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',7,4,1):
        raise TargetValidationError('Anomalize changed its printed Mage Arcane spell')
    return data


def register_anomalize_card(registry):
    registry.register_behavior(BODY,lambda c:(SummonAndScramble(c.player_id,'constructed.cards',(10,1),SummonCause.capture(c)),))
    raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=7,spell_school=SpellSchool.ARCANE,
                        on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
