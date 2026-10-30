"""Printed combat keywords for complete original past Legendary faces."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.model import AttackPolicySpec,CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-keywords-v1.json'
BATCH_HASH='cf7e77a4da033702a66bbcb0ac1e771bc6e72c52045074f8d4b418225b04bcbc'
ROOTS=('EX1_543','FP1_010','CFM_815','WON_312','AT_125')
KEYWORDS={ROOTS[0]:(Keyword.CHARGE,),ROOTS[1]:(Keyword.POISONOUS,),
    ROOTS[2]:(Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL),
    ROOTS[3]:(Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL),ROOTS[4]:(Keyword.CHARGE,)}


def make_definition(raw):
    cid=raw['id']
    if (cid not in ROOTS or raw['type']!='MINION' or raw['collectible']is not True or
            raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health')) or
            any(raw['tags'].get(k.name)!=1 for k in KEYWORDS[cid])):
        raise TargetValidationError('Past keyword consumers require their full original Legendary minion faces')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=KEYWORDS[cid],attack_policies=(AttackPolicySpec('cannot_attack_heroes'),)if cid=='AT_125'else(),
        metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-keywords-v1' or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=14 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past keyword consumers lost original roles or claimed an incomplete source complete')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Past keyword consumer lost a complete original source row')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Past keyword consumers changed the complete original Legendary reference')
    reference=json.loads(p.read_text(encoding='utf8'))
    if (len(reference['candidate_ids'])!=732 or reference['candidate_ids']!=d['original_candidate_ids']or
            any(row['record']!=next(x['record']for x in reference['candidate_records']if x['record']['id']==row['record']['id'])for row in d['cards'])):
        raise TargetValidationError('Past keyword consumers cropped or changed original full membership')
    return d


def register_past_legendary_keywords(registry):
    prepared=[]
    for row in load_batch()['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Past keyword consumers cannot replace or change an original native face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Past keyword consumer changed existing complete metadata')
        prepared.append(card)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
