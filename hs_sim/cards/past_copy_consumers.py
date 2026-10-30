"""Actual hand, board and draw copies through existing immutable recipes."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.choose_one import normalize
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial,CopyEntryMaterial
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.minion_type_history import match_minion_type_plays
from hs_sim.engine.model import (CardDefinition,CardType,ChooseBranch,ChooseOneSpec,CostSpec,
    SpellSchool,SummonStats,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.tribes import has_any_tribe,tribe_state
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-copy-consumers-v1.json'
BATCH_HASH='fb51096b318f8e5745a35fabcac5d714b497bbbf3262b1a0eeb7fdda04b3bfbf'
VOONE,LADY,ZAI,PIP,VORAZJ,FREYA,ARUGAL,DORIAN,NEW_DORIAN,ROCK=ROOTS=(
    'TRL_328','RLK_713','DMF_231','WW_394','OG_316','TTN_940','GIL_691','GIL_620','MIS_026','ETC_121')
BOARD_OPTION,HAND_OPTION=DEPENDENCIES=('TTN_940a','TTN_940b')
PREFIX='cards.past_copy.'
TYPES=tuple(sorted(('beast','demon','dragon','draenei','elemental','mech','murloc','naga','pirate','quilboar','totem','undead')))


def make_definition(raw):
    cid=raw['id'];fields={}
    if cid in DEPENDENCIES:
        if raw['type']!='SPELL'or raw['collectible']:raise TargetValidationError('Copy choice requires its original nonphysical spell face')
        return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],choice_only=True,
            metadata=metadata_from_record(raw),spell_school=SpellSchool.NATURE if raw['tags'].get('SPELL_SCHOOL')==4 else None)
    if cid not in ROOTS or raw['type']!='MINION'or not raw['collectible']:
        raise TargetValidationError('Past copy consumer requires its complete original minion face')
    if cid in(ARUGAL,DORIAN,NEW_DORIAN):fields['triggers']=(TriggerSpec('card_drawn',PREFIX+cid),)
    elif cid==LADY:fields['deathrattle']=PREFIX+cid
    elif cid==FREYA:
        if raw['tags'].get('CHOOSE_ONE')!=1:raise TargetValidationError('Freya lost her actual Choose One declaration')
        fields['choose_one']=ChooseOneSpec((ChooseBranch(HAND_OPTION,'未来之种',PREFIX+HAND_OPTION),
            ChooseBranch(BOARD_OPTION,'生命守卫',PREFIX+BOARD_OPTION)),ChooseBranch('both','两者兼得',PREFIX+'both'))
    else:fields['battlecry']=PREFIX+cid
    return normalize(CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(d['complete_local_minion_type_universe'])!=TYPES or len(d['official_observations'])!=22 or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past copy batch lost complete identities, roles or evidence boundaries')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[group]):
            raise TargetValidationError('Past copy changed a complete original raw record')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Past copy changed its complete original reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Past copy cropped full original candidate membership')
    return d


def register_past_copy_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Past copy changed a complete shared dependency')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                (None if card.choice_only else canonical_digest(asdict(PoolCard.from_definition(card))))!=row['pool_card_sha256']):
            raise TargetValidationError('Past copy cannot replace or alter a physical or choice face')
        registry._validate_card(card);prepared.append(card)
    def copy_hand(c,selection):
        cards=tuple(c.state.entities[i]for i in tuple(c.state.players[c.player_id].hand))
        materials=tuple(CapturedCardCopyMaterial.capture(c.state,e)for e in selection(c,cards))
        return tuple(CopyCard(m,c.player_id,mode='current',source_id=c.source_id)for m in materials)
    def dragon(c,cards):return tuple(e for e in cards if e.kind==CardType.MINION and has_any_tribe(registry,e,('dragon',)))
    def frost(c,cards):return tuple(e for e in cards if e.kind==CardType.SPELL and registry.card(e.card_id).spell_school==SpellSchool.FROST)
    def edges(c,cards):return cards if len(cards)<2 else(cards[0],cards[-1])
    def one_cost(c,cards):return tuple(e for e in cards if quote_unselected_cost(c.state,registry,e).amount==1)
    def menagerie(c,cards):
        facts=tuple((e.id,tribe_state(registry,e))for e in cards if e.kind==CardType.MINION)
        selected={eid for eid,_ in match_minion_type_plays(facts,TYPES)}
        return tuple(e for e in cards if e.id in selected)
    def board(c,stats=None):
        materials=tuple(CopyEntryMaterial.capture(c.state,c.state.entities[eid],'remembered_copy','current',stats,
            registry=registry,player_id=c.player_id)for eid in minions(c,registry,c.player_id)if eid!=c.source_id)
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(material,),cause)for material in materials)
    def drawn(c):
        row=draw_record(c.state,dict(c.event.data)['draw_id'])
        if(row.entity_id,row.player_id)!=(c.event.target_id,c.event.player_id)or row.outcome not in('hand','cast'):
            raise ResolutionError('Past minion copy lost its actual original draw')
        if row.player_id!=c.player_id or not living_source(c):return()
        if registry.card(row.card_id).kind!=CardType.MINION:return()
        e=c.state.entities[row.entity_id]
        if e.controller!=row.player_id or e.card_id!=row.card_id and row.transformation is None:
            raise ResolutionError('Past minion copy lost its original drawn face')
        if c.source.card_id==DORIAN:
            if row.outcome!='hand':raise ResolutionError('Dorian auto-cast minion copy needs an explicit entry policy')
            material=CopyEntryMaterial.capture(c.state,e,'stored_copy','current',SummonStats(1,1),registry=registry,player_id=c.player_id)
            return(SummonByCard(c.player_id,(material,),SummonCause.capture(c)),)
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,e),c.player_id,
            mode='current'if row.outcome=='hand'else'base',source_id=c.source_id,
            stats=SummonStats(1,1)if c.source.card_id==NEW_DORIAN else None,
            cost=CostSpec(set_to=1)if c.source.card_id==NEW_DORIAN else None),)
    bodies={VOONE:lambda c:copy_hand(c,dragon),LADY:lambda c:copy_hand(c,frost),ZAI:lambda c:copy_hand(c,edges),
        PIP:lambda c:copy_hand(c,one_cost),ROCK:lambda c:copy_hand(c,menagerie),
        VORAZJ:lambda c:board(c,SummonStats(1,1)),HAND_OPTION:lambda c:copy_hand(c,lambda c,cards:cards),
        BOARD_OPTION:board,'both':lambda c:(*copy_hand(c,lambda c,cards:cards),*board(c))}
    for cid in(ARUGAL,DORIAN,NEW_DORIAN):bodies[cid]=drawn
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
