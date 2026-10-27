"""AmanThul and Voltron use existing original choices, entries and full-body echoes."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.effects import ChoiceOption,CopyMinion,Draw,InvokeBehavior,RandomDamage,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (ActivatedAbilitySpec,CardDefinition,CardType,DamageKind,Keyword,
    Rarity,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.targeting import target_choices
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/titan-copy-echo-v1.json'
BATCH_HASH='037b0107e5c8f1682260f21a0e9bb3dce579781f262f1df28085eb1fcd0bd994'
AMAN,VOLTRON='TTN_429','TTN_721'
AMAN_SKILLS=('TTN_429t','TTN_429t2','TTN_429t3')
VOLTRON_SKILLS=('TTN_721t','TTN_721t1','TTN_721t2')
ROOTS=(AMAN,VOLTRON);SKILLS=AMAN_SKILLS+VOLTRON_SKILLS
DEPENDENCIES=SKILLS;COLLECTIBLE_ROOTS=()
PREFIX='cards.titan_copy_echo.';RULE=PREFIX+'non_titan';POOL='constructed.cards'
SIXES=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=6,max_cost=6)
LEGENDS=PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=SKILLS or tuple(d['choice_only_ids'])!=SKILLS or
            any(d[k]for k in('existing_dependencies','evidence_only','new_token_ids','source_scope_bound',
                'formal_pool_complete','cn_calibrated','real_excavate_profile_bound'))or
            len(d['official_observations'])!=16 or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in d['cards']+d['dependencies'])):
        raise TargetValidationError('Titan copy/echo requires complete original faces and explicit roles')
    for ref in d['references']:
        if hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise TargetValidationError('Titan copy/echo changed a complete original shared reference')
    return d


def register_titan_copy_echo(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Titan copy/echo cannot overwrite an existing face')
        if cid in ROOTS:
            if (raw['cost'],raw['attack'],raw['health'])!=((7,3,10)if cid==AMAN else(6,3,5))or not raw['collectible']or raw['tags'].get('TITAN')!=1:
                raise TargetValidationError('Titan copy/echo lost its true printed body')
            skills=AMAN_SKILLS if cid==AMAN else VOLTRON_SKILLS
            extra.update(keywords=(Keyword.TITAN,),activated_abilities=tuple(
                ActivatedAbilitySpec(skill,PREFIX+skill,card_id=skill,
                    targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if skill==AMAN_SKILLS[0]else None,
                    target_rule=RULE if skill==AMAN_SKILLS[0]else'any_entity')for skill in skills))
            if cid==AMAN:extra['triggers']=(TriggerSpec('minion_ability_used',PREFIX+'after'),)
        else:
            if kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']:
                raise TargetValidationError('Titan copy/echo skills are nonphysical zero-cost descriptors')
            extra['choice_only']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Titan copy/echo changed original printed pool metadata')
        prepared.append(card)

    def two(c):
        domain=replace(registry.card(AMAN),targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'))
        ids=tuple(i for i in target_choices(c.state,registry,c.source,domain)if i is not None)
        options=tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])),sort_keys=True),
            registry.card(c.state.entities[i].card_id).name,entity_id=i)for i in ids)
        count=min(2,len(options))
        return(RequestChoice(c.player_id,options,c.source_id,min_count=count,max_count=count,
            on_select=PREFIX+'remove',targeting=domain.targeting),)if count else ()
    def remove(c):
        if c.choice is None:raise ResolutionError('AmanThul lost its complete original removal selection')
        return(RemoveFromGame(tuple(MinionReference(**json.loads(key))for key in c.choice.selected_ids),c.source_id),)
    def after(c):
        if c.event.source_id!=c.source_id or dict(c.event.data).get('ability_card_id')not in AMAN_SKILLS:return ()
        return(DiscoverFromPool(c.player_id,POOL,LEGENDS,source_id=c.source_id),)
    def cannon(c):
        targets=(c.state.players[3-c.player_id].hero_id,)+minions(c,registry,3-c.player_id)
        return(RandomDamage(targets,4,c.source_id,DamageKind.MINION_ABILITY),)
    def body(c,skill,receiver):
        ref=MinionReference.capture(c.state.entities[receiver])
        if skill==VOLTRON_SKILLS[0]:
            return(BuffCapturedMinion(ref,2,1,receiver),InvokeBehavior(PREFIX+'cannon',receiver,c.player_id))
        if skill==VOLTRON_SKILLS[1]:
            return(BuffCapturedMinion(ref,1,2,receiver),Draw(c.player_id,source_id=receiver))
        return(BuffCapturedMinion(ref,health=3,source_id=receiver),GrantCapturedKeyword(ref,Keyword.ELUSIVE,receiver))
    def echo(c,skill):
        targets=tuple(i for i in minions(c,registry,c.player_id)if i!=c.source_id)
        options=tuple(ChoiceOption(str(i),registry.card(c.state.entities[i].card_id).name,body(c,skill,i),entity_id=i)for i in targets)
        return(ChooseRandomEffects(c.player_id,c.source_id,options),)if options else ()
    registry.register_player_target_rule(PlayerTargetRuleSpec(RULE,'v1'),
        lambda c:c.target is not None and Keyword.TITAN.value not in c.target.get('keywords',()))
    funcs={AMAN_SKILLS[0]:lambda c:()if c.target_id is None else(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c),minion_grant=CreatedMinionGrant(2,2)),),
        AMAN_SKILLS[1]:two,AMAN_SKILLS[2]:lambda c:(SummonFromPool(c.player_id,POOL,SIXES,source_id=c.source_id,
            cause=SummonCause.capture(c),entry_keywords=(Keyword.TAUNT,Keyword.LIFESTEAL)),),
        'remove':remove,'after':after,'cannon':cannon}
    for skill in VOLTRON_SKILLS:
        funcs[skill]=lambda c,skill=skill:(*body(c,skill,c.source_id),InvokeBehavior(PREFIX+'echo.'+skill,c.source_id,c.player_id))
        funcs['echo.'+skill]=lambda c,skill=skill:echo(c,skill)
    for name,fn in funcs.items():registry.register_behavior(PREFIX+name,fn)
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
