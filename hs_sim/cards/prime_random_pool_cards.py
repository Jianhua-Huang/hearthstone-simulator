"""The two remaining named Prime bodies use complete current-host domains."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path
from hs_sim.engine.automatic_targets import AutomaticTargetPreference
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.model import CardClass, CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/prime-random-pool-v1.json'
BATCH_HASH='6c6ce29b2376081f9ffcde232bab71de128ea7b3a568b37b97c895c28b326c52'
MURGUR,SOLARIAN=ROOTS=('BT_019','BT_028')
MURGUR_PRIME,SOLARIAN_PRIME=DEPENDENCIES=('BT_019t','BT_028t')
EXISTING=()
EVIDENCE=('MIS_701',)
PREFIX='cards.prime_random_pools.'
MINIONS_POOL='constructed.minions'
SPELLS_POOL='constructed.cards'
MURLOCS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('murloc',))
MAGE_SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)


def make_definition(raw):
    cid=raw['id']
    if cid not in (*ROOTS,*DEPENDENCIES) or raw['type']!='MINION' or any(type(raw[k])is not int for k in ('cost','attack','health')):
        raise TargetValidationError('Random Prime requires its complete original physical face')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),keywords=(Keyword.DIVINE_SHIELD,) if raw['tags'].get('DIVINE_SHIELD')==1 else (),
        spell_damage=raw['tags'].get('SPELLPOWER',0),deathrattle=PREFIX+'shuffle.'+cid if cid in ROOTS else None,
        battlecry=PREFIX+('murlocs' if cid==MURGUR_PRIME else 'spells') if cid in DEPENDENCIES else None)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=ROOTS or
            tuple(x['record']['id'] for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies'] or
            tuple(x['record']['id'] for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=10 or
            any(d[k] for k in ('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Random Prime changed its full source roles or claimed full past coverage')
    if any(canonical_digest(x['record'])!=x['record_sha256'] for key in ('cards','dependencies','evidence_only') for x in d[key]):
        raise TargetValidationError('Random Prime changed a complete original raw row')
    for parent,child in zip(d['cards'],d['dependencies']):
        if parent['record']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID']!=child['record']['dbf_id'] or child['record']['collectible']:
            raise TargetValidationError('Random Prime substituted its exact noncollectible named body')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Random Prime changed its original full past reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record'] for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids'] or any(x['record']!=rows[x['record']['id']] for x in d['cards']):
        raise TargetValidationError('Random Prime cropped its complete past reference')
    for key,count in (('Murlocs',23),('Mage_spells',51)):
        domain=d['complete_host_domains'][key]
        if len(domain['complete_ordered_members'])!=count or len(domain['members'])!=count or not domain['membership_not_implementation_filter']:
            raise TargetValidationError('Random Prime lost a complete declared host query')
        if any(canonical_digest(x['full_record'])!=x['record_sha256'] for x in domain['members']):
            raise TargetValidationError('Random Prime changed a complete candidate source row')
    return d


def register_prime_random_pool_cards(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256'] or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Random Prime cannot replace another complete original face')
        registry._validate_card(card);prepared.append(card)
    for parent,child in zip(ROOTS,DEPENDENCIES):
        def death(c,child=child):return shuffled(c,(AddToDeck(c.player_id,child,source_id=c.source_id),))
        registry.register_behavior(PREFIX+'shuffle.'+parent,death)
    def murlocs(c):
        cause=SummonCause.capture(c)
        return tuple(SummonFromPool(c.player_id,MINIONS_POOL,MURLOCS,c.source_id,cause=cause,
            entry_keywords=(Keyword.DIVINE_SHIELD,)) for _ in range(4))
    registry.register_behavior(PREFIX+'murlocs',murlocs)
    registry.register_behavior(PREFIX+'spells',lambda c:(CastFromPool(c.player_id,SPELLS_POOL,MAGE_SPELLS,5,c.source_id,
        target_preference=AutomaticTargetPreference.ENEMY_IF_AVAILABLE),))
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
