"""Original power-draw cost, Pirate pricing and real conditional/choice cards."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.choose_one import normalize
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.draw_transformations import hand_reference
from hs_sim.engine.effects import Damage,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardMinionCostSpec,CardDefinition,CardType,ChooseBranch,ChooseOneSpec,
    CostSpec,DamageKind,Keyword,Rarity,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion,DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import TribeState,has_any_tribe
from hs_sim.engine.zones import ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/classic-power-pirate-targets-v1.json'
BATCH_HASH='20194baf47be57e046490e723feb0fbf27ed52f7ef98bf927033264116d334fb'
FIZZLE,KRAGG,REND,GORMOK,CENARIUS=ROOTS=('AT_027','AT_070','BRM_029','AT_122','EX1_573')
TREANT,=DEPENDENCIES=('EX1_573t',)
BUFF_OPTION,SUMMON_OPTION,BUFF_ENCHANT='EX1_573a','EX1_573b','EX1_573ae'
PREFIX='cards.classic_power_pirate.'
PIRATE_PROFILE='cost.board-friendly-pirates-v1'


def make_definition(raw):
    cid=raw['id'];fields={}
    if(cid not in(*ROOTS,*DEPENDENCIES)or raw['type']!='MINION'or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Classic consumers require their complete original minion faces')
    if cid in ROOTS and(not raw['collectible']or raw['tags'].get('RARITY')!=5):
        raise TargetValidationError('Classic parent lost its original Legendary role')
    if cid==FIZZLE:fields['triggers']=(TriggerSpec('card_drawn',PREFIX+'fizzle'),)
    elif cid==KRAGG:
        if raw['tags'].get('CHARGE')!=1:raise TargetValidationError('Kragg lost its printed Charge')
        fields.update(keywords=(Keyword.CHARGE,),board_minion_cost=BoardMinionCostSpec('friendly',PIRATE_PROFILE))
    elif cid in(REND,GORMOK):
        fields.update(battlecry=PREFIX+cid,targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,)if cid==REND else(Zone.HERO,Zone.BOARD),
            kinds=(CardType.MINION,)if cid==REND else(CardType.HERO,CardType.MINION)),
            target_rule=PREFIX+('dragon_legendary'if cid==REND else'four_others'))
    elif cid==CENARIUS:
        if raw['tags'].get('CHOOSE_ONE')!=1:raise TargetValidationError('Cenarius lost its real Choose One declaration')
        fields['choose_one']=ChooseOneSpec((ChooseBranch(BUFF_OPTION,'其他随从+2/+2',PREFIX+'cenarius_buff'),
            ChooseBranch(SUMMON_OPTION,'召唤两棵嘲讽树人',PREFIX+'cenarius_treants')),
            ChooseBranch('both','两项效果',PREFIX+'cenarius_both'))
    else:
        if raw['collectible']or raw['tags'].get('TAUNT')!=1:raise TargetValidationError('Cenarius requires its real Taunt Treant')
        fields['keywords']=(Keyword.TAUNT,)
    return normalize(CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-classic-power-pirate-targets-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['existing_dependencies']]!=['HERO_07bp','TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701',BUFF_OPTION,SUMMON_OPTION,BUFF_ENCHANT]or
            len(d['official_observations'])!=16 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Classic consumers lost complete source identities, choices or roles')
    for key in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[key]):
            raise TargetValidationError('Classic consumers changed a complete original row')
    treant=d['dependencies'][0]['record']
    faces=[x['face']for x in d['official_observations']if x['card_id']==CENARIUS]
    if len(faces)!=2 or any(f['childIds']!=[treant['dbf_id']]for f in faces):
        raise TargetValidationError('Cenarius lost its actual complete named child')
    for entry in d['retained_documents'].values():
        p=(ROOT/entry['path']).resolve()
        if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:
            raise TargetValidationError('Classic consumers changed a complete retained reference')
    if d['retained_documents']['full_reference']!={'path':d['full_reference_document'],'sha256':d['full_reference_sha256']}:
        raise TargetValidationError('Classic consumers lost their exact complete reference binding')
    ref=json.loads((ROOT/d['full_reference_document']).read_text(encoding='utf8'));full={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=full[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Classic consumers cropped the complete original past domain')
    return d


def register_classic_power_pirate_targets(registry):
    d=load_batch();prepared=[]
    dependency=next(x for x in d['existing_dependencies']if x['record']['id']=='HERO_07bp')
    if canonical_digest(asdict(registry.card('HERO_07bp')))!=dependency['definition_sha256']:
        raise TargetValidationError('Wilfred requires the complete unchanged actual Life Tap dependency')
    registry.behavior(registry.card('HERO_07bp').on_use)
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Classic consumer cannot replace or alter an existing face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Classic consumer changed existing complete metadata')
        prepared.append(card)
    def own(c):return next(p for p in c.observation['players']if p['id']==c.player_id)
    def public_dragon(c):
        for card in own(c)['hand']:
            if card.get('kind')!='minion'or card.get('ref')==c.source['ref']:continue
            tribes=card.get('tribes')
            if tribes is None:raise UnsupportedDefinitionError('Unknown original held minion tribes')
            if TribeState(tuple(sorted(tribes)),tuple(sorted(card.get('tribes_excluded',())))).matches_any(('dragon',)):return True
        return False
    def legendary(card_id):
        meta=registry.card(card_id).metadata
        if meta is None or meta.rarity is None:raise UnsupportedDefinitionError('Unknown original minion rarity')
        return meta.rarity==Rarity.LEGENDARY
    def four_others(c):
        return sum(card.get('kind')=='minion'and card.get('ref')!=c.source['ref']and
            'interactable'not in card and'passive_object'not in card for card in own(c)['board'])>=4
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'dragon_legendary','current-own-hand-printed-target-v1'),
        lambda c:public_dragon(c)and legendary(c.target['card_id']))
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'four_others','current-four-other-ordinary-minions-v1'),four_others)
    def held_dragon(c):
        return any(e.kind==CardType.MINION and eid!=c.source_id and has_any_tribe(registry,e,('dragon',))
            for eid in c.state.players[c.player_id].hand for e in(c.state.entities[eid],))
    def others(c):
        return tuple(eid for eid in c.state.players[c.player_id].board if eid!=c.source_id and
            c.state.entities[eid].kind==CardType.MINION and registry.card(c.state.entities[eid].card_id).interactable is None)
    def rend(c):
        if c.target_id is None or not held_dragon(c):return()
        e=c.state.entities[c.target_id]
        return(DestroyCapturedMinion(MinionReference.capture(e),c.source_id),)if(
            e.zone==Zone.BOARD and e.active and not e.doomed and e.health>0 and legendary(e.card_id))else()
    def gormok(c):
        return(Damage(c.target_id,4,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None and len(others(c))>=4 else()
    def fizzle(c):
        row=draw_record(c.state,dict(c.event.data)['draw_id'])
        if(row.source_id,row.entity_id,row.player_id)!=(c.event.source_id,c.event.target_id,c.event.player_id):
            raise ResolutionError('Wilfred lost its original physical draw receipt')
        if row.player_id!=c.player_id or not living_source(c):return()
        powers=[p for p in c.state.hero_power_history if(p.source_id,p.player_id,p.turn,p.action)==
            (row.source_id,row.player_id,row.turn,row.action)and not p.interrupted and p.failure is None]
        if not powers:return()
        ref=hand_reference(c.state,row)
        return(ModifyStoredCost(ref,CostSpec(set_to=0),c.source_id),)if ref is not None else()
    def cenarius_buff(c):
        return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[eid]),2,2,c.source_id)
            for eid in minions(c,registry,c.player_id)if eid!=c.source_id)
    def cenarius_treants(c):
        board=c.state.players[c.player_id].board
        index=board.index(c.source_id)if c.source_id in board else None
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(TREANT),),cause,position=pos)
            for pos in((None,None)if index is None else(index+1,index)))
    def cenarius_both(c):
        return(*cenarius_treants(c),InvokeBehavior(PREFIX+'cenarius_buff',c.source_id,c.player_id,c.target_id,
            None if c.play is None else c.play.id))
    bodies={'fizzle':fizzle,REND:rend,GORMOK:gormok,'cenarius_buff':cenarius_buff,
        'cenarius_treants':cenarius_treants,'cenarius_both':cenarius_both}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
