"""Complete named rewards and their real physical/turn/history consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.reference_inputs import reference_path
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.deck_exchange import SwapPlayerDecks,TakeRandomDeckMinion
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.destruction_resources import DestroyMinionsForMill
from hs_sim.engine.effects import (AddToHand,Buff,Damage,DamageBatch,Draw,EquipWeapon,GrantKeyword,Heal,
    ModifyWeapon,ReturnToHand,Destroy)
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,EndTurnSpec,EquippedWeaponReference,
    HealingKind,Keyword,Rarity,TargetSpec,TimedKeywordSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerateFromCandidates,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.spell_history import spell_history_candidates
from hs_sim.engine.spell_source_costs import SpellSourceCostObserverProfile
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.weapon_kill_memory import PROFILE as WEAPON_MEMORY,validate_link
from hs_sim.engine.zones import AddToDeck,CardReference,DestroyStoredBatch,DestroyStoredCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-fixed-rewards-turns-v1.json'
BATCH_HASH='a92a8199f60d5bb7b170819c9351269254d49d3c447f6eb69738dc06082bac48'
XARIL,KING,ARFUS,MEDIVH,OAKHEART,ALANNA,TEMPORUS,TOGWAGGLE,ELISE,RIN=ROOTS=(
    'OG_080','ICC_314','ICC_854','KAR_097','LOOT_521','LOOT_535','LOOT_538','LOOT_541','LOE_079','LOOT_415')
TOXINS=('OG_080b','OG_080f','OG_080d','OG_080c','OG_080e')
DRAW_TOXIN,FIRE_TOXIN,ATTACK_TOXIN,RETURN_TOXIN,STEALTH_TOXIN=TOXINS
REWARDS=('ICC_314t5','ICC_314t4','ICC_314t6','ICC_314t8','ICC_314t7','ICC_314t3','ICC_314t2','ICC_314t1')
COIL,GRIP,OBLITERATE,DECAY,SHELL,PACT,ARMY,FROSTMOURNE=REWARDS
ATIESH,DRAGON,RANSOM,MAP,MONKEY=('KAR_097t','LOOT_535t','LOOT_541t','LOE_019t','LOE_019t2')
SEALS=tuple('LOOT_415t'+str(i)for i in range(1,6))
AZARI='LOOT_415t6';HOUNDS=tuple(cid+'t'for cid in SEALS)
DEPENDENCIES=(*TOXINS,*REWARDS,ATIESH,DRAGON,RANSOM,MAP,MONKEY,*SEALS,AZARI,*HOUNDS)
EVIDENCE=('MIS_701','OG_080ae','OG_080de','OG_080ee','ICC_314t1e','ICC_314t7e')
PREFIX='cards.past_fixed_rewards_turns.'
POOL='constructed.cards'
LEGENDARY=PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,))


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower())
    if cid not in ROOTS+DEPENDENCIES or kind not in(CardType.MINION,CardType.SPELL,CardType.WEAPON):
        raise TargetValidationError('Fixed rewards require their complete original physical faces')
    fields={}
    if cid in(XARIL,MEDIVH,OAKHEART,ALANNA,TEMPORUS,TOGWAGGLE,ELISE,MONKEY,AZARI):fields['battlecry']=PREFIX+cid
    if cid in(XARIL,ARFUS,RIN,FROSTMOURNE):fields['deathrattle']=PREFIX+cid
    if cid in(KING,RIN,MONKEY):fields['keywords']=(Keyword.TAUNT,)
    if cid==KING:fields['triggers']=(TriggerSpec('turn_ended',PREFIX+KING,EndTurnSpec()),)
    if cid==ATIESH:fields['triggers']=(TriggerSpec('spell_cast_finished',PREFIX+ATIESH),)
    if cid==FROSTMOURNE:fields['native_deathrattle']=WEAPON_MEMORY
    if kind==CardType.SPELL:fields['on_play']=PREFIX+cid
    if cid in(FIRE_TOXIN,COIL):fields['targeting']=TargetSpec()
    if cid in(ATTACK_TOXIN,OBLITERATE):fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid in(RETURN_TOXIN,STEALTH_TOXIN):fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']if kind in(CardType.MINION,CardType.WEAPON)else 0,
        health=raw['health']if kind==CardType.MINION else 0,durability=raw['health']if kind==CardType.WEAPON else 0,
        spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL'))if kind==CardType.SPELL else None,
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['existing_dependencies']or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=80 or
            tuple(d['fixed_Toxin_ids'])!=TOXINS or tuple(d['fixed_Death_Knight_ids'])!=REWARDS or
            d['fixed_Toxin_weights']!=[1]*5 or d['fixed_Death_Knight_weights']!=[1]*8 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Fixed reward source lost complete original roles or open boundaries')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Changed complete original fixed reward row')
    for entry in d['retained_documents'].values():
        p=(reference_path(entry['path'], root=ROOT)).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Changed original full fixed reward reference')
    ref=json.loads((reference_path(d['retained_documents']['past']['path'], root=ROOT)).read_text(encoding='utf8'))
    rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if ref['candidate_ids']!=d['original_candidate_ids']or len(ref['candidate_ids'])!=732 or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped original complete past source')
    return d


def register_past_fixed_rewards_turns(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Fixed rewards cannot replace or change a complete physical face')
        registry._validate_card(card);prepared.append(card)
    def reward(c,ids):return(GenerateFromCandidates(c.player_id,ids,c.source_id),)
    def atiesh(c):
        cast=c.cast
        if cast is None or cast.player_id!=c.player_id or not cast.completed or cast.failure is not None:return()
        e=c.source
        if e.zone!=Zone.WEAPON or not e.active or e.durability<=0 or e.doomed or c.state.players[c.player_id].weapon_id!=e.id:return()
        if cast.source_cost is None:raise TargetValidationError('Atiesh lost original actual spell-cost quote')
        cost=cast.source_cost.amount;ref=EquippedWeaponReference.capture(e)
        return(GenerateFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost),
            source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),ModifyWeapon(ref,durability=-1,source_id=c.source_id))
    def alanna(c):
        rows=spell_history_candidates(c.state,registry,c.player_id,source_id=c.source_id)
        if any(row.source_cost is None for row in rows):raise TargetValidationError('Alanna lost complete actual spell-cost history')
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(DRAGON),),SummonCause.capture(c))for row in rows if row.source_cost.amount>=5)
    def references(c,player,zone):
        return tuple(CardReference.capture(c.state.entities[eid])for eid in getattr(c.state.players[player],zone.value))
    def monkey(c):return tuple(TransformStoredFromPool(ref,POOL,LEGENDARY,c.source_id)
        for zone in(Zone.HAND,Zone.DECK)for ref in references(c,c.player_id,zone))
    def army(c):
        cards=references(c,c.player_id,Zone.DECK)[:5];cause=SummonCause.capture(c);work=[]
        for ref in cards:
            if registry.card(ref.card_id).kind==CardType.MINION:work.append(SummonStoredCard(ref,c.player_id,cause=cause))
            # A successful physical summon retired this reference; a full board
            # still removes the original card. Neither branch is a draw.
            work.append(DestroyStoredCard(ref,c.source_id))
        return tuple(work)
    def pact(c):
        if c.cast is None:raise TargetValidationError('Doom Pact requires its actual original CAST')
        return(DestroyMinionsForMill(c.player_id,c.source_id,c.cast.id),)
    def frostmourne(c):
        memory=None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
        if memory is None or memory.spec!=WEAPON_MEMORY:raise TargetValidationError('Frostmourne requires its original native killing-blow memory')
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(validate_link(c.state,registry,link).card_id),),SummonCause.capture(c))for link in memory.weapon_kills)
    def coil(c):
        e=c.state.entities[c.target_id]
        return(Heal(e.id,5,c.source_id,HealingKind.SPELL),)if e.controller==c.player_id else(Damage(e.id,5,c.source_id,DamageKind.SPELL),)
    def obliterate(c):
        health=max(0,c.state.entities[c.target_id].health)
        return(Destroy(c.target_id,c.source_id),Damage(c.state.players[c.player_id].hero_id,health,c.source_id,DamageKind.SPELL))
    def shield(c):
        refs=tuple(MinionReference.capture(c.state.entities[eid])for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].kind==CardType.MINION and c.state.entities[eid].active and c.state.entities[eid].health>0 and not c.state.entities[eid].doomed)
        return tuple(work for ref in refs for work in(BuffCapturedMinion(ref,2,2,c.source_id),GrantCapturedKeyword(ref,Keyword.ELUSIVE,c.source_id)))
    bodies={XARIL:lambda c:reward(c,TOXINS),KING:lambda c:reward(c,REWARDS),ARFUS:lambda c:reward(c,REWARDS),
        MEDIVH:lambda c:(EquipWeapon(c.player_id,ATIESH),),ATIESH:atiesh,
        OAKHEART:lambda c:tuple(SummonFromZone(c.player_id,query=PoolQuery(kinds=(CardType.MINION,),attack_equals=n),
            source_id=c.source_id,cause=SummonCause.capture(c),attack_basis='current')for n in(1,2,3)),
        ALANNA:alanna,TEMPORUS:lambda c:(QueueTurns((3-c.player_id,3-c.player_id,c.player_id,c.player_id),c.source_id),),
        TOGWAGGLE:lambda c:(SwapPlayerDecks(c.source_id),AddToHand(3-c.player_id,RANSOM,c.source_id)),RANSOM:lambda c:(SwapPlayerDecks(c.source_id),),
        ELISE:lambda c:shuffled(c,(AddToDeck(c.player_id,MAP,source_id=c.source_id),)),
        MAP:lambda c:(*shuffled(c,(AddToDeck(c.player_id,MONKEY,source_id=c.source_id),)),Draw(c.player_id,1,c.source_id)),MONKEY:monkey,
        RIN:lambda c:(AddToHand(c.player_id,SEALS[0],c.source_id),),
        AZARI:lambda c:(DestroyStoredBatch(references(c,3-c.player_id,Zone.DECK),c.source_id),),
        DRAW_TOXIN:lambda c:(Draw(c.player_id,1,c.source_id),),FIRE_TOXIN:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        ATTACK_TOXIN:lambda c:(Buff(c.target_id,3,0,c.source_id),),RETURN_TOXIN:lambda c:(ReturnToHand(c.target_id,cost=CostSpec(delta=-2)),),
        STEALTH_TOXIN:lambda c:(GrantKeyword(c.target_id,Keyword.STEALTH,c.source_id,duration=TimedKeywordSpec(Keyword.STEALTH)),),
        COIL:coil,GRIP:lambda c:(TakeRandomDeckMinion(c.player_id,3-c.player_id,c.source_id),),OBLITERATE:obliterate,
        DECAY:lambda c:(DamageBatch(tuple(Damage(eid,3,c.source_id,DamageKind.SPELL)for eid in
            (c.state.players[3-c.player_id].hero_id,*c.state.players[3-c.player_id].board)
            if c.state.entities[eid].is_character and c.state.entities[eid].active)),),
        SHELL:shield,PACT:pact,ARMY:army,FROSTMOURNE:frostmourne}
    for i,cid in enumerate(SEALS):
        follow=SEALS[i+1]if i<4 else AZARI;token=HOUNDS[i]
        bodies[cid]=lambda c,follow=follow,token=token:(SummonByCard(c.player_id,(SummonEntryMaterial(token),),SummonCause.capture(c)),AddToHand(c.player_id,follow,c.source_id))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_spell_source_cost_observer(SpellSourceCostObserverProfile(ATIESH,school=None))
    registry.register_spell_source_cost_observer(SpellSourceCostObserverProfile(ALANNA,school=None,purpose='history_count'))
