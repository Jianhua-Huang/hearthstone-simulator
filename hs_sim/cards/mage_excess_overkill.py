"""Real Mage excess spells and original-result Overkill rewards."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.adjacent_excess_damage import DamageMinionExcess
from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.health_outcomes import is_overkill
from hs_sim.engine.model import CardClass,CardDefinition,CardType,DamageKind,TargetSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/mage-excess-overkill-v1.json'
BATCH_HASH='84d0152fb1f9f675629c5e4de4606006576687684b363cda42648d07ae699b14'
POLICY='cn37-local-mage-excess-overkill-v1'
ROLLING,COMBUSTION,BLAST=LEAVES=DEPENDENCIES=('DRG_321','SCH_348','TRL_317')
COLLECTIBLE_ROOTS=()
PREFIX='cards.mage_excess_overkill.'
POOL='constructed.cards'
MAGE_SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(data['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES or
            len(data['official_observations'])!=6 or any(data[k] for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Mage excess spells require three complete original records')
    path=ROOT/data['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=data['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Mage excess spells lost their full original source scope')
    return data


def register_mage_excess_overkill(registry):
    def spread(c,amount,policy):
        target=c.state.entities[c.target_id]
        return (DamageMinionExcess(MinionReference.capture(target),amount,c.source_id,policy),)
    def blast(c):
        targets=tuple(i for player in c.state.players.values() for i in player.board
            if (e:=c.state.entities[i]).kind==CardType.MINION and e.active and not e.doomed and
            e.health>0 and not registry.card(e.card_id).interactable)
        return (DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL,on_result=PREFIX+'overkill')
            for i in targets)),) if targets else ()
    def overkill(c):
        return (GenerateFromPool(c.player_id,POOL,MAGE_SPELLS,source_id=c.source_id),) if is_overkill(c.event,c.source_id) else ()
    bodies={ROLLING:lambda c:spread(c,8,'rolling'),COMBUSTION:lambda c:spread(c,4,'neighbors'),
        BLAST:blast,'overkill':overkill}
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Mage excess face already registered')
        extra={'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))} if cid!=BLAST else {}
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card);prepared.append(card)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
