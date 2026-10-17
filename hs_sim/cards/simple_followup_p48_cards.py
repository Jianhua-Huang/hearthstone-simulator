"""Original health results, physical hands and committed-history consumers."""
import json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.effects import CopyMinion,Damage,DamageBatch,Draw,GainArmor,InvokeBehavior,LoseArmor
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,EndTurnSpec,
    HandProgressSpec,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference,DiscardMatching,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p48-v1.json'
BATCH_HASH='2387dc60a1aaf05a6e45ea45adee49493104c6399f1b66656e7c8aece31db515'
MOONKIN='EDR_940';TRUTH='TIME_057';CONSTRUCT='TIME_858';SHELL='TLC_601';OVERHEAT='FIR_906'
SPELLCASTER='CATA_483';TOLVIR='CATA_560';HARBINGER='EDR_781'
ROOTS=(MOONKIN,TRUTH,CONSTRUCT,SHELL,OVERHEAT,SPELLCASTER,TOLVIR,HARBINGER)
SKIPPED=('TLC_987','DINO_417');EXISTING_DEPENDENCIES=('CORE_CS2_231','EDR_851t')
PREFIX='cards.simple_followup_p48.';POOL_ID='constructed.cards'

def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS
            or tuple(x['record']['id']for x in d['skipped'])!=SKIPPED
            or tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING_DEPENDENCIES):
        raise TargetValidationError('P48 reviewed complete batch changed')
    for row in d['cards']+d['skipped']+d['existing_dependencies']+d['wisp_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('P48 complete original row changed')
    return d

def register_simple_followup_p48_cards(registry):
    data=load_batch();wisps=frozenset(x['record']['id']for x in data['wisp_identity_evidence'])
    for row in data['existing_dependencies']:
        from dataclasses import asdict
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('P48 existing Wisp executable changed')
    def moonkin(c):
        count=sum(c.state.entities[i].card_id in wisps for i in minions(c,registry,c.player_id))
        return(GainArmor(c.player_id,1+count),)
    def truth(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),
            CostSpec(set_to=registry.card(c.state.entities[i].card_id).cost),c.source_id)
            for p in(1,2)for i in c.state.players[p].hand)
    def excess(c):
        r=c.health_result;count=max(0,r.damage_dealt-max(0,r.health_before))
        return(Draw(c.player_id,count,c.source_id),)if count else()
    def shell_after(c):
        return tuple(InvokeBehavior(PREFIX+'pulse',c.source_id,c.player_id)for _ in range(c.armor_result.actual))
    def pulse(c):
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)
            for p in(1,2)for i in minions(c,registry,p))),)
    def overheat(c):
        buffs=tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),1,1,c.source_id)
            for i in minions(c,registry,c.player_id))
        return(*buffs,DiscardMatching(c.player_id,PoolQuery(kinds=(CardType.SPELL,),
            spell_schools=(SpellSchool.NATURE,)),source_id=c.source_id,on_success=buffs))
    def spellcaster(c):
        if not living_source(c)or spell_damage_dealt(c.state,registry,c.player_id,turn=c.state.turn)<=0:return()
        return(CopyMinion(capture_board_presence(c.state,c.source_id),c.player_id,
            cause=SummonCause.capture(c)),)
    def tolvir(c):
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(p.played_face.card_id),),cause)
            for p in played_cards(c.state,c.player_id,kind=CardType.MINION)
            if registry.card(p.played_face.card_id).cost==1)
    def returned(c):
        if c.event is None or(c.event.kind,c.event.target_id,c.event.player_id)!=('card_returned',c.source_id,c.player_id):return False
        row=hand_entry(c.state,c.source.hand_entry_id)
        return(row.entity_id,row.player_id,row.card_id,row.zone_epoch,row.from_zone,row.reason)==(
            c.source_id,c.player_id,HARBINGER,c.source.zone_epoch,Zone.BOARD,'return')
    def harbinger(c):
        return(GenerateFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),
            collectible=True,min_cost=2,max_cost=2),count=2,destination='board',
            source_id=c.source_id,cause=SummonCause.capture(c)),)
    bodies={MOONKIN:moonkin,TRUTH:truth,CONSTRUCT:lambda c:(Damage(c.target_id,5,c.source_id,
        DamageKind.MINION_ABILITY,PREFIX+'excess'),)if c.target_id is not None else(),
        SHELL:lambda c:(LoseArmor(c.player_id,5,c.source_id,PREFIX+'shell_after'),),
        OVERHEAT:overheat,SPELLCASTER:spellcaster,TOLVIR:tolvir,HARBINGER:harbinger,
        'excess':excess,'shell_after':shell_after,'pulse':pulse}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    registry.register_trigger_condition(PREFIX+'returned',returned)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if cid==MOONKIN:kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec()),)
        elif cid==HARBINGER:kwargs['hand_progress']=HandProgressSpec('event',event='card_returned',
            condition_id=PREFIX+'returned',on_complete=PREFIX+cid,repeat=True)
        else:kwargs['battlecry'if kind==CardType.MINION else'on_play']=PREFIX+cid
        if cid==CONSTRUCT:kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),
            kinds=(CardType.MINION,),relation='enemy')
        if cid==SPELLCASTER:kwargs['spell_damage']=1
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
