"""Eight real roots and two complete tokens consume the shared native mechanisms."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards.native_followup_cards import ALIASES, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import Attack, EndTurn, Keyword, PlayCard
from hs_sim.engine.model import CardType, Zone
from hs_sim.targets import canonical_digest
import test_health_theft as theft_tests


class NativeFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.registry = theft_tests.registry()

    game = theft_tests.HealthTheftTests.game
    play = theft_tests.HealthTheftTests.play
    hero = theft_tests.HealthTheftTests.hero
    portable = theft_tests.HealthTheftTests.portable
    choose = theft_tests.HealthTheftTests.choose
    def test_full_records_dependencies_and_current_alias_declarations(self):
        data = load_batch(); self.assertEqual(len(data['cards']), 10)
        self.assertEqual(sum(row['recipe']['root'] for row in data['cards']), 8)
        for row in data['cards']:
            raw, recipe = row['record'], row['recipe']; card = self.registry.card(raw['id'])
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            self.assertEqual((card.cost, card.attack, card.health),
                             (recipe['cost'], recipe['attack'], recipe['health']))
            self.assertEqual(card.metadata, replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']))
            if card.id in ALIASES:
                old = self.registry.card(ALIASES[card.id])
                for name in ('auras', 'choose_both', 'battlecry', 'dormant_turns', 'keywords', 'targeting', 'target_rule'):
                    self.assertEqual(getattr(card, name), getattr(old, name))
        self.assertEqual(self.registry.card('EDR_810t').metadata.tribes, ('beast',))
        self.assertEqual(self.registry.card('CAP_107t').metadata.tribes, ('pirate',))
        self.assertIsNone(self.registry.card('EDR_476').spell_school)

    def test_all_eight_roots_have_paid_full_execution_or_native_declarations(self):
        for row in load_batch()['cards']:
            if not row['recipe']['root']: continue
            cid = row['record']['id']
            with self.subTest(card=cid):
                g = self.game((cid,)); target = g.state.players[2].board[0] if cid == 'CORE_EX1_059' else None
                eid = self.play(g, cid, target)
                self.assertEqual(g.state.players[1].mana, 30-row['recipe']['cost'])
                self.assertEqual(sum(e.kind == 'card_played' and e.source_id == eid for e in g.events), 1)
                if row['record']['type'] == 'MINION': self.assertIn(eid, g.state.players[1].board)
                else: self.assertEqual(g.state.entities[eid].zone, Zone.GRAVEYARD)
                if cid in ('CAP_102', 'EDR_817'):
                    expected = 'CAP_107t' if cid == 'CAP_102' else 'EDR_810t'
                    self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].board], [expected]*2)

    def test_raid_leader_and_champion_auras_exclude_themselves_and_follow_silence(self):
        g = self.game(('CORE_CS2_122', 'CORE_CS2_222', 'k15.silence', 'k15.silence'), board=('k15.big',))
        big = g.state.players[1].board[0]; leader = self.play(g, 'CORE_CS2_122')
        champion = self.play(g, 'CORE_CS2_222')
        self.assertEqual((g.state.entities[big].attack, g.state.entities[big].health), (4, 9))
        self.assertEqual((g.state.entities[leader].attack, g.state.entities[champion].attack), (3, 8))
        self.play(g, 'k15.silence', champion)
        self.assertEqual((g.state.entities[big].attack, g.state.entities[big].health), (3, 8))
        self.play(g, 'k15.silence', leader)
        self.assertEqual(g.state.entities[big].attack, 2)

    def test_alchemist_has_ordinary_minion_battlecry_target_and_swaps_stats(self):
        g = self.game(('CORE_EX1_059',)); donor = g.state.players[2].board[0]
        self.play(g, 'CORE_EX1_059', donor)
        self.assertEqual((g.state.entities[donor].attack, g.state.entities[donor].health), (8, 2))

    def test_fandral_runs_existing_combined_choose_one_body_and_current_six_health(self):
        g = self.game(('CORE_OG_044', 'CORE_EX1_154'))
        source = self.play(g, 'CORE_OG_044'); self.assertEqual(g.state.entities[source].health, 6)
        target = g.state.players[2].board[0]
        wrath = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == 'CORE_EX1_154')
        g.apply(PlayCard(1, wrath, target, branch_id='both'))
        self.assertEqual(g.state.entities[target].health, 4)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.assertIsNone(g.state.pending_choice)

    def test_dormant_rush_alias_awakens_on_second_owner_start(self):
        g = self.game(('CORE_BT_156',)); source = self.play(g, 'CORE_BT_156')
        self.assertFalse(g.state.entities[source].active)
        for player in (1, 2): g.apply(EndTurn(player))
        self.assertFalse(g.state.entities[source].active)
        for player in (1, 2): g.apply(EndTurn(player))
        self.assertTrue(g.state.entities[source].active)
        self.assertIn(Keyword.RUSH, g.state.entities[source].keywords)
        self.assertTrue(any(isinstance(a, Attack) and a.attacker_id == source for a in g.legal_actions()))

    def test_moonwell_damages_enemy_characters_then_heals_friendly_characters(self):
        g = self.game(('k15.wound', 'k15.hit', 'EDR_476'), board=('k15.big',))
        own = g.state.players[1].board[0]; enemy = g.state.players[2].board[0]
        self.play(g, 'k15.wound'); self.play(g, 'k15.hit', own); self.play(g, 'EDR_476')
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health, self.hero(g, 2).armor), (27, 30, 5))
        self.assertEqual((g.state.entities[own].health, g.state.entities[enemy].health), (8, 4))

    def test_moonwell_late_heal_includes_new_wounded_friendly_after_damage_choice(self):
        g = self.game(('EDR_476',), board=('k15.watch',), mode='moonwell')
        self.play(g, 'EDR_476'); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'moonwell'); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        new = next(e for e in g.state.entities.values() if e.card_id == 'k15.new' and e.zone == Zone.BOARD)
        self.assertEqual(new.health, 8)
        self.assertTrue(any(e.kind == 'healed' and e.target_id == new.id and e.amount == 2 for e in g.events))
        self.portable(g, 'moonwell')

    def test_both_draw_spells_draw_twice_before_their_two_token_summons(self):
        for cid in ('CAP_102', 'EDR_817'):
            g = self.game((cid,)); self.play(g, cid)
            draws = [e.sequence for e in g.events if e.kind == 'card_drawn']
            summons = [e.sequence for e in g.events if e.kind == 'minion_summoned']
            self.assertEqual((len(draws), len(summons)), (2, 2))
            self.assertLess(max(draws), min(summons))

    def test_draw_spell_respects_one_remaining_board_slot_without_losing_draws(self):
        for cid in ('CAP_102', 'EDR_817'):
            g = self.game((cid,), board=('k15.big',)*6); self.play(g, cid)
            self.assertEqual(len(g.state.players[1].board), 7)
            self.assertEqual(len(g.state.players[1].hand), 2)

    def test_cannoneers_trigger_once_each_on_owner_end_without_spell_damage(self):
        g = self.game(('CAP_102',), board=('k15.bonus',), enemy=())
        self.play(g, 'CAP_102'); g.apply(EndTurn(1))
        rows = [row.health_result for row in g.state.damage_history if row.health_result.source_card_id == 'CAP_107t']
        self.assertEqual([(row.damage_dealt, row.spell_bonus, row.damage_kind) for row in rows],
                         [(1, 0, 'minion_ability')]*2)
        g.apply(EndTurn(2))
        self.assertEqual(sum(row.health_result.source_card_id == 'CAP_107t' for row in g.state.damage_history), 2)

    def test_leeches_requery_after_first_kill_and_bypass_shield(self):
        g = self.game(('EDR_817',), enemy=('CORE_EX1_008', 'k15.big'))
        squire, big = g.state.players[2].board
        self.play(g, 'EDR_817'); g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[squire].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[big].health, 7)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health), (32, 32))
        self.assertFalse(any(row.health_result.source_card_id == 'EDR_810t' for row in g.state.damage_history))
        self.assertFalse(any(e.kind == 'shield_lost' for e in g.events))
        self.portable(g)

    def test_leeches_reduce_enemy_hero_maximum_without_spending_armor(self):
        g = self.game(('EDR_817',), enemy=()); before = g.snapshot()['rng_state']
        self.play(g, 'EDR_817'); g.apply(EndTurn(1))
        self.assertEqual((self.hero(g).health, self.hero(g, 2).health, self.hero(g, 2).max_health), (32, 28, 28))
        self.assertEqual(self.hero(g, 2).armor, 9)
        self.assertEqual(g.snapshot()['rng_state'], before)
        public = json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn('"pending_frames"', public); self.assertNotIn('"enchantment_id"', public)

    def test_silenced_leech_does_not_trigger_and_gains_do_not_revert_on_source_death(self):
        g = self.game(('EDR_817', 'k15.silence', 'k15.kill'), enemy=())
        self.play(g, 'EDR_817'); first, second = g.state.players[1].board
        self.play(g, 'k15.silence', first); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.hero(g).max_health, 31)
        self.play(g, 'k15.kill', second)
        self.assertEqual(self.hero(g).max_health, 31)


if __name__ == '__main__': unittest.main()
