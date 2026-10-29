"""Original Shaman damage, tribe rewards, discovery and existing resource consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Damage,DamageBatch,Heal,InvokeBehavior,Overload
from hs_sim.engine.excavate import Excavate
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,HealingKind,IntrinsicCostSpec,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.previous_turn_spell_costs import CONDITION,HISTORY
from hs_sim.engine.random_split_damage import RandomSplitHealing
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-nature-resources-v1.json'
BATCH_HASH='fbe59807b87c9877167e83192946838f56a177763d68f69fe8b6eb4e5c25f2b1'
ROOTS=('BOT_246','GIL_600','GIL_586','OG_023','DEEP_009','YOP_023','BT_110','DRG_219','WW_080','VAC_329','LOOT_373')
TARGETED=('GIL_600','GIL_586','OG_023','DEEP_009','BT_110','DRG_219','WW_080')
PREFIX='cards.past_shaman_nature_resources.'
NORMALIZATIONS={'BOT_246':{'cost':0},'GIL_600':{'cost':0}}
OVERLOAD={'BOT_246':2,'GIL_600':1}


def make_definition(raw):
    cid=raw['id'];cost=NORMALIZATIONS.get(cid,{}).get('cost',raw['cost']);fields={}
    if (cid not in ROOTS or raw['type']!='SPELL' or raw['collectible']is not True or
            raw['tags'].get('SPELL_SCHOOL')!=4 or type(cost)is not int or
            raw['tags'].get('OVERLOAD',0)!=OVERLOAD.get(cid,0)):
        raise TargetValidationError('Shaman resources require complete original Nature spell roles')
    if cid in NORMALIZATIONS and raw['cost']is not None:
        raise TargetValidationError('Zero-cost evidence normalization changed its original raw scalar')
    if cid in TARGETED:fields['targeting']=TargetSpec()if cid=='WW_080'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid=='BT_110':fields['intrinsic_costs']=(IntrinsicCostSpec(delta=-3,condition=CONDITION,history_profile_id=HISTORY),)
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=cost,on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or d['dependencies']or d['evidence_only']or
            [v['record']['id']for v in d['existing_dependencies']]!=['CORE_LOOT_373','TIME_013']or
            len(d['official_observations'])!=26 or d['numeric_normalizations']!=NORMALIZATIONS or
            len(d['original_shaman_member_ids'])!=71 or any(cid not in d['original_shaman_member_ids']for cid in ROOTS)or
            any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman resources changed complete source roles or claimed partial coverage complete')
    for row in d['cards']+d['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Shaman resources lost a complete original row')
    for ref in d['references']:
        p=(ROOT/ref['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=ref['sha256']:
            raise TargetValidationError('Shaman resources changed a complete source or treasure reference')
    return d


def register_past_shaman_nature_resources(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        if row['record']['id']=='TIME_013':continue
        cid=row['record']['id']
        if canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']:
            raise TargetValidationError('Historical Rain cannot replace its complete existing Core counterpart')
    for row in d['cards']:
        c=make_definition(row['record'])
        if c.id in registry.cards or canonical_digest(asdict(c))!=row['definition_sha256']:
            raise TargetValidationError('Shaman resources cannot replace or alter a complete native face')
        registry._validate_card(c)
        if c.id in registry.pool_cards and registry.pool_card(c.id)!=PoolCard.from_definition(c):
            raise TargetValidationError('Shaman resources changed existing complete metadata')
        prepared.append(c)

    def area(c,amount,enemy=False):
        return(DamageBatch(tuple(Damage(eid,amount,c.source_id,DamageKind.SPELL)
            for p in((3-c.player_id,)if enemy else(1,2))for eid in minions(c,registry,p))),)
    def might(c):
        target=c.state.entities[c.target_id];qualified=has_any_tribe(registry,target,('elemental',))
        return(BuffCapturedMinion(MinionReference.capture(target),2,2,c.source_id),)+((GenerateFromPool(c.player_id,'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,),tribes_any=('elemental',),collectible=True),source_id=c.source_id),)if qualified else())
    def fusion(c):
        n=sum(has_any_tribe(registry,c.state.entities[eid],('totem',))for eid in minions(c,registry,c.player_id))
        return(BuffCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),n,n,c.source_id),)if n else()
    def slide(c):
        p=c.state.players[c.player_id];qualified=p.overload_owed>0 or p.overload_locked>0
        return(*area(c,1,True),)+((InvokeBehavior(PREFIX+'slide_second',c.source_id,c.player_id),)if qualified else())
    def breath(c):
        target=c.state.entities[c.target_id];targets=[target.id]
        held=any(has_any_tribe(registry,c.state.entities[eid],('dragon',))for eid in c.state.players[c.player_id].hand if c.state.entities[eid].kind==CardType.MINION)
        if held:
            board=c.state.players[target.controller].board;i=board.index(target.id);live=set(minions(c,registry,target.controller))
            targets.extend(board[j]for j in(i-1,i+1)if 0<=j<len(board)and board[j]in live)
        return(DamageBatch(tuple(Damage(eid,4,c.source_id,DamageKind.SPELL)for eid in targets)),)
    def gifts(c):
        return tuple(GenerateFromPool(c.player_id,'constructed.cards',q,source_id=c.source_id,cost=CostSpec(delta=-2))for q in
            (PoolQuery(kinds=(CardType.MINION,),tribes_any=('naga',),collectible=True),PoolQuery(kinds=(CardType.SPELL,),collectible=True)))
    bodies={
        'BOT_246':lambda c:area(c,1),
        'GIL_600':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        'GIL_586':might,'OG_023':fusion,
        'DEEP_009':lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL),Excavate(c.player_id,c.source_id)),
        'YOP_023':slide,'slide_second':lambda c:area(c,1,True),
        'BT_110':lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL),),
        'DRG_219':breath,
        'WW_080':lambda c:(Heal(c.target_id,5,c.source_id,HealingKind.SPELL),DiscoverFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),source_id=c.source_id)),
        'VAC_329':gifts,
        'LOOT_373':lambda c:(RandomSplitHealing(c.player_id,c.cast.id,c.source_id,12),),
    }
    for name,body in bodies.items():
        n=OVERLOAD.get(name,0)
        registry.register_behavior(PREFIX+name,lambda c,body=body,n=n:((Overload(c.player_id,n),)if n else())+tuple(body(c)))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
