"""Two real Titans reuse finite minion abilities, combat and native side auras."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import Buff,GainArmor,InvokeBehavior,RandomForceAttack
from hs_sim.engine.model import (ActivatedAbilitySpec,CardDefinition,CardType,CostSpec,Keyword,KeywordAuraSpec,TriggerSpec)
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,DrawMatching,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/titan-reference-khaz-argus-v1.json'
BATCH_HASH='559e026dad6f551aa9f327cdc626229fd0ac50aff744cde83523fe131d622163'
KHAZ,ARGUS='TTN_415','TTN_862'
KHAZ_SKILLS=('TTN_415t','TTN_415t2','TTN_415t3')
ARGUS_SKILLS=('TTN_862t1','TTN_862t2','TTN_862t3')
TOKEN='TTN_862t4'
ROOTS=(KHAZ,ARGUS)
SKILLS=KHAZ_SKILLS+ARGUS_SKILLS
DEPENDENCIES=SKILLS
COLLECTIBLE_ROOTS=()
PREFIX='cards.titan_khaz_argus.'
POOL='constructed.cards'
LEFT=KeywordAuraSpec(Keyword.RUSH,'friendly_minions_left_of_source')
RIGHT=KeywordAuraSpec(Keyword.LIFESTEAL,'friendly_minions_right_of_source')


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=DEPENDENCIES or
            tuple(d['choice_only_ids'])!=SKILLS or d['new_token_ids'] or
            len(d['inventory']['candidate_ids'])!=12 or d['inventory']['weights']!=[1]*12 or
            d['inventory']['runtime_bound']is not False or len(d['official_observations'])!=40 or
            any(d[k]for k in('source_scope_bound','formal_pool_complete','cn_calibrated','real_excavate_profile_bound')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for k in
                ('cards','dependencies','existing_dependencies','evidence_only')for r in d[k])):
        raise TargetValidationError('Titans lost their complete original faces or explicitly unbound full reference')
    return d


def register_titan_khaz_argus(registry):
    d=load_batch()
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Titans changed a complete original Eonar or Hawk dependency')
    prepared=[]
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Titans cannot overwrite an existing native face')
        if cid in ROOTS:
            if (raw['type'],raw['collectible'],raw['tags'].get('TITAN'))!=('MINION',True,1):
                raise TargetValidationError('Titan requires its true collectible printed keyword')
            skills=KHAZ_SKILLS if cid==KHAZ else ARGUS_SKILLS
            extra.update(keywords=(Keyword.TITAN,),activated_abilities=tuple(
                ActivatedAbilitySpec(skill,PREFIX+skill,card_id=skill)for skill in skills))
            if cid==KHAZ:extra['triggers']=(TriggerSpec('minion_ability_used',PREFIX+'khaz_after'),)
            else:extra['keyword_auras']=(LEFT,RIGHT)
        elif cid in SKILLS:
            if kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']:
                raise TargetValidationError('Titan skills require original nonphysical zero-cost descriptors')
            extra['choice_only']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Titan differs from existing complete printed pool metadata')
        prepared.append(card)

    def khaz_after(c):
        if (c.event.source_id!=c.source_id or dict(c.event.data).get('ability_card_id')not in KHAZ_SKILLS or not living_source(c)):
            return ()
        return(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.IMMUNE,c.source_id,c.state.turn),
            InvokeBehavior(PREFIX+'khaz_attack',c.source_id,c.player_id))
    def khaz_attack(c):
        targets=minions(c,registry,3-c.player_id)
        return(RandomForceAttack((c.source_id,),targets,c.source_id),)if living_source(c)and targets else ()
    def growth(c,attack=0,health=0):return BuffCapturedMinion(MinionReference.capture(c.source),attack,health,c.source_id)
    bodies={
        KHAZ_SKILLS[0]:lambda c:(growth(c,2,2),DrawMatching(c.player_id,PoolQuery(kinds=(CardType.WEAPON,)),'skip',source_id=c.source_id)),
        KHAZ_SKILLS[1]:lambda c:(growth(c,attack=5),Buff(c.state.players[c.player_id].hero_id,attack=5,source_id=c.source_id,expires_turn=c.state.turn)),
        KHAZ_SKILLS[2]:lambda c:(growth(c,health=5),GainArmor(c.player_id,5)),
        'khaz_after':khaz_after,'khaz_attack':khaz_attack,
        ARGUS_SKILLS[0]:lambda c:(DiscoverFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            class_mode='current',deathrattle=True),source_id=c.source_id,cost=CostSpec(delta=-3)),),
        ARGUS_SKILLS[1]:lambda c:tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-2),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION),
        ARGUS_SKILLS[2]:lambda c:tuple(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),SummonCause.capture(c))for _ in range(4)),
    }
    for name,fn in bodies.items():registry.register_behavior(PREFIX+name,fn)
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
