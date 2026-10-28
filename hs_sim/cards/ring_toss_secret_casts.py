"""Original Ring Toss and its full Corrupted face over ordinary Secret CASTs."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,HandProgressSpec,Keyword
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/ring-toss-secret-casts-v1.json'
BATCH_HASH='b4a7ff8f8a432b50c98c1d642233f37ae8cb124038fd21a3a3950315ceba4ac5'
POLICY='cn37-local-ring-toss-secret-casts-v1'
LEAVES=('DMF_105',)
TOKENS=('DMF_105t',)
DEPENDENCIES=LEAVES+TOKENS
COLLECTIBLE_ROOTS=()
PREFIX='cards.ring_toss_secret_casts.'
POOL='constructed.cards'
SECRETS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',keywords_all=(Keyword.SECRET,))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(d['new_token_ids'])!=TOKENS or
            tuple(row['record']['id'] for row in d['dependencies'])!=DEPENDENCIES or
            len(d['official_observations'])!=4 or any(d[k] for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(row['record'])!=row['record_sha256'] for row in d['dependencies'])):
        raise TargetValidationError('Ring Toss requires both complete original forms')
    path=ROOT/d['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Ring Toss lost its full past-Mage source reference')
    return d


def register_ring_toss_secret_casts(registry):
    prepared=[]
    for row in load_batch()['dependencies']:
        raw=row['record'];cid=raw['id'];fields={}
        if raw['type']!='SPELL' or cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Ring Toss requires its original new spell faces')
        if cid==LEAVES[0]:
            fields.update(keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id=TOKENS[0]))
        else:fields['keywords']=(Keyword.CORRUPTED,)
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**fields)
        registry._validate_card(card);prepared.append(card)
    for count,cid in enumerate(DEPENDENCIES,1):
        registry.register_behavior(PREFIX+cid,lambda c,count=count:(DiscoverFromPool(c.player_id,POOL,SECRETS,
            source_id=c.source_id,destination='cast',discoveries=count),))
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
