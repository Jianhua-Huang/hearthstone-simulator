"""Real past Nature draws, held progress and complete Treant identities."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_discovery_actions import DiscoverDeckCardAction
from hs_sim.engine.effects import AddToHand, Buff, Draw, InvokeBehavior, Overload
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    HandProgressSpec, Keyword, PlayerEffectSpec, SpellRepeatSpec, TargetSpec,
    TreantBoardMinionCostSpec, TriggerSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.play_history import play_record
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedDeathrattle, MinionReference
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.spell_targets import DamageResidentSpellTarget
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ChooseFromZone
from hs_sim.engine.model import BoardPresenceReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .entry_native_cards import submitted_tribes
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOTS = ('DEEP_026','DMF_058','DRG_314','LOOT_051','MAW_024','MIS_301',
    'REV_311','REV_365','SCH_612','SW_437','TSC_651','WORK_024','WORK_050')
DEPENDENCIES = ('LOOT_051t1','LOOT_051t2','MIS_301t',
    'SCH_612a','SCH_612b','SCH_612t','WORK_024t','WORK_050t')
CHOICES = ('REV_311t','REV_311t2','SCH_612a','SCH_612b')
TOKENS = ('MIS_301t','SCH_612t','WORK_024t')
PREFIX = 'cards.past_nature_draw_growth.'
PROGRAM = PREFIX+'dew_process'
CORE_BODY = 'cards.past_summon_prices.CORE_REV_365'
POLICY = 'cn37-local-past-nature-draw-growth-v1'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-nature-draw-growth-v1.json'
BATCH_HASH = 'd061673af443cb2ce50d792fc870c3bbf8455a3e241b610ef956b9c0a3bd1827'
MINIONS = PoolQuery(kinds=(CardType.MINION,))
SPELLS = PoolQuery(kinds=(CardType.SPELL,))


def make_definition(raw, treant_ids):
    cid=raw['id'];fields={}
    if cid in TOKENS:
        if cid=='WORK_024t':
            fields.update(keywords=(Keyword.TAUNT,), hand_progress=HandProgressSpec('event',
                on_complete=PREFIX+'bear_growth',repeat=True,event='turn_started',condition_id=PREFIX+'owner'))
        return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],
            attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**fields)
    if cid in CHOICES: fields['choice_only']=True
    else: fields['on_play']=CORE_BODY if cid=='REV_365' else PREFIX+cid
    if cid=='DRG_314': fields['board_minion_cost']=TreantBoardMinionCostSpec(tuple(treant_ids))
    if cid in ('LOOT_051','LOOT_051t1','LOOT_051t2','TSC_651'):
        fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid in ('LOOT_051','LOOT_051t1'):
        following='LOOT_051t1' if cid=='LOOT_051' else 'LOOT_051t2'
        fields['hand_progress']=HandProgressSpec('event',3,following,event='armor_gained',
            condition_id=PREFIX+'owner',amount_basis='event_amount',upgrade_cost_policy='clear_local')
    if cid=='TSC_651':
        fields['hand_progress']=HandProgressSpec('event',on_complete=PREFIX+'held_naga',
            event='card_committed',condition_id=PREFIX+'naga')
    if cid in ('WORK_050','WORK_050t'):
        fields['hand_progress']=HandProgressSpec('event',upgrade_card_id=(
            'WORK_050t' if cid=='WORK_050' else 'WORK_050'),event='turn_ended',condition_id=PREFIX+'owner')
    if cid in ('REV_311','SCH_612'):
        branches=(('REV_311t2','发现并召唤牌库随从'),('REV_311t','发现并施放牌库法术')) if cid=='REV_311' else (
            ('SCH_612a','召唤四个树人图腾'),('SCH_612b','召唤四个突袭树人图腾并过载'))
        fields.update(on_play='engine.choose_one',choose_one=ChooseOneSpec(tuple(
            ChooseBranch(key,label,PREFIX+key)for key,label in branches),
            ChooseBranch(cid+':combined','两者兼得',PREFIX+cid+'_combined')))
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
        spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            len(d['existing_dependencies'])!=21 or len(d['evidence_only'])!=15 or
            len(d['official_observations'])!=36 or len(d['complete_druid_Nature_inventory'])!=85 or
            len(d['original_missing_native_ids'])!=19 or not set(ROOTS)<=set(d['original_missing_native_ids']) or
            any(d[k]for k in('new_standard_roots','membership_uses_executable_coverage',
                'source_scope_bound','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Nature draw/growth consumers require their complete original source')
    rows=d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in rows):
        raise TargetValidationError('Nature draw/growth lost a complete original row')
    actual=sorted(x['record']['id']for x in rows if x['record'].get('tags',{}).get('2831')==1)
    if len(actual)!=29 or actual!=d['treant_member_ids']:
        raise TargetValidationError('Nature draws/pricing cropped the complete fixed Treant family')
    return d


def register_past_nature_draw_growth(registry):
    d=load_batch();family=frozenset(d['treant_member_ids'])
    for row in d['existing_dependencies']:
        cid=row['record']['id'];meta=registry.pool_cards.get(cid)
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256'] or
                (canonical_digest(asdict(meta))if meta is not None else None)!=row['pool_card_sha256']):
            raise TargetValidationError('Nature draws changed an existing complete Treant/Convoke identity')
    prepared=[]
    for row in d['cards']+d['dependencies']:
        cid=row['record']['id']
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Nature draws cannot replace an existing identity: '+cid)
        card=make_definition(row['record'],d['treant_member_ids'])
        if canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Nature draw/growth differs from its complete reviewed face')
        prepared.append(card)
    registry.behavior(CORE_BODY)

    def owner(c):return c.event is not None and c.event.player_id==c.player_id

    def naga(c):
        if c.event is None or c.event.kind!='card_committed':
            raise ResolutionError('Held Naga qualification requires its original committed hand play')
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Held Naga qualification lost its original committed play identity')
        return (record.player_id==c.player_id and record.kind==CardType.MINION and
            record.source_id!=c.source_id and submitted_tribes(record).matches_any(('naga',)))

    def fixed(c,token,count,*,rush=False):
        material=SummonEntryMaterial(token,keywords=(Keyword.RUSH,)if rush else ())
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(material,),cause)for _ in range(count))

    def treant_draw(c):
        count=sum(e.kind==CardType.MINION and e.card_id in family and
            registry.card(e.card_id).interactable is None for i in c.state.players[c.player_id].board
            for e in (c.state.entities[i],))
        return (Draw(c.player_id,count,c.source_id),)if count else ()

    def runic_rush(c):return (*fixed(c,'SCH_612t',4,rush=True),Overload(c.player_id,2))

    def nightshade(c,kind):return (DiscoverDeckCardAction(c.player_id,kind,SummonCause.capture(c)),)

    def kelp(c):
        ability=progress_ability(c.source)
        bonus=ability is not None and ability.progress_completions>0
        return (DamageResidentSpellTarget(BoardPresenceReference.capture(c.state,c.target_id),c.source_id,4),)+(
            (Buff(c.state.players[c.player_id].hero_id,attack=4,source_id=c.source_id,expires_turn=c.state.turn),)
            if bonus else ())

    def dew(c):
        if c.event is None or c.event.kind!='turn_started' or c.event.player_id not in(1,2):
            raise ResolutionError('Dew Process requires an actual turn-start event')
        return (Draw(c.event.player_id,1,c.source_id),)

    bodies={
        'DEEP_026':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.DECK,MINIONS,
            operation='take',distinct='entity',source_id=c.source_id,discovery=True,
            selected_reward='heal_hero_by_local_cost'),),
        'DMF_058':lambda c:(AddSpellRepeatModifier(c.player_id,SpellRepeatSpec(2,'any'),c.source_id,
            uses=1,expires_turn=c.state.turn,automatic=True),),
        'DRG_314':lambda c:(Draw(c.player_id,2,c.source_id),),
        'MAW_024':lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),),
        'MIS_301':lambda c:(*fixed(c,'MIS_301t',1),InvokeBehavior(PREFIX+'treant_draw',c.source_id,c.player_id)),
        'treant_draw':treant_draw,
        'REV_311t2':lambda c:nightshade(c,CardType.MINION),
        'REV_311t':lambda c:nightshade(c,CardType.SPELL),
        'REV_311_combined':lambda c:(*nightshade(c,CardType.MINION),*nightshade(c,CardType.SPELL)),
        'SCH_612a':lambda c:fixed(c,'SCH_612t',4),
        'SCH_612b':runic_rush,
        'SCH_612_combined':lambda c:(*fixed(c,'SCH_612t',4),*runic_rush(c)),
        'SW_437':lambda c:tuple(GrantCapturedDeathrattle(MinionReference.capture(c.state.entities[i]),
            PREFIX+'compost_draw',c.source_id)for i in minions(c,registry,c.player_id)),
        'compost_draw':lambda c:(Draw(c.player_id,1,c.source_id),),
        'TSC_651':kelp,
        'held_naga':lambda c:(),
        'WORK_024':lambda c:tuple(AddToHand(c.player_id,'WORK_024t',c.source_id)for _ in range(2)),
        'bear_growth':lambda c:(BuffStoredCard(CardReference.capture(c.source),1,1,c.source_id),),
        'WORK_050':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(MINIONS),)*2,
            DrawGroupReward('buff_all',2)),),
        'WORK_050t':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(SPELLS),)*2,
            DrawGroupReward('cost_original_spells',1)),),
        'dew':dew,
    }
    for cid,amount in zip(('LOOT_051','LOOT_051t1','LOOT_051t2'),(2,4,6)):
        bodies[cid]=lambda c,amount=amount:(DamageResidentSpellTarget(
            BoardPresenceReference.capture(c.state,c.target_id),c.source_id,amount),)
    registry.register_trigger_condition(PREFIX+'owner',owner)
    registry.register_trigger_condition(PREFIX+'naga',naga)
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,'MAW_024',
        triggers=(TriggerSpec('turn_started',PREFIX+'dew'),)))
