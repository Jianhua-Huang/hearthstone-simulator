"""Two independent missing wear combinations, original immutable v149 only."""
from copy import deepcopy
from pathlib import Path
import json, os, unittest
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, HealthFlow, HealthLayer,
    HealthOp, HealthRule, Keyword, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, WeaponWearPredicate, WeaponWearProfile,
    WeaponWearSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, EquipWeapon, GainArmor, RandomDamage, RequestChoice)
from hs_sim.engine.model import CardClass, CardMetadata, DamageKind
from hs_sim.engine.resolver import BeginAttack
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def registry(window='pre_wear_current', weapon_dr=False):
    r = Registry('v157-root-wear-original-Reborn-and-DR-attack-'+window)
    def after_reborn(c):
        return [RequestChoice(1, (ChoiceOption('ok','Continue', (GainArmor(1,1),)),
            ChoiceOption('bad','Rollback RNG failure',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
                EquipWeapon(1,'invalid')))), c.source_id)]
    def old_weapon_dr(c):
        hero, target = c.state.players[1].hero_id, c.state.players[2].board[0]
        return [EquipWeapon(1,'new_weapon'), RequestChoice(1,(ChoiceOption('ok','Continue original DR',()),
            ChoiceOption('bad','Rollback RNG failure',(RandomDamage((c.state.players[2].hero_id,),1,c.source_id),
                EquipWeapon(1,'invalid')))), c.source_id), BeginAttack(Attack(1,hero,target))]
    r.register_behavior('reborn_wait',after_reborn)
    r.register_behavior('weapon_dr',old_weapon_dr)
    redirect = HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
        target_relation='friendly',target_kinds=(CardType.HERO,),damage_kinds=(DamageKind.COMBAT,),redirect_to='self')
    spec = WeaponWearSpec('prevent_durability',WeaponWearProfile('friendly_minion',window,'active_living'),
        (WeaponWearPredicate('own_turn'),))
    cards = (
        CardDefinition('hero','Hero',CardType.HERO,health=30,attack=2,keywords=(Keyword.WINDFURY,)),
        CardDefinition('enemyhero','Enemy Hero',CardType.HERO,health=30),
        CardDefinition('reborn_source','Reborn source',CardType.MINION,health=1,health_rules=(redirect,),
            keywords=(Keyword.REBORN,),weapon_wear_policies=(spec,)),
        CardDefinition('listener','Reborn listener',CardType.MINION,health=5,triggers=(TriggerSpec('minion_reborn','reborn_wait'),)),
        CardDefinition('defender','Defender',CardType.MINION,health=30,attack=2 if not weapon_dr else 0),
        CardDefinition('weapon','Weapon',CardType.WEAPON,attack=2,durability=3),
        CardDefinition('old_weapon','Old weapon',CardType.WEAPON,attack=3,durability=1,deathrattle='weapon_dr'),
        CardDefinition('new_weapon','New weapon',CardType.WEAPON,attack=2,durability=3),
        CardDefinition('invalid','Invalid equipment',CardType.MINION,health=1),
    )
    for card in cards:
        r.register_card(card)
    return r


