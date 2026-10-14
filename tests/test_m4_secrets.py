"""Hidden information and resumable spell/attack interruption contracts."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, CounterSpell, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, RemoveSecret, ResolutionError,
    Ruleset, Scenario, SecretSpec, SelectChoice, SetSecret, SnapshotError, TriggerSpec,
    UseHeroPower, Zone)
from hs_sim.engine import TargetMode, TargetSpec
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, ForceAttack, GainArmor, RequestChoice, Summon)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.secrets import CheckSecret
from hs_sim.engine.serialization import canonical_hash


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('small','Small',CardType.MINION,attack=2,health=2))
        self.r.register_card(CardDefinition('big','Big',CardType.MINION,attack=4,health=8))
        self.r.register_behavior('yes',lambda c:[GainArmor(c.player_id,1)])
        self.r.register_secret_condition('yes',lambda c:True)
        self.spell('noop',lambda c:[])

    def spell(self,name,callback):
        self.r.register_behavior(name,callback)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))

    def secret(self,name='secret',events=('card_committed',),condition='yes',behavior='yes',turn='opponent',key=None):
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec(key or name,events,condition,behavior,turn)))

    def game(self,hand=(),enemy_hand=(),board=(),enemy_board=(),rules=None,weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01',hand=hand,board=board,deck=('small',)*20,max_mana=10,mana=10),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('small',)*20,max_mana=10,mana=10,
                weapon_card_id=weapon,hero_power_card_id='HERO_08bp')),seed=96),self.r,ruleset=rules)

    def play(self,g,name,target=None):
        player=g.state.active_player
        source=next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(player,source,target))

    def arm(self,g,*names):
        for name in names:self.play(g,name)
        g.apply(EndTurn(1))

    def attack(self,g,target=None,attacker=None):
        state=g.state;attacker=attacker or state.players[2].board[0]
        g.apply(Attack(2,attacker,target or state.players[1].hero_id))

    def secrets(self,g,player=1):
        return [g.state.entities[i].card_id for i in g.state.players[player].secrets]

    def hero(self,g,player=1):
        return g.state.entities[g.state.players[player].hero_id]

    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_play_uses_hidden_independent_zone_and_pays(self):
        g=self.game(hand=('EX1_287',),board=('small',)*7);source=g.state.players[1].hand[0];self.play(g,'EX1_287')
        self.assertEqual(g.state.entities[source].zone,Zone.SECRET);self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(g.observe(1)['players'][0]['secrets'][0]['card_id'],'EX1_287')
        back=g.observe(2)['players'][0]['secrets'][0]
        self.assertIsNone(back['card_id']);self.assertEqual(back['classes'],['mage']);self.assertNotIn('keywords',back);self.check(g)

    def test_generated_secret_never_reveals_card_through_hand_or_log(self):
        self.spell('set',lambda c:[SetSecret(c.player_id,'EX1_287')]);g=self.game(hand=('set',));self.play(g,'set')
        self.assertEqual(self.secrets(g),['EX1_287']);self.assertNotIn('EX1_287',json.dumps(g.observe(2)))
        self.assertNotIn('EX1_287',json.dumps(g.player_events(2)));self.check(g)

    def test_duplicate_secret_rejected_transactionally(self):
        g=self.game(hand=('EX1_287','EX1_287'));self.play(g,'EX1_287');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'EX1_287')
        self.assertEqual(before,g.snapshot())

    def test_aliases_share_explicit_secret_identity(self):
        self.secret('alias',key='EX1_287');g=self.game(hand=('EX1_287','alias'));self.play(g,'EX1_287')
        with self.assertRaises(IllegalAction):self.play(g,'alias')

    def test_shared_area_capacity_includes_quests_and_timed_effects(self):
        g=self.game(hand=('ULD_155','BAR_306','EX1_287'),rules=Ruleset(max_secret_zone=2))
        self.play(g,'ULD_155');self.play(g,'BAR_306');before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'EX1_287')
        self.assertEqual(before,g.snapshot());self.check(g)

    def test_secret_blocks_quest_and_ongoing_at_shared_capacity(self):
        g=self.game(hand=('EX1_287','ULD_155','BAR_306'),rules=Ruleset(max_secret_zone=1));self.play(g,'EX1_287')
        for name in ('ULD_155','BAR_306'):
            with self.assertRaises(IllegalAction):self.play(g,name)

    def test_failed_generation_does_not_allocate_or_reveal_secret(self):
        self.spell('set',lambda c:[SetSecret(c.player_id,'EX1_287')]);g=self.game(hand=('EX1_287','set'))
        self.play(g,'EX1_287');next_id=g.state.next_entity_id;self.play(g,'set')
        self.assertEqual(g.state.next_entity_id,next_id);self.assertEqual(len(self.secrets(g)),1)

    def test_secret_not_triggered_during_owner_turn(self):
        self.secret();g=self.game(hand=('secret','noop'));self.play(g,'secret');self.play(g,'noop')
        self.assertEqual(self.secrets(g),['secret']);self.assertEqual(self.hero(g).armor,0)

    def test_owner_turn_policy_is_explicit_exception(self):
        self.secret(turn='owner');g=self.game(hand=('secret','noop'));self.play(g,'secret');self.play(g,'noop')
        self.assertFalse(self.secrets(g));self.assertEqual(self.hero(g).armor,1);self.check(g)

    def test_counterspell_pays_cost_and_prevents_spell_effect(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('CS2_029',));self.arm(g,'EX1_287');self.play(g,'CS2_029',self.hero(g).id)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(g.state.players[2].mana,6)
        self.assertFalse(self.secrets(g));self.assertTrue(any(e.kind=='spell_countered' for e in g.events));self.check(g)

    def test_countered_spell_still_has_before_and_after_cast_reactions(self):
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=3,
            triggers=(TriggerSpec('card_committed','yes'),TriggerSpec('card_played','yes'))))
        g=self.game(hand=('EX1_287',),enemy_hand=('noop',),enemy_board=('watcher',));self.arm(g,'EX1_287')
        before=self.hero(g,2).armor;self.play(g,'noop');self.assertEqual(self.hero(g,2).armor-before,2);self.check(g)

    def test_counterspell_does_not_counter_minions(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('small',));self.arm(g,'EX1_287');self.play(g,'small')
        self.assertEqual(self.secrets(g),['EX1_287']);self.assertTrue(g.state.players[2].board)

    def test_counterspell_does_not_counter_hero_power(self):
        g=self.game(hand=('EX1_287',));self.arm(g,'EX1_287')
        g.apply(UseHeroPower(2,g.state.players[2].hero_power_id,self.hero(g).id))
        self.assertEqual(self.hero(g).health,29);self.assertTrue(self.secrets(g))

    def test_countered_quest_never_activates(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('ULD_155',));self.arm(g,'EX1_287');self.play(g,'ULD_155')
        self.assertFalse(g.state.players[2].quests);self.check(g)

    def test_countered_ongoing_spell_never_installs_effect(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('BAR_306',));self.arm(g,'EX1_287');self.play(g,'BAR_306')
        self.assertFalse(g.state.players[2].player_effects);self.check(g)

    def test_countered_secret_reveals_but_never_activates(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('EX1_289',));self.arm(g,'EX1_287');self.play(g,'EX1_289')
        self.assertFalse(self.secrets(g,2));self.assertIn('EX1_289',json.dumps(g.player_events(1)));self.check(g)

    def test_freezing_returns_attacker_and_cancels_exchange(self):
        g=self.game(hand=('EX1_611',),enemy_board=('big',));self.arm(g,'EX1_611');attacker=g.state.players[2].board[0]
        self.attack(g);self.assertEqual(g.state.entities[attacker].zone,Zone.HAND)
        self.assertEqual(g.state.entities[attacker].cost,2);self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_freezing_uses_owner_instead_of_current_controller(self):
        self.spell('give',lambda c:[ChangeControl(c.state.players[1].board[0],2)])
        g=self.game(hand=('EX1_611','give'),board=('big',));self.play(g,'give');self.arm(g,'EX1_611');self.attack(g)
        card=next(g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id=='big')
        self.assertEqual((card.owner,card.controller,card.cost),(1,1,2));self.check(g)

    def test_freezing_full_owner_hand_destroys_original_attacker(self):
        from hs_sim.engine import Resource
        g=self.game(hand=('EX1_611',),enemy_hand=('noop',)*10,enemy_board=('big',));self.arm(g,'EX1_611')
        attacker=g.state.players[2].board[0];self.attack(g)
        self.assertEqual(g.state.entities[attacker].zone,Zone.GRAVEYARD)
        death, = g.state.death_history
        self.assertEqual((death.entity_id,death.owner,death.controller,death.base_cost),(attacker,2,2,0))
        self.assertEqual((death.cause.kind,death.cause.reason),('destroy','ReturnToHand'))
        self.assertEqual(death.enchantments,())
        self.assertEqual(g.state.players[2].resources[Resource.CORPSES],1)
        self.assertEqual(self.hero(g).health,30)
        self.assertEqual(sum(e.kind=='minion_died' for e in g.events),1)
        self.check(g)

    def test_freezing_does_not_trigger_for_hero_attack(self):
        g=self.game(hand=('EX1_611',),weapon='CS2_106');self.arm(g,'EX1_611');self.attack(g,attacker=self.hero(g,2).id)
        self.assertEqual(self.secrets(g),['EX1_611']);self.assertEqual(self.hero(g).health,27)

    def test_explosive_damage_can_cancel_attack_by_killing_attacker(self):
        g=self.game(hand=('EX1_610',),enemy_board=('small','big'));self.arm(g,'EX1_610');self.attack(g)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(self.hero(g,2).health,28)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,6);self.check(g)

    def test_explosive_uses_current_spell_damage(self):
        g=self.game(hand=('EX1_610',),board=('EX1_012',),enemy_board=('big',));self.arm(g,'EX1_610');self.attack(g)
        self.assertEqual(self.hero(g,2).health,27);self.assertEqual(self.hero(g).health,26)

    def test_explosive_does_not_trigger_on_minion_target(self):
        g=self.game(hand=('EX1_610',),board=('big',),enemy_board=('small',));self.arm(g,'EX1_610')
        self.attack(g,target=g.state.players[1].board[0]);self.assertEqual(self.secrets(g),['EX1_610'])

    def test_freezing_before_explosive_leaves_explosive_armed(self):
        g=self.game(hand=('EX1_611','EX1_610'),enemy_board=('big',));self.arm(g,'EX1_611','EX1_610');self.attack(g)
        self.assertEqual(self.secrets(g),['EX1_610']);self.assertEqual(self.hero(g,2).health,30);self.check(g)

    def test_explosive_lethal_before_freezing_leaves_freezing_armed(self):
        g=self.game(hand=('EX1_610','EX1_611'),enemy_board=('small',));self.arm(g,'EX1_610','EX1_611');self.attack(g)
        self.assertEqual(self.secrets(g),['EX1_611']);self.check(g)

    def test_nonlethal_explosive_then_freezing_both_resolve(self):
        g=self.game(hand=('EX1_610','EX1_611'),enemy_board=('big',));self.arm(g,'EX1_610','EX1_611');self.attack(g)
        self.assertFalse(self.secrets(g));self.assertEqual(self.hero(g,2).health,28);self.assertEqual(self.hero(g).health,30)

    def test_ice_barrier_gains_armor_before_combat(self):
        g=self.game(hand=('EX1_289',),enemy_board=('small',));self.arm(g,'EX1_289');self.attack(g)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(30,6));self.check(g)

    def test_noble_sacrifice_replaces_target_with_returned_summon(self):
        g=self.game(hand=('EX1_130',),enemy_board=('big',));self.arm(g,'EX1_130');self.attack(g)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,6)
        self.assertEqual(g.state.death_history[0].card_id,'EX1_130a');self.check(g)

    def test_noble_redirect_stops_later_hero_only_secret(self):
        g=self.game(hand=('EX1_130','EX1_610'),enemy_board=('big',));self.arm(g,'EX1_130','EX1_610');self.attack(g)
        self.assertEqual(self.secrets(g),['EX1_610']);self.assertEqual(self.hero(g,2).health,30)

    def test_noble_does_not_trigger_without_board_space(self):
        g=self.game(hand=('EX1_130',),board=('big',)*7,enemy_board=('small',));self.arm(g,'EX1_130');self.attack(g)
        self.assertEqual(self.secrets(g),['EX1_130']);self.assertEqual(self.hero(g).health,28)

    def test_defender_killed_by_summon_reaction_cancels_original_attack(self):
        self.r.register_behavior('kill_defender',lambda c:[Destroy(c.event.target_id)]
            if c.state.entities[c.event.target_id].card_id=='EX1_130a' else [])
        self.r.register_card(CardDefinition('killer','Killer',CardType.MINION,health=3,triggers=(TriggerSpec('minion_summoned','kill_defender'),)))
        g=self.game(hand=('EX1_130',),board=('killer',),enemy_board=('big',));self.arm(g,'EX1_130');self.attack(g)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,8);self.check(g)

    def test_mirror_waits_until_after_battlecry(self):
        self.r.register_behavior('grow',lambda c:[Buff(c.source_id,attack=2,health=2)])
        self.r.register_card(CardDefinition('cry','Cry',CardType.MINION,attack=1,health=1,on_play='grow'))
        g=self.game(hand=('EX1_294',),enemy_hand=('cry',));self.arm(g,'EX1_294');self.play(g,'cry')
        self.assertEqual([g.state.entities[p.board[0]].attack for p in g.state.players.values()],[3,3]);self.check(g)

    def test_mirror_does_not_trigger_on_effect_summon(self):
        self.spell('summon',lambda c:[Summon(c.player_id,'small')]);g=self.game(hand=('EX1_294',),enemy_hand=('summon',))
        self.arm(g,'EX1_294');self.play(g,'summon');self.assertEqual(self.secrets(g),['EX1_294'])

    def test_mirror_skips_minion_that_dies_during_battlecry(self):
        self.r.register_behavior('die',lambda c:[Destroy(c.source_id)])
        self.r.register_card(CardDefinition('cry','Cry',CardType.MINION,health=1,on_play='die'))
        g=self.game(hand=('EX1_294',),enemy_hand=('cry',));self.arm(g,'EX1_294');self.play(g,'cry')
        self.assertEqual(self.secrets(g),['EX1_294'])

    def test_mirror_waits_when_owner_board_is_full(self):
        g=self.game(hand=('EX1_294',),board=('small',)*7,enemy_hand=('big',));self.arm(g,'EX1_294');self.play(g,'big')
        self.assertEqual(self.secrets(g),['EX1_294'])

    def test_hidden_secret_identity_does_not_change_opponent_observation_or_actions(self):
        pairs=[]
        for card in ('EX1_287','EX1_289'):
            g=self.game(hand=(card,),enemy_hand=('CS2_029',),enemy_board=('small',));self.arm(g,card)
            pairs.append((g.observe(2),g.player_events(2),g.for_player(2).legal_actions()))
        self.assertEqual(pairs[0],pairs[1])

    def test_reveal_does_not_rewrite_old_hidden_logs(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('noop',));self.arm(g,'EX1_287');old=g.player_events(2)
        self.play(g,'noop');self.assertNotIn('EX1_287',json.dumps(old))
        self.assertIn('EX1_287',json.dumps(g.player_events(2)));self.check(g)

    def test_removal_reveals_without_executing_secret(self):
        self.spell('remove',lambda c:[RemoveSecret(c.state.players[1].secrets[0])])
        g=self.game(hand=('EX1_610',),enemy_hand=('remove',));self.arm(g,'EX1_610');self.play(g,'remove')
        self.assertFalse(self.secrets(g));self.assertEqual(self.hero(g,2).health,30)
        self.assertIn('EX1_610',json.dumps(g.player_events(2)));self.check(g)

    def test_pending_secret_choice_preserves_attack_and_remaining_checks(self):
        self.r.register_behavior('choose',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','Armor',(GainArmor(c.player_id,3),)),),c.source_id)])
        self.secret(events=('attack_declared',),behavior='choose')
        g=self.game(hand=('secret','EX1_289'),enemy_board=('small',));self.arm(g,'secret','EX1_289');self.attack(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.action_windows),1)
        self.assertEqual(self.hero(g).health,30);self.assertEqual(self.secrets(g),['EX1_289']);self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('armor',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g).armor,9);self.assertFalse(g.state.action_windows);self.check(g)

    def test_choice_can_counter_pending_spell_after_restore(self):
        self.r.register_behavior('choose_counter',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('counter','Counter',(CounterSpell(c.window.id),)),),c.source_id)])
        self.secret(behavior='choose_counter');g=self.game(hand=('secret',),enemy_hand=('CS2_029',))
        self.arm(g,'secret');self.play(g,'CS2_029',self.hero(g).id);self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        restored.apply(SelectChoice(1,restored.state.pending_choice.id,('counter',)))
        self.assertEqual(self.hero(restored).health,30);self.assertFalse(restored.state.action_windows);self.check(restored)

    def test_secret_consumed_before_recursive_matching_event(self):
        self.secret(events=('card_played',))
        g=self.game(hand=('secret',),enemy_hand=('noop','noop'));self.arm(g,'secret')
        self.play(g,'noop');self.play(g,'noop');self.assertEqual(self.hero(g).armor,1)

    def test_condition_reads_detached_state(self):
        def mutate(c):
            c.state.players[1].hand.clear();return False
        self.r.register_secret_condition('mutate',mutate);self.secret(condition='mutate')
        g=self.game(hand=('secret','big'),enemy_hand=('noop',));self.arm(g,'secret');self.play(g,'noop')
        self.assertEqual(len(g.state.players[1].hand),1);self.assertTrue(self.secrets(g))

    def test_nonboolean_condition_rolls_back_whole_action(self):
        self.r.register_secret_condition('bad',lambda c:1);self.secret(condition='bad')
        g=self.game(hand=('secret',),enemy_hand=('noop',));self.arm(g,'secret');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'noop')
        self.assertEqual(g.snapshot(),before)

    def test_failure_after_secret_reveal_restores_hidden_information_and_payment(self):
        self.r.register_behavior('bad',lambda c:[SetSecret(1,'big')]);self.secret(behavior='bad')
        g=self.game(hand=('secret',),enemy_hand=('CS2_029',));self.arm(g,'secret');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'CS2_029',self.hero(g).id)
        self.assertEqual(before,g.snapshot())

    def test_secret_added_during_matching_event_waits_for_later_event(self):
        self.secret('later');self.r.register_behavior('install',lambda c:[SetSecret(1,'later')])
        self.secret('first',behavior='install');g=self.game(hand=('first',),enemy_hand=('noop','noop'));self.arm(g,'first')
        self.play(g,'noop');self.assertEqual(self.hero(g).armor,0);self.assertEqual(self.secrets(g),['later'])
        self.play(g,'noop');self.assertEqual(self.hero(g).armor,1);self.check(g)

    def test_nested_forced_attack_preserves_outer_window(self):
        self.r.register_behavior('nested',lambda c:[ForceAttack(c.state.players[2].board[1],c.state.players[1].hero_id)])
        self.secret(events=('attack_declared',),behavior='nested');g=self.game(hand=('secret',),enemy_board=('big','small'))
        self.arm(g,'secret');self.attack(g);self.assertEqual(self.hero(g).health,24)
        self.assertFalse(g.state.action_windows);self.check(g)

    def test_lethal_secret_ends_game_without_remaining_combat_or_windows(self):
        self.r.register_behavior('lethal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        self.secret(events=('attack_declared',),behavior='lethal');g=self.game(hand=('secret',),enemy_board=('big',))
        self.arm(g,'secret');self.attack(g);self.assertEqual(g.state.winner,1);self.assertEqual(self.hero(g).health,30)
        self.assertFalse(g.state.action_windows);self.check(g)

    def test_secret_definition_requires_keyword_and_explicit_registration(self):
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.SPELL,keywords=(Keyword.SECRET,)))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.SPELL,secret=SecretSpec('a',('x',),'yes','yes')))

    def test_secret_condition_references_and_freeze_are_validated(self):
        self.secret(condition='missing')
        with self.assertRaises(ValueError):self.r.freeze()

    def test_secret_invalid_turn_and_mutable_events_rejected(self):
        for events,turn in ((['x'],'opponent'),((),'opponent'),(('x','x'),'opponent'),(('x',),'sometimes')):
            with self.assertRaises(ValueError):SecretSpec('a',events,'yes','yes',turn)

    def test_registry_fingerprint_includes_secret_conditions(self):
        old=self.r.fingerprint();self.r.register_secret_condition('extra',lambda c:False)
        self.assertNotEqual(old,self.r.fingerprint());self.r.freeze()
        with self.assertRaises(ValueError):self.r.register_secret_condition('other',lambda c:False)

    def test_secret_instance_collision_and_wrong_zone_rejected(self):
        g=self.game(hand=('EX1_287',));self.play(g,'EX1_287')
        for value in (None,True,0):
            data=g.snapshot();source=g.state.players[1].secrets[0];data['state']['entities'][str(source)]['secret_instance_id']=value
            with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_old_schema_rejected(self):
        g=self.game();data=g.snapshot();self.assertEqual(data['schema_version'],265);data['schema_version']=25
        with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_spellbender_redirects_minion_spell_to_fresh_token(self):
        g=self.game(hand=('tt_010',),board=('big',),enemy_hand=('CS2_029',));self.arm(g,'tt_010')
        target=g.state.players[1].board[0];self.play(g,'CS2_029',target)
        self.assertEqual(g.state.entities[target].health,8);self.assertEqual(g.state.death_history[0].card_id,'tt_010a')
        self.assertFalse(self.secrets(g));self.check(g)

    def test_spellbender_can_redirect_buff_on_opponents_own_minion(self):
        self.r.register_behavior('buff',lambda c:[Buff(c.target_id,attack=2,health=2)])
        self.r.register_card(CardDefinition('buff','Buff',CardType.SPELL,on_play='buff',targeting=TargetSpec(
            TargetMode.REQUIRED,relation='friendly',zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
        g=self.game(hand=('tt_010',),enemy_board=('big',),enemy_hand=('buff',));self.arm(g,'tt_010')
        target=g.state.players[2].board[0];self.play(g,'buff',target)
        self.assertEqual(g.state.entities[target].attack,4)
        token=g.state.entities[g.state.players[1].board[0]];self.assertEqual((token.attack,token.health),(3,5));self.check(g)

    def test_spellbender_ignores_hero_target_and_untargeted_spell(self):
        g=self.game(hand=('tt_010',),enemy_hand=('noop','CS2_029'));self.arm(g,'tt_010')
        self.play(g,'noop');self.play(g,'CS2_029',self.hero(g).id)
        self.assertEqual(self.secrets(g),['tt_010']);self.assertEqual(self.hero(g).health,24)

    def test_counterspell_precedes_target_replacement_in_either_play_order(self):
        for order in (('tt_010','EX1_287'),('EX1_287','tt_010')):
            with self.subTest(order=order):
                g=self.game(hand=order,board=('big',),enemy_hand=('CS2_029',));self.arm(g,*order)
                self.play(g,'CS2_029',g.state.players[1].board[0])
                self.assertEqual(self.secrets(g),['tt_010']);self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_spellbender_requires_free_board_slot(self):
        g=self.game(hand=('tt_010',),board=('big',)*7,enemy_hand=('CS2_029',));self.arm(g,'tt_010')
        target=g.state.players[1].board[0];self.play(g,'CS2_029',target)
        self.assertEqual(self.secrets(g),['tt_010']);self.assertEqual(g.state.entities[target].health,2)

    def test_killed_spell_replacement_target_does_not_restore_original_target(self):
        self.r.register_behavior('kill_token',lambda c:[Destroy(c.event.target_id)]
            if c.state.entities[c.event.target_id].card_id=='tt_010a' else [])
        self.r.register_card(CardDefinition('killer','Killer',CardType.MINION,health=3,triggers=(TriggerSpec('minion_summoned','kill_token'),)))
        g=self.game(hand=('tt_010',),board=('big','killer'),enemy_hand=('CS2_029',));self.arm(g,'tt_010')
        target=g.state.players[1].board[0];self.play(g,'CS2_029',target)
        self.assertEqual(g.state.entities[target].health,8);self.check(g)

    def test_target_phase_choice_restores_before_spell_effect(self):
        self.r.register_behavior('choose',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('counter','Counter',(CounterSpell(c.window.id),)),),c.source_id)])
        self.secret(events=('spell_targeted',),behavior='choose')
        g=self.game(hand=('secret',),enemy_hand=('CS2_029',));self.arm(g,'secret');self.play(g,'CS2_029',self.hero(g).id)
        self.assertTrue(g.state.action_windows[0].target_phase);self.check(g)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('counter',)));self.assertEqual(self.hero(g).health,30);self.check(g)

    def test_window_state_and_continuation_must_match_even_with_valid_hash(self):
        self.r.register_behavior('choose',lambda c:[RequestChoice(c.player_id,(
            ChoiceOption('armor','Armor',(GainArmor(c.player_id,1),)),),c.source_id)])
        self.secret(events=('attack_declared',),behavior='choose')
        g=self.game(hand=('secret',),enemy_board=('small',));self.arm(g,'secret');self.attack(g)
        for change in ('missing','phase','source','id'):
            with self.subTest(change=change):
                data=g.snapshot();window=data['state']['action_windows'][0]
                if change=='missing':data['state']['action_windows']=[]
                elif change=='phase':window['target_phase']=True
                elif change=='source':window['source_id']=g.state.players[1].graveyard[0]
                else:window['id']=data['state']['next_window_id']
                data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_stale_counter_does_not_counter_a_new_spell(self):
        self.spell('stale',lambda c:[CounterSpell(99999)])
        g=self.game(hand=('stale',));self.play(g,'stale')
        self.assertFalse(any(e.kind=='spell_countered' for e in g.events));self.check(g)

    def test_real_example_uses_player_ports_restores_and_replays(self):
        from examples.trigger_secrets import run
        game,snapshot,hidden=run()
        self.assertEqual((len(game.history),len(game.events)),(9,56))
        self.assertEqual(sum(e.kind == 'health_resolved' for e in game.events), 3)
        self.assertEqual(snapshot['schema_version'],265)
        self.assertTrue(all(s['card_id'] is None for s in hidden['players'][0]['secrets']))

    def test_spent_secret_can_be_set_again_with_fresh_instance(self):
        self.spell('set',lambda c:[SetSecret(1,'EX1_287')])
        g=self.game(hand=('EX1_287',),enemy_hand=('noop','set','noop'));self.arm(g,'EX1_287')
        first=g.state.entities[g.state.players[1].secrets[0]].secret_instance_id;self.play(g,'noop');self.play(g,'set')
        second=g.state.entities[g.state.players[1].secrets[0]].secret_instance_id;self.assertGreater(second,first)
        self.play(g,'noop');self.assertFalse(self.secrets(g));self.check(g)


if __name__=='__main__':unittest.main()
