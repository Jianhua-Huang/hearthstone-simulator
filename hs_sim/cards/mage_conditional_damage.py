"""Three original Mage damage spells over actual debit, turn and batch facts."""
import hashlib,json
from pathlib import Path

from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import Damage,RandomDamage,SpendMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,PlayedTypeQuery,TargetSpec,Zone
from hs_sim.engine.owner_turns import query_previous_owner_turn
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import active_cast,cast_record
from hs_sim.engine.spell_sequences import DamageMinionsRepeatIfNoDeaths
from hs_sim.engine.spell_target_conditions import PreviousElementalTargetProfile
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/mage-conditional-damage-v1.json'
BATCH_HASH='f11c5027f010be9610fbe7c1e1e93247b13b4427611e474bc51abf0c69db8af5'
POLICY='cn37-local-mage-conditional-damage-v1'
FLAME,COMBUSTION,WAVES=LEAVES=DEPENDENCIES=('OG_086','GDB_456','VAC_953')
COLLECTIBLE_ROOTS=()
PREFIX='cards.mage_conditional_damage.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            len(d['official_observations'])!=6 or d['numeric_normalizations']!={FLAME:{'cost':0}} or
            any(d[k]for k in('cards','existing_dependencies','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Mage damage spells require their three complete original records')
    path=ROOT/d['reference_document']
    if(hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256']or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Mage damage spells lost their full original source scope')
    return d


def register_mage_conditional_damage(registry):
    def flame_damage(c):
        row=c.mana_result
        if row is None or(row.player_id,row.source_id,row.requested)!=(c.player_id,c.source_id,None)or row.cast_id is None:
            raise ResolutionError('Forbidden Flame lost its original all-Mana debit')
        cast=cast_record(c.state,row.cast_id);active=active_cast(c.state,c.source_id,c.player_id)
        if active is None or active.id!=cast.id:raise ResolutionError('Forbidden Flame lost its original active CAST')
        from hs_sim.engine.next_spell_bodies import body_target
        target=body_target(registry,cast)
        if target is None or target.kind!=CardType.MINION or target.zone!=Zone.BOARD:
            raise ResolutionError('Forbidden Flame lost its original minion allocation')
        ref=MinionReference(target.entity_id,target.controller,target.card_id,target.zone_epoch,target.entered_order)
        return(DamageCapturedMinionGroup((ref,),(row.actual,),c.source_id),)
    def elemental(c):
        return query_previous_owner_turn(c.state,c.player_id,PlayedTypeQuery(CardType.MINION,('elemental',))).matched
    def combustion(c):
        if elemental(c):
            if c.target_id is None:raise ResolutionError('Spontaneous Combustion lost its original chosen target')
            return(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),)
        if c.target_id is not None:raise ResolutionError('Untargeted Combustion borrowed a chosen target')
        return(RandomDamage(characters(c,registry,3-c.player_id),4,c.source_id,DamageKind.SPELL),)
    def waves(c):
        if c.cast is None:raise ResolutionError('Rising Waves requires its actual original CAST')
        return(DamageMinionsRepeatIfNoDeaths(c.player_id,c.cast.id,c.source_id,2),)
    bodies={FLAME:lambda c:(SpendMana(c.player_id,None,c.source_id,PREFIX+'flame_damage'),),
        COMBUSTION:combustion,WAVES:waves,'flame_damage':flame_damage}
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id'];extra={}
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Mage damage face already registered')
        if cid==FLAME:extra['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        elif cid==COMBUSTION:extra['targeting']=TargetSpec(relation='enemy')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if cid==FLAME else raw['cost'],on_play=PREFIX+cid,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card);prepared.append(card)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_target_profile(PreviousElementalTargetProfile(COMBUSTION))
