"""Bounded original-window hero attack facts; internal policy, no CN claim."""
import copy
import json
import unittest
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, HeroAttackQuery,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, Zone, hero_attack_count, hero_attacks)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CombatExchange, Damage,
    DamageBatch, EquipWeapon, ForceAttack, Freeze, GainArmor, GrantKeyword, ReplaceHero,
    RequestChoice, ReturnToHand)
from hs_sim.engine.model import DamageKind
from hs_sim.engine.interrupts import RedirectAttack, ResolveAttack, resolve_attack
from hs_sim.engine.resolver import CombatDamage, default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.replay import build_replay, replay


class HeroAttackHistoryTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('u19-isolated-original-window-v1')
        for name,kind,attrs in (
            ('hero',CardType.HERO,dict(attack=2,health=100)),
            ('newhero',CardType.HERO,dict(attack=3,health=100)),
            ('otherhero',CardType.HERO,dict(attack=4,health=100)),
            ('plain',CardType.MINION,dict(attack=1,health=30,keywords=(Keyword.CHARGE,))),
            ('fragile',CardType.MINION,dict(attack=1,health=1)),
            ('shield',CardType.MINION,dict(attack=0,health=30,keywords=(Keyword.DIVINE_SHIELD,))),
            ('axe',CardType.WEAPON,dict(attack=2,durability=1)),
        ):self.r.register_card(CardDefinition(name,name,kind,**attrs))

    def spell(self,name,fn):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))

    def watcher(self,name,events,fn):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=100,
            triggers=tuple(TriggerSpec(e,name) for e in events)))

    def game(self,board=(),enemy=(),hand=(),weapon=None,mechanics=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',board=board,hand=hand,deck=('plain',)*20,mana=10,max_mana=10,weapon_card_id=weapon),
            PlayerSetup('hero',board=enemy,deck=('plain',)*20,mana=10,max_mana=10)),seed=134),
            self.r,mechanics=mechanics)

    def hero(self,g,p=1):return g.state.players[p].hero_id
    def attack(self,g,target=None,p=1):return g.apply(Attack(p,self.hero(g,p),target or self.hero(g,3-p)))
    def cast(self,g,name):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,i))
    def count(self,g,phase='completed',window='match',p=1):
        return hero_attack_count(g.state,p,HeroAttackQuery(phase,window=window))
    def check(self,g,mechanics=None):
        s=g.snapshot()
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),self.r,mechanics).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),self.r,mechanics).snapshot(),s)
    def choose(self,g,key='ok'):
        c=g.state.pending_choice
        return g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def rehash(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        return s
    def assert_bad(self,s,mechanics=None):
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),self.r,mechanics)

    def test_persistent_across_turns_and_three_physical_heroes(self):
        self.spell('replace',lambda c:[ReplaceHero(1,'newhero')])
        self.spell('again',lambda c:[ReplaceHero(1,'otherhero')])
        g=self.game(hand=('replace','again'));original=self.hero(g)
        self.attack(g);self.cast(g,'replace');second=self.hero(g)
        self.assertNotEqual(original,second)
        with self.assertRaises(IllegalAction):self.attack(g)
        g.apply(EndTurn(1));self.assertEqual(self.count(g,window='owner_turn'),0)
        g.apply(EndTurn(2));self.attack(g);self.cast(g,'again')
        self.assertEqual(self.count(g),2)
        rows=hero_attacks(g.state,1,HeroAttackQuery())
        self.assertEqual([r.declaration.identity.physical_hero_id for r in rows],[original,second])
        self.assertEqual([r.declaration.identity.hero_card_id for r in rows],['hero','newhero'])
        self.assertEqual([r.declaration.identity.owner_turn_id for r in rows],[1,3])
        g.apply(EndTurn(1));self.assertEqual(self.count(g,window='actual_interval'),0)
        self.assertEqual(self.count(g),2);self.check(g)

    def test_current_limits_wind_mega_unlimited_do_not_rewrite_history(self):
        from hs_sim.engine import AttackPolicySpec, GrantAttackPolicy
        self.spell('wind',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.WINDFURY)])
        self.spell('mega',lambda c:[GrantKeyword(c.state.players[1].hero_id,Keyword.MEGA_WINDFURY)])
        self.spell('unlimited',lambda c:[GrantAttackPolicy(c.state.players[1].hero_id,AttackPolicySpec('attacks_per_turn',None))])
        g=self.game(hand=('wind','mega','unlimited'));self.attack(g)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g)
        self.assertEqual(g.snapshot(),before)
        self.cast(g,'wind');self.attack(g);self.cast(g,'mega');self.attack(g);self.attack(g)
        with self.assertRaises(IllegalAction):self.attack(g)
        self.cast(g,'unlimited');self.attack(g);self.attack(g)
        self.assertEqual(self.count(g),6)
        ids=[r.declaration.identity.record_id for r in g.state.hero_attack_history]
        self.assertEqual(len(set(ids)),6);self.assertGreater(max(ids),6);self.check(g)

    def test_nonhero_forced_defense_and_damage_are_excluded(self):
        self.spell('force',lambda c:[ForceAttack(*c.state.players[1].board[:2],combat_relation='friendly_minions'),
            Damage(c.state.players[2].hero_id,1,c.source_id)])
        g=self.game(board=('plain','plain'),hand=('force',));a=g.state.players[1].board[0]
        g.apply(Attack(1,a,self.hero(g,2)));self.cast(g,'force')
        self.assertEqual(self.count(g,'declared'),0)
        g.apply(EndTurn(1));self.attack(g,p=2)
        self.assertEqual(self.count(g,p=1),0);self.assertEqual(self.count(g,p=2),1)
        with self.assertRaises(ValueError):HeroAttackQuery(origins=('forced',))
        self.check(g)

    def test_three_delivery_cancellations_consume_declaration_not_completion(self):
        for reason in ('attacker_frozen','combatant_left_play','combatants_became_friendly'):
            with self.subTest(reason=reason):
                self.setUp()
                def react(c):
                    if c.state.entities[c.event.source_id].kind!=CardType.HERO:return []
                    return [Freeze(c.event.source_id)] if reason=='attacker_frozen' else (
                        [ReturnToHand(c.event.target_id)] if reason=='combatant_left_play' else [ChangeControl(c.event.target_id,1)])
                self.watcher('watch',('attack_declared',),react)
                g=self.game(board=('watch',),enemy=('plain',))
                self.attack(g,g.state.players[2].board[0])
                row=g.state.hero_attack_history[0]
                self.assertEqual((row.terminal.outcome,row.terminal.reason,row.terminal.stage),('cancelled',reason,'delivery_pending'))
                self.assertEqual((self.count(g,'declared'),self.count(g),g.state.entities[self.hero(g)].attacks_this_turn),(1,0,1))
                self.assertIsNone(row.combat);self.check(g)

    def test_replace_during_declaration_cancels_original_physical_source(self):
        self.watcher('replace',('attack_declared',),lambda c:[ReplaceHero(1,'newhero')])
        g=self.game(board=('replace',));old=self.hero(g);self.attack(g)
        row=g.state.hero_attack_history[0]
        self.assertEqual(row.declaration.identity.physical_hero_id,old)
        self.assertEqual(row.terminal.reason,'combatant_left_play')
        self.assertNotEqual(self.hero(g),old);self.assertEqual(self.count(g),0);self.check(g)

    def test_terminal_before_delivery_interrupts_but_simultaneous_lethal_completes(self):
        self.watcher('lethal',('attack_declared',),lambda c:[Damage(c.event.source_id,999,c.source_id)])
        g=self.game(board=('lethal',));self.attack(g)
        row=g.state.hero_attack_history[0]
        self.assertEqual((row.terminal.outcome,row.terminal.stage),('interrupted','declared'))
        self.assertEqual((self.count(g,'interrupted'),self.count(g)),(1,0));self.check(g)
        self.setUp();self.spell('low',lambda c:[Damage(c.state.players[1].hero_id,99),Damage(c.state.players[2].hero_id,99)])
        g=self.game(hand=('low',),weapon='axe');self.cast(g,'low');weapon=g.state.players[1].weapon_id
        self.attack(g);self.assertEqual(g.state.status,'draw')
        self.assertEqual(self.count(g),1);self.assertEqual(g.state.entities[weapon].durability,0)
        self.assertEqual(g.state.hero_attack_history[0].combat.weapon_id,weapon);self.check(g)

    def test_shield_zero_amount_still_completes_after_wear(self):
        self.watcher('zero',('attack_declared',),lambda c:[Buff(c.event.source_id,attack=-4)])
        g=self.game(board=('zero',),enemy=('shield',),weapon='axe');weapon=g.state.players[1].weapon_id
        target=g.state.players[2].board[0];self.attack(g,target)
        self.assertEqual(self.count(g),1);self.assertEqual(g.state.entities[target].health,30)
        self.assertEqual(g.state.entities[weapon].durability,0);self.check(g)

    def test_declared_wait_failed_choice_rollback_and_nested_friendly_child(self):
        def wait(c):
            if c.state.entities[c.event.source_id].kind!=CardType.HERO:return []
            a,b=c.state.players[1].board[:2]
            return [RequestChoice(1,(ChoiceOption('bad','Bad',(EquipWeapon(1,'plain'),)),
                ChoiceOption('ok','Okay',(ForceAttack(a,b,combat_relation='friendly_minions'),))),c.source_id)]
        self.watcher('wait',('attack_declared',),wait)
        g=self.game(board=('plain','plain','wait'));self.attack(g)
        self.assertEqual((self.count(g,'declared'),self.count(g)),(1,0));self.check(g)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.count(g),1)
        self.assertEqual([g.state.entities[i].attacks_this_turn for i in g.state.players[1].board[:2]],[0,0]);self.check(g)

    def test_health_context_is_accepted_while_finished_context_is_completed(self):
        def pause(c):
            if c.event.target_id!=c.state.players[2].hero_id:return []
            return [RequestChoice(1,(ChoiceOption('ok','Okay'),),c.source_id)]
        def probe(c):
            if c.event.target_id!=c.state.players[2].hero_id:return []
            return [GainArmor(1,hero_attack_count(c.state,1,HeroAttackQuery('combat_accepted'))+
                10*hero_attack_count(c.state,1,HeroAttackQuery()))]
        self.watcher('pause',('health_resolved',),pause)
        self.watcher('probe',('health_resolved','attack_finished'),probe)
        g=self.game(board=('pause','probe'));self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.count(g),1)
        self.check(g);self.choose(g)
        self.assertEqual(g.state.entities[self.hero(g)].armor,12);self.check(g)

    def test_delivery_wait_reference_survives_real_choice_and_terminal(self):
        m=default_mechanics('u19-delivery-wait-test')
        def paused(r,e):
            tail=resolve_attack(r,e)
            return [RequestChoice(1,(ChoiceOption('ok','Okay'),ChoiceOption('kill','Kill',
                (Damage(r.state.players[1].hero_id,999),))),source_id=r.state.players[1].hero_id),*tail]
        m.replace(ResolveAttack,paused)
        g=self.game(mechanics=m);self.attack(g)
        row=g.state.hero_attack_history[0]
        self.assertIsNotNone(row.delivery);self.assertIsNone(row.combat);self.assertFalse(g.state.action_windows)
        self.check(g,m);restored=Game.from_snapshot(g.snapshot(),self.r,m)
        self.choose(g);self.choose(restored,'kill')
        self.assertEqual(self.count(g),1)
        self.assertEqual((restored.state.hero_attack_history[0].terminal.outcome,
            restored.state.hero_attack_history[0].terminal.stage),('interrupted','delivery_pending'))
        self.check(g,m);self.check(restored,m)

    def test_redirect_preserves_original_target_and_completed_current_target(self):
        self.watcher('redirect',('attack_declared',),lambda c:[RedirectAttack(c.state.action_windows[-1].id,c.state.players[2].board[0])])
        g=self.game(board=('redirect',),enemy=('plain',));declared=self.hero(g,2)
        self.attack(g);row=g.state.hero_attack_history[0];target=g.state.players[2].board[0]
        self.assertEqual(row.declaration.identity.declared_target_id,declared)
        self.assertEqual((row.delivery.target_id,row.combat.defender_id),(target,target));self.check(g)

    def test_rehashed_private_identity_tail_and_context_negatives(self):
        self.watcher('wait',('attack_declared',),lambda c:[RequestChoice(1,(ChoiceOption('ok','Okay'),),c.source_id)])
        g=self.game(board=('wait',));self.attack(g)
        for label in ('foreign_hero','owner','future','bool','duplicate','crop_tail'):
            with self.subTest(label=label):
                s=g.snapshot();row=s['state']['hero_attack_history'][0];i=row['declaration']['identity']
                if label=='foreign_hero':i['physical_hero_id']=self.hero(g,2)
                elif label=='owner':i['owner_turn_id']=2
                elif label=='future':i['window_id']=i['record_id']=s['state']['next_window_id']
                elif label=='bool':i['root_action_number']=True
                elif label=='duplicate':s['state']['hero_attack_history'].append(copy.deepcopy(row))
                else:s['resolution_frame']['fields']['continuation']['tuple']=[]
                self.assert_bad(s)
        for field in ('hero_attack_history','physical_hero_id','hero_attack','root_action_number'):
            self.assertNotIn('"'+field+'"',json.dumps(g.observe(1))+json.dumps(g.for_player(2).legal_actions()))
        self.choose(g);self.check(g)

    def test_bare_hero_combat_is_explicitly_rejected_without_fabricated_history(self):
        self.spell('raw',lambda c:[CombatDamage(c.state.players[1].hero_id,c.state.players[2].hero_id)])
        def exchange(c):
            a,b=c.state.players[1].hero_id,c.state.players[2].hero_id
            return [DamageBatch((Damage(b,2,a,DamageKind.COMBAT),Damage(a,2,b,DamageKind.COMBAT)),CombatExchange(a,b))]
        self.spell('batch',exchange)
        g=self.game(hand=('raw','batch'))
        for card in ('raw','batch'):
            before=g.snapshot()
            with self.assertRaisesRegex(ResolutionError,'Bare hero combat'):self.cast(g,card)
            self.assertEqual(before,g.snapshot())
        self.assertEqual(self.count(g,'declared'),0)
        self.check(g)

    def test_bare_minion_combat_compatibility_does_not_allocate_hero_history(self):
        self.spell('raw',lambda c:[CombatDamage(c.state.players[1].board[0],c.state.players[2].board[0])])
        g=self.game(board=('plain',),enemy=('plain',),hand=('raw',));self.cast(g,'raw')
        self.assertEqual([g.state.entities[g.state.players[p].board[0]].damage for p in (1,2)],[1,1])
        self.assertEqual(g.state.hero_attack_history,[]);self.check(g)

    def test_delivery_reference_and_choice_branch_control_tail_negatives(self):
        m=default_mechanics('u19-delivery-private-test')
        def paused(r,e):return [RequestChoice(1,(ChoiceOption('ok','Okay'),),source_id=r.state.players[1].hero_id),*resolve_attack(r,e)]
        m.replace(ResolveAttack,paused)
        g=self.game(mechanics=m);self.attack(g)
        for label in ('foreign','future','bool','duplicate_tail','crop_tail','offered_tail','missing_reference'):
            with self.subTest(label=label):
                s=g.snapshot();f=s['resolution_frame']['fields'];tail=f['continuation']['tuple'][0]
                i=tail['fields']['hero_attack']['fields']['identity']['fields']
                if label=='foreign':i['physical_hero_id']=self.hero(g,2)
                elif label=='future':i['record_id']=i['window_id']=s['state']['next_window_id']
                elif label=='bool':i['owner_turn_id']=True
                elif label=='duplicate_tail':f['continuation']['tuple'].append(copy.deepcopy(tail))
                elif label=='crop_tail':f['continuation']['tuple']=[]
                elif label=='offered_tail':f['options']['tuple'][0]['fields']['effects']['tuple'].append(copy.deepcopy(tail))
                else:tail['fields']['hero_attack']=None
                self.assert_bad(s,m)
        self.check(g,m);self.choose(g);self.assertEqual(self.count(g),1);self.check(g,m)

    def test_captured_health_context_future_cursor_is_not_trusted_as_live_tail(self):
        def pause(c):
            return [RequestChoice(1,(ChoiceOption('ok','Okay'),),c.source_id)] if c.event.target_id==c.state.players[2].hero_id else []
        self.watcher('pause',('health_resolved',),pause)
        self.watcher('probe',('health_resolved',),lambda c:[GainArmor(1,hero_attack_count(c.state,1))])
        g=self.game(board=('pause','probe'));self.attack(g);self.check(g)
        s=g.snapshot();found=[]
        def visit(value):
            if type(value) is dict:
                if set(value)=={'state'} and value['state'].get('hero_attack_history'):
                    row=value['state']['hero_attack_history'][0]
                    if row['combat'] is not None and row['terminal'] is None:found.append(row)
                for child in value.values():visit(child)
            elif type(value) is list:
                for child in value:visit(child)
        visit(s['resolution_frame']);self.assertTrue(found)
        found[0]['combat']['event_cursor']=10**9
        self.assert_bad(s);self.choose(g);self.check(g)

    def test_health_redirect_conversion_and_finished_lethal_preserve_completion(self):
        from hs_sim.engine import HealthRule, HealthFlow, HealthOp, HealthLayer
        for mode in ('redirect','convert','finished_lethal'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='finished_lethal':
                    self.watcher('route',('attack_finished',),lambda c:[Damage(c.event.source_id,999,c.source_id)])
                    g=self.game(board=('route',),enemy=('plain',))
                elif mode=='redirect':
                    rule=HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,layer=HealthLayer.TARGET,
                        target_relation='friendly',target_kinds=(CardType.MINION,),redirect_to='friendly_hero')
                    self.r.register_card(CardDefinition('route','route',CardType.MINION,health=100,health_rules=(rule,)))
                    g=self.game(enemy=('route','plain'))
                else:
                    rule=HealthRule(HealthFlow.DAMAGE,HealthOp.CONVERT,source_relation='friendly',damage_kinds=(DamageKind.COMBAT,))
                    self.r.register_card(CardDefinition('route','route',CardType.MINION,health=100,health_rules=(rule,)))
                    g=self.game(board=('route',),enemy=('plain',))
                target=g.state.players[2].board[-1];self.attack(g,target)
                row=g.state.hero_attack_history[0]
                self.assertEqual((row.delivery.target_id,row.combat.defender_id),(target,target))
                self.assertEqual(self.count(g),1)
                if mode!='finished_lethal':self.assertEqual(g.state.entities[target].health,30)
                else:self.assertEqual(g.state.winner,2)
                self.check(g)

    def test_declared_handler_exception_and_completed_reference_reuse_rollback(self):
        self.watcher('bad',('attack_declared',),lambda c:[EquipWeapon(1,'plain')])
        g=self.game(board=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.count(g,'declared'),0)
        self.setUp()
        from hs_sim.engine.model import HeroAttackReference
        def reuse(c):
            row=c.state.hero_attack_history[0]
            return [CombatDamage(row.declaration.identity.physical_hero_id,row.delivery.target_id,
                hero_attack=HeroAttackReference(row.declaration.identity,row.delivery))]
        self.spell('reuse',reuse);g=self.game(hand=('reuse',));self.attack(g);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'duplicated'):self.cast(g,'reuse')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.count(g),1);self.check(g)

if __name__=='__main__':unittest.main()
