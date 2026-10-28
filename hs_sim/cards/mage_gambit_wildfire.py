"""Original Mage school questline and already established game-long damage rules."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddToHand,GrantHealthRule,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,HealthFlow,HealthOp,HealthRule,
    Keyword,QuestSpec,QuestStageSpec,SpellSchool)
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/mage-gambit-wildfire-v1.json'
BATCH_HASH='acb709778c3acffaf90f4ba6500244d25639e388641cadf8d6213b37182eb60c'
POLICY='cn37-local-mage-gambit-wildfire-v1'
GAMBIT,WILDFIRE=LEAVES=('SW_450','BAR_546')
DESCRIPTORS=('SW_450t','SW_450t2')
DEPENDENCIES=LEAVES+DESCRIPTORS
METADATA_IDS=LEAVES
REWARD='SW_450t4'
COLLECTIBLE_ROOTS=()
PREFIX='cards.mage_gambit_wildfire.'
POOL='constructed.cards'
SCHOOL_SET=(SpellSchool.FIRE,SpellSchool.FROST,SpellSchool.ARCANE)
POWER_RULE=HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,source_relation='friendly',damage_kinds=(DamageKind.HERO_POWER,))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=d['dependencies']+d['existing_dependencies']+d['evidence_only']
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(d['choice_only_ids'])!=DESCRIPTORS or
            tuple(row['record']['id']for row in d['dependencies'])!=DEPENDENCIES or
            tuple(row['record']['id']for row in d['existing_dependencies'])!=(REWARD,) or
            tuple(row['record']['id']for row in d['evidence_only'])!=('SW_450t4e','BAR_546e','BAR_546e2') or
            len(d['official_observations'])!=10 or any(d[k]for k in ('cards','new_token_ids','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in rows)):
        raise TargetValidationError('Mage Gambit and Wildfire require their eight complete original records')
    path=ROOT/d['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Mage Gambit and Wildfire lost their full original source scope')
    return d


def register_mage_gambit_wildfire(registry):
    d=load_batch();pin=d['existing_dependencies'][0]
    if (canonical_digest(asdict(registry.card(REWARD)))!=pin['definition_sha256'] or
            REWARD in registry.pool_cards or pin['pool_metadata_previously_registered'] is not False or
            canonical_digest(asdict(registry.player_effect(pin['player_effect_id'])))!=pin['player_effect_sha256']):
        raise TargetValidationError('Mage Gambit changed its complete existing Dawngrasp reward')
    def progress(c):
        if c.event is None or c.event.kind!='spell_cast_started':raise ResolutionError('Gambit requires an actual original CAST')
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        if (row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Gambit lost its original cast identity')
        if row.player_id!=c.player_id or row.failure not in (None,'countered'):return ()
        school=registry.card(row.card_id).spell_school
        if school not in SCHOOL_SET:return ()
        q=c.source.quest_progress
        return(AdvanceQuest(c.source_id,q.id,q.stage,key='school:'+school.value),)
    bodies={
        'progress':progress,
        'draw':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)),),
        'discover':lambda c:(DiscoverFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.SPELL,),collectible=True,
            class_mode='current',spell_schools=SCHOOL_SET),source_id=c.source_id),),
        'reward':lambda c:(AddToHand(c.player_id,REWARD,c.source_id),),
        'wildfire':lambda c:(InvokeBehavior(PREFIX+'wildfire_grant',c.source_id,c.player_id),),
        'wildfire_grant':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_id,POWER_RULE,c.source_id),),
    }
    prepared=[]
    for row in d['dependencies']:
        raw=row['record'];cid=raw['id'];kw={}
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Mage quest face already exists')
        if cid==GAMBIT:
            kw.update(keywords=(Keyword.QUESTLINE,),quest=QuestSpec('questline',tuple(
                QuestStageSpec(stage,3,('spell_cast_started',),PREFIX+'progress',PREFIX+reward)
                for stage,reward in zip((GAMBIT,)+DESCRIPTORS,('draw','discover','reward')))))
        elif cid==WILDFIRE:kw['on_play']=PREFIX+'wildfire'
        else:kw['choice_only']=True
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if cid in DESCRIPTORS else raw['cost'],
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**kw)
        registry._validate_card(card);prepared.append(card)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:registry.register_pool_card(PoolCard.from_definition(card))