class RootWearCombinations(unittest.TestCase):
    def blob(self,g,label):
        if not os.environ.get('V157_INPUT_DIR'):return
        p = Path(os.environ['V157_INPUT_DIR'])/self._testMethodName
        p.mkdir(parents=True,exist_ok=True)
        n = getattr(self,'input_number',0)+1; self.input_number=n
        value = g.snapshot() if isinstance(g,Game) else g
        (p/(f'{n:03d}-'+label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def portable(self,g,window='pre_wear_current',weapon_dr=False,label='portable'):
        s = json.loads(json.dumps(g.snapshot())); self.blob(s,label)
        self.assertEqual(Game.from_snapshot(deepcopy(s),registry(window,weapon_dr)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(window,weapon_dr)).snapshot(),s)
        for p in (1,2):
            dto=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for private in ('wear_receipt','wear_acceptance','WeaponWearPlan','weapon_wear_committed','hero_allocation','resolution_frame'):
                self.assertNotIn(private,dto)
        return s

    def choose(self,g,key):
        self.blob(g,'before-'+key)
        c=g.state.pending_choice
        g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def test_original_dead_source_then_Reborn_next_acceptance_uses_new_physical_row(self):
        for window,loss in (('pre_wear_current',1),('combat_accept_original',0)):
            with self.subTest(window=window):
                g=Game.from_scenario(Scenario((PlayerSetup('hero',board=('reborn_source','listener'),weapon_card_id='weapon'),
                    PlayerSetup('enemyhero',board=('defender',))),seed=15701),registry(window))
                self.blob(g,'initial-'+window)
                original=g.state.players[1].board[0]; hero=g.state.players[1].hero_id
                weapon=g.state.players[1].weapon_id; target=g.state.players[2].board[0]
                g.apply(Attack(1,hero,target))
                self.assertIsNotNone(g.state.pending_choice)
                self.assertEqual(g.state.entities[original].zone,Zone.GRAVEYARD)
                new=next(i for i in g.state.players[1].board if g.state.entities[i].card_id=='reborn_source')
                self.assertNotEqual(new,original)
                first=g.state.hero_attack_history[0]
                self.assertEqual(first.terminal.outcome,'completed')
                self.assertEqual(first.wear_receipt.durability_after,3-loss)
                self.assertEqual(first.wear_receipt.plan.decisions[0].entity_id,original)
                before=self.portable(g,window,label='first-wear-Reborn-true-wait-'+window)
                with self.assertRaises(ResolutionError): self.choose(g,'bad')
                self.assertEqual(g.snapshot(),before)
                self.choose(g,'ok')
                g.apply(Attack(1,hero,target))
                second=g.state.hero_attack_history[-1]
                self.assertNotEqual(first.declaration.identity.record_id,second.declaration.identity.record_id)
                self.assertEqual(second.wear_receipt.plan.decisions[0].entity_id,new)
                self.assertNotEqual(first.wear_receipt.plan.decisions[0].ability_id,second.wear_receipt.plan.decisions[0].ability_id)
                self.assertEqual(g.state.entities[new].zone,Zone.GRAVEYARD)
                self.assertEqual(g.state.entities[weapon].durability,3-2*loss)
                self.assertEqual(sum(e.kind=='weapon_wear_committed' for e in g.events),2)
                self.assertEqual(g.state.entities[target].health,22)
                self.portable(g,window,label='new-row-second-window-'+window)

    def test_original_weapon_DR_true_wait_replaces_weapon_then_new_attack_has_own_wear(self):
        g=Game.from_scenario(Scenario((PlayerSetup('hero',weapon_card_id='old_weapon'),
            PlayerSetup('enemyhero',board=('defender',))),seed=15702),registry(weapon_dr=True))
        self.blob(g,'initial-weapon-DR')
        old=g.state.players[1].weapon_id; hero=g.state.players[1].hero_id; target=g.state.players[2].board[0]
        g.apply(Attack(1,hero,target))
        self.assertIsNotNone(g.state.pending_choice)
        new=g.state.players[1].weapon_id
        self.assertNotEqual(new,old)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[new].durability,3)
        self.assertEqual(len(g.state.hero_attack_history),1)
        first=g.state.hero_attack_history[0]
        self.assertEqual((first.combat.weapon_id,first.wear_receipt.durability_after,first.terminal.outcome),(old,0,'completed'))
        before=self.portable(g,weapon_dr=True,label='old-weapon-DR-installed-new-true-wait')
        with self.assertRaises(ResolutionError): self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.choose(g,'ok')
        rows=g.state.hero_attack_history
        self.assertEqual(len(rows),2)
        self.assertEqual([r.combat.weapon_id for r in rows],[old,new])
        self.assertEqual([r.wear_receipt.durability_after for r in rows],[0,2])
        self.assertEqual([r.terminal.outcome for r in rows],['completed','completed'])
        self.assertEqual(sum(e.kind=='weapon_wear_committed' for e in g.events),2)
        self.assertEqual(g.state.entities[target].health,21)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g,weapon_dr=True,label='two-original-independent-wear-records')


if __name__=='__main__': unittest.main()
