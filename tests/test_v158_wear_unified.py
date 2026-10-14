"""New cross-mechanism cases over the unified candidate; local policies only."""
from copy import deepcopy
from pathlib import Path
import json, os, unittest
from hs_sim.engine import (Attack, CardDefinition, CardType, DamageKind, Game, HealthFlow,
    HealthLayer, HealthLossFloorSpec, HealthOp, HealthRule, Keyword, LoseHealth, PlayCard,
    PlayerSetup, RandomSplitDamage, RecoverHero, Registry, ResolutionError, Resource,
    Scenario, SelectChoice, SpendUpToResource, SplitDamageScope, StatRelationSpec,
    WeaponWearPredicate, WeaponWearProfile, WeaponWearSpec, loss_floor_result)
from hs_sim.engine.effects import ChoiceOption, EquipWeapon, GainArmor, RandomDamage, RequestChoice
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.resource_operations import resource_result
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.allocation_facts import SourceAllocationFact


def registry():
    r=Registry('v158-unified-wear-Hero-resource-floor-split-local')
    def recovery(c):
        ref=c.hero_lethal
        good=(SpendUpToResource(1,Resource.CORPSES,3,c.source_id,'recover_result','hero_lethal_at_debit',ref),)
        bad=(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'invalid'))
        return [RequestChoice(1,(ChoiceOption('save','Recover',good),ChoiceOption('bad','Failure',bad)),c.source_id)]
    def weapon_dr(c):
        return [RequestChoice(1,(ChoiceOption('equip','Install fresh weapon',(EquipWeapon(1,'fresh'),)),),c.source_id)]
    def after_packet(c):
        value=health_result(c.event)
        return [SpendUpToResource(1,Resource.CORPSES,2,c.source_id,'resource_floor_wait')] if value.split_packet.index==1 else []
    def resource_floor_wait(c):
        t=c.state.players[2].board[0]
        bad=(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),EquipWeapon(1,'invalid'))
        return [LoseHealth(t,c.resource_result.actual_amount,c.source_id),RequestChoice(1,
            (ChoiceOption('ok','Continue three-unit budget',(GainArmor(1,1),)),ChoiceOption('bad','Failure',bad)),c.source_id)]
    for name,body in {'save':recovery,'recover_result':lambda c:[RecoverHero(c.resource_result.hero_lethal_reference,c.resource_result.actual_amount)],
            'weapon_dr':weapon_dr,'after_packet':after_packet,'resource_floor_wait':resource_floor_wait,
            'spell':lambda c:[RandomSplitDamage(1,c.cast.id,c.source_id,3,SplitDamageScope('enemy',(CardType.MINION,)),'after_packet')]}.items():
        r.register_behavior(name,body)
    replace=WeaponWearSpec('replace_with_attack',WeaponWearProfile('self_weapon'),
        (WeaponWearPredicate('defender_kind','minion'),))
    for card in (
        CardDefinition('hero','Hero',CardType.HERO,health=30,attack=2),
        CardDefinition('savehero','Fragile save Hero',CardType.HERO,health=5,attack=2,
            deathrattle='save',health_loss_floors=(HealthLossFloorSpec(),)),
        CardDefinition('defender','Lethal defender',CardType.MINION,health=30,attack=10),
        CardDefinition('dual_floor','Dual scopes and derived attack',CardType.MINION,health=5,attack=8,
            health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.FLOOR,3,layer=HealthLayer.TARGET,target_relation='self'),),
            health_loss_floors=(HealthLossFloorSpec(2),),stat_relations=(StatRelationSpec(),)),
        CardDefinition('old','Last weapon',CardType.WEAPON,attack=3,durability=1,deathrattle='weapon_dr'),
        CardDefinition('fresh','Fresh weapon',CardType.WEAPON,attack=2,durability=3),
        CardDefinition('replacement','Attack-loss weapon',CardType.WEAPON,attack=2,durability=1,weapon_wear_policies=(replace,)),
        CardDefinition('invalid','Invalid equipment',CardType.MINION,health=1),
        CardDefinition('spell','Three-unit spell',CardType.SPELL,cost=2,on_play='spell'),
    ):r.register_card(card)
    return r


