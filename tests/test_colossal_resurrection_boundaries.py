"""Attributed resurrection keeps its own printed Colossal material contract."""
from dataclasses import replace
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (AppendageSpec,CardDefinition,CardType,Game,Keyword,
    PlayerSetup,Scenario,TriggerSpec)
from hs_sim.engine.effects import ChoiceOption,Destroy,GainArmor,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.resurrection_summons import validate_death_face
from hs_sim.engine.summon_quantities import SummonEntryMaterial,validate_material
from card_batch_testkit import CardBatchTestMixin

P='fixture.resurrect-colossal.'
GIANT,LIMB,FILL,BIG,CHEAP,WATCH,KILL=(P+x for x in ('giant','limb','fill','big','cheap','watch','kill'))
MERITHRA='EDR_238'


@lru_cache(maxsize=None)
def registry(mode,role):
    assert mode in ('normal','wait','fault')
    assert role in ('writer','independent-reader')
    r=build_registry()
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=10))
    r.register_card(CardDefinition(LIMB,LIMB,CardType.MINION,health=2))
    r.register_card(CardDefinition(BIG,BIG,CardType.MINION,cost=8,health=8))
    r.register_card(CardDefinition(CHEAP,CHEAP,CardType.MINION,cost=7,health=7))
    r.register_behavior(P+'battlecry',lambda c:(GainArmor(c.player_id,99),))
    r.register_card(CardDefinition(GIANT,GIANT,CardType.MINION,cost=9,attack=8,health=9,
        keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB),)*2,battlecry=P+'battlecry'))
    r.register_behavior(KILL,lambda c:(Destroy(c.target_id,c.source_id),))
    r.register_card(CardDefinition(KILL,KILL,CardType.SPELL,on_play=KILL,requires_target=True))
    def fail(c):raise ResolutionError('Deliberate resurrection limb failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        if mode=='normal' or c.state.entities[c.event.target_id].card_id!=LIMB:return ()
        if mode=='fault':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Finish appendage'),
            ChoiceOption('bad','Rollback',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=10,
        triggers=(TriggerSpec('minion_summoned',WATCH),)))
    return r


class ColossalResurrectionBoundaryTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(registry)
    def game(self,board=(GIANT,),mode='normal',player=1):
        self.mode=mode
        owner=PlayerSetup('HERO_08',hand=(KILL,)*6+(MERITHRA,),board=board,
            mana=30,max_mana=30,mana_cap=30)
        enemy=PlayerSetup('HERO_08',board=(GIANT,))
        return Game.from_scenario(Scenario((owner,enemy)if player==1 else(enemy,owner),
            active_player=player,seed=938),registry(mode,'writer'),mode='release')
    def bodies(self,g,cid,player=1):
        return [g.state.entities[i]for i in g.state.players[player].board if g.state.entities[i].card_id==cid]
    def test_merithra_resurrects_distinct_printed_colossals_without_battlecry(self):
        for player in (1,2):
            with self.subTest(player=player):
                g=self.game((GIANT,GIANT,BIG,CHEAP),player=player)
                for cid in (GIANT,GIANT,BIG,CHEAP):
                    self.play(g,KILL,self.bodies(g,cid,player)[0].id,player)
                self.play(g,KILL,self.bodies(g,GIANT,3-player)[0].id,player)
                self.play(g,MERITHRA,player=player)
                self.assertEqual((len(self.bodies(g,GIANT,player)),len(self.bodies(g,BIG,player)),
                    len(self.bodies(g,LIMB,player)),len(self.bodies(g,CHEAP,player))),(1,1,2,0))
                self.assertEqual(g.state.entities[g.state.players[player].hero_id].armor,0)
                self.assertEqual(g.state.players[player].mana,24)
                row=g.state.colossal_history[-1]
                self.assertEqual((row.reason,row.card_id),('resurrect',GIANT));self.portable(g)
    def test_last_slot_enters_body_without_fabricating_appendage_capacity(self):
        g=self.game((GIANT,)+(FILL,)*5);self.play(g,KILL,self.bodies(g,GIANT)[0].id)
        self.play(g,MERITHRA)
        self.assertEqual((len(g.state.players[1].board),len(self.bodies(g,GIANT)),len(self.bodies(g,LIMB))),(7,1,0))
        self.assertEqual(g.state.colossal_history[-1].limbs,(None,None));self.portable(g)
    def test_limb_waits_restore_and_replay_without_reselecting_death(self):
        g=self.game((GIANT,WATCH),'wait');self.play(g,KILL,self.bodies(g,GIANT)[0].id)
        self.play(g,MERITHRA);waiting=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for _ in range(2):self.choose(g);self.choose(waiting)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.snapshot(),waiting.snapshot())
        self.assertEqual((len(self.bodies(g,GIANT)),len(self.bodies(g,LIMB))),(1,2));self.portable(g)
    def test_late_limb_failure_rolls_back_full_merithra_action_and_rng(self):
        g=self.game((GIANT,WATCH),'fault');self.play(g,KILL,self.bodies(g,GIANT)[0].id)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,MERITHRA)
        self.assertEqual(g.snapshot(),before);self.portable(g)
    def test_ordinary_summon_guard_and_original_composition_checks_stay_strict(self):
        g=self.game();self.play(g,KILL,self.bodies(g,GIANT)[0].id)
        with self.assertRaisesRegex(ValueError,'ordinary non-composite'):
            validate_material(g.registry,SummonEntryMaterial(GIANT))
        death=g.state.death_history[-1]
        self.assertEqual(validate_death_face(g.registry,death).id,GIANT)
        with self.assertRaisesRegex(ValueError,'original composition'):
            validate_death_face(g.registry,replace(death,components=(FILL,)))
