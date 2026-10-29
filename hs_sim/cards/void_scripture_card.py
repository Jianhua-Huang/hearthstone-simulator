"""Void Scripture uses ordinary discovery and the affordable-copy producer."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.discovered_spell_casts import QUERY
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
CARD='YOG_507'
BODY='cards.void_scripture.discover'
BATCH_PATH=ROOT/'data/cards/void-scripture-v1.json'
BATCH_HASH='443c3e207f26be45d5ebbe351f6851a13a3c52771db650f35d406c900ae157aa'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            [v['record']['id']for v in d['cards']]!=[CARD]or len(d['official_observations'])!=2 or
            any(d[k]for k in('dependencies','evidence_only','new_standard_roots','formal_pool_complete','cn_calibrated'))or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in d['cards'])):
        raise TargetValidationError('Void Scripture requires its complete original record and two primary faces')
    raw=d['cards'][0]['record'];ref=ROOT/d['reference_document']
    if ((raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,4,6)or
            hashlib.sha256(ref.read_bytes()).hexdigest()!=d['reference_sha256']or
            CARD not in json.loads(ref.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Void Scripture lost its original face or full past-Mage reference')
    return d


def register_void_scripture_card(registry):
    raw=load_batch()['cards'][0]['record']
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',QUERY,
        source_id=c.source_id,cast_affordable_copy=True),))
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,spell_school=SpellSchool.SHADOW,
        on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
