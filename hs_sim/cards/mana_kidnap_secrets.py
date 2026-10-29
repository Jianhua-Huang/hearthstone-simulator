"""Double Cross and actual original-minion custody for Kidnap's generated Sack."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.effects import Draw
from hs_sim.engine.kidnap_custody import KidnapPlayedMinion,ReturnSackCaptive,SPEC
from hs_sim.engine.mana_exhaustion import exhausted
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.secret_conditions import SecretHandSpace
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/mana-kidnap-secrets-v1.json'
BATCH_HASH='3e92c6be9d5643664a239b7c08de0e06f373972eeafeeb0787d712f20cbf847c'
CROSS,KIDNAP=LEAVES=('REV_825','REV_828')
SACK='REV_828t'
PREFIX='cards.mana_kidnap_secrets.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-mana-kidnap-secrets-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=(*LEAVES,SACK) or
            tuple(x['record']['id']for x in d['evidence_only'])!=('REV_828e',) or len(d['official_observations'])!=4 or
            any(d[k]for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in (*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Mana/custody Secrets lost complete original records or finite policies')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Mana/custody Secrets lost the complete unfiltered reference')
    return d


def physical_minion(c):
    row=event_play(c)
    if (row is None or row.player_id==c.player_id or row.kind!=CardType.MINION or row.countered or row.interrupted
            or row.minion_result!='summoned' or row.minion_entry is None):return None
    entity=resolve_board_presence(c.state,row.minion_entry.reference)
    return row if entity is not None and entity.active and entity.health>0 and not entity.doomed else None


def register_mana_kidnap_secrets(registry):
    d=load_batch();prepared=[]
    def cross(c):return SecretHandSpace(bool(c.event and c.event.player_id!=c.player_id and exhausted(c.event)))
    def kidnap(c):
        row=physical_minion(c)
        return () if row is None else (KidnapPlayedMinion(row.id,SummonCause.capture(c)),)
    def release(c):
        memory=None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec!=SPEC:
            raise UnsupportedDefinitionError('Sack return requires its original native Deathrattle memory')
        return () if memory.custody is None else (ReturnSackCaptive(c.source_id,c.deathrattle.id),)
    for item in d['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Mana/custody identity already registered')
        if cid==SACK:
            if raw['type']!='MINION' or raw['tags'].get('DEATHRATTLE')!=1 or raw['health']!=4:
                raise TargetValidationError('Captive requires its actual 0/4 Sack record')
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health'],
                deathrattle=PREFIX+SACK,native_deathrattle=SPEC,metadata=metadata_from_record(raw))
        else:
            if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Mana/custody root must be a real Secret')
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
                secret=SecretSpec(cid,('mana_spent','mana_consumed')if cid==CROSS else('card_played',),PREFIX+cid,PREFIX+cid,
                    requires_board_space=cid==KIDNAP),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    registry.register_secret_condition(PREFIX+CROSS,cross);registry.register_secret_condition(PREFIX+KIDNAP,lambda c:physical_minion(c)is not None)
    registry.register_behavior(PREFIX+CROSS,lambda c:(Draw(c.player_id,2,source_id=c.source_id),))
    registry.register_behavior(PREFIX+KIDNAP,kidnap);registry.register_behavior(PREFIX+SACK,release)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