class UnifiedWearTests(unittest.TestCase):
    def blob(self,g,label):
        if not os.environ.get('V158_INPUT_DIR'):return
        root=Path(os.environ['V158_INPUT_DIR'])/self._testMethodName;root.mkdir(parents=True,exist_ok=True)
        n=getattr(self,'input_number',0)+1;self.input_number=n
        (root/(f'{n:03d}-'+label+'.json')).write_text(json.dumps(g.snapshot(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def portable(self,g,label):
        self.blob(g,label);s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in (1,2):
            dto=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for k in ('wear_receipt','wear_acceptance','source_allocation','loss_floor_result','split_damage_history',
                    'hero_lethal_roots','hero_lethal_history','parked_hashes','resolution_frame'):
                self.assertNotIn('"'+k+'"',dto)
        return s
    def choose(self,g,key):
        self.blob(g,'before-'+key);c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def test_fatal_Hero_resource_recovery_then_parked_weapon_DR_has_one_original_wear(self):
        g=Game.from_scenario(Scenario((PlayerSetup('savehero',weapon_card_id='old',corpses=5),
            PlayerSetup('hero',board=('defender',))),seed=15801),registry())
        self.blob(g,'initial-fatal-weapon')
        h=g.state.players[1].hero_id;w=g.state.players[1].weapon_id;t=g.state.players[2].board[0]
        g.apply(Attack(1,h,t))
        self.assertEqual(g.state.pending_choice.source_id,h)
        record=g.state.hero_attack_history[0]
        self.assertEqual((record.terminal.outcome,record.wear_receipt.durability_after),('completed',0))
        self.assertEqual(sum(e.kind=='weapon_wear_committed' for e in g.events),1)
        before=self.portable(g,'original-wear-before-true-fatal-Hero-wait')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g,'save')
        self.assertEqual(g.state.entities[h].health,3)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],2)
        self.assertEqual(g.state.pending_choice.source_id,w)
        values=[v for e in g.events if (v:=resource_result(e))is not None]
        self.assertEqual(len(values),1)
        self.assertIs(type(values[0].source_allocation),SourceAllocationFact)
        self.portable(g,'recovered-original-Hero-parked-weapon-DR-wait')
        self.choose(g,'equip')
        self.assertIsNone(g.state.pending_choice)
        new=g.state.players[1].weapon_id
        self.assertNotEqual(new,w);self.assertEqual(g.state.entities[new].durability,3)
        self.assertEqual(g.state.hero_attack_history[0].combat.weapon_id,w)
        self.assertEqual(sum(e.kind=='weapon_wear_committed' for e in g.events),1)
        self.assertEqual(g.state.entities[t].health,25)
        self.portable(g,'one-complete-wear-new-installed-weapon')

    def test_spell_budget_resource_effect_floor_wait_then_zero_damage_combat_wear_shared_allocation(self):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('spell',),mana=10,max_mana=10,
            corpses=5,weapon_card_id='replacement'),PlayerSetup('hero',board=('dual_floor',))),seed=15802),registry())
        self.blob(g,'initial-five-mechanisms')
        s=g.state.players[1].hand[0];h=g.state.players[1].hero_id;w=g.state.players[1].weapon_id;t=g.state.players[2].board[0]
        g.apply(PlayCard(1,s))
        self.assertIsNotNone(g.state.pending_choice)
        root=g.state.split_damage_history[0]
        self.assertEqual((len(root.packets),root.quote.budget),(1,3))
        self.assertIs(type(root.quote.source),SourceAllocationFact)
        values=[v for e in g.events if (v:=loss_floor_result(e))is not None]
        self.assertEqual((values[0].actual_lost,values[0].health_after),(2,2))
        self.assertIs(type(values[0].plan.source),SourceAllocationFact)
        before=self.portable(g,'split-resource-loss-real-wait-common-fact-type')
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g,'ok')
        root=g.state.split_damage_history[0]
        self.assertTrue(root.completed);self.assertEqual(len(root.packets),3)
        self.assertEqual((g.state.players[1].mana,g.state.players[1].resources[Resource.CORPSES]),(8,3))
        self.assertEqual((g.state.entities[t].health,g.state.entities[t].attack),(2,2))
        self.portable(g,'original-budget-complete-live-below-damage-floor')
        g.apply(Attack(1,h,t))
        row=g.state.hero_attack_history[0]
        self.assertEqual((row.wear_receipt.plan.axis,row.wear_receipt.plan.amount),('attack',1))
        self.assertEqual((g.state.entities[w].attack,g.state.entities[w].durability),(1,1))
        self.assertEqual(g.state.entities[t].health,2)
        self.assertEqual(row.terminal.outcome,'completed')
        self.assertEqual(len(g.state.play_history),1)
        self.portable(g,'zero-damage-Hero-combat-one-axis-replacement')
