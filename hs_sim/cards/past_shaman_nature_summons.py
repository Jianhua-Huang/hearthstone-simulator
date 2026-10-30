"""Named Shaman summons, current cost-pool portals and real corrupt forms."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Buff,Damage,DamageBatch,InvokeBehavior,Overload,Transform
from hs_sim.engine.jade import CLASSIC,SummonJadeGolem
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HandProgressSpec,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-nature-summons-v1.json'
BATCH_HASH='3a60c3a7e2c7f7956ff4d99e36bf2df8ea335ea04d9b81cf71608cd25fd13393'
ROOTS=('BOT_451','EX1_248','TID_005','TTN_722','TOY_508','YOD_041','WW_090',
    'CFM_707','WON_082','EX1_246','BT_100','KAR_073','DMF_701')
DEPENDENCIES=('TID_005t','TTN_833t','YOD_041t','WW_090t','DMF_701t')
EXISTING=('BOT_102t','EX1_tk11','hexfrog','CFM_712_t01','CFM_712_t04','CFM_712_t07','CFM_712_t20','TIME_013')
PREFIX='cards.past_shaman_nature_summons.'
OVERLOAD={'BOT_451':1,'EX1_248':1,'TID_005':1,'TTN_722':1,'YOD_041':3,'BT_100':1}
FIXED={'BOT_451':('BOT_102t',2),'EX1_248':('EX1_tk11',2),'TID_005':('TID_005t',2),
    'TTN_722':('TTN_833t',1),'TOY_508':('hexfrog',2),'YOD_041':('YOD_041t',3),'WW_090':('WW_090t',1)}
TARGETED=('TOY_508','CFM_707','WON_082','EX1_246','BT_100','DMF_701','DMF_701t')


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower());fields={}
    if cid not in ROOTS+DEPENDENCIES or raw['collectible']is not(cid in ROOTS):
        raise TargetValidationError('Shaman summons require original complete native face roles')
    if kind==CardType.SPELL:
        if raw['tags'].get('SPELL_SCHOOL')!=4 or raw['tags'].get('OVERLOAD',0)!=OVERLOAD.get(cid,0):
            raise TargetValidationError('Shaman spell lost original Nature/Overload facts')
        fields.update(on_play=PREFIX+cid,spell_school=SpellSchool.NATURE)
        if cid in TARGETED:fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid=='EX1_246'else TargetSpec()
        if cid=='DMF_701':fields.update(keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id='DMF_701t'))
        if cid=='DMF_701t':fields['keywords']=(Keyword.CORRUPTED,)
    elif cid in DEPENDENCIES and kind==CardType.MINION:
        expected={'TID_005t':(4,5,4,Keyword.RUSH),'TTN_833t':(3,3,3,Keyword.RUSH),
            'YOD_041t':(5,5,6,Keyword.TAUNT),'WW_090t':(6,6,6,None)}[cid]
        if (raw['cost'],raw['attack'],raw['health'])!=expected[:3]:raise TargetValidationError('Named Shaman token lost original printed stats')
        fields.update(attack=raw['attack'],health=raw['health'],keywords=(expected[3],)if expected[3]is not None else())
    else:raise TargetValidationError('Unreviewed Shaman native type')
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or
            tuple(v['record']['id']for v in d['dependencies'])!=DEPENDENCIES or
            tuple(v['record']['id']for v in d['existing_dependencies'])!=EXISTING or d['evidence_only']or
            len(d['official_observations'])!=52 or len(d['original_shaman_member_ids'])!=71 or
            any(cid not in d['original_shaman_member_ids']for cid in ROOTS) or
            any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman summons changed a complete source role or claimed partial coverage complete')
    for group in('cards','dependencies','existing_dependencies'):
        for row in d[group]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Shaman summons lost a complete original row')
    path=(ROOT/d['full_union_source_document']).resolve()
    if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Shaman summons changed the original full reference')
    return d


def checked_existing(registry,d):
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if cid=='TIME_013':continue
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Shaman summons changed a complete existing named dependency')
    if (CLASSIC not in registry.jade_families or
            canonical_digest(asdict(registry.jade_families[CLASSIC]))!=d['jade_family']['canonical_sha256']):
        raise TargetValidationError('Shaman Jade spells require the original complete classic artwork profile')


def register_past_shaman_nature_summons(registry):
    d=load_batch();checked_existing(registry,d);prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Shaman summons cannot replace or change a real face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Shaman summons changed complete existing pool metadata')
        prepared.append(card)

    def named(c,cid):
        token,count=FIXED[cid];request=SummonByCard(c.player_id,(SummonEntryMaterial(token),),SummonCause.capture(c))
        return(request,)*count
    def area(c,amount,enemy=False):
        return(DamageBatch(tuple(Damage(eid,amount,c.source_id,DamageKind.SPELL)
            for player in((3-c.player_id,)if enemy else(1,2))for eid in minions(c,registry,player))),)
    def portal(c,cost):
        return(SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=cost,max_cost=cost),source_id=c.source_id,cause=SummonCause.capture(c)),)
    def jade(c):return(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),SummonJadeGolem(c.player_id,c.source_id,cause=SummonCause.capture(c)))
    bodies={cid:(lambda c,cid=cid:named(c,cid))for cid in('BOT_451','EX1_248','TID_005','YOD_041')}
    bodies.update({
        'TTN_722':lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=3,source_id=c.source_id,expires_turn=c.state.turn),*named(c,'TTN_722')),
        'TOY_508':lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),*named(c,'TOY_508')),
        'WW_090':lambda c:(*area(c,6),*named(c,'WW_090')),
        'CFM_707':jade,'WON_082':jade,
        'EX1_246':lambda c:(Transform(c.target_id,'hexfrog'),),
        'BT_100':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),*portal(c,3)),
        'KAR_073':lambda c:(*area(c,1,True),*portal(c,1)),
        'DMF_701':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
        'DMF_701t':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),InvokeBehavior(PREFIX+'corrupt_area',c.source_id,c.player_id)),
        'corrupt_area':lambda c:area(c,2,True),
    })
    for name,body in bodies.items():
        n=OVERLOAD.get(name,0)
        registry.register_behavior(PREFIX+name,lambda c,body=body,n=n:((Overload(c.player_id,n),)if n else())+tuple(body(c)))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
