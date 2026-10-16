"""Sixteen complete native conditional/stat/zone Battlecries."""
import json
import unittest
from _conditional_battlecry_support import CardHelpers
from hs_sim.cards.conditional_battlecry_cards import load_batch
from hs_sim.engine import Attack,EndTurn,Keyword,UseHeroPower
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import Zone
from hs_sim.targets import canonical_digest


class ConditionalBattlecryCardTests(CardHelpers,unittest.TestCase):
    def test_complete_sixteen_source_faces_and_native_battlecries(self):
        data=load_batch();self.assertEqual(len(data['cards']),16)
        for row in data['cards']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            card=self.registry.card(raw['id']);self.assertIsNotNone(card.battlecry);self.assertIsNone(card.on_play)
            self.assertEqual((card.cost,card.attack),(raw['cost'],raw['attack']))
        self.assertEqual((self.registry.card('END_001').attack,self.registry.card('END_001').durability),(3,2))

    def test_self_freeze_preserves_new_minion_clock(self):
        g=self.game(('CATA_612',));source=self.play(g,'CATA_612')
        self.assertTrue(g.state.entities[source].frozen);g.apply(EndTurn(1))
        self.assertTrue(g.state.entities[source].frozen);g.apply(EndTurn(2));g.apply(EndTurn(1))
        self.assertFalse(g.state.entities[source].frozen)

    def test_egg_draws_actual_zero_attack_minion_not_zero_attack_spell(self):
        g=self.game(('DINO_411',),deck=('k23.noop','k23.zero','k23.one'))
        before=list(g.state.players[1].deck);self.play(g,'DINO_411')
        self.assertEqual(g.state.players[1].hand,[before[1]])
        self.assertEqual(g.state.players[1].deck,[before[0],before[2]])

    def test_held_spell_false_has_no_target_and_rejects_prescribed_target(self):
        g=self.game(('EDR_472',),enemy=('CORE_CS2_182',));target=self.body(g,'CORE_CS2_182',2).id
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'EDR_472',target)
        self.assertEqual(g.snapshot(),before);self.play(g,'EDR_472');self.assertFalse(self.rows(g,'EDR_472'))

    def test_held_spell_current_cost_threshold_and_minion_ability_budget(self):
        g=self.game(('EDR_472','k23.expensive'),board=('CORE_EX1_012',),enemy=('CORE_CS2_182',))
        target=self.body(g,'CORE_CS2_182',2).id;self.play(g,'EDR_472',target)
        self.assertEqual(g.state.entities[target].health,2);self.assertEqual(self.rows(g,'EDR_472')[0].spell_bonus,0)
        g=self.game(('k23.lower','EDR_472','k23.expensive'),enemy=('CORE_CS2_182',))
        self.play(g,'k23.lower');self.play(g,'EDR_472');self.assertFalse(self.rows(g,'EDR_472'))

    def test_held_spell_condition_rechecks_after_real_summon_wait(self):
        g=self.game(('EDR_472','k23.expensive'),board=('k23.watch',),enemy=('CORE_CS2_182',),mode='holding')
        target=self.body(g,'CORE_CS2_182',2).id;self.play(g,'EDR_472',target)
        self.assertIsNotNone(g.state.pending_choice);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);other=self.portable(g,'holding')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertFalse(self.rows(g,'EDR_472'))

    def test_dreamer_requires_two_imbues_and_has_real_lifesteal(self):
        g=self.game(('EDR_860',),enemy=('CORE_CS2_182',));self.play(g,'EDR_860')
        self.assertFalse(self.rows(g,'EDR_860'))
        g=self.game(('k23.twice','k23.hero_hurt','EDR_860'),enemy=('CORE_CS2_182',))
        self.play(g,'k23.twice');self.play(g,'k23.hero_hurt');target=self.body(g,'CORE_CS2_182',2).id
        self.play(g,'EDR_860',target);self.assertEqual(g.state.entities[target].health,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
        self.assertEqual(self.rows(g,'EDR_860')[0].spell_bonus,0);self.portable(g)

    def test_priestess_enemy_attack_expires_at_next_owner_start_and_imbues(self):
        g=self.game(('EDR_970',),enemy=('CORE_CS2_182',));target=self.body(g,'CORE_CS2_182',2).id
        self.play(g,'EDR_970');self.assertEqual(g.state.entities[target].attack,2)
        self.assertEqual(len(g.state.imbue_history),1);g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[target].attack,2);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[target].attack,4);self.portable(g)

    def test_saw_equips_replaces_and_battlecry_imbues_then_normal_wear(self):
        g=self.game(('END_001',),weapon='CS2_082');old=g.state.players[1].weapon_id
        source=self.play(g,'END_001');self.assertEqual(g.state.players[1].weapon_id,source)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.imbue_history),1)
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.assertEqual(g.state.entities[source].durability,1)

    def test_survivor_counts_actual_damage_including_armor_not_missing_health(self):
        g=self.game(('END_019',));source=self.play(g,'END_019')
        self.assertEqual(g.state.entities[source].attack,5)
        g=self.game(('k23.armor_hurt','END_019'));self.play(g,'k23.armor_hurt');source=self.play(g,'END_019')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(8,9))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_survivor_previous_turn_damage_does_not_qualify(self):
        g=self.game(('k23.hero_hurt','END_019'));self.play(g,'k23.hero_hurt');g.apply(EndTurn(1));g.apply(EndTurn(2))
        source=self.play(g,'END_019');self.assertEqual(g.state.entities[source].attack,5)

    def test_soul_manual_power_current_turn_not_effect_activation(self):
        g=self.game(('FIR_777',),power=True);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        source=self.play(g,'FIR_777');self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(4,6))
        g=self.game(('k23.effect_power','FIR_777'),power=True);self.play(g,'k23.effect_power')
        source=self.play(g,'FIR_777');self.assertEqual(g.state.entities[source].attack,1)
        self.assertEqual(g.state.hero_power_history[0].origin,'effect')

    def test_attendant_threshold_zero_one_two(self):
        for prefix in (None,'k23.imbue','k23.twice'):
            hand=('FIR_921',) if prefix is None else (prefix,'FIR_921')
            g=self.game(hand)
            if prefix:self.play(g,prefix)
            self.play(g,'FIR_921');self.assertEqual(len(g.state.draw_history),2 if prefix=='k23.twice' else 0)

    def test_dryad_grants_only_at_current_expensive_spell_threshold(self):
        for prefix in (None,'k23.lower'):
            hand=('FIR_961','k23.expensive') if prefix is None else (prefix,'FIR_961','k23.expensive')
            g=self.game(hand)
            if prefix:self.play(g,prefix)
            source=self.play(g,'FIR_961')
            self.assertEqual(Keyword.LIFESTEAL in g.state.entities[source].keywords,prefix is None)
            self.assertEqual(Keyword.DIVINE_SHIELD in g.state.entities[source].keywords,prefix is None)

    def test_pickpocket_exact_physical_deck_threshold(self):
        for size in (24,25):
            g=self.game(('JAIL_456',),deck=('CORE_CS2_182',)*size)
            self.play(g,'JAIL_456');self.assertEqual(len(g.state.draw_history),int(size==25))

    def test_skull_counts_actual_other_hand_cards_and_zero(self):
        for extra in (0,3):
            g=self.game(('JAIL_513',)+('k23.noop',)*extra);source=self.play(g,'JAIL_513')
            self.assertEqual((g.state.entities[source].health,g.state.entities[source].max_health),(1+extra,1+extra))

    def test_skull_reads_current_hand_after_reaction_draw(self):
        g=self.game(('JAIL_513',),board=('k23.watch',),mode='skull')
        source=self.play(g,'JAIL_513');other=self.portable(g,'skull')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].health,2)

    def test_krona_bottom_five_original_refs_cost_one_and_preserves_order(self):
        g=self.game(('TIME_705',),deck=('k23.expensive',)*7);before=list(g.state.players[1].deck)
        self.play(g,'TIME_705');self.assertEqual(g.state.players[1].deck,before)
        self.assertEqual([self.price(g,e) for e in before],[5,5,1,1,1,1,1]);self.portable(g)

    def test_krona_short_or_empty_deck(self):
        for count in (0,2):
            g=self.game(('TIME_705',),deck=('k23.expensive',)*count);self.play(g,'TIME_705')
            self.assertTrue(all(self.price(g,e)==1 for e in g.state.players[1].deck))

    def test_soldier_doubles_remaining_health_not_printed_or_heals_damage(self):
        g=self.game(('TIME_720',),board=('k23.watch',),mode='soldier')
        source=self.play(g,'TIME_720');other=self.portable(g,'soldier')
        for current in (g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());entity=g.state.entities[source]
        self.assertEqual((entity.health,entity.max_health,entity.damage),(4,5,1))

    def test_scion_counts_both_sides_damaged_minions_not_hero(self):
        g=self.game(('k23.wound_board','k23.hero_hurt','TIME_871'),board=('CORE_CS2_182',),enemy=('CORE_CS2_182',))
        self.play(g,'k23.wound_board');self.play(g,'k23.hero_hurt');source=self.play(g,'TIME_871')
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,10))

    def test_pest_only_current_typed_enemy_minion_and_no_target_play(self):
        g=self.game(('TLC_633',),enemy=('k23.zero','CORE_EX1_012'))
        with self.assertRaises(IllegalAction):self.play(g,'TLC_633',self.body(g,'k23.zero',2).id)
        target=self.body(g,'CORE_EX1_012',2).id;self.play(g,'TLC_633',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        g=self.game(('TLC_633',),enemy=('k23.zero',));self.play(g,'TLC_633');self.assertFalse(self.rows(g,'TLC_633'))

    def test_pest_unknown_type_is_explicit_error_not_filtered(self):
        g=self.game(('TLC_633',),enemy=('k23.unknown',));before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Minion type is unknown'):self.play(g,'TLC_633')
        self.assertEqual(g.snapshot(),before)

    def public_play(self,g,cid):
        listing=g.for_player(1).legal_actions();self.assertIsInstance(listing['actions'],list)
        own=next(p for p in listing['observation']['players'] if p['id']==1)
        source=next(c['ref'] for c in own['hand'] if c['card_id']==cid)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==source)
        result=g.for_player(1).submit({'revision':listing['revision'],'action':action})
        self.assertTrue(result['accepted'],result.get('error'));return action

    def test_player_interface_holding_rule_current_cost_no_private_opponent_leak(self):
        for prefix in (None,'k23.lower'):
            hand=('EDR_472','k23.expensive') if prefix is None else (prefix,'EDR_472','k23.expensive')
            g=self.game(hand)
            if prefix:self.play(g,prefix)
            action=self.public_play(g,'EDR_472')
            self.assertEqual(action.get('target') is not None,prefix is None)
            self.assertNotIn('k23.expensive',json.dumps(g.observe(2)))

    def test_player_interface_imbue_rule_false_and_true(self):
        for prefix in (None,'k23.twice'):
            g=self.game(('EDR_860',) if prefix is None else (prefix,'EDR_860'),enemy=('CORE_CS2_182',))
            if prefix:self.play(g,prefix)
            action=self.public_play(g,'EDR_860');self.assertEqual(action.get('target') is not None,prefix is not None)

    def test_player_interface_typed_target_and_independent_replay(self):
        g=self.game(('TLC_633',),enemy=('k23.zero','CORE_EX1_012'))
        action=self.public_play(g,'TLC_633');self.assertIsNotNone(action.get('target'));self.portable(g)
