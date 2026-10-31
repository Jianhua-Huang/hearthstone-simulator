"""Real historical counters and finite original attack, play and health providers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import AddCostModifier,AddToHand,Buff,Damage,DamageBatch,Freeze,InvokeBehavior
from hs_sim.engine.model import (AttackPolicySpec,CardDefinition,CardType,CostSpec,DamageKind,HealthFlow,
    HealthLayer,HealthOp,HealthRule,Keyword,LimitedTriggerSpec,PaymentType,SpellSchool,SummonStats,TriggerSpec,Zone)
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.hero_attack_gains import gained_this_turn as attack_gained_this_turn
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_history import SpellHistoryQuery,spell_history_candidates
from hs_sim.engine.starships import construction
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery,Resurrect
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-history-resource-providers-v1.json'
BATCH_HASH='d4344ca5006353fca01385ee6cffa9a7b46e3178bbd3cef1d2b4ccd707b8f989'
BEARON,KARGAL,SAURFANG,ZOK,CHEN,AKAMA,ASKARA,MALADAAR,OTHAAR,TALGATH=ROOTS=(
    'AV_257','BAR_077','BAR_334','ETC_386','DRG_104','GDB_235','GDB_455','GDB_470','GDB_856','GDB_472')
STAG,LOOKOUT,FAN,SNOW,FAR,CROSS,MORSHAN,GRUNT=DEPENDENCIES=(
    'AV_257t','BAR_077t','ETC_386t','DRG_104t2','BAR_074','BAR_075','BAR_076','BAR_076t')
POSTS=(FAR,CROSS,MORSHAN)
EXISTING=('CORE_CS2_072',)
EVIDENCE=('MIS_701','GDB_100t6')
PREFIX='cards.past_history_resource_providers.'
ARCANE=PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.ARCANE,))
FROST=SpellHistoryQuery(cards=PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.FROST,)))
FRENZY=DeathQuery(cards=PoolQuery(keywords_all=(Keyword.FRENZY,)))
UNDAMAGED=HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,layer=HealthLayer.TARGET,
    target_relation='undamaged_enemy_minions',target_kinds=(CardType.MINION,))


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS+DEPENDENCIES or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Historical providers require complete real original Minion faces')
    fields={}
    if cid in(BEARON,KARGAL,SAURFANG,ZOK,ASKARA,MALADAAR,OTHAAR):fields['battlecry']=PREFIX+cid
    if cid==CHEN:fields['limited_triggers']=(LimitedTriggerSpec('spell_cast_finished',PREFIX+'chen',PREFIX+'own_cast',uses=3,reset='cycle_turn'),)
    if cid==AKAMA:fields['triggers']=(TriggerSpec('attack_finished',PREFIX+'akama'),)
    if cid==TALGATH:fields.update(health_rules=(UNDAMAGED,),keywords=(Keyword.COMBO,),combo=PREFIX+'backstab')
    if cid==STAG:fields['triggers']=(TriggerSpec('damage_dealt',PREFIX+'freeze_hit'),)
    if cid==FAN:fields['keywords']=(Keyword.TAUNT,)
    if cid in POSTS:
        fields['attack_policies']=(AttackPolicySpec('cannot_attack'),)
        fields['triggers']=(TriggerSpec('card_drawn'if cid==FAR else'spell_cast_started'if cid==CROSS else'card_played',PREFIX+cid),)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=40 or
            tuple(d['watch_post_card_ids'])!=POSTS or tuple(d['validation_provider_ids'])!=POSTS or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Historical provider original source roles changed')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Changed complete original provider row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full original past source')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):raise TargetValidationError('Cropped complete original past source')
    return d


def register_past_history_resource_providers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Historical provider changed its existing actual Backstab')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Historical provider replaced another original face')
        registry._validate_card(card);prepared.append(card)
    def summon(c,cid,count=1,stats=None):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(cid,stats=stats),),SummonCause.capture(c))
        return(request,)*count
    def bearon(c):return summon(c,STAG,len(spell_history_candidates(c.state,registry,c.player_id,FROST,c.source_id)))
    def kargal(c):return summon(c,LOOKOUT,sum(row.player_id==c.player_id and row.card_id in POSTS for row in c.state.successful_summon_history))
    def saurfang(c):return(Resurrect(c.player_id,2,FRENZY,source_id=c.source_id,cause=SummonCause.capture(c)),InvokeBehavior(PREFIX+'damage_others',c.source_id,c.player_id))
    def minions(c,pids):
        return tuple(c.state.entities[i]for pid in pids for i in c.state.players[pid].board if
            c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active and
            not c.state.entities[i].doomed and c.state.entities[i].health>0)
    def damage_others(c):return(DamageBatch(tuple(Damage(e.id,1,c.source_id)for e in minions(c,(1,2))if e.id!=c.source_id)),)
    def zok(c):
        interval=current_owner_turn(c.state)
        attack=attack_gained_this_turn(c.state,c.player_id)
        armor=sum(row.amount for row in c.state.armor_gain_history if row.turn==c.state.turn and row.event_sequence>interval.start_event and row.player_id==c.player_id)
        return summon(c,FAN,2,SummonStats(1+attack,1+armor))
    def own_cast(c):
        if c.event is None or c.event.kind!='spell_cast_finished'or c.event.player_id!=c.player_id:return False
        from hs_sim.engine.spell_casts import cast_record
        row=cast_record(c.state,dict(c.event.data)['cast_id'])
        return row.completed and row.failure is None
    def akama(c):
        if c.event is None or c.event.kind!='attack_finished'or c.event.source_id!=c.source_id:return ()
        return tuple(GrantAttackPolicy(e.id,AttackPolicySpec('additional_attacks',1),c.source_id,expires_turn=c.state.turn,
            recipient=MinionReference.capture(e))for e in minions(c,(c.player_id,))if e.card_id!=AKAMA)
    def far(c):
        if c.event is None or c.event.kind!='card_drawn'or c.event.player_id!=3-c.player_id:return ()
        e=c.state.entities.get(c.event.target_id)
        if e is None or e.zone!=Zone.HAND or e.controller!=3-c.player_id or local_cost(e)[0]>=10:return ()
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=1),c.source_id),)
    def cross(c):
        if c.event is None or c.event.kind!='spell_cast_started'or c.event.player_id!=3-c.player_id:return ()
        return tuple(Buff(e.id,1,1,c.source_id)for e in minions(c,(c.player_id,)))
    def morshan(c):
        if c.event is None or c.event.kind!='card_played'or c.event.player_id!=3-c.player_id:return ()
        from hs_sim.engine.play_history import play_record
        play=play_record(c.state,dict(c.event.data)['play_id'])
        if play.kind!=CardType.MINION or play.countered:return ()
        return summon(c,GRUNT)
    def freeze_hit(c):
        return(Freeze(c.event.target_id,c.source_id),)if c.event is not None and c.event.source_id==c.source_id and c.event.amount>0 else()
    registry.register_trigger_condition(PREFIX+'own_cast',own_cast)
    bodies={BEARON:bearon,KARGAL:kargal,SAURFANG:saurfang,'damage_others':damage_others,ZOK:zok,
        'chen':lambda c:summon(c,SNOW),'akama':akama,
        ASKARA:lambda c:(AddCostModifier(c.player_id,CostSpec(card_types=(CardType.MINION,)),uses_remaining=2,
            source_id=c.source_id,tribes_any=('draenei',),copy_after_play=True),),
        MALADAAR:lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.CORPSES),uses_remaining=1,
            source_id=c.source_id,expires_turn=c.state.turn),),
        OTHAAR:lambda c:(GenerateFromPool(c.player_id,'constructed.cards',ARCANE,count=3,source_id=c.source_id,
            replacement=False,cost=CostSpec(delta=-2)),)if construction(c.state,c.player_id)is not None else(),
        'backstab':lambda c:(AddToHand(c.player_id,EXISTING[0],c.source_id),),
        FAR:far,CROSS:cross,MORSHAN:morshan,'freeze_hit':freeze_hit}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
