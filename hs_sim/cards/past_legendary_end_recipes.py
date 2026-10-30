"""Real past Legendary end bodies delegate timing and effects to shared kernels."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Buff,ChoiceOption,Damage,DamageBatch,Heal,RandomDamage
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (AttackPolicySpec,CardDefinition,CardType,DamageKind,EndTurnSpec,
    HealingKind,Keyword,TriggerSpec)
from hs_sim.engine.ordered_group_batches import FillBoardWithCard
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-end-recipes-v1.json'
BATCH_HASH='0dd4cb36618bd188b2ce6ebad6c97eb3444ff33c56d123d950cd811886f72c1b'
ROOTS=('AT_063t','WON_025','EX1_249','EX1_298','NEW1_038','NEW1_040','KAR_044','DRG_091',
    'LEG_CS3_032','OG_229','RLK_539','ULD_258')
DEPENDENCIES=('NEW1_040t','KAR_044a','DRG_091t')
PREFIX='cards.past_legendary_end.'
FIXED={'NEW1_040':'NEW1_040t','KAR_044':'KAR_044a'}
FILL={'DRG_091':'DRG_091t','LEG_CS3_032':'ds1_whelptoken'}
EITHER=('NEW1_038','LEG_CS3_032')
KEYWORDS={'KAR_044':(Keyword.STEALTH,),'RLK_539':(Keyword.LIFESTEAL,),
    'ULD_258':(Keyword.TAUNT,),'NEW1_040t':(Keyword.TAUNT,)}


def make_definition(raw):
    cid=raw['id'];root=cid in ROOTS
    if (cid not in(*ROOTS,*DEPENDENCIES)or raw['type']!='MINION'or raw['collectible']is not root or
            root and raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('End recipes require complete original Legendary and actual dependency roles')
    triggers=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec('either'if cid in EITHER else'controller')), )if root else()
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=KEYWORDS.get(cid,()),triggers=triggers,metadata=metadata_from_record(raw),
        attack_policies=(AttackPolicySpec('cannot_attack'),)if cid=='EX1_298'else())


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-end-recipes-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=['ds1_whelptoken','TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=28 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('End recipes lost original complete roles or claimed a partial source complete')
    rows={x['record']['id']:x['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]}
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('End recipes changed a complete original source row')
    if any(rows[cid]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=rows[token]['dbf_id']for cid,token in{**FIXED,**FILL}.items()):
        raise TargetValidationError('End recipes changed an actual client-linked named identity')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('End recipes changed the complete original past reference')
    ref=json.loads(p.read_text(encoding='utf8'));records={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or any(x['record']!=records[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('End recipes cropped full membership or changed original root rows')
    return d


def register_past_legendary_end_recipes(registry):
    d=load_batch();prepared=[]
    old=d['existing_dependencies'][0]
    if (canonical_digest(asdict(registry.card('ds1_whelptoken')))!=old['definition_sha256']or
            canonical_digest(asdict(registry.pool_card('ds1_whelptoken')))!=old['pool_card_sha256']):
        raise TargetValidationError('Broodmother requires the unchanged complete existing Onyxia Whelp')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('End recipes cannot replace or change complete native definitions')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('End recipes changed existing complete metadata')
        prepared.append(card)
    def area(c,amount,both=False):
        players=(1,2)if both else(3-c.player_id,)
        return(DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.MINION_ABILITY)
            for p in players for i in characters(c,registry,p)if not both or i!=c.source_id)),)
    def random_enemy(c):
        ids=characters(c,registry,3-c.player_id)
        return(RandomDamage(ids,8,c.source_id,DamageKind.MINION_ABILITY),)if ids else()
    def lightlord(c):
        ids=tuple(i for i in characters(c,registry,c.player_id)if c.state.entities[i].health<c.state.entities[i].max_health)
        return(ChooseRandomEffects(c.player_id,c.source_id,tuple(ChoiceOption(str(i),'Restore 8 Health',
            (Heal(i,8,c.source_id,HealingKind.EFFECT),))for i in ids)),)if ids else()
    def hand_taunts(c):
        return tuple(BuffStoredCard(CardReference.capture(e),2,2,c.source_id)
            for i in c.state.players[c.player_id].hand for e in(c.state.entities[i],)
            if e.kind==CardType.MINION and(Keyword.TAUNT in e.keywords or any(
                a.kind=='keyword'and a.keyword==Keyword.TAUNT and not a.consumed for a in e.abilities)))
    bodies={
        'AT_063t':lambda c:area(c,1),'WON_025':lambda c:area(c,1),'EX1_249':lambda c:area(c,2,True),
        'EX1_298':random_enemy,'NEW1_038':lambda c:(Buff(c.source_id,1,1,c.source_id),),
        'OG_229':lightlord,'RLK_539':lambda c:(Damage(c.state.players[3-c.player_id].hero_id,6,c.source_id,DamageKind.MINION_ABILITY),),
        'ULD_258':hand_taunts,
    }
    for cid,token in FIXED.items():
        bodies[cid]=lambda c,token=token:(SummonByCard(c.player_id,(SummonEntryMaterial(token),),SummonCause.capture(c)),)
    for cid,token in FILL.items():
        bodies[cid]=lambda c,token=token:(FillBoardWithCard(c.player_id,token,SummonCause.capture(c)),)
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
