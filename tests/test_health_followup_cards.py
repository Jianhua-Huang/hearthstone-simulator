"""Current real faces share health, Combo and staged followup interpreters."""
from dataclasses import replace
import json
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.health_followup_cards import ALIASES, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
                           PlayerSetup, Scenario, SelectChoice, TriggerSpec)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, InvokeBehavior,
                                   RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.model import HealthFlow, HealthOp, HealthRule, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest


def registry(waiting=False):
    r = build_registry()
    r.register_card(CardDefinition('k14.big', 'Target', CardType.MINION, attack=1, health=9))
    r.register_card(CardDefinition('k14.new', 'New target', CardType.MINION, health=9))
    r.register_card(CardDefinition('k14.bonus', 'Spell bonus', CardType.MINION, health=1, spell_damage=1))
    r.register_card(CardDefinition('k14.sleep', 'Dormant', CardType.MINION, health=9, dormant_turns=3))
    r.register_card(CardDefinition('k14.convert', 'Healing conversion', CardType.MINION, health=9,
        health_rules=(HealthRule(HealthFlow.HEALING, HealthOp.CONVERT, source_relation='friendly'),)))
    for name, body in {
        'noop': lambda c: (),
        'hit': lambda c: (Damage(c.target_id, 1, c.source_id),),
        'wound': lambda c: (Damage(c.state.players[c.player_id].hero_id, 10, c.source_id),),
        'fail': lambda c: (AddToHand(c.player_id, 'missing.k14'),),
    }.items():
        r.register_behavior('k14.'+name, body)
        r.register_card(CardDefinition('k14.'+name, name, CardType.SPELL,
            on_play='k14.'+name, requires_target=name == 'hit'))
    r.register_card(CardDefinition('k14.location', 'Location', CardType.LOCATION, durability=3,
                                  on_use='k14.noop'))
    if waiting:
        def watch(c):
            if (c.state.entities[c.event.source_id].card_id != 'CATA_485'
                    or c.state.entities[c.event.target_id].card_id != 'k14.big'):
                return ()
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Change the live pool', (Destroy(c.event.target_id),
                    Summon(2, 'k14.new'), Summon(1, 'k14.bonus'))),
                ChoiceOption('bad', 'Reject and roll back',
                    (InvokeBehavior('k14.fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        r.register_behavior('k14.watch', watch)
        r.register_card(CardDefinition('k14.watch', 'Damage observer', CardType.MINION, health=9,
            triggers=(TriggerSpec('damage_dealt', 'k14.watch'),)))
    return r


class HealthFollowupCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registry()

    def game(self, hand=(), *, board=(), enemy=(), deck=('CORE_CS2_182',), custom_registry=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero', hand=hand, board=board, deck=deck, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('test.hero', board=enemy, deck=('CORE_CS2_182',)*2)), seed=233),
            custom_registry or self.registry)

    def play(self, g, cid, target=None):
        eid = next(e for e in g.state.players[1].hand if g.state.entities[e].card_id == cid)
        g.apply(PlayCard(1, eid, target)); return eid

    def rows(self, g, cid):
        return [row.health_result for row in g.state.damage_history if row.health_result.source_card_id == cid]

    def portable(self, g, waiting=False):
        saved = g.snapshot()
        other = Game.from_snapshot(saved, registry(waiting))
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(waiting)).snapshot(), saved)
        return other

    def test_complete_records_current_metadata_and_independent_alias_entries(self):
        rows = load_batch()['cards']; self.assertEqual(len(rows), 10)
        for row in rows:
            raw, recipe = row['record'], row['recipe']; c = self.registry.card(raw['id'])
            self.assertEqual(canonical_digest(raw), row['record_sha256'])
            self.assertEqual((c.name, c.cost, c.kind), (raw['name'], raw['cost'], CardType(raw['type'].lower())))
            self.assertEqual(c.metadata, replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']))
            if c.id in ALIASES:
                alias, entry, body = ALIASES[c.id]; original = self.registry.card(alias)
                self.assertEqual(getattr(c, entry), body)
                self.assertEqual((c.targeting, c.target_condition, c.keywords),
                                 (original.targeting, original.target_condition, original.keywords))
        self.assertIsNone(self.registry.card('CORE_EX1_134').battlecry)
        self.assertEqual(self.registry.card('CORE_EX1_134').combo, 'm5.si7')

    def test_all_ten_roots_execute_paid_complete_entries(self):
        for row in load_batch()['cards']:
            cid = row['record']['id']; recipe = row['recipe']
            with self.subTest(card=cid):
                g = self.game(('k14.noop', cid), board=('k14.big',), enemy=('k14.big',))
                self.play(g, 'k14.noop')
                targeted = recipe['target'] is not None or cid in ('CORE_CS2_024', 'CORE_EX1_134')
                eid = self.play(g, cid, g.state.players[2].board[0] if targeted else None)
                self.assertEqual(g.state.players[1].mana, 30-row['record']['cost'])
                self.assertEqual(sum(e.kind == 'card_played' and e.source_id == eid for e in g.events), 1)
                self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.entities[eid].zone, Zone.BOARD if cid == 'CORE_EX1_134' else Zone.GRAVEYARD)
                if cid == 'CATA_302': self.assertEqual(len(g.state.players[1].hand), 1)
                else: self.assertTrue(self.rows(g, cid))

    def test_nova_damages_only_enemy_minions_and_heals_friendly_characters(self):
        g = self.game(('k14.wound', 'k14.hit', 'CORE_CS1_112'), board=('k14.big',), enemy=('k14.big',))
        own = g.state.players[1].board[0]; enemy = g.state.players[2].board[0]
        self.play(g, 'k14.wound'); self.play(g, 'k14.hit', own); self.play(g, 'CORE_CS1_112')
        self.assertEqual((g.state.entities[own].health, g.state.entities[enemy].health), (9, 7))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 22)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_current_frostbolt_and_blizzard_damage_and_freeze_survivors(self):
        for cid, amount in (('CORE_CS2_024', 3), ('CORE_CS2_028', 2)):
            g = self.game((cid,), enemy=('k14.big',)); target = g.state.players[2].board[0]
            self.play(g, cid, target if cid == 'CORE_CS2_024' else None)
            self.assertEqual(g.state.entities[target].health, 9-amount)
            self.assertTrue(g.state.entities[target].frozen)
            self.assertEqual(self.rows(g, cid)[0].damage_kind, 'spell')

    def test_si7_combo_is_not_a_battlecry_and_has_no_target_before_prior_play(self):
        g = self.game(('CORE_EX1_134',), enemy=('k14.big',))
        eid = g.state.players[1].hand[0]; saved = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1, eid, g.state.players[2].hero_id))
        self.assertEqual(g.snapshot(), saved)
        self.play(g, 'CORE_EX1_134'); self.assertFalse(self.rows(g, 'CORE_EX1_134'))

    def test_si7_active_combo_uses_three_effect_damage_without_spell_bonus(self):
        g = self.game(('k14.noop', 'CORE_EX1_134'), board=('k14.bonus',), enemy=('k14.big',))
        self.play(g, 'k14.noop'); target = g.state.players[2].board[0]
        self.play(g, 'CORE_EX1_134', target)
        self.assertEqual(g.state.entities[target].health, 6)
        self.assertEqual(self.rows(g, 'CORE_EX1_134')[0].spell_bonus, 0)

    def test_soul_bomb_uses_one_batch_even_when_first_packet_kills_spell_bonus(self):
        g = self.game(('CORE_BOT_222',), board=('k14.bonus',)); bonus = g.state.players[1].board[0]
        self.play(g, 'CORE_BOT_222', bonus); rows = self.rows(g, 'CORE_BOT_222')
        self.assertEqual([(row.target_id, row.damage_dealt, row.spell_bonus) for row in rows],
                         [(bonus, 5, 1), (g.state.players[1].hero_id, 5, 1)])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 25)
        self.assertEqual(g.state.entities[bonus].zone, Zone.GRAVEYARD)

    def test_both_lifesteal_spells_heal_actual_damage_and_shield_heals_zero(self):
        for cid, target_card, amount in (('CORE_ICC_055', 'k14.big', 3),
                                       ('CORE_SW_442', 'k14.big', 4),
                                       ('CORE_ICC_055', 'CORE_EX1_008', 0)):
            g = self.game(('k14.wound', cid), enemy=(target_card,))
            self.play(g, 'k14.wound'); self.play(g, cid, g.state.players[2].board[0])
            self.assertEqual(self.rows(g, cid)[0].damage_dealt, amount)
            self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 20+amount)
        g = self.game(('k14.wound', 'CORE_SW_442'))
        self.play(g, 'k14.wound'); self.play(g, 'CORE_SW_442', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 24)

    def test_minion_only_targets_reject_heroes_dormancy_and_locations_atomically(self):
        for cid in ('CORE_BOT_222', 'CORE_ICC_055', 'CATA_302'):
            g = self.game((cid,), enemy=('k14.sleep', 'k14.location'))
            eid = g.state.players[1].hand[0]
            for target in (g.state.players[2].hero_id, *g.state.players[2].board):
                saved = g.snapshot()
                with self.assertRaises(IllegalAction): g.apply(PlayCard(1, eid, target))
                self.assertEqual(g.snapshot(), saved)

    def test_mend_requests_full_maximum_then_draws_for_wounded_or_full_target(self):
        for wound in (False, True):
            g = self.game(('k14.hit', 'CATA_302'), enemy=('k14.big',)); target = g.state.players[2].board[0]
            if wound: self.play(g, 'k14.hit', target)
            self.play(g, 'CATA_302', target)
            self.assertEqual(g.state.entities[target].health, 9)
            self.assertFalse(g.state.players[1].deck)
            healed = [e for e in g.events if e.kind == 'healed' and e.target_id == target]
            if wound:
                self.assertEqual((healed[-1].amount, dict(healed[-1].data)['base_amount']), (1, 9))

    def test_mend_conversion_on_full_health_requests_maximum_and_still_draws(self):
        g = self.game(('CATA_302',), board=('k14.convert',), enemy=('k14.big',))
        target = g.state.players[2].board[0]; self.play(g, 'CATA_302', target)
        row = self.rows(g, 'CATA_302')[0]
        self.assertTrue(row.converted); self.assertEqual(row.damage_dealt, 9)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 1)
        self.portable(g)

    def test_torrent_empty_followup_pool_after_first_kill_does_not_consume_rng(self):
        g = self.game(('CATA_485',), enemy=('CORE_EX1_008',))
        # Hit the own hero so the enemy shield absorbs only the random second packet.
        self.play(g, 'CATA_485', g.state.players[1].hero_id)
        self.assertEqual([row.damage_dealt for row in self.rows(g, 'CATA_485')], [2, 0])
        g = self.game(('CATA_485',), enemy=('CORE_EX1_319',))
        before = g.snapshot()['rng_state']; self.play(g, 'CATA_485', g.state.players[2].board[0])
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(len(self.rows(g, 'CATA_485')), 1)

    def test_torrent_uniform_physical_pool_preserves_spell_source(self):
        g = self.game(('CATA_485',), enemy=('k14.big', 'k14.new', 'k14.sleep', 'k14.location'))
        ids = tuple(g.state.players[2].board[:2]); rng = Random(); rng.setstate(g._rng.getstate())
        expected = rng.choice(ids); eid = self.play(g, 'CATA_485', g.state.players[2].hero_id)
        rows = self.rows(g, 'CATA_485')
        self.assertEqual((rows[1].target_id, rows[1].damage_dealt, rows[1].source_id), (expected, 1, eid))
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(dict(next(e for e in g.events if e.kind == 'random_choice').data)['candidates'], ids)

    def test_torrent_requeries_pool_and_bonus_after_wait_with_restore_and_rollback(self):
        g = self.game(('CATA_485',), board=('k14.watch',), enemy=('k14.big', 'k14.sleep', 'k14.location'),
                      custom_registry=registry(True))
        target = g.state.players[2].board[0]; self.play(g, 'CATA_485', target)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(len(self.rows(g, 'CATA_485')), 1)
        other = self.portable(g, True); saved = g.snapshot(); choice = g.state.pending_choice
        with self.assertRaises(Exception): g.apply(SelectChoice(choice.player_id, choice.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, ('ok',)))
            rows = self.rows(game, 'CATA_485')
            self.assertEqual([row.damage_dealt for row in rows], [2, 2])
            self.assertEqual(rows[1].target_card_id, 'k14.new')
            self.assertEqual(rows[1].spell_bonus, 1)
        self.assertEqual(g.snapshot(), other.snapshot()); self.portable(g, True)
        public = json.dumps(g.for_player(2).observe())+json.dumps(g.player_events(2))
        self.assertNotIn('"rng_state"', public); self.assertNotIn('"pending_frames"', public)

    def test_rift_batches_all_live_minions_then_buffs_hero_and_expires_at_turn_end(self):
        g = self.game(('CATA_582',), board=('k14.bonus',), enemy=('k14.big', 'k14.sleep', 'k14.location'))
        enemy = g.state.players[2].board[0]; self.play(g, 'CATA_582')
        self.assertFalse(g.state.players[1].board)
        self.assertEqual(g.state.entities[enemy].health, 7)
        self.assertEqual([row.damage_dealt for row in self.rows(g, 'CATA_582')], [2, 2])
        hero = g.state.players[1].hero_id
        self.assertEqual((g.state.entities[hero].attack, g.state.entities[hero].health), (3, 30))
        self.portable(g); g.apply(EndTurn(1)); self.assertEqual(g.state.entities[hero].attack, 0)

    def test_rift_with_empty_boards_still_gives_temporary_attack(self):
        g = self.game(('CATA_582',)); self.play(g, 'CATA_582')
        self.assertFalse(self.rows(g, 'CATA_582'))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attack, 3)

    def test_pin_rejects_modified_full_record(self):
        data = load_batch(); data['cards'][0]['record']['text'] += ' changed'
        with TemporaryDirectory() as temp:
            path = Path(temp)/'batch.json'; path.write_text(json.dumps(data), encoding='utf-8')
            with patch('hs_sim.cards.health_followup_cards.BATCH_PATH', path):
                with self.assertRaises(TargetValidationError): load_batch()


if __name__ == '__main__': unittest.main()
