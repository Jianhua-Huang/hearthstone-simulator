"""Azure Queen Sindragosa's complete Fabled family over ordinary native effects."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.arcane_dragon_providers import ARCANE,PROFILE
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import (CardDefinition,CardType,CostAuraSpec,CostSpec,NativeSourceCondition,RepeatWitnessProfile)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

QUEEN,KING,STONE='TIME_852','TIME_852t1','TIME_852t3'
BODY='cards.azure_oathstone.resurrect'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/arcane-dragon-fabled-v1.json'
BATCH_HASH='61a2678953f996167dc66735289f764aa31513c7c378b71fc6510c11b981dd5b'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(QUEEN,KING):raise TargetValidationError('Azure Fabled complete source pin changed')
    if data['dependencies']or data['evidence_only']or tuple(x['record']['id']for x in data['existing_dependencies'])!=(STONE,):raise TargetValidationError('Unexpected Azure Fabled source scope')
    for row in (*data['cards'],*data['existing_dependencies']):
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Azure Fabled original source changed')
    return data


def register_arcane_dragon_fabled_cards(registry):
    registry.register_repeat_witness_profile(RepeatWitnessProfile(PROFILE,basis='current_tribes'))
    reused=registry.card(STONE);raw=load_batch()['existing_dependencies'][0]['record']
    if(reused.kind,reused.cost,reused.metadata)!=(CardType.SPELL,raw['cost'],replace(metadata_from_record(raw),deck_identity=STONE)):
        raise TargetValidationError('Existing Azure Oathstone differs from its current complete source')
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kw={}
        if cid==QUEEN:
            kw=dict(native_condition=NativeSourceCondition('controller_other_dragon'),
                cost_auras=(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.SPELL,)),relation='friendly_arcane_spells'),))
        elif cid==KING:kw=dict(spell_repeats=(ARCANE,))
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],
            attack=raw['attack']or 0,health=raw['health']or 0,metadata=replace(metadata_from_record(raw),deck_identity=cid),**kw)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(QUEEN,(KING,STONE)))
