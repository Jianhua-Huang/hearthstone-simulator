"""Actual K24 roots with small physical-reference and reaction fixtures."""
from dataclasses import replace
import json
from _conditional_battlecry_support import CardHelpers,registry as base_registry
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayerSetup,Rarity,Scenario,TriggerSpec)
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.cross_zone import TakeCapturedMinion
from hs_sim.engine.model import CostSpec,Keyword,TargetMode,TargetSpec,TribeChangeSpec,Zone
from hs_sim.engine.sacrifice import BuffCapturedMinion,DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyLowestCostMinion,ModifyStoredCost


def registry(mode=None):
    r=base_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def first(c,cid):return next(c.state.entities[e] for e in c.state.players[1].hand if c.state.entities[e].card_id==cid)
    def options(c,good):
        return RequestChoice(1,(ChoiceOption('ok','Continue original references',good),
            ChoiceOption('bad','Rollback',(InvokeBehavior('k24.fail',c.source_id,1),))),c.source_id)
    def cycle(c,eid):
        return (ReturnToHand(eid),SummonFromZone(1,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
    def wait_destroy(c):
        ref=MinionReference.capture(c.state.entities[c.target_id])
        return (options(c,cycle(c,c.target_id)),DestroyCapturedMinion(ref,c.source_id,(GainArmor(1,5),)))
    def wait_control(c):
        ref=MinionReference.capture(c.state.entities[c.target_id])
        return (options(c,cycle(c,c.target_id)),TakeCapturedMinion(ref,2,c.source_id))
    def dead_beneficiary(c):
        source=next(c.state.entities[e] for e in c.state.players[1].board if c.state.entities[e].card_id=='CORE_EX1_198')
        ref=MinionReference.capture(source);victim=MinionReference.capture(c.state.entities[c.target_id])
        return (Destroy(source.id,c.source_id),DestroyCapturedMinion(victim,source.id,(BuffCapturedMinion(ref,health=5,source_id=source.id),)))
    scripts={
        'wait_destroy':wait_destroy,'wait_control':wait_control,'dead_beneficiary':dead_beneficiary,
        'invalid_source':lambda c:(DestroyCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),999999),),
        'wait_copy':lambda c:(options(c,(GainArmor(1,1),)),CopyLowestCostMinion(1,('beast',),c.source_id)),
        'prepare_copy':lambda c:(BuffStoredCard(CardReference.capture(first(c,'k24.beast5')),3,4,c.source_id),
            ModifyStoredCost(CardReference.capture(first(c,'k24.beast5')),CostSpec(delta=-4),c.source_id)),
        'make_beast':lambda c:(ChangeMinionTribes(CardReference.capture(first(c,'k24.plain')),TribeChangeSpec('set',('beast',)),c.source_id),),
        'unbeast':lambda c:(ChangeMinionTribes(CardReference.capture(first(c,'k24.beast2')),TribeChangeSpec('set',()),c.source_id),),
        'boost_nightmare':lambda c:(BuffStoredCard(CardReference.capture(first(c,'CATA_161')),attack=2,source_id=c.source_id),),
        'boost_eternus':lambda c:(BuffStoredCard(CardReference.capture(first(c,'TIME_435')),health=4,source_id=c.source_id),),
        'hit':lambda c:(Damage(c.target_id,1,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'summon':lambda c:(Summon(1,'CORE_ULD_178'),),
        'fail':lambda c:(AddToHand(1,'missing.k24'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k24.'+name,body)
        if name!='fail':r.register_card(CardDefinition('k24.'+name,name,CardType.SPELL,on_play='k24.'+name,
            requires_target=name in ('wait_destroy','wait_control','dead_beneficiary','invalid_source','hit','silence'),metadata=meta))
    def paid_take(c):
        if c.target_id is None:return ()
        good=(ReturnToHand(c.target_id),SummonFromZone(2,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
        return (options(c,good),TakeCapturedMinion(None,1,c.source_id,c.play.id))
    r.register_behavior('k24.paid_take',paid_take)
    r.register_card(CardDefinition('k24.paid_take','Paid control fixture',CardType.MINION,health=2,
        battlecry='k24.paid_take',metadata=meta,targeting=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')))
    for cid,cost,attack,health,metadata in (
        ('beast5',5,2,4,replace(meta,tribes=('beast',))),('beast2',2,1,3,replace(meta,tribes=('beast',))),
        ('plain',1,2,4,meta),('paladin',2,1,4,replace(meta,classes=(CardClass.PALADIN,))),
        ('large',3,4,9,meta)):
        r.register_card(CardDefinition('k24.'+cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=metadata))
    r.register_card(CardDefinition('k24.unknown','Unknown metadata',CardType.MINION,health=6))
    r.register_card(CardDefinition('k24.reborn','Reborn',CardType.MINION,health=1,keywords=(Keyword.REBORN,),metadata=meta))
    if mode:
        def watch(c):
            if mode=='cycle_target':
                if c.state.entities[c.event.source_id].card_id!='TIME_435':return ()
                target=c.state.players[2].board[0]
                good=(ReturnToHand(target),SummonFromZone(2,zone=Zone.HAND,selection='first',source_id=c.source_id,cause=SummonCause.capture(c)))
                return (options(c,good),)
            if mode=='health':
                if c.state.entities[c.event.source_id].card_id!='TLC_606':return ()
                return (options(c,(GainArmor(1,1),)),)
            if mode=='unrelated_death':
                if c.state.entities[c.event.source_id].card_id!='TLC_606':return ()
                return (Destroy(c.event.target_id,c.source_id),)
            if mode=='cycle_source':
                if c.state.entities[c.event.target_id].card_id!='k24.plain':return ()
                source=next((e for e in c.state.players[1].board if c.state.entities[e].card_id=='CORE_EX1_198'),None)
                return (options(c,cycle(c,source)),) if source else ()
            return ()
        r.register_behavior('k24.watch',watch)
        r.register_card(CardDefinition('k24.watch','Observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('minion_summoned' if mode=='cycle_target' else 'minion_died' if mode=='cycle_source' else 'health_resolved','k24.watch'),)))
    return r


class TargetHelpers(CardHelpers):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=('CORE_CS2_182',)*8,mode=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_05',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8)),seed=337),registry(mode) if mode else self.registry)
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def public_play(self,g,cid,target_cid=None,*,target_zone='board',target_player=1):
        listing=g.for_player(1).legal_actions();self.assertIsInstance(listing['actions'],list)
        players={p['id']:p for p in listing['observation']['players']}
        source=next(c['ref'] for c in players[1]['hand'] if c['card_id']==cid)
        target=next((c['ref'] for c in players[target_player][target_zone] if c['card_id']==target_cid),None) if target_cid else None
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==source and a.get('target')==target)
        reply=g.for_player(1).submit({'revision':listing['revision'],'action':action})
        self.assertTrue(reply['accepted'],reply.get('error'))
