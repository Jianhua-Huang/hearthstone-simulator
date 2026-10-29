"""Burndown joins the existing physical draw group to original hand deadlines."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
CARD='WORK_026'
BODY='cards.burndown.draw'
BATCH_PATH=ROOT/'data/cards/burndown-card-v1.json'
BATCH_HASH='e9502e8b4cc1c59c7c2b48e00bd515e820491586f1e31f72479a96833a097106'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=(*data['cards'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            [v['record']['id']for v in rows]!=[CARD,CARD+'e',CARD+'e2',CARD+'e3']or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in rows)or
            len(data['official_observations'])!=2 or
            any(data[k]for k in ('dependencies','new_standard_roots','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Burndown requires complete original rows and two primary faces')
    raw=rows[0]['record'];ref=ROOT/data['reference_document']
    if ((raw['type'],raw['cost'],raw['tags'].get('SPELL_SCHOOL'),rows[-1]['record']['tags'].get('TAG_SCRIPT_DATA_NUM_2'))!=
            ('SPELL',3,2,3)or hashlib.sha256(ref.read_bytes()).hexdigest()!=data['reference_sha256']or
            CARD not in json.loads(ref.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Burndown lost its original face, duration or past-Mage reference')
    return data


def register_burndown_card(registry):
    raw=load_batch()['cards'][0]['record']
    def draw(c):
        return (DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*3,
            DrawGroupReward('destroy_drawn_after_ends',3)),)
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=3,spell_school=SpellSchool.FIRE,
        on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_behavior(BODY,draw);registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
