"""Twelve full native Battlecries, actual choices, data and physical materials."""
import json
import unittest
from _targeted_battlecry_support import TargetHelpers
from hs_sim.cards.targeted_battlecry_cards import load_batch
from hs_sim.engine import SelectChoice,Keyword
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import Zone
from hs_sim.targets import canonical_digest


class TargetedBattlecryCardTests(TargetHelpers,unittest.TestCase):
    def test_twelve_full_roots_and_existing_coin_dependency(self):
        data=load_batch();self.assertEqual(len(data['cards']),12);self.assertEqual(len(data['existing_dependencies']),1)
        for row in (*data['cards'],*data['existing_dependencies']):self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual(data['existing_dependencies'][0]['record']['dbf_id'],1746)
        self.assertTrue(all(self.registry.card(row['record']['id']).battlecry for row in data['cards']))

    def test_nightmare_current_buffed_attack_to_actual_hand_minion(self):
        g=self.game(('k24.boost_nightmare','CATA_161','k24.plain'))
        target=g.state.players[1].hand[-1];self.play(g,'k24.boost_nightmare')
        self.public_play(g,'CATA_161','k24.plain',target_zone='hand')
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].health),(7,4));self.portable(g)

    def test_nightmare_friendly_board_and_rejects_enemy(self):
        g=self.game(('CATA_161',),board=('k24.plain',),enemy=('k24.plain',))
        with self.assertRaises(IllegalAction):self.play(g,'CATA_161',self.body(g,'k24.plain',2).id)
        self.public_play(g,'CATA_161','k24.plain');self.assertEqual(self.body(g,'k24.plain').attack,5)

    def test_eye_transforms_same_hand_entity_to_complete_playable_coin(self):
        g=self.game(('CATA_200','k23.expensive'));target=g.state.players[1].hand[-1]
        self.public_play(g,'CATA_200','k23.expensive',target_zone='hand')
        self.assertEqual(g.state.entities[target].card_id,'GAME_005');self.assertEqual(self.price(g,target),0)
        before=g.state.players[1].mana;self.play(g,'GAME_005');self.assertEqual(g.state.players[1].mana,before+1)

    def test_no_other_hand_target_still_allows_eye_and_garden_imbues(self):
        g=self.game(('CATA_200',));self.public_play(g,'CATA_200')
        g=self.game(('EDR_518',));self.public_play(g,'EDR_518');self.assertEqual(len(g.state.imbue_history),1)

    def test_natalie_gains_target_remaining_health_after_actual_destroy(self):
        g=self.game(('k24.hit','CORE_EX1_198'),enemy=('k24.plain',));target=self.body(g,'k24.plain',2).id
        self.play(g,'k24.hit',target);source=self.play(g,'CORE_EX1_198',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual((g.state.entities[source].health,g.state.entities[source].max_health),(4,4));self.portable(g)

    def test_natalie_reward_skips_same_id_reentered_beneficiary_after_death_choice(self):
        g=self.game(('CORE_EX1_198',),board=('k24.watch',),enemy=('k24.plain',),mode='cycle_source')
        target=self.body(g,'k24.plain',2).id;source=self.play(g,'CORE_EX1_198',target)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'cycle_source')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].health,1)

    def test_rift_uses_original_remaining_health_as_minion_ability_damage(self):
        g=self.game(('k24.hit','CORE_ULD_165'),enemy=('k24.plain',));target=self.body(g,'k24.plain',2).id
        self.play(g,'k24.hit',target);self.play(g,'CORE_ULD_165',target)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,27)
        self.assertEqual(self.rows(g,'CORE_ULD_165')[0].damage_dealt,3)

    def test_siamat_exactly_two_distinct_keywords_waiting_and_private_projection(self):
        g=self.game(('CORE_ULD_178',));source=self.play(g,'CORE_ULD_178')
        q=g.state.pending_choice;self.assertEqual((q.min_count,q.max_count),(2,2));saved=g.snapshot()
        with self.assertRaises(ValueError):g.apply(SelectChoice(1,q.id,('rush','rush')))
        self.assertEqual(g.snapshot(),saved);other=self.portable(g)
        for current in (g,other):current.apply(SelectChoice(1,current.state.pending_choice.id,('rush','windfury')))
        self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[source].keywords,{Keyword.RUSH,Keyword.WINDFURY})
        self.assertNotIn('rng_state',json.dumps(g.observe(2)))

    def test_siamat_plain_summon_has_no_battlecry_choice(self):
        g=self.game(('k24.summon',));self.play(g,'k24.summon');self.assertIsNone(g.state.pending_choice)
        self.assertFalse(self.body(g,'CORE_ULD_178').keywords)

    def test_garden_only_other_hand_minion_discount_then_real_imbue(self):
        g=self.game(('EDR_518','k24.beast5','k23.expensive'));target=g.state.players[1].hand[1]
        self.public_play(g,'EDR_518','k24.beast5',target_zone='hand')
        self.assertEqual(self.price(g,target),4);self.assertEqual(len(g.state.imbue_history),1)

    def test_nurturer_current_cost_complete_independent_copy_material(self):
        g=self.game(('k24.prepare_copy','FIR_960','k24.beast5','k24.beast2'))
        original=g.state.players[1].hand[2];self.play(g,'k24.prepare_copy');self.play(g,'FIR_960')
        copied=g.state.entities[g.state.players[1].hand[-1]]
        self.assertNotEqual(copied.id,original);self.assertEqual(copied.origin_entity_id,original)
        self.assertEqual((copied.card_id,copied.attack,copied.health),('k24.beast5',5,8))
        self.assertEqual(self.price(g,copied.id),1);self.portable(g)

    def test_nurturer_uses_current_tribes_not_printed_face(self):
        g=self.game(('k24.make_beast','FIR_960','k24.plain','k24.beast2'))
        self.play(g,'k24.make_beast');self.play(g,'FIR_960')
        self.assertEqual(g.state.entities[g.state.players[1].hand[-1]].card_id,'k24.plain')
        g=self.game(('k24.unbeast','FIR_960','k24.beast2'));self.play(g,'k24.unbeast');self.play(g,'FIR_960')
        self.assertEqual(len(g.state.players[1].hand),1)

    def test_vama_same_batch_non_paladin_current_faces_both_sides(self):
        g=self.game(('JAIL_118',),board=('k24.plain','k24.paladin'),enemy=('k24.plain','k24.paladin'))
        self.play(g,'JAIL_118')
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[2].board],['k24.paladin'])
        self.assertEqual(set(g.state.entities[e].card_id for e in g.state.players[1].board),{'JAIL_118','k24.paladin'})
        self.assertEqual(len(g.state.death_history),2)

    def test_vama_unknown_class_is_not_silently_neutral(self):
        g=self.game(('JAIL_118',),enemy=('k24.unknown',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'classes are unknown'):self.play(g,'JAIL_118')
        self.assertEqual(g.snapshot(),before)

    def test_augur_sets_both_stats_to_higher_and_ignores_spells(self):
        g=self.game(('TIME_429','k24.plain','EDR_227','k23.expensive'))
        held=list(g.state.players[1].hand)[1:];self.play(g,'TIME_429')
        self.assertEqual([(g.state.entities[e].attack,g.state.entities[e].health) for e in held],[(4,4),(5,5),(0,0)])

    def test_eternus_current_source_health_player_rule_and_physical_control(self):
        g=self.game(('k24.boost_eternus','TIME_435'),enemy=('CORE_CS2_182',));target=self.body(g,'CORE_CS2_182',2).id
        self.play(g,'k24.boost_eternus');self.public_play(g,'TIME_435','CORE_CS2_182',target_player=2)
        self.assertIn(target,g.state.players[1].board);self.assertEqual(g.state.entities[target].owner,2);self.portable(g)

    def test_eternus_no_matching_health_allows_no_target(self):
        g=self.game(('TIME_435',),enemy=('CORE_CS2_182',));self.public_play(g,'TIME_435')
        self.assertIn(self.body(g,'CORE_CS2_182',2).id,g.state.players[2].board)

    def test_eternus_target_cycle_after_actual_summon_choice_does_not_rebind(self):
        g=self.game(('TIME_435',),board=('k24.watch',),enemy=('CORE_EX1_008',),mode='cycle_target')
        target=self.body(g,'CORE_EX1_008',2).id;entered=g.state.entities[target].entered_order
        self.public_play(g,'TIME_435','CORE_EX1_008',target_player=2)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'cycle_target')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertIn(target,g.state.players[2].board)
        self.assertNotEqual(g.state.entities[target].entered_order,entered)

    def test_incubator_other_current_low_attack_minions_only(self):
        g=self.game(('TLC_233',),board=('k24.plain','k24.large'),enemy=('k24.plain',))
        source=self.play(g,'TLC_233')
        self.assertEqual((self.body(g,'k24.plain').attack,self.body(g,'k24.plain').health),(3,5))
        self.assertIn(Keyword.TAUNT,self.body(g,'k24.plain').keywords)
        self.assertNotIn(Keyword.TAUNT,self.body(g,'k24.large').keywords)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords)
        self.assertEqual(self.body(g,'k24.plain',2).attack,2)

    def test_armorer_actual_original_packet_death_with_reborn_still_awards(self):
        g=self.game(('TLC_606',),enemy=('k24.reborn',));target=self.body(g,'k24.reborn',2).id
        self.play(g,'TLC_606',target);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5)
        self.assertTrue(g.state.players[2].board);self.assertNotEqual(g.state.players[2].board[0],target)

    def test_armorer_nonlethal_then_unrelated_destroy_does_not_award(self):
        g=self.game(('TLC_606',),board=('k24.watch',),enemy=('k24.large',),mode='unrelated_death')
        target=self.body(g,'k24.large',2).id;self.play(g,'TLC_606',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0)

    def test_armorer_health_choice_original_result_rollback_restore_replay(self):
        g=self.game(('TLC_606',),board=('k24.watch',),enemy=('k24.reborn',),mode='health')
        self.play(g,'TLC_606',self.body(g,'k24.reborn',2).id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g,'health')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,6)
