"""Original Shaman cost-tier/Legendary transformations and two Joust heals."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.cross_zone import LEGENDARY_BOARD_QUERY,MinionScope,TransformMinionFromPool,TransformMinionsInZones
from hs_sim.engine.effects import Heal
from hs_sim.engine.joust import Joust,joust_result
from hs_sim.engine.model import CardDefinition,CardType,HandRepeatSpec,HealingKind,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-transforms-joust-v1.json'
BATCH_HASH='363fc224f9acf7cfc3619861ec788b1ef75b92f81a1453f633faadb22417e479'
ROOTS=('BOT_245','CFM_696','DAL_071','LOOT_504','OG_027','REV_924','YOD_020','AT_048','WON_320')
TARGETED=('DAL_071','LOOT_504','YOD_020','AT_048','WON_320')
NORMALIZATIONS={'DAL_071':{'cost':0}}
PREFIX='cards.past_shaman_transforms_joust.'
BOARD=MinionScope(zones=(Zone.BOARD,))


def make_definition(raw):
    cid=raw['id'];cost=NORMALIZATIONS.get(cid,{}).get('cost',raw['cost']);fields={}
    if cid not in ROOTS or raw['type']!='SPELL' or not raw['collectible']or raw['tags'].get('SPELL_SCHOOL')!=4 or type(cost)is not int:
        raise TargetValidationError('Shaman transformation/Joust requires complete original Nature spell faces')
    if cid=='DAL_071'and raw['cost']is not None:raise TargetValidationError('Mutate lost original zero-cost primary normalization')
    if cid in TARGETED:
        fields['targeting']=TargetSpec()if cid in('AT_048','WON_320')else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'if cid in('DAL_071','LOOT_504')else'any')
    if cid=='LOOT_504':
        if raw['tags'].get('ECHO')!=1:raise TargetValidationError('Original Unstable Evolution lost printed Echo')
        fields['keywords']=(Keyword.ECHO,)
        fields['hand_repeat']=HandRepeatSpec()
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=cost,on_play=PREFIX+cid,spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or tuple(v['record']['id']for v in d['cards'])!=ROOTS or
            d['dependencies']or d['evidence_only']or [v['record']['id']for v in d['existing_dependencies']]!=['TIME_013']or
            len(d['official_observations'])!=20 or d['numeric_normalizations']!=NORMALIZATIONS or
            len(d['original_shaman_member_ids'])!=71 or any(cid not in d['original_shaman_member_ids']for cid in ROOTS)or
            any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman transformation/Joust changed full source roles or claimed partial support complete')
    for row in d['cards']+d['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Transformation/Joust lost a complete original row')
    p=(ROOT/d['full_union_source_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Transformation/Joust changed the original full union reference')
    return d


def register_past_shaman_transforms_joust(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Transformation/Joust cannot replace or change a complete face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):raise TargetValidationError('Transformation/Joust changed existing metadata')
        prepared.append(card)
    def group(c,player,delta):return TransformMinionsInZones(player,'constructed.cards',delta,scope=BOARD,source_id=c.source_id)
    def one(c,delta):return(TransformMinionFromPool(MinionReference.capture(c.state.entities[c.target_id]),'constructed.cards',delta,source_id=c.source_id),)
    def heal(c):
        result=joust_result(c.event)
        if result is None or result.player_id!=c.player_id:raise TargetValidationError('Healing Wave requires its original accepted comparison')
        return(Heal(c.target_id,16 if result.won else 8,c.source_id,HealingKind.SPELL),)
    bodies={
        'BOT_245':lambda c:(TransformMinionsInZones(c.player_id,'constructed.cards',scope=BOARD,query=LEGENDARY_BOARD_QUERY,cost_basis='none',source_id=c.source_id),),
        'CFM_696':lambda c:(group(c,3-c.player_id,-1),),
        'DAL_071':lambda c:one(c,1),'LOOT_504':lambda c:one(c,1),
        'OG_027':lambda c:(group(c,c.player_id,1),),
        'REV_924':lambda c:(group(c,3-c.player_id,-1),group(c,c.player_id,1)),
        'YOD_020':lambda c:one(c,3),
        'AT_048':lambda c:(Joust(c.player_id,PREFIX+'heal',c.source_id,c.target_id),),
        'WON_320':lambda c:(Joust(c.player_id,PREFIX+'heal',c.source_id,c.target_id),),
        'heal':heal,
    }
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
