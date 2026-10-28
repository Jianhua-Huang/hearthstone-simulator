"""Glacial Mysteries and Azerite Vein consume actual original physical sources."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.secret_source_operations import CopyCommittedHandCard,InstallDeckSecrets
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/secret-original-sources-v1.json'
BATCH_HASH='0be5fa795bfee54d2ffdaa71249b4dd02f4c5bb4e8608e2ffed55191e60161e5'
POLICY='cn37-local-secret-original-sources-v1'
BOOK,VEIN=LEAVES=DEPENDENCIES=('ICC_086','WW_422')
COLLECTIBLE_ROOTS=()
PREFIX='cards.secret_original_sources.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(data['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES or
            len(data['official_observations'])!=4 or any(data[k] for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Secret sources require two full original records and four primary faces')
    path=ROOT/data['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=data['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Secret source cards lost their full past-Mage scope')
    return data


def committed_quick_card(c):
    if c.event is None or c.event.kind!='card_committed':return None
    row=play_record(c.state,dict(c.event.data).get('play_id'))
    if (row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
        raise ResolutionError('Azerite Vein lost its original committed hand play')
    return row if row.player_id!=c.player_id and row.turn==c.state.turn and row.hand_entry_turn==row.turn else None


def register_secret_original_sources(registry):
    def book(c):
        if c.cast is None:raise ResolutionError('Glacial Mysteries requires its actual original CAST')
        return (InstallDeckSecrets(c.cast.id),)
    def vein(c):
        row=committed_quick_card(c)
        return () if row is None else (CopyCommittedHandCard(row.id,c.player_id,c.source_id),)
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Secret source face already registered')
        extra={'on_play':PREFIX+cid} if cid==BOOK else {'keywords':(Keyword.SECRET,),
            'secret':SecretSpec(cid,('card_committed',),PREFIX+cid,PREFIX+cid)}
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card);prepared.append(card)
    registry.register_behavior(PREFIX+BOOK,book);registry.register_behavior(PREFIX+VEIN,vein)
    registry.register_secret_condition(PREFIX+VEIN,lambda c:committed_quick_card(c) is not None)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
