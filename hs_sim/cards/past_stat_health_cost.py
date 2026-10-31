"""Ten actual past minions composed from ordinary stored, health and cost kernels."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.costs import local_cost
from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import Damage, Heal, RandomDamage
from hs_sim.engine.hand_upgrades import BuffStoredCard, SetStoredMinionStats
from hs_sim.engine.health_outcomes import is_overheal
from hs_sim.engine.model import (CardDefinition, CardType, DamageKind, HealingKind, IntrinsicCostSpec,
    Keyword, StatRelationLayer, StatRelationOperand, StatRelationSpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.zones import CardReference, DrawSpellsUntilHandFull, FillHandWithCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-stat-health-cost-v1.json'
BATCH_HASH='a79a5aee39b9aa5036b014f07ac7b2989864a8d2c984bc16db47c36cac2ab661'
EMERISS,WHITE,VALANAR,ALEX,MALYGOS,HOBART,HEDANIS,MUKLA,FANOTTEM,LANA=ROOTS=(
    'GIL_128','GIL_840','ICC_853','LEG_CS3_031','LEG_CS3_034','WON_117','ETC_334','ETC_836','JAM_030','ICC_841')
DEPENDENCIES=()
EXISTING=('EX1_014t',)
EVIDENCE=('MIS_701',)
PREFIX='cards.past_stat_health_cost.'
DECK_PRICE=IntrinsicCostSpec(condition='current_deck_count',history_profile_id='deck.current-count-as-cost-v1',card_count=0,comparison='at_least')


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Stat/health/cost requires its complete actual minion face')
    fields={}
    if cid not in(FANOTTEM,LANA):fields['battlecry']=PREFIX+cid
    if cid==ALEX:fields['targeting']=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
    if cid==HEDANIS:fields['triggers']=(TriggerSpec('health_resolved',PREFIX+'overheal'),)
    if cid==MUKLA:fields['keywords']=(Keyword.RUSH,)
    if cid==FANOTTEM:fields.update(keywords=(Keyword.TAUNT,Keyword.LIFESTEAL),intrinsic_costs=(DECK_PRICE,))
    if cid==LANA:fields.update(keywords=(Keyword.LIFESTEAL,),stat_relations=(StatRelationSpec(
        operand=StatRelationOperand.CONTROLLER_DISCARD_COUNT,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=1),))
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=24 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Stat/health/cost changed full roles or claimed complete support')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete stat/health/cost row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped full past reference')
    return d


def register_past_stat_health_cost(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']:
            raise TargetValidationError('Mukla changed the exact existing1694 Banana')
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']:
            raise TargetValidationError('Stat/health/cost replaced or changed an existing face')
        registry._validate_card(card);prepared.append(card)
    def stored(c,white=False):
        zone=Zone.DECK if white else Zone.HAND;ids=c.state.players[c.player_id].deck if white else c.state.players[c.player_id].hand
        units=[c.state.entities[i]for i in ids if c.state.entities[i].kind==CardType.MINION]
        return tuple(SetStoredMinionStats(CardReference.capture(e),e.health,None,c.source_id)if white else
            BuffStoredCard(CardReference.capture(e),e.attack,e.health,c.source_id)for e in units)
    def valanar(c):
        if any(local_cost(c.state.entities[i])[0]==4 for i in c.state.players[c.player_id].deck)or not living_source(c):return()
        ref=MinionReference.capture(c.source)
        return tuple(GrantCapturedKeyword(ref,k,c.source_id)for k in(Keyword.LIFESTEAL,Keyword.TAUNT))
    def alex(c):
        e=c.state.entities.get(c.target_id)
        if e is None or e.kind not in(CardType.HERO,CardType.MINION)or e.zone not in(Zone.HERO,Zone.BOARD)or not e.active or e.doomed or e.health<=0:return()
        return(Heal(e.id,8,c.source_id,HealingKind.EFFECT),)if e.controller==c.player_id else(Damage(e.id,8,c.source_id,DamageKind.MINION_ABILITY),)
    def hobart(c):
        if c.state.players[c.player_id].weapon_id is None:return()
        return(BuffMinionsInZones(c.player_id,2,2,MinionScope(zones=(Zone.HAND,Zone.DECK)),c.source_id),)
    def overheal(c):
        if not is_overheal(c.event,c.source_id):return()
        ids=characters(c,registry,3-c.player_id)
        return(RandomDamage(ids,5,c.source_id,DamageKind.MINION_ABILITY),)if ids else()
    bodies={EMERISS:stored,WHITE:lambda c:stored(c,True),VALANAR:valanar,ALEX:alex,
        MALYGOS:lambda c:(DrawSpellsUntilHandFull(c.player_id,c.source_id),),HOBART:hobart,
        HEDANIS:lambda c:(Damage(c.source_id,4,c.source_id,DamageKind.MINION_ABILITY),),
        MUKLA:lambda c:(FillHandWithCard(3-c.player_id,EXISTING[0],c.source_id),)}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    registry.register_behavior(PREFIX+'overheal',overheal)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
