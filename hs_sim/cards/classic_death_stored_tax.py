"""Fixed spell rewards, a real named death cycle, stored growth and spell tax."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.cross_zone import MinionScope,minion_references
from hs_sim.engine.effects import AddCostModifier,AddToHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,PlayerEffectSpec,TriggerSpec,Zone
from hs_sim.engine.player_effects import AddPlayerEffect,ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference,SetCapturedMinionStats
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/classic-death-stored-tax-v1.json'
BATCH_HASH='5b07673b63e1c00bc106f607deb65f853e5f3fa7faa52f30b60c4dda54556e5b'
RHONIN,ANUBARAK,MISTCALLER,EADRIC,LOATHEB=ROOTS=('AT_009','AT_036','AT_054','AT_081','FP1_030')
NERUBIAN,=DEPENDENCIES=('AT_036t',)
MISSILES='EX1_277'
PREFIX='cards.classic_death_stored_tax.'
PROGRAM=PREFIX+'loatheb_pending'


def make_definition(raw):
    cid=raw['id']
    if(cid not in(*ROOTS,*DEPENDENCIES)or raw['type']!='MINION'or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Classic consumers require complete original minion faces')
    if cid in ROOTS and(not raw['collectible']or raw['tags'].get('RARITY')!=5):
        raise TargetValidationError('Classic parent lost its original collectible Legendary role')
    if cid==NERUBIAN and(raw['collectible']or raw['tags'].get('DEATHRATTLE')!=1):
        raise TargetValidationError('Named Nerubian requires its original uncollectible Deathrattle face')
    fields={'deathrattle'if cid in(RHONIN,ANUBARAK,NERUBIAN)else'battlecry':PREFIX+cid}
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-classic-death-stored-tax-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=[MISSILES,'TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=18 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Classic consumers lost complete identities, source roles or policy')
    rows={x['record']['id']:x['record']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]}
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Classic consumers changed a complete original row')
    for parent,child in((RHONIN,MISSILES),(ANUBARAK,NERUBIAN)):
        if rows[parent]['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=rows[child]['dbf_id']:
            raise TargetValidationError('Classic consumer lost its actual original named child')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Classic consumers changed a complete retained source')
    if d['retained_documents']['full_reference']!={'path':d['full_reference_document'],'sha256':d['full_reference_sha256']}:
        raise TargetValidationError('Classic consumers lost their exact complete reference binding')
    ref=json.loads((ROOT/d['full_reference_document']).read_text(encoding='utf8'))
    full={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=full[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Classic consumers cropped the complete original past domain')
    return d


def register_classic_death_stored_tax(registry):
    d=load_batch();prepared=[]
    original=next(x for x in d['existing_dependencies']if x['record']['id']==MISSILES)
    if(canonical_digest(asdict(registry.card(MISSILES)))!=original['definition_sha256']or
            canonical_digest(asdict(registry.pool_card(MISSILES)))!=original['pool_card_sha256']):
        raise TargetValidationError('Rhonin requires the complete unchanged original Arcane Missiles effect')
    registry.behavior(registry.card(MISSILES).on_play)
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Classic consumer cannot replace or alter an existing face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Classic consumer changed complete existing metadata')
        prepared.append(card)
    def rhonin(c):return tuple(AddToHand(c.player_id,MISSILES,c.source_id)for _ in range(3))
    def death_summon(c,cid):
        return(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c),position=deathrattle_position(c)),)
    def mistcaller(c):
        refs=minion_references(c.state,registry,c.player_id,MinionScope((Zone.HAND,Zone.DECK)),c.source_id)
        return tuple(BuffStoredCard(ref,1,1,c.source_id)for ref in refs)
    def eadric(c):
        return tuple(SetCapturedMinionStats(MinionReference.capture(c.state.entities[eid]),attack=1,source_id=c.source_id)
            for eid in minions(c,registry,3-c.player_id))
    def loatheb(c):return(AddPlayerEffect(3-c.player_id,PROGRAM,c.source_id),)
    def tax_start(c):
        if c.event.player_id!=c.player_id:return()
        if c.player_effect is None or c.player_effect.spec_id!=PROGRAM:
            raise ResolutionError('Loatheb lost its exact original opponent player instance')
        return(ConsumePlayerEffect(c.player_id,c.player_effect,(
            AddCostModifier(c.player_id,CostSpec(delta=5,card_types=(CardType.SPELL,)),
                source_id=c.source_id,expires_turn=c.state.turn),)),)
    bodies={RHONIN:rhonin,ANUBARAK:lambda c:death_summon(c,NERUBIAN),
        NERUBIAN:lambda c:death_summon(c,ANUBARAK),MISTCALLER:mistcaller,EADRIC:eadric,LOATHEB:loatheb,'tax_start':tax_start}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,LOATHEB,triggers=(TriggerSpec('turn_started',PREFIX+'tax_start'),)))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
