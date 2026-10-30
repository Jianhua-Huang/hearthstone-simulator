"""Explicit linked printings, preserving each real named Deathrattle cycle."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path

from hs_sim.engine.model import CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-linked-printings-v1.json'
BATCH_HASH='8e0bec78a9a25da58bbdcfd6af10862e7c0b3b5916522a4c926c42927107ba26'
DEATHWING,ACIDMAW,ANUBARAK=ROOTS=('LEG_CS3_036','WON_024','WON_076')
NERUBIAN='WON_076t'
DEPENDENCIES=(NERUBIAN,)
COUNTERPARTS={DEATHWING:'CS3_036',ACIDMAW:'AT_063',ANUBARAK:'AT_036',NERUBIAN:'AT_036t'}
PREFIX='cards.past_legendary_linked.'


def semantic_pair(original,counterpart):
    if COUNTERPARTS.get(original['id'])!=counterpart['id']:
        raise TargetValidationError('Linked printing requires its explicit real counterpart')
    if any(original[k]!=counterpart[k]for k in('name','name_en','text','text_en','cost','attack',
            'health','type','collectible','power_keyword_tags')):
        raise TargetValidationError('Linked printing changed complete actual printed semantics')
    changes={k for k in set(original['tags'])|set(counterpart['tags'])
        if original['tags'].get(k)!=counterpart['tags'].get(k)}
    if(not changes<={'CARD_SET','858','DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'}or
            original['tags'].get('858')!=counterpart['dbf_id']or
            original['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID',counterpart['dbf_id'])!=counterpart['dbf_id']):
        raise TargetValidationError('Linked printing has an unreviewed gameplay-tag difference')


def make_definition(raw,counterpart):
    if(COUNTERPARTS.get(raw['id'])!=counterpart.id or raw['type']!='MINION'or
            counterpart.kind!=CardType.MINION or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Linked printing requires its complete physical minion face')
    card=replace(counterpart,id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw))
    return replace(card,deathrattle=PREFIX+raw['id'])if raw['id']in(ANUBARAK,NERUBIAN)else card


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-legendary-linked-printings-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or
            tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in data['existing_dependencies']]!=list(COUNTERPARTS.values())+['TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701']or
            len(data['official_observations'])!=12 or
            any(data[k]for k in('new_counterpart_primary_faces_verified','complete_past_legendary_source_bound',
                'new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Linked printings lost complete identities, roles or source boundaries')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Linked printing changed a complete pinned source row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Linked printing changed a complete retained reference')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    records={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Linked printings cropped the original complete past domain')
    counterparts={x['record']['id']:x['record']for x in data['existing_dependencies']}
    for row in data['cards']+data['dependencies']:
        raw=row['record'];other=counterparts[COUNTERPARTS[raw['id']]];semantic_pair(raw,other)
        faces=[x['face']for x in data['official_observations']if x['card_id']==raw['id']]
        if len(faces)!=2 or any(other['dbf_id']not in f.get('copyOfCardId',[])for f in faces):
            raise TargetValidationError('Linked printing lost its complete bilingual primary copy association')
    token=data['dependencies'][0]['record']
    if any(token['dbf_id']not in x['face'].get('childIds',[])for x in data['official_observations']
            if x['card_id']==ANUBARAK):
        raise TargetValidationError('Linked Anubarak lost its actual distinct named Nerubian child')
    return data


def register_past_legendary_linked_printings(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Linked printing changed a complete existing dependency')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];card=make_definition(raw,registry.card(COUNTERPARTS[raw['id']]))
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Linked printing cannot replace or silently alter a physical face')
        registry._validate_card(card);prepared.append(card)
    def summon(c,cid):
        return(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c),
            position=deathrattle_position(c)),)
    registry.register_behavior(PREFIX+ANUBARAK,lambda c:summon(c,NERUBIAN))
    registry.register_behavior(PREFIX+NERUBIAN,lambda c:summon(c,ANUBARAK))
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
