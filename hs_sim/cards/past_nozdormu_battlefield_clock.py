"""Original Nozdormu supplies a live, source-removable public clock rule."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.battlefield_turn_clocks import BattlefieldTurnClockProfile,EVENT
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-nozdormu-battlefield-clock-v1.json'
BATCH_HASH='9ae9003b8a823fb06c868a12651c51f36db96549302047fb4cec5522c13e36fe'
CARD='EX1_560'
ROOTS=(CARD,)
BEHAVIOR='cards.nozdormu_battlefield.passive'


def make_definition(raw):
    if(raw['id'],raw['type'],raw['cost'],raw['attack'],raw['health'])!=(CARD,'MINION',9,8,8):
        raise TargetValidationError('Original Nozdormu requires its complete actual nine-mana face')
    return CardDefinition(CARD,raw['name'],CardType.MINION,cost=9,attack=8,health=8,
        triggers=(TriggerSpec(EVENT,BEHAVIOR),),metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-nozdormu-battlefield-clock-v1'or
            [x['record']['id']for x in d['cards']]!=[CARD]or d['dependencies']or
            [x['record']['id']for x in d['existing_dependencies']]!=['CS3_035','TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=8 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Original Nozdormu lost full source roles or explicit local clock policy')
    for key in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Original Nozdormu changed a complete source row')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Original Nozdormu changed a complete retained reference')
    if d['retained_documents']['full_reference']!={'path':d['full_reference_document'],'sha256':d['full_reference_sha256']}:
        raise TargetValidationError('Original Nozdormu lost the exact retained domain binding')
    ref=json.loads((ROOT/d['full_reference_document']).read_text(encoding='utf8'))
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            next(x['record']for x in ref['candidate_records']if x['record']['id']==CARD)!=d['cards'][0]['record']):
        raise TargetValidationError('Original Nozdormu cropped its complete original past domain')
    return d


def register_past_nozdormu_battlefield_clock(registry):
    d=load_batch();row=d['cards'][0];card=make_definition(row['record'])
    if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
        raise TargetValidationError('Original Nozdormu cannot replace or alter an existing face')
    # The engine reads this ordinary ability; uncaptured host-time receipts never
    # execute a second card-layer timer or another turn-start program.
    registry.register_behavior(BEHAVIOR,lambda c:())
    registry.register_card(card)
    member=PoolCard.from_definition(card)
    if card.id in registry.pool_cards:
        if registry.pool_card(card.id)!=member:raise TargetValidationError('Original Nozdormu changed existing metadata')
    else:registry.register_pool_card(member)
    registry.register_turn_clock_profile(BattlefieldTurnClockProfile(CARD,BEHAVIOR))
