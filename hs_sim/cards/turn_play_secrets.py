"""Hidden Meaning and Sacred Trial use the original shared turn/play facts."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.sacrifice import DestroyCapturedMinion
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/turn-play-secrets-v1.json'
BATCH_HASH='28358160507bbdd78d08d2c586abf103193734f0120ad068b61350def2229020'
MEANING,TRIAL=LEAVES=('JAM_003','LOE_027')
PREFIX='cards.turn_play_secrets.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-turn-play-secrets-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            d['evidence_only'] or len(d['official_observations'])!=4 or
            any(d[k]for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Turn/play Secrets lost complete source and original policy data')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Turn/play Secrets lost the complete unfiltered reference')
    return d


def zero_mana_end(c):
    return bool(c.event and c.event.kind=='turn_ended' and c.event.player_id in (1,2)
        and c.event.player_id!=c.player_id and c.state.players[c.event.player_id].mana==0)


def trial_recipient(c):
    row=event_play(c)
    if (row is None or row.player_id==c.player_id or row.kind!=CardType.MINION or row.countered or row.interrupted
            or row.minion_result!='summoned' or row.minion_entry is None or row.minion_entry.other_minion_count<3):
        return None
    ref=row.minion_entry.reference
    entity=resolve_board_presence(c.state,ref)
    return ref if entity is not None and entity.active and entity.health>0 and not entity.doomed else None


def register_turn_play_secrets(registry):
    d=load_batch();prepared=[]
    def meaning(c):
        return (SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=3,max_cost=3),
            source_id=c.source_id,cause=SummonCause.capture(c)),)
    def trial(c):
        ref=trial_recipient(c)
        return () if ref is None else (DestroyCapturedMinion(ref,c.source_id),)
    for item in d['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Turn/play Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Turn/play root must be an actual Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('turn_ended'if cid==MEANING else'card_played',),PREFIX+cid,PREFIX+cid,
                requires_board_space=cid==MEANING),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    registry.register_secret_condition(PREFIX+MEANING,zero_mana_end)
    registry.register_secret_condition(PREFIX+TRIAL,lambda c:trial_recipient(c) is not None)
    registry.register_behavior(PREFIX+MEANING,meaning);registry.register_behavior(PREFIX+TRIAL,trial)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
