"""Other-class Secret discovery and printed copies of actual opponent hand plays."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.secret_conditions import SecretHandSpace
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/perjury-plagiarize-v1.json'
BATCH_HASH='fcbff9cbf4ee2eade27fa16b52fde323dced96e3355ab06bac24765c32676d05'
PERJURY,PLAGIARIZE=LEAVES=('MAW_018','SCH_706')
COLLECTIBLE_ROOTS=()
PREFIX='cards.perjury_plagiarize.'
SECRETS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='other',keywords_all=(Keyword.SECRET,))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-perjury-plagiarize-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            len(d['official_observations'])!=4 or any(d[k]for k in ('cards','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Perjury/Plagiarize lost complete original records or finite local policies')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(
            json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Perjury/Plagiarize lost the complete unfiltered past Secret reference')
    return d


def ending_plays(c):
    e=c.event
    return ()if e is None or e.player_id==c.player_id else played_cards(c.state,e.player_id,turn=c.state.turn)


def register_perjury_plagiarize(registry):
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1 or cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Perjury/Plagiarize requires original new Secret spell faces')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('turn_started',)if cid==PERJURY else('turn_ended',),PREFIX+cid,PREFIX+cid,
                turn='owner'if cid==PERJURY else'opponent'),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    registry.register_secret_condition(PREFIX+PERJURY,lambda c:bool(c.event and c.event.player_id==c.player_id))
    registry.register_secret_condition(PREFIX+PLAGIARIZE,lambda c:SecretHandSpace(bool(ending_plays(c))))
    registry.register_behavior(PREFIX+PERJURY,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',SECRETS,
        source_id=c.source_id,destination='cast'),))
    registry.register_behavior(PREFIX+PLAGIARIZE,lambda c:tuple(CopyCard(
        row.minion_copy_material if row.kind==CardType.MINION else row.played_face,c.player_id,
        mode='base',source_id=c.source_id)for row in ending_plays(c)))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
