"""Shared finite fixtures for actual K23 cards and attack-filtered physical draw."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,
    Rarity,Scenario,SelectChoice,TriggerSpec,UseHeroPower)
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,DamageBatch,Draw,GainArmor,
    InvokeBehavior,RequestChoice)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.hero_powers import TriggerHeroPower
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CostSpec,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,DrawMinionWithAttack,ModifyStoredCost


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def choice(c,good):
        return RequestChoice(1,(ChoiceOption('ok','Continue original body',good),
            ChoiceOption('bad','Rollback',(InvokeBehavior('k23.fail',c.source_id,1),))),c.source_id)
    def expensive(c):return next(c.state.entities[e] for e in c.state.players[1].hand if c.state.entities[e].card_id=='k23.expensive')
    scripts={
        'noop':lambda c:(),
        'draw':lambda c:(DrawMinionWithAttack(1,0,c.source_id),),
        'invalid_source':lambda c:(DrawMinionWithAttack(1,0,999999),),
        'wait_draw':lambda c:(choice(c,(GainArmor(1,1),)),DrawMinionWithAttack(1,0,c.source_id)),
        'lower':lambda c:(ModifyStoredCost(CardReference.capture(expensive(c)),CostSpec(delta=-1),c.source_id),),
        'deck_lower':lambda c:(BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),attack=-1,source_id=c.source_id),),
        'hurt':lambda c:(Damage(c.target_id,1,c.source_id),),
        'hero_hurt':lambda c:(Damage(c.state.players[1].hero_id,3,c.source_id),),
        'armor_hurt':lambda c:(GainArmor(1,5),Damage(c.state.players[1].hero_id,3,c.source_id)),
        'wound_board':lambda c:(DamageBatch(tuple(Damage(e,1,c.source_id) for p in (1,2) for e in c.state.players[p].board)),),
        'imbue':lambda c:(Imbue(1,c.source_id),),
        'twice':lambda c:(Imbue(1,c.source_id,count=2),),
        'effect_power':lambda c:(TriggerHeroPower(1,c.source_id),),
        'fill':lambda c:tuple(AddToHand(1,'CORE_CS2_182',c.source_id) for _ in range(10)),
        'burn_draw':lambda c:tuple(AddToHand(1,'CORE_CS2_182',c.source_id) for _ in range(10))+(DrawMinionWithAttack(1,0,c.source_id),),
        'fail':lambda c:(AddToHand(1,'missing.k23'),),
    }
    for name,body in scripts.items():
        r.register_behavior('k23.'+name,body)
        if name!='fail':r.register_card(CardDefinition('k23.'+name,name,CardType.SPELL,
            on_play='k23.'+name,requires_target=name=='hurt',metadata=meta))
    r.register_card(CardDefinition('k23.expensive','Five',CardType.SPELL,cost=5,on_play='k23.noop',metadata=meta))
    for cid,attack in (('zero',0),('one',1)):
        r.register_card(CardDefinition('k23.'+cid,cid,CardType.MINION,attack=attack,health=4,metadata=meta))
    r.register_card(CardDefinition('k23.unknown','Unknown tribe',CardType.MINION,health=9))
    r.register_card(CardDefinition('k23.power','Skill',CardType.HERO_POWER,on_use='k23.noop',metadata=meta))
    if mode:
        def watch(c):
            if c.event.player_id!=1:return ()
            expected={'soldier':'TIME_720','holding':'EDR_472','skull':'JAIL_513'}
            if mode in expected and c.state.entities[c.event.source_id].card_id!=expected[mode]:return ()
            good=((Damage(c.event.source_id,1,c.source_id),) if mode=='soldier' else
                (ModifyStoredCost(CardReference.capture(expensive(c)),CostSpec(delta=-1),c.source_id),) if mode=='holding' else
                (Draw(1,source_id=c.source_id),) if mode=='skull' else (GainArmor(1,1),))
            return (choice(c,good),)
        r.register_behavior('k23.watch',watch)
        r.register_card(CardDefinition('k23.watch','Observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('card_drawn' if mode=='draw' else 'minion_summoned','k23.watch'),)))
    return r


class CardHelpers:
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(),deck=('CORE_CS2_182',)*8,mode=None,weapon=None,power=False):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_05',hand=hand,board=board,deck=deck,weapon_card_id=weapon,
                hero_power_card_id='k23.power' if power else None,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',board=enemy,deck=('CORE_CS2_182',)*8)),seed=317),registry(mode) if mode else self.registry)
    def play(self,g,cid,target=None):
        source=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        g.apply(PlayCard(1,source,target));return source
    def body(self,g,cid,p=1):return next(g.state.entities[e] for e in g.state.players[p].board if g.state.entities[e].card_id==cid)
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def price(self,g,eid):
        state=g.state;return quote_cost(state,g.registry,state.entities[eid]).amount
    def portable(self,g,mode=None):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(mode))
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),saved);return other
    def rows(self,g,cid):return [r.health_result for r in g.state.damage_history if r.health_result.source_card_id==cid]
