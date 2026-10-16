"""Corrupt/Infuse witnesses, continuous stages, lifecycle and private recovery."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BuffStoredCard, CardDefinition, CardType, CostSpec, EndTurn, Game,
    HandProgressSpec, IllegalAction, Keyword, PlayCard, PlayerSetup, ResolutionError, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, UpgradeHandCard, UseHeroPower, UseHandAction, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, DamageBatch, Destroy, Draw,
    GainArmor, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.hand_progress import AdvanceHandProgress, identity, progress_ability
from hs_sim.engine.representative import build_registry
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard


class HandProgressTests(unittest.TestCase):
    def setUp(self):
        self.r=build_registry()
        self.r.register_card(CardDefinition('plain','Plain',CardType.MINION,attack=2,health=8))
        self.spell('high',lambda c:[],cost=4)
        self.spell('low',lambda c:[],cost=2)
        self.spell('kill',lambda c:[Destroy(c.state.players[1].board[0])])
        self.spell('wipe',lambda c:[DamageBatch(tuple(Damage(i,99,c.source_id) for p in c.state.players.values() for i in p.board))])

    def spell(self,name,callback,**kwargs):
        self.r.register_behavior(name,callback);self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,**kwargs))

    def minion(self,name,spec=None,**kwargs):
        self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=4,
            keywords=(spec.keyword,) if spec and spec.keyword else (),hand_progress=spec,**kwargs))

    def game(self,hand=(),enemy_hand=(),board=(),enemy_board=(),deck=None):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=hand,board=board,deck=tuple(deck or ('plain',)*12),max_mana=10,mana=10,hero_power_card_id='HERO_01bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy_board,deck=('plain',)*12,max_mana=10,mana=10)),seed=110),self.r)

    def find(self,g,card,player=1,zone='hand'):
        return next(i for i in getattr(g.state.players[player],zone) if g.state.entities[i].card_id==card)
    def play(self,g,card,target=None):
        i=self.find(g,card,g.state.active_player);g.apply(PlayCard(g.state.active_player,i,target));return i
    def card(self,g,card,player=1):return g.state.entities[self.find(g,card,player)]
    def progress(self,g,card,player=1):return progress_ability(self.card(g,card,player))
    def ref(self,c,card):return CardReference.capture(next(e for e in c.state.entities.values() if e.card_id==card and e.zone==Zone.HAND))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r).snapshot(),g.snapshot())
        self.assertEqual(g.clone().snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_corrupt_strictly_higher_cost_upgrades_without_playing(self):
        g=self.game(hand=('DMF_073','high'));i=self.find(g,'DMF_073');self.play(g,'high');e=g.state.entities[i]
        self.assertEqual(e.card_id,'DMF_073t');self.assertEqual(e.zone,Zone.HAND)
        self.assertIn(Keyword.RUSH,e.keywords);self.assertTrue(progress_ability(e).consumed);self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_equal_or_lower_cost_does_not_corrupt(self):
        self.spell('equal',lambda c:[],cost=3)
        for spell in ('equal','low'):
            g=self.game(hand=('DMF_073',spell));self.play(g,spell);self.assertEqual(self.progress(g,'DMF_073').progress_value,0);self.check(g)

    def test_corrupt_uses_both_modified_quotes(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'DMF_073').entity_id,CostSpec(delta=-2))])
        g=self.game(hand=('DMF_073','discount','low'));self.play(g,'discount');self.play(g,'low')
        self.assertEqual(self.card(g,'DMF_073t').cost,1);self.check(g)

    def test_discounted_play_does_not_use_printed_cost(self):
        self.spell('discount',lambda c:[ModifyCost(self.ref(c,'high').entity_id,CostSpec(delta=-3))])
        g=self.game(hand=('DMF_073','discount','high'));self.play(g,'discount');self.play(g,'high')
        self.assertEqual(self.progress(g,'DMF_073').progress_completions,0);self.check(g)

    def test_cost_change_during_play_does_not_rewrite_captured_qualification(self):
        self.spell('change',lambda c:[ModifyCost(self.ref(c,'DMF_073').entity_id,CostSpec(delta=10))],cost=4)
        g=self.game(hand=('DMF_073','change'));self.play(g,'change');self.assertEqual(self.card(g,'DMF_073t').cost,13);self.check(g)

    def test_corrupt_effect_occurs_after_play_body(self):
        self.spell('read',lambda c:[GainArmor(1,1 if self.ref(c,'DMF_073') else 0)],cost=4)
        g=self.game(hand=('DMF_073','read'));self.play(g,'read');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,1);self.card(g,'DMF_073t');self.check(g)

    def test_generated_or_drawn_corrupt_card_does_not_retroactively_qualify(self):
        self.spell('make',lambda c:[AddToHand(1,'DMF_073'),Draw(1)],cost=4)
        g=self.game(hand=('make',),deck=('DMF_073','plain'));self.play(g,'make')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['DMF_073','DMF_073']);self.check(g)

    def test_copied_candidate_midplay_does_not_inherit_eligibility(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'DMF_073'),1)],cost=4)
        g=self.game(hand=('DMF_073','copy'));self.play(g,'copy')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['DMF_073t','DMF_073']);self.check(g)

    def test_played_corrupt_card_cannot_corrupt_itself(self):
        g=self.game(hand=('DMF_073',));i=self.play(g,'DMF_073')
        self.assertEqual(g.state.entities[i].card_id,'DMF_073');self.assertFalse(g.state.play_history[0].corrupt_candidates);self.check(g)

    def test_opponent_play_cannot_corrupt_your_card(self):
        g=self.game(hand=('high',),enemy_hand=('DMF_073',));self.play(g,'high');self.card(g,'DMF_073',2);self.check(g)

    def test_countered_spell_still_corrupts(self):
        g=self.game(hand=('EX1_287',),enemy_hand=('DMF_073','high'));self.play(g,'EX1_287');g.apply(EndTurn(1));self.play(g,'high')
        self.assertTrue(g.state.play_history[-1].countered);self.card(g,'DMF_073t',2);self.check(g)

    def test_skills_trade_forge_are_not_qualifying_plays(self):
        g=self.game(hand=('DMF_124','SW_094','TTN_042'));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        g.apply(UseHandAction(1,self.find(g,'SW_094'),'trade'));g.apply(UseHandAction(1,self.find(g,'TTN_042'),'forge'))
        self.assertFalse(self.progress(g,'DMF_124').progress_keys);self.check(g)

    def test_corrupt_multiple_candidates_are_independent(self):
        g=self.game(hand=('DMF_073','DMF_073','high'));self.play(g,'high')
        abilities=[progress_ability(g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertEqual(len({a.id for a in abilities}),2);self.assertTrue(all(a.consumed for a in abilities));self.check(g)

    def test_endless_corrupt_advances_only_once_per_play(self):
        g=self.game(hand=('DMF_124','high','high'));self.play(g,'high');e=self.card(g,'DMF_124t');original=progress_ability(e).id
        self.assertEqual((e.attack,e.health),(3,3));self.play(g,'high');e=self.card(g,'DMF_124t')
        self.assertEqual((e.attack,e.health),(4,4));a=progress_ability(e);self.assertEqual((a.id,a.progress_completions,len(a.progress_keys)),(original,2,2));self.check(g)

    def test_felsteel_converts_buffed_health_to_durability(self):
        self.spell('buff',lambda c:[BuffStoredCard(self.ref(c,'DMF_248'),2,3)])
        g=self.game(hand=('DMF_248','buff','high'));self.play(g,'buff');self.play(g,'high');e=self.card(g,'DMF_248t')
        self.assertEqual((e.kind,e.attack,e.durability,e.health),(CardType.WEAPON,6,6,0));self.assertIsNone(g.state.players[1].weapon_id)
        self.play(g,'DMF_248t');self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack,6);self.check(g)

    def test_play_body_discarding_or_moving_candidate_cancels_corrupt(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'DMF_073'),1,Zone.DECK,position='top')],cost=4)
        g=self.game(hand=('DMF_073','move'));self.play(g,'move');self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,'DMF_073');self.check(g)

    def test_candidate_leave_and_return_does_not_reuse_original_eligibility(self):
        self.r.register_behavior('back',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1,Zone.HAND)])
        self.spell('roundtrip',lambda c:[MoveCard(self.ref(c,'DMF_073'),1,Zone.DECK,position='top'),InvokeBehavior('back',c.source_id,1)],cost=4)
        g=self.game(hand=('DMF_073','roundtrip'));old=self.progress(g,'DMF_073').id;self.play(g,'roundtrip')
        self.assertNotEqual(self.progress(g,'DMF_073').id,old);self.assertFalse(self.progress(g,'DMF_073').consumed);self.check(g)

    def test_external_upgrade_during_play_does_not_inherit_candidate(self):
        self.spell('change',lambda c:[UpgradeHandCard(self.ref(c,'DMF_124'),'DMF_124t')],cost=4)
        g=self.game(hand=('DMF_124','change'));self.play(g,'change');e=self.card(g,'DMF_124t')
        self.assertEqual(e.attack,3);self.assertEqual(progress_ability(e).progress_completions,0);self.check(g)

    def test_infuse_counts_each_friendly_death_in_one_batch(self):
        g=self.game(hand=('REV_956','wipe'),board=('plain',)*3);self.play(g,'wipe')
        a=self.progress(g,'REV_956t');self.assertEqual((a.progress_value,a.progress_completions,len(a.progress_keys)),(3,1,3));self.assertEqual(len({d.batch for d in g.state.death_history}),1);self.check(g)

    def test_enemy_deaths_do_not_count(self):
        g=self.game(hand=('REV_956','wipe'),enemy_board=('plain',)*3);self.play(g,'wipe')
        self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)

    def test_opponent_turn_friendly_deaths_count(self):
        g=self.game(hand=('REV_956',),enemy_hand=('wipe',),board=('plain',)*3);g.apply(EndTurn(1));self.play(g,'wipe')
        self.card(g,'REV_956t');self.check(g)

    def test_infuse_outside_hand_does_not_count(self):
        g=self.game(hand=('wipe',),board=('REV_956','plain','plain'),deck=('REV_956','plain'));i=self.find(g,'REV_956',zone='board');self.play(g,'wipe')
        self.assertEqual(progress_ability(g.state.entities[i]).progress_value,0)
        self.assertEqual(progress_ability(g.state.entities[g.state.players[1].deck[0]]).progress_value,0);self.check(g)

    def test_discard_is_not_a_minion_death(self):
        from hs_sim.engine.zones import DiscardCard
        self.spell('discard',lambda c:[DiscardCard(self.ref(c,'plain'))])
        g=self.game(hand=('REV_956','plain','discard'));self.play(g,'discard');self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)

    def test_destroyed_location_does_not_infuse(self):
        from hs_sim.engine import DestroyLocation
        self.spell('demolish',lambda c:[DestroyLocation(c.state.players[1].board[0])])
        g=self.game(hand=('REV_956','demolish'),board=('CORE_REV_990',));self.play(g,'demolish')
        self.assertFalse(g.state.players[1].board);self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)

    def test_transferred_minion_uses_controller_at_death(self):
        from hs_sim.engine.effects import ChangeControl
        self.spell('steal',lambda c:[ChangeControl(c.state.players[2].board[0],1),Destroy(c.state.players[2].board[0])])
        g=self.game(hand=('REV_956','steal'),enemy_board=('plain',));self.play(g,'steal')
        self.assertEqual(self.progress(g,'REV_956').progress_value,1);self.check(g)

    def test_deathrattle_generated_infuse_card_misses_old_death(self):
        self.r.register_behavior('generate',lambda c:[AddToHand(1,'REV_956')])
        self.r.register_card(CardDefinition('donor','Donor',CardType.MINION,health=1,deathrattle='generate'))
        g=self.game(hand=('kill',),board=('donor',));self.play(g,'kill');self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)

    def test_generated_before_death_gets_that_death(self):
        self.spell('makekill',lambda c:[AddToHand(1,'REV_956'),Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('makekill',),board=('plain',));self.play(g,'makekill');self.assertEqual(self.progress(g,'REV_956').progress_value,1);self.check(g)

    def test_silencing_death_source_does_not_prevent_infuse(self):
        self.spell('silencekill',lambda c:[Silence(c.state.players[1].board[0]),Destroy(c.state.players[1].board[0])])
        g=self.game(hand=('REV_956','silencekill'),board=('plain',));self.play(g,'silencekill');self.assertEqual(self.progress(g,'REV_956').progress_value,1);self.check(g)

    def test_reborn_death_and_later_death_each_count(self):
        g=self.game(hand=('REV_956','kill','kill'),board=('ULD_205',));self.play(g,'kill');self.play(g,'kill')
        self.assertEqual(self.progress(g,'REV_956').progress_value,2);self.check(g)

    def test_infused_fool_draws_three_uninfused_one(self):
        g=self.game(hand=('REV_019','wipe'),board=('plain',)*4);self.play(g,'wipe');self.play(g,'REV_019t')
        self.assertEqual(len(g.state.players[1].deck),9);self.check(g)
        g=self.game(hand=('REV_019',));self.play(g,'REV_019');self.assertEqual(len(g.state.players[1].deck),11)

    def test_infused_frozen_touch_adds_fresh_uninfused_card(self):
        g=self.game(hand=('REV_601','wipe'),board=('plain',)*3);self.play(g,'wipe');self.play(g,'REV_601t',g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,27);a=self.progress(g,'REV_601');self.assertEqual(a.progress_value,0);self.assertFalse(a.progress_keys);self.check(g)

    def test_murlocula_upgrades_to_zero_cost(self):
        g=self.game(hand=('REV_957','wipe'),board=('plain',)*4);self.play(g,'wipe');self.assertEqual(self.card(g,'REV_957t').cost,0)
        before=g.state.players[1].mana;self.play(g,'REV_957t');self.assertEqual(g.state.players[1].mana,before);self.check(g)

    def test_stat_and_cost_enchantments_survive_infuse(self):
        self.spell('buff',lambda c:[BuffStoredCard(self.ref(c,'REV_956'),1,2),ModifyCost(self.ref(c,'REV_956').entity_id,CostSpec(delta=-1))])
        g=self.game(hand=('REV_956','buff','wipe'),board=('plain',)*3);self.play(g,'buff');self.play(g,'wipe');e=self.card(g,'REV_956t')
        self.assertEqual((e.attack,e.health,e.cost),(5,7,1));self.check(g)

    def test_multi_stage_infuse_keeps_all_deaths_in_same_batch(self):
        self.minion('stage1',HandProgressSpec('infuse',1,'stage2'));self.minion('stage2',HandProgressSpec('infuse',2,'stage3'));self.minion('stage3')
        g=self.game(hand=('stage1','wipe'),board=('plain',)*3);original=self.progress(g,'stage1').id;self.play(g,'wipe');a=self.progress(g,'stage3')
        self.assertEqual((a.id,a.progress_completions,len(a.progress_keys)),(original,2,3));self.assertTrue(a.consumed);self.check(g)

    def test_endless_infuse_consumes_each_witness_and_carries_remainder(self):
        self.r.register_behavior('armor',lambda c:[GainArmor(c.player_id,1)])
        self.minion('endless',HandProgressSpec('infuse',2,on_complete='armor',repeat=True))
        g=self.game(hand=('endless','wipe'),board=('plain',)*5);self.play(g,'wipe');a=self.progress(g,'endless')
        self.assertEqual((a.progress_value,a.progress_completions,len(a.progress_keys)),(1,2,5));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)

    def test_duplicate_death_witness_is_not_counted_twice(self):
        def duplicate(c):
            e=next(e for e in c.state.entities.values() if e.card_id=='REV_956' and e.zone==Zone.HAND)
            return [AdvanceHandProgress(identity(e,progress_ability(e)),c.event)]
        self.r.register_behavior('duplicate',duplicate)
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=5,triggers=(TriggerSpec('minion_died','duplicate'),)))
        g=self.game(hand=('REV_956','kill'),board=('plain','watcher'));self.play(g,'kill');self.assertEqual(self.progress(g,'REV_956').progress_value,1);self.check(g)

    def test_progress_condition_reads_frozen_death_record(self):
        self.r.register_trigger_condition('big',lambda c:c.death.attack>=3)
        self.minion('filtered',HandProgressSpec('infuse',1,'alt',condition_id='big'));self.minion('alt')
        self.r.register_card(CardDefinition('big','Big',CardType.MINION,attack=3,health=1))
        g=self.game(hand=('filtered','kill','kill'),board=('plain','big'));self.play(g,'kill');self.assertEqual(self.progress(g,'filtered').progress_value,0)
        self.play(g,'kill');self.card(g,'alt');self.check(g)

    def test_condition_non_bool_rolls_back_death_and_progress(self):
        self.r.register_trigger_condition('bad',lambda c:1);self.minion('bad',HandProgressSpec('infuse',1,'alt',condition_id='bad'));self.minion('alt')
        g=self.game(hand=('bad','kill'),board=('plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'kill')
        self.assertEqual(g.snapshot(),before)

    def test_progress_callback_observes_updated_progress_and_event(self):
        def gain(c):
            self.assertEqual(c.trigger.progress_value,1);self.assertEqual(c.death.attack,2);return [GainArmor(c.player_id,c.death.attack)]
        self.r.register_behavior('gain',gain);self.minion('count',HandProgressSpec('infuse',2,'alt',on_progress='gain'));self.minion('alt')
        g=self.game(hand=('count','kill'),board=('plain',));self.play(g,'kill');self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)

    def test_copy_current_keeps_progress_base_copy_resets(self):
        self.spell('copy',lambda c:[CopyCard(self.ref(c,'REV_956'),1),CopyCard(self.ref(c,'REV_956'),1,mode='base')])
        g=self.game(hand=('REV_956','kill','copy'),board=('plain',));self.play(g,'kill');self.play(g,'copy')
        abilities=[progress_ability(g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertEqual([a.progress_value for a in abilities],[1,1,0]);self.assertEqual(len({a.id for a in abilities}),3);self.check(g)

    def test_move_preserves_partial_progress_and_resumes_in_hand(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'REV_956'),1,Zone.DECK,position='top')])
        self.spell('back',lambda c:[MoveCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),1,Zone.HAND)])
        g=self.game(hand=('REV_956','kill','move','kill','back','kill'),board=('plain',)*3);self.play(g,'kill');self.play(g,'move');self.play(g,'kill');self.play(g,'back');self.play(g,'kill')
        self.assertEqual(self.progress(g,'REV_956').progress_value,2);self.check(g)

    def test_reset_move_clears_partial_progress(self):
        self.spell('move',lambda c:[MoveCard(self.ref(c,'REV_956'),1,Zone.DECK,position='top',reset=True)])
        g=self.game(hand=('REV_956','kill','move'),board=('plain',));self.play(g,'kill');self.play(g,'move')
        self.assertEqual(progress_ability(g.state.entities[g.state.players[1].deck[0]]).progress_value,0);self.check(g)

    def test_play_and_return_resets_unfinished_progress(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('REV_956','kill','bounce'),board=('plain',));self.play(g,'kill');self.play(g,'REV_956');self.play(g,'bounce')
        self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)

    def test_returned_infused_form_remains_infused(self):
        self.spell('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('REV_956','wipe','bounce'),board=('plain',)*3);self.play(g,'wipe');self.play(g,'REV_956t');self.play(g,'bounce')
        self.assertEqual(self.card(g,'REV_956t').attack,4);self.assertIsNone(self.progress(g,'REV_956t'));self.check(g)

    def test_earlier_board_listener_moving_card_cancels_pending_death(self):
        self.r.register_behavior('move',lambda c:[MoveCard(self.ref(c,'REV_956'),1,Zone.DECK,position='top')])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=5,triggers=(TriggerSpec('minion_died','move'),)))
        g=self.game(hand=('REV_956','kill'),board=('plain','watcher'));self.play(g,'kill')
        self.assertEqual(progress_ability(g.state.entities[g.state.players[1].deck[0]]).progress_value,0);self.check(g)

    def test_corrupt_choice_preserves_original_candidates(self):
        self.spell('choice',lambda c:[RequestChoice(1,(ChoiceOption('go','Go',(AddToHand(1,'DMF_073'),)),),c.source_id)],cost=4)
        g=self.game(hand=('DMF_073','choice'));self.play(g,'choice');self.card(g,'DMF_073');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['DMF_073t','DMF_073']);self.check(g)

    def test_paused_death_listener_preserves_pending_infuse_work(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id)])
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=5,triggers=(TriggerSpec('minion_died','pause'),)))
        g=self.game(hand=('REV_956','kill'),board=('plain','watcher'));self.play(g,'kill');self.assertEqual(self.progress(g,'REV_956').progress_value,0);self.check(g)
        g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.assertEqual(self.progress(g,'REV_956').progress_value,1);self.check(g)

    def test_completion_choice_roundtrips_with_consumed_instance(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go',(GainArmor(1,3),)),),c.source_id)])
        self.minion('choice',HandProgressSpec('infuse',1,on_complete='pause'))
        g=self.game(hand=('choice','kill'),board=('plain',));self.play(g,'kill');self.assertTrue(self.progress(g,'choice').consumed);self.check(g)
        g=Game.from_snapshot(g.snapshot(),self.r);g.apply(SelectChoice(1,g.state.pending_choice.id,('go',)));self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,3);self.check(g)

    def test_failed_completion_rolls_back_all_progress(self):
        def fail(c):raise RuntimeError('intentional')
        self.r.register_behavior('fail',fail);self.minion('bad',HandProgressSpec('infuse',1,on_complete='fail'))
        g=self.game(hand=('bad','kill'),board=('plain',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'kill')
        self.assertEqual(g.snapshot(),before)

    def test_hidden_progress_and_events_are_private(self):
        g=self.game(hand=('REV_956','kill'),board=('plain',));self.play(g,'kill')
        own=g.observe(1)['players'][0]['hand'][0];enemy=g.observe(2)['players'][0]['hand'][0]
        self.assertEqual(own['hand_progress'],{'kind':'infuse','value':1,'goal':3,'completions':0,'completed':False});self.assertEqual(set(enemy),{'ref','card_id'})
        self.assertNotIn('hand_progressed',[e['kind'] for e in g.player_events(2)]);self.assertIn('hand_progressed',[e['kind'] for e in g.player_events(1)])
        for forbidden in ('progress_keys','ability_id','corrupt_candidates'):self.assertNotIn(forbidden,json.dumps(g.observe(1)))
        self.check(g)

    def test_hidden_card_choice_does_not_change_opponent_observation_or_logs(self):
        games=[self.game(hand=(card,'kill'),board=('plain',)) for card in ('REV_019','REV_956')]
        for g in games:self.play(g,'kill')
        self.assertEqual(games[0].observe(2),games[1].observe(2));self.assertEqual(games[0].player_events(2),games[1].player_events(2))

    def test_generic_hand_event_progress_uses_registered_condition(self):
        self.r.register_behavior('gain',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_trigger_condition('own',lambda c:c.event.player_id==c.player_id)
        self.minion('generic',HandProgressSpec('event',2,on_complete='gain',event='card_played',condition_id='own'))
        g=self.game(hand=('generic','low','low'));self.play(g,'low');self.play(g,'low')
        self.assertTrue(self.progress(g,'generic').consumed);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)

    def test_corrupt_snapshot_usage_and_witnesses_are_rejected(self):
        g=self.game(hand=('REV_956','kill'),board=('plain',));self.play(g,'kill')
        for key,value in (('progress_value',True),('progress_value',-1),('progress_value',3),('progress_completions',4),
                ('progress_keys',['death:1','death:1']),('progress_keys',['death:999']),('progress_keys',['garbage']),('consumed',True)):
            with self.subTest(key=key,value=value):
                data=g.snapshot();a=next(a for a in data['state']['entities'][str(self.find(g,'REV_956'))]['abilities'] if a['kind']=='hand_progress');a[key]=value
                data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
                with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_corrupt_candidate_provenance_is_validated(self):
        g=self.game(hand=('DMF_073','high'));self.play(g,'high')
        for key,value in (('source_id',99999),('ability_id',99999),('player_id',2)):
            data=g.snapshot();data['state']['play_history'][0]['corrupt_candidates'][0][key]=value
            data['state_hash']=canonical_hash({k:v for k,v in data.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(data,self.r)

    def test_invalid_specs_and_bare_keyword_rejected(self):
        for kwargs in ({'goal':0},{'goal':True},{'kind':'unknown'},{'kind':'corrupt','goal':2},{'repeat':True,'upgrade_card_id':'plain'}):
            fields={'kind':'infuse','on_complete':'old'};fields.update(kwargs)
            with self.assertRaises(ValueError):HandProgressSpec(**fields)
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','Bad',CardType.MINION,health=1,keywords=(Keyword.INFUSE,)))

    def test_unregistered_completion_and_invalid_form_rejected_at_freeze(self):
        self.minion('bad',HandProgressSpec('infuse',1,on_complete='missing'))
        with self.assertRaises(UnsupportedDefinitionError):self.game(hand=('bad',))

    def test_terminal_play_does_not_complete_corrupt(self):
        self.spell('lethal',lambda c:[Damage(c.state.players[2].hero_id,99,c.source_id)],cost=4)
        g=self.game(hand=('DMF_073','lethal'));self.play(g,'lethal')
        self.assertFalse(g.state.play_history[-1].completed)
        self.assertEqual(self.progress(g,'DMF_073').progress_value,0);self.check(g)

    def test_copy_during_death_batch_misses_already_captured_deaths(self):
        def copy_once(c):
            return [CopyCard(self.ref(c,'REV_956'),1)] if dict(c.event.data)['death_id']==1 else []
        self.r.register_behavior('copy_once',copy_once)
        self.r.register_card(CardDefinition('watcher','Watcher',CardType.MINION,health=100,triggers=(TriggerSpec('minion_died','copy_once'),)))
        g=self.game(hand=('REV_956','wipe'),board=('plain','plain','watcher'));self.play(g,'wipe')
        self.assertEqual([progress_ability(g.state.entities[i]).progress_value for i in g.state.players[1].hand],[2,0]);self.check(g)

    def test_multistage_completion_choice_keeps_remaining_batch_after_restore(self):
        self.r.register_behavior('pause',lambda c:[RequestChoice(1,(ChoiceOption('go','Go'),),c.source_id)])
        self.minion('first',HandProgressSpec('infuse',1,'second',on_complete='pause'))
        self.minion('second',HandProgressSpec('infuse',2,'third'));self.minion('third')
        g=self.game(hand=('first','wipe'),board=('plain',)*3);self.play(g,'wipe')
        self.assertEqual(self.progress(g,'second').progress_value,0);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):match.apply(SelectChoice(1,match.state.pending_choice.id,('go',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.progress(g,'third').progress_completions,2);self.check(g)

    def test_unregistered_upgrade_form_rejected_at_freeze(self):
        self.minion('bad',HandProgressSpec('infuse',1,'missing'))
        with self.assertRaises(UnsupportedDefinitionError):self.game(hand=('bad',))

    def test_metadata_elemental_murloc_and_infuse_thresholds(self):
        self.assertEqual(self.r.card('DMF_248').metadata.tribes,('elemental',));self.assertEqual(self.r.card('REV_957').metadata.tribes,('murloc',))
        self.assertEqual([self.r.card(i).hand_progress.goal for i in ('REV_019','REV_601','REV_956','REV_957')],[4,3,3,4])

    def test_real_player_port_example_restores_and_replays(self):
        from examples.hand_progress import run
        game,snapshot=run();self.assertEqual(len(game.history),8);self.assertEqual(snapshot['schema_version'],SNAPSHOT_SCHEMA_VERSION)


if __name__=='__main__':unittest.main()
