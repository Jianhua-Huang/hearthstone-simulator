"""Actual past turn consumers, with original physical source references."""
from dataclasses import asdict
import hashlib, json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.effects import AddToHand, GainResource
from hs_sim.engine.guarded_corpse_spends import SpendCorpsesForMinion
from hs_sim.engine.health_loss import GainMaxHealth
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, Keyword, Resource, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.turn_event_consumers import (ResurrectFriendlyTurnDeaths,
    BuffUnattackedOtherMinions, EatOpponentDeckMinion, AttackRandomEnemyAndGrow)
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-turn-lifecycle-v1.json'
BATCH_HASH='f302acdbf84244ec6dde20d0e901e4fd6a0f2641d37f636e5a22363ed0c33c6a'
KEL,HAMM,GILLY,AFK,MAW,LOTHAR=ROOTS=('FP1_013','VAC_340','VAC_413','VAC_446','WW_357','SW_024')
CROC='VAC_413t'
DEPENDENCIES=(CROC,)
EXISTING=()
EVIDENCE=('MIS_701',)
PREFIX='cards.past_turn_lifecycle.'


def make_definition(raw):
    cid=raw['id'];attack=raw['attack']
    if cid==AFK and attack is None and 'ATK' not in raw['tags']:attack=0
    if (cid not in ROOTS+DEPENDENCIES or raw['type']!='MINION' or
            any(type(v)is not int for v in(raw['cost'],attack,raw['health']))):
        raise TargetValidationError('Turn consumer requires its full original minion face')
    fields={}
    if cid in ROOTS:fields['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec('either'if cid==KEL else'controller')),)
    if cid==HAMM:fields['keywords']=(Keyword.TAUNT,)
    if cid==GILLY:fields['deathrattle']=PREFIX+'gilly_death'
    if cid==MAW:fields['triggers']+=(TriggerSpec('turn_started',PREFIX+'maw_start'),)
    if cid==CROC and(raw['text']or raw['text_en']or raw['collectible'] or
            (raw['dbf_id'],raw['cost'],attack,raw['health'])!=(113343,2,2,3)):
        raise TargetValidationError('Gilly requires the exact actual Island Crocolisk face')
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=attack,health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies']or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=16 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Turn consumers changed full roles or claimed complete support')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original turn row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped full past reference')
    return d


def own_turn(c,kind):
    if c.event is None or c.event.kind!=kind:raise ValueError('Native turn consumer requires its actual turn event')
    return c.event.player_id==c.player_id and living_source(c)


def register_past_turn_lifecycle(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']:
            raise TargetValidationError('Turn consumer changed or replaced an existing face')
        registry._validate_card(card);prepared.append(card)
    def kel(c):
        return(ResurrectFriendlyTurnDeaths(MinionReference.capture(c.source),SummonCause.capture(c)),)if living_source(c)else()
    def ending(c,cid):
        if not living_source(c):return()
        ref=MinionReference.capture(c.source)
        if cid==HAMM:return(EatOpponentDeckMinion(ref),)
        if cid==GILLY:return(AddToHand(c.player_id,CROC,c.source_id),)
        if cid==AFK:return(BuffUnattackedOtherMinions(ref),)
        if cid==MAW:return(GainResource(c.player_id,Resource.CORPSES,5),)
        if cid==LOTHAR:return(AttackRandomEnemyAndGrow(ref),)
        raise ValueError('Unknown original turn body')
    def gilly_death(c):
        return tuple(BuffStoredCard(CardReference.capture(c.state.entities[i]),2,3,c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
    def maw_start(c):
        if not own_turn(c,'turn_started'):return()
        return(SpendCorpsesForMinion(MinionReference.capture(c.source),5,
            (GainMaxHealth(c.player_id,5,c.source_id),)),)
    registry.register_behavior(PREFIX+KEL,kel)
    for cid in ROOTS[1:]:registry.register_behavior(PREFIX+cid,lambda c,cid=cid:ending(c,cid))
    registry.register_behavior(PREFIX+'gilly_death',gilly_death)
    registry.register_behavior(PREFIX+'maw_start',maw_start)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
