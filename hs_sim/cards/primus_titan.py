"""The Primus uses actual native skills and shared Rune discovery/program effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.health_loss import GainMaxHealth
from hs_sim.engine.model import (ActivatedAbilitySpec,CardDefinition,CardType,Keyword,
    PlayerEffectSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.next_spell_bonuses import KIND
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/primus-native-spell-bonus-v1.json'
BATCH_HASH='c4131f5c5b426fda15be5b5d84cd1e9334ae6dd91729e92a1a174b4b4cdf42cb'
CARD='TTN_737'
BLOOD,UNHOLY,FROST='TTN_737t','TTN_737t1','TTN_737t3'
SKILLS=(BLOOD,UNHOLY,FROST)
TOKEN='TTN_737t2'
ROOTS=(CARD,)
DEPENDENCIES=SKILLS
COLLECTIBLE_ROOTS=()
PREFIX='cards.primus_titan.'
SPEC=PREFIX+FROST
POOL='constructed.cards'
RUNE_BY_SKILL=dict(zip(SKILLS,('blood','unholy','frost')))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=SKILLS or
            tuple(r['record']['id']for r in d['existing_dependencies'])!=(TOKEN,) or
            tuple(d['choice_only_ids'])!=SKILLS or d['new_token_ids'] or
            len(d['official_observations'])!=14 or
            any(d[k]for k in('source_scope_bound','formal_pool_complete','cn_calibrated','real_excavate_profile_bound')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for key in
                ('cards','dependencies','existing_dependencies','evidence_only')for r in d[key])):
        raise TargetValidationError('Primus requires its complete original faces and explicitly unbound reference')
    reference=ROOT/d['titan_reference']['path']
    import hashlib
    if hashlib.sha256(reference.read_bytes()).hexdigest()!=d['titan_reference']['sha256']:
        raise TargetValidationError('Primus cannot change the complete original Titan reference')
    return d


def register_primus_titan(registry):
    d=load_batch()
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Primus cannot replace its original Servant dependency')
    prepared=[]
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Primus cannot overwrite an existing face')
        if cid==CARD:
            if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TITAN'))!=('MINION',True,8,7,9,1):
                raise TargetValidationError('Primus lost its true printed Titan body')
            extra.update(keywords=(Keyword.TITAN,),activated_abilities=tuple(
                ActivatedAbilitySpec(skill,PREFIX+skill,card_id=skill,
                    targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')if skill==BLOOD else None)
                for skill in SKILLS),triggers=(TriggerSpec('minion_ability_used',PREFIX+'after'),))
        else:
            if kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']:
                raise TargetValidationError('Primus skills require the complete nonphysical descriptor')
            extra['choice_only']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Primus differs from the complete printed pool metadata')
        prepared.append(card)

    def blood(c):
        if c.target_id is None:return ()
        victim=c.state.entities[c.target_id]
        return(DestroyCapturedMinion(MinionReference.capture(victim),c.source_id,
            (BuffCapturedMinion(MinionReference.capture(c.source),health=victim.health,source_id=c.source_id),
             GainMaxHealth(c.player_id,victim.health,c.source_id))),)
    def after(c):
        rune=RUNE_BY_SKILL.get(dict(c.event.data).get('ability_card_id'))
        if c.event.source_id!=c.source_id or rune is None:return ()
        return(DiscoverFromPool(c.player_id,POOL,PoolQuery(collectible=True,runes_any=(rune,)),source_id=c.source_id),)
    bodies={BLOOD:blood,
        UNHOLY:lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c))for _ in range(2)),
        FROST:lambda c:(AddPlayerEffect(c.player_id,SPEC,c.source_id,
            ability_event=c.event,ability_source=SourceAllocationFact.capture(c.state,c.source)),),
        'after':after}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(PlayerEffectSpec(SPEC,CARD,kind=KIND,spell_damage=3,next_spell_cost_reduction=3))
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
