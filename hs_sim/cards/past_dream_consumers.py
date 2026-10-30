"""Three original Dream consumers share the complete existing five-card recipes."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption,RequestChoice
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,TriggerSpec
from hs_sim.engine.pools import GenerateFromCandidates,PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .fixed_dream_source import DREAMS,DRYAD,PREFIX as FIXED_PREFIX
from .shaladrassil_cards import ROOT as SHALADRASSIL,PREFIX as SHALA_PREFIX
from .complex_dream_cards import YSERA_IDS

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-dream-consumers-v1.json'
BATCH_HASH='729506ffe241974a2d64dd91f964c84a84fc53afff91e5cb49d013f59e372b4b'
ROOTS=('EX1_572','LEG_CS3_033','WC_035')
DEPENDENCIES=()
PREFIX='cards.past_dream.'
ONE_BODY=FIXED_PREFIX+'dryad'
ORDERED_BODY=SHALA_PREFIX+'ordered'


def make_definition(raw):
    cid=raw['id']
    if (cid not in ROOTS or raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('RARITY')!=5 or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Past Dream consumers require their complete original Legendary faces')
    fields={}
    if cid=='EX1_572':fields['triggers']=(TriggerSpec('turn_ended',PREFIX+'two',EndTurnSpec()),)
    elif cid=='LEG_CS3_033':fields['battlecry']=PREFIX+'all'
    else:fields.update(dormant_turns=2,dormant_triggers=(TriggerSpec('turn_ended',ONE_BODY,EndTurnSpec()),))
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Dream-consumers-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=DREAMS+(DRYAD,SHALADRASSIL,'TIME_013')or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701','DREAM_05e']or len(d['official_observations'])!=14 or
            d['member_ids']!=list(DREAMS)or d['member_weights']!=[1]*5 or d['binding_kind']!='complete_finite_recipes'or
            d['requires_generation_context']is not False or any(d[k]for k in(
                'complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past Dream consumers lost complete source roles or claimed a partial domain complete')
    rows={x['record']['id']:x['record']for key in('cards','existing_dependencies','evidence_only')for x in d[key]}
    for key in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Past Dream consumers changed a complete source row')
    # Preserve the API's child order, which differs from DREAM_01..05 order.
    dbfs=[rows[cid]['dbf_id']for cid in('DREAM_05','DREAM_04','DREAM_01','DREAM_02','DREAM_03')]
    parents=[x for x in d['official_observations']if x['card_id']in(*ROOTS,DRYAD)]
    if len(parents)!=8 or any(x['face'].get('childIds')!=dbfs for x in parents):
        raise TargetValidationError('Dream consumers lost an actual complete ordered five-child official declaration')
    for key in('full_reference','fixed_source','all_delivery','ysera_exclusion'):
        item=d['retained_documents'][key];p=(ROOT/item['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Dream consumers changed an original complete retained document')
    reference=json.loads((ROOT/d['retained_documents']['full_reference']['path']).read_text(encoding='utf8'))
    originals={x['record']['id']:x['record']for x in reference['candidate_records']}
    if (len(reference['candidate_ids'])!=732 or d['original_candidate_ids']!=reference['candidate_ids']or
            any(x['record']!=originals[x['record']['id']]for x in d['cards'])or
            sorted(YSERA_IDS)!=d['retained_ysera_exclusion_ids']or not set(ROOTS[:2])<=YSERA_IDS):
        raise TargetValidationError('Dream consumers cropped past identities or changed the existing exact Ysera family')
    return d


def register_past_dream_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if cid=='TIME_013':continue
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Past Dream consumers require unchanged complete existing Dream effects and sources')
    if (registry.card(DRYAD).battlecry!=ONE_BODY or registry.card(SHALADRASSIL).on_play!=SHALA_PREFIX+'dreams'):
        raise TargetValidationError('Dream consumers lost their actual accepted source recipes')
    registry.behavior(ONE_BODY);registry.behavior(ORDERED_BODY)
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Past Dream consumers cannot replace or change existing definitions')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Past Dream consumers changed existing complete metadata')
        prepared.append(card)
    def two(c):return(GenerateFromCandidates(c.player_id,DREAMS,c.source_id),)*2
    def all_dreams(c):
        return(RequestChoice(c.player_id,tuple(ChoiceOption(cid,registry.card(cid).name,card_id=cid)for cid in DREAMS),
            c.source_id,min_count=0,max_count=0,sample_size=5,on_select=ORDERED_BODY),)
    registry.register_behavior(PREFIX+'two',two);registry.register_behavior(PREFIX+'all',all_dreams)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
