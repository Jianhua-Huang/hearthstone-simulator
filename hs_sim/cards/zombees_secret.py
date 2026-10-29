"""Original Zombees Secret with its real Beast/Undead physical token."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_attack_groups import AttackSummonedGroup,SummonAttackProfile
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/zombees-secret-v1.json'
BATCH_HASH='75b0e1637f8b472b6494338936b0ff174aed1b64889c00de4d937556d91dbe9e'
CARD='NX2_013'
TOKEN='NX2_013t'
LEAVES=(CARD,)
COLLECTIBLE_ROOTS=()
PREFIX='cards.zombees_secret.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-zombees-secret-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(d['new_token_ids'])!=(TOKEN,) or
            tuple(x['record']['id']for x in d['dependencies'])!=(CARD,TOKEN) or len(d['official_observations'])!=2 or
            any(d[k]for k in('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Zombees lost the complete original Secret/token or finite policies')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or CARD not in json.loads(
            p.read_text(encoding='utf8'))['candidate_ids']:
        raise TargetValidationError('Zombees lost the complete unfiltered past Secret reference')
    return d


def played_target(c):
    row=event_play(c)
    if (row is None or row.player_id==c.player_id or row.kind!=CardType.MINION or not row.completed or
            row.countered or row.interrupted or row.minion_result!='summoned' or row.minion_entry is None):return None
    entity=resolve_board_presence(c.state,row.minion_entry.reference)
    return row if entity is not None and entity.active and entity.health>0 and not entity.doomed else None


def register_zombees_secret(registry):
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Zombees identity already registered')
        if cid==CARD:
            if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Zombees requires its real Secret')
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
                secret=SecretSpec(cid,('card_played',),PREFIX+CARD,PREFIX+CARD,requires_board_space=True),metadata=metadata_from_record(raw))
        else:
            if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',1,1,1):
                raise TargetValidationError('Zombees requires its actual printed 1/1 token')
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    def body(c):
        row=played_target(c)
        if row is None:return ()
        request=SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c))
        return(*(request for _ in range(4)),AttackSummonedGroup(c,row.minion_entry.reference))
    registry.register_secret_condition(PREFIX+CARD,lambda c:played_target(c)is not None)
    registry.register_behavior(PREFIX+CARD,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_summon_attack_profile(SummonAttackProfile(CARD,TOKEN,4,combat_relation='any_minions',
        target_policy='opponent_played_minion'))
