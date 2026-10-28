"""Reverberations uses current-copy material; Ice Block declares a native rule."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.effects import CopyMinion,GrantTrigger
from hs_sim.engine.fatal_damage_secrets import RULE
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/damage-fragility-ice-block-v1.json'
BATCH_HASH='249afd3c7970f6eb02efc23ae7f3d670f28dd579fcd82291836d997e56075667'
POLICY='cn37-local-damage-fragility-ice-block-v1'
REVERB,BLOCK=LEAVES=DEPENDENCIES=('JAM_031','EX1_295')
COLLECTIBLE_ROOTS=()
PREFIX='cards.damage_fragility_ice_block.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id'] for x in d['evidence_only'])!=('JAM_031e','EX1_295o') or
            len(d['official_observations'])!=4 or any(d[k] for k in ('cards','existing_dependencies','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in (*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Damage fragility and Ice Block require full pinned cards and enchantment evidence')
    path=ROOT/d['reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Damage fragility/Ice Block lost complete past-Mage scope')
    return d


def register_damage_fragility_ice_block(registry):
    def reverb(c):
        original=capture_board_presence(c.state,c.target_id)
        return (GrantTrigger(c.target_id,'damage_dealt',PREFIX+'fragile',c.source_id),
            CopyMinion(original,c.player_id,cause=SummonCause.capture(c)))
    def fragile(c):
        e=c.event
        return (DestroyCapturedMinion(MinionReference.capture(c.source),c.source_id),) if (
            e is not None and e.kind=='damage_dealt' and e.target_id==c.source_id and e.amount>0 and
            c.source.zone==Zone.BOARD and c.source.active and c.source.health>0 and not c.source.doomed) else ()
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Damage-fragility root already registered')
        extra={'on_play':PREFIX+'reverb','targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid==REVERB else {
            'keywords':(Keyword.SECRET,), 'health_rules':(RULE,),
            'secret':SecretSpec(cid,('health_resolved',),PREFIX+'false',PREFIX+'noop')}
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card);prepared.append(card)
    for key,body in (('reverb',reverb),('fragile',fragile),('noop',lambda c:())):registry.register_behavior(PREFIX+key,body)
    registry.register_secret_condition(PREFIX+'false',lambda c:False)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
