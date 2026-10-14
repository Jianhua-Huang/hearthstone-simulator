"""Explicit same-controller forced combat and unchanged voluntary attacks."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (Attack, CardDefinition, CardType, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Damage, EquipWeapon, ForceAttack,
    Freeze, GainArmor, GrantKeyword, RandomForceAttack, RequestChoice, Summon, CombatExchange)
from hs_sim.engine.interrupts import RedirectAttack, SummonAttackTarget
from hs_sim.engine.model import ActionWindow
from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.model import AttackPolicySpec
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay

FRIEND = 'friendly_minions'

class ForcedRelationTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.minion('plain')
        self.minion('small', health=2)
        self.minion('poison', keywords=(Keyword.POISONOUS,))
        self.minion('stealth', keywords=(Keyword.STEALTH,))
        self.minion('immune', keywords=(Keyword.IMMUNE,))
        self.minion('shield', keywords=(Keyword.DIVINE_SHIELD,))
        self.minion('leech', keywords=(Keyword.LIFESTEAL,))
        self.minion('sleeping', dormant_turns=2)
        self.spell('friendly', lambda c: [ForceAttack(*c.state.players[1].board[:2], combat_relation=FRIEND)])
        self.spell('default', lambda c: [ForceAttack(*c.state.players[1].board[:2])])
        self.spell('random', lambda c: [RandomForceAttack(tuple(c.state.players[1].board),
            tuple(c.state.players[1].board + c.state.players[2].board), c.source_id, FRIEND)])

    def minion(self, name, attack=2, health=8, **fields):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, attack=attack, health=health, **fields))

    def spell(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def game(self, board=('plain','plain'), hand=('friendly',), enemy=(), seed=73):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', board=board, hand=hand, deck=('plain',)*12, mana=10,max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=('plain',)*12,mana=10,max_mana=10)),seed=seed),self.r)

    def cast(self, g, name):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        return g.apply(PlayCard(1,source))

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_friendly_force_is_real_simultaneous_combat_without_spending_opportunities(self):
        g=self.game();ids=g.state.players[1].board[:]
        result=self.cast(g,'friendly')
        self.assertEqual([g.state.entities[i].damage for i in ids],[2,2])
        self.assertEqual([g.state.entities[i].attacks_this_turn for i in ids],[0,0])
        self.assertEqual(sum(e.kind=='attack_declared' for e in result.events),1)
        self.assertEqual(sum(e.kind=='attack_finished' for e in result.events),1)
        hits=[e for e in result.events if e.kind=='damage_dealt']
        self.assertEqual(len(hits),2)
        self.assertTrue(all(dict(e.data)['damage_kind']=='combat' for e in hits))
        self.check(g)

    def test_default_force_still_rejects_friendly_pair_without_damage(self):
        g=self.game(hand=('default',));result=self.cast(g,'default')
        self.assertFalse(any(e.kind=='attack_declared' for e in result.events))
        self.assertEqual([g.state.entities[i].damage for i in g.state.players[1].board],[0,0])
        self.check(g)

    def test_player_cannot_submit_friendly_attack(self):
        g=self.game();a,d=g.state.players[1].board[:2];before=g.snapshot()
        self.assertFalse(any(isinstance(x,Attack) and x.defender_id==d for x in g.legal_actions()))
        with self.assertRaises(IllegalAction):g.apply(Attack(1,a,d))
        self.assertEqual(before,g.snapshot())

    def test_forced_pair_ignores_freeze_restriction_and_consumes_stealth_only(self):
        self.spell('restricted',lambda c:[Freeze(c.state.players[1].board[0]),
            GrantAttackPolicy(c.state.players[1].board[0],AttackPolicySpec('cannot_attack')),
            ForceAttack(*c.state.players[1].board[:2],combat_relation=FRIEND)])
        g=self.game(board=('stealth','plain'),hand=('restricted',));a,d=g.state.players[1].board
        self.cast(g,'restricted')
        self.assertTrue(g.state.entities[a].frozen)
        self.assertNotIn(Keyword.STEALTH,g.state.entities[a].keywords)
        self.assertEqual(g.state.entities[d].damage,2)
        self.assertEqual(g.state.entities[a].attacks_this_turn,0)
        self.check(g)

    def test_damage_prevention_does_not_erase_retaliation(self):
        for target in ('immune','shield'):
            with self.subTest(target=target):
                g=self.game(board=('plain',target));a,d=g.state.players[1].board[:]
                result=self.cast(g,'friendly')
                self.assertEqual(g.state.entities[d].damage,0)
                self.assertEqual(g.state.entities[a].damage,2)
                self.assertEqual(sum(e.kind=='attack_finished' for e in result.events),1)
                self.check(g)

    def test_lifesteal_belongs_to_current_attacker_controller(self):
        self.spell('leechfight',lambda c:[Damage(c.state.players[1].hero_id,7),
            ForceAttack(*c.state.players[1].board[:2],combat_relation=FRIEND)])
        g=self.game(board=('leech','plain'),hand=('leechfight',))
        self.cast(g,'leechfight')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage,5)
        self.check(g)

    def test_both_friendly_deaths_have_real_deathrattles_and_corpses(self):
        self.r.register_behavior('dead',lambda c:[GainArmor(c.player_id,1)])
        self.minion('doomed_pair',health=2,deathrattle='dead')
        g=self.game(board=('doomed_pair','doomed_pair'));result=self.cast(g,'friendly')
        self.assertFalse(g.state.players[1].board)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(len(g.state.death_history),2)
        self.assertEqual(sum(e.kind=='minion_died' for e in result.events),2)
        self.check(g)

    def test_poisonous_friendly_combat_uses_shared_death_path(self):
        g=self.game(board=('poison','plain'));a,d=g.state.players[1].board[:]
        self.cast(g,'friendly')
        self.assertEqual(g.state.players[1].board,[a])
        self.assertEqual(g.state.entities[a].damage,2)
        self.assertEqual(g.state.entities[d].zone.value,'graveyard')
        self.check(g)

    def test_friendly_policy_never_targets_hero_or_self(self):
        self.spell('hero',lambda c:[ForceAttack(c.state.players[1].board[0],
            c.state.players[1].hero_id,combat_relation=FRIEND)])
        self.spell('self',lambda c:[ForceAttack(c.state.players[1].board[0],
            c.state.players[1].board[0],combat_relation=FRIEND)])
        for name in ('hero','self'):
            g=self.game(board=('plain',),hand=(name,));result=self.cast(g,name)
            self.assertFalse(any(e.kind=='attack_declared' for e in result.events))
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].damage,0)
            self.assertEqual(g.state.entities[g.state.players[1].board[0]].damage,0)
            self.check(g)

    def test_random_pair_uses_same_controller_distinct_live_minions(self):
        g=self.game(board=('plain','plain','sleeping'),hand=('random',),enemy=('plain',))
        original=g.state.players[1].board[:2]
        result=self.cast(g,'random')
        chosen=[e for e in result.events if e.kind=='random_choice']
        self.assertEqual(len(chosen),1)
        self.assertIn(chosen[0].target_id,original)
        defender=dict(chosen[0].data)['defender_id']
        self.assertIn(defender,original);self.assertNotEqual(defender,chosen[0].target_id)
        self.assertEqual([g.state.entities[i].damage for i in original],[2,2])
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage,0)
        self.check(g)

    def test_empty_random_friendly_pool_keeps_rng_and_does_not_fallback_to_enemy(self):
        g=self.game(board=('plain',),hand=('random',),enemy=('plain',))
        before=g._rng.getstate();result=self.cast(g,'random')
        self.assertEqual(g._rng.getstate(),before)
        self.assertFalse(any(e.kind in ('random_choice','attack_declared') for e in result.events))
        self.check(g)

    def test_transfer_one_combatant_cancels_changed_friendly_relation(self):
        self.r.register_behavior('take',lambda c:[ChangeControl(c.event.target_id,2)])
        self.minion('watched',triggers=(TriggerSpec('attack_declared','take'),))
        g=self.game(board=('watched','plain'));result=self.cast(g,'friendly')
        self.assertFalse(any(e.kind=='damage_dealt' for e in result.events))
        cancels=[e for e in result.events if e.kind=='attack_cancelled']
        self.assertEqual(len(cancels),1)
        self.assertEqual(dict(cancels[0].data)['reason'],'combat_relation_changed')
        self.assertFalse(g.state.action_windows);self.check(g)

    def test_transfer_both_preserves_current_same_controller_relation(self):
        self.r.register_behavior('takeboth',lambda c:[ChangeControl(c.event.source_id,2),ChangeControl(c.event.target_id,2)])
        self.minion('watched',triggers=(TriggerSpec('attack_declared','takeboth'),))
        g=self.game(board=('watched','plain'));ids=g.state.players[1].board[:]
        self.cast(g,'friendly')
        self.assertEqual([g.state.entities[i].controller for i in ids],[2,2])
        self.assertEqual([g.state.entities[i].damage for i in ids],[2,2])
        self.check(g)

    def test_redirect_uses_captured_relation_and_rejects_hero_self_and_enemy(self):
        def redirect(c):
            selector=c.state.entities[c.source_id].card_id.rsplit('.',1)[-1]
            targets={'friend':c.state.players[1].board[2],'enemy':c.state.players[2].board[0],
                     'hero':c.state.players[1].hero_id,'self':c.event.source_id}
            return [RedirectAttack(dict(c.event.data)['window_id'],targets[selector])]
        self.r.register_behavior('redirect',redirect)
        for selector in ('friend','enemy','hero','self'):
            self.minion('watch.'+selector,triggers=(TriggerSpec('attack_declared','redirect'),))
        for selector in ('friend','enemy','hero','self'):
            with self.subTest(selector=selector):
                g=self.game(board=('watch.'+selector,'plain','plain'),enemy=('plain',))
                a,d,new=g.state.players[1].board[:]
                result=self.cast(g,'friendly')
                self.assertEqual(g.state.entities[d].damage,0 if selector=='friend' else 2)
                self.assertEqual(g.state.entities[new].damage,2 if selector=='friend' else 0)
                self.assertEqual(g.state.entities[a].damage,2)
                self.check(g)

    def test_summoned_redirect_target_can_share_controller(self):
        self.r.register_behavior('summontarget',lambda c:[SummonAttackTarget(dict(c.event.data)['window_id'],1,'small')])
        self.minion('watched',triggers=(TriggerSpec('attack_declared','summontarget'),))
        g=self.game(board=('watched','plain'));a,d=g.state.players[1].board[:]
        result=self.cast(g,'friendly')
        self.assertEqual(g.state.entities[d].damage,0)
        self.assertEqual(g.state.entities[a].damage,2)
        self.assertEqual(len(g.state.death_history),1)
        self.assertTrue(any(e.kind=='attack_redirected' for e in result.events))
        self.check(g)

    def waiting_game(self):
        def pause(c):
            if c.event.source_id!=c.source_id:return ()
            inner=ForceAttack(*c.state.players[1].board[2:4],combat_relation=FRIEND)
            return [RequestChoice(1,(ChoiceOption('continue','Continue',(inner,)),
                ChoiceOption('bad','Bad',(EquipWeapon(1,'plain'),))),source_id=c.source_id)]
        self.r.register_behavior('pause',pause)
        self.minion('watched',triggers=(TriggerSpec('attack_declared','pause'),))
        g=self.game(board=('watched','plain','plain','plain'))
        self.cast(g,'friendly')
        self.assertIsNotNone(g.state.pending_choice)
        return g

    def test_waiting_private_window_and_nested_effect_restore_clone_replay(self):
        g=self.waiting_game();ids=g.state.players[1].board[:]
        self.assertEqual(g.state.action_windows[0].combat_relation,FRIEND)
        self.assertTrue(g.state.action_windows[0].forced)
        self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        action=SelectChoice(1,g.state.pending_choice.id,('continue',))
        g.apply(action);restored.apply(action)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual([g.state.entities[i].damage for i in ids],[2,2,2,2])
        self.assertEqual([g.state.entities[i].attacks_this_turn for i in ids],[0,0,0,0])
        self.assertFalse(g.state.action_windows);self.check(g)

    def test_waiting_failed_choice_rolls_back_window_and_queued_attack(self):
        g=self.waiting_game();before=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(before,g.snapshot());self.check(g)

    def test_invalid_relation_and_nonforced_window_and_snapshot_are_rejected(self):
        for invalid in ('any','ally',None,True,1):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):ForceAttack(1,2,combat_relation=invalid)
                with self.assertRaises(ValueError):RandomForceAttack((1,),(2,),combat_relation=invalid)
                with self.assertRaises(ValueError):CombatExchange(1,2,combat_relation=invalid)
        with self.assertRaises(ValueError):ActionWindow(1,'attack',1,1,2,combat_relation=FRIEND)
        with self.assertRaises(ValueError):CombatExchange(1,2,3,combat_relation=FRIEND)
        g=self.waiting_game();before=g.snapshot();bad=deepcopy(before)
        bad['state']['action_windows'][0]['combat_relation']='any'
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,self.r)
        self.assertEqual(g.snapshot(),before)

    def test_player_choice_actions_do_not_expose_combat_policy(self):
        g=self.waiting_game()
        commands=g.for_player(1).legal_actions()
        self.assertTrue(commands['actions'])
        self.assertNotIn('combat_relation',json.dumps(commands))
        self.assertNotIn('friendly_minions',json.dumps(commands))
        chosen=next(a for a in commands['actions'] if a.get('options')==['o1'])
        result=g.for_player(1).submit({'revision':commands['revision'],'action':chosen})
        self.assertTrue(result['accepted'])
        self.assertIsNone(g.state.pending_choice)
        self.check(g)

    def test_late_execution_failure_rolls_back_damage_rng_and_deaths(self):
        self.spell('bad',lambda c:[ForceAttack(*c.state.players[1].board[:2],combat_relation=FRIEND),
            RandomForceAttack(tuple(c.state.players[1].board),tuple(c.state.players[1].board),
                              c.source_id,FRIEND),EquipWeapon(1,'plain')])
        g=self.game(hand=('bad',));before=g.snapshot();rng=g._rng.getstate()
        with self.assertRaises(ResolutionError):self.cast(g,'bad')
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(g._rng.getstate(),rng)

if __name__=='__main__':unittest.main()
