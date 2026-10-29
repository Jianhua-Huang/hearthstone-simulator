"""Thirteen real Shaman Nature consumers of existing ordinary effects."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.effects import Buff,Damage,DamageBatch,Heal,InvokeBehavior,Overload,Silence
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealingKind,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,GrantCapturedSpellDamage,MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-nature-common-v1.json'
BATCH_HASH='49a7c9c31963e1f6560a59c09b78f1631e30bf9bf844b41746e18e566751ecb8'
ROOTS=('CS2_039','CS2_041','CS2_045','DRG_215','EX1_245','EX1_259','OG_206',
    'SCH_535','UNG_817','ULD_181','TSC_923','DMF_702','ULD_171')
TARGETED=('CS2_039','CS2_041','EX1_245','OG_206','UNG_817','DMF_702')
PREFIX='cards.past_shaman_nature_common.'
NORMALIZATIONS={'CS2_041':{'cost':0},'ULD_171':{'cost':0}}
OVERLOAD={'DRG_215':1,'EX1_259':1,'OG_206':1}


def make_definition(raw):
    cid=raw['id'];cost=NORMALIZATIONS.get(cid,{}).get('cost',raw['cost']);fields={}
    if (cid not in ROOTS or raw['type']!='SPELL' or raw['collectible']is not True or
            raw['tags'].get('SPELL_SCHOOL')!=4 or type(cost)is not int or
            raw['tags'].get('OVERLOAD',0)!=OVERLOAD.get(cid,0)):
        raise TargetValidationError('Shaman common Nature requires complete original spell faces')
    if cid in NORMALIZATIONS and raw['cost']is not None:
        raise TargetValidationError('Shaman zero-cost primary normalization lost its original missing scalar')
    if cid in TARGETED:fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid=='CS2_045':fields['targeting']=TargetSpec(relation='friendly')
    if cid in('SCH_535','UNG_817'):fields['keywords']=(Keyword.LIFESTEAL,)
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=cost,on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or d['dependencies']or d['evidence_only']or
            [v['record']['id']for v in d['existing_dependencies']]!=['TIME_013']or
            len(d['official_observations'])!=28 or d['numeric_normalizations']!=NORMALIZATIONS or
            len(d['original_shaman_member_ids'])!=71 or any(cid not in d['original_shaman_member_ids']for cid in ROOTS) or
            any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman common cohort changed source roles or claimed a partial source complete')
    for group in('cards','existing_dependencies'):
        for row in d[group]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Shaman common cohort lost a complete original row')
    path=(ROOT/d['full_union_source_document']).resolve()
    if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Shaman common cohort changed the original complete reference')
    return d


def register_past_shaman_nature_common(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Shaman common cohort cannot replace or lose a real face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Shaman common cohort changed complete existing metadata')
        prepared.append(card)

    def refs(c,totems=False):
        return tuple(MinionReference.capture(c.state.entities[eid])for eid in minions(c,registry,c.player_id)
            if not totems or has_any_tribe(registry,c.state.entities[eid],('totem',)))
    def area(c,amount,enemy=False):
        return(DamageBatch(tuple(Damage(eid,amount,c.source_id,DamageKind.SPELL)
            for player in((3-c.player_id,)if enemy else(1,2))for eid in minions(c,registry,player))),)
    def healing(c):
        e=c.state.entities[c.target_id];ref=MinionReference.capture(e)
        return(Heal(e.id,e.max_health,c.source_id,HealingKind.SPELL),GrantCapturedKeyword(ref,Keyword.TAUNT,c.source_id))
    def shock(c):
        ref=MinionReference.capture(c.state.entities[c.target_id])
        return(Silence(c.target_id),DamageCapturedMinionGroup((ref,),(1,),c.source_id))
    bodies={
        'CS2_039':lambda c:(GrantCapturedKeyword(MinionReference.capture(c.state.entities[c.target_id]),Keyword.WINDFURY,c.source_id),),
        'CS2_041':healing,
        'CS2_045':lambda c:(Buff(c.target_id,attack=3,source_id=c.source_id,expires_turn=c.state.turn),),
        'DRG_215':lambda c:tuple(BuffCapturedMinion(ref,1,1,c.source_id)for ref in refs(c)),
        'EX1_245':shock,
        'EX1_259':lambda c:area(c,3,True),
        'OG_206':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
        'SCH_535':lambda c:area(c,3),
        'UNG_817':lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL),),
        'ULD_181':lambda c:(*area(c,5),InvokeBehavior(PREFIX+'quake_second',c.source_id,c.player_id)),
        'TSC_923':lambda c:tuple(GrantCapturedSpellDamage(ref,1,c.source_id)for ref in refs(c)),
        'DMF_702':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),Buff(c.state.players[c.player_id].hero_id,attack=3,source_id=c.source_id,expires_turn=c.state.turn)),
        'ULD_171':lambda c:tuple(BuffCapturedMinion(ref,2,0,c.source_id)for ref in refs(c,True)),
        'quake_second':lambda c:area(c,2),
    }
    for name,body in bodies.items():
        n=OVERLOAD.get(name,0)
        registry.register_behavior(PREFIX+name,lambda c,body=body,n=n:
            ((Overload(c.player_id,n),)if n else())+tuple(body(c)))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
