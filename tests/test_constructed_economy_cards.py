"""Actual card consumers of drawing, resource accounts and existing continuations."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards.economy_cards import EconomyStep, load_batch
from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec,
)
from hs_sim.engine.effects import (
    Buff, ChangeControl, ChoiceOption, CopyMinion, Damage, Destroy, GainArmor,
    GrantKeyword, RequestChoice, Silence, Summon,
)
from hs_sim.engine.model import CardClass, CardMetadata, Resource, SpellSchool, Zone
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import ReorderZone
from hs_sim.targets import TargetValidationError


def registry(*, waiting=False):
    r = build_registry()
    for name, body in (
        ('kill', lambda c: (Destroy(c.target_id),)),
        ('hit', lambda c: (Damage(c.target_id, 1, c.source_id),)),
        ('silence', lambda c: (Silence(c.target_id),)),
        ('copy', lambda c: (CopyMinion(c.target_id, c.player_id),)),
        ('transfer', lambda c: (ChangeControl(c.target_id, 2),)),
        ('shield', lambda c: (GrantKeyword(c.target_id, Keyword.DIVINE_SHIELD, c.source_id),)),
    ):
        r.register_behavior('k03.test.'+name, body)
        r.register_card(CardDefinition('k03.test.'+name, name, CardType.SPELL,
            on_play='k03.test.'+name, requires_target=True))
    r.register_behavior('k03.test.summon', lambda c: (Summon(c.player_id, 'RLK_708'),))
    r.register_card(CardDefinition('k03.test.summon', 'Summon without battlecry', CardType.SPELL,
        on_play='k03.test.summon'))
    for tribe in ('beast', 'dragon', 'murloc'):
        r.register_card(CardDefinition('k03.test.'+tribe, tribe, CardType.MINION, cost=1, health=2,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(tribe,))))
    for school in (SpellSchool.FROST, SpellSchool.FIRE):
        r.register_card(CardDefinition('k03.test.'+school.value, school.value, CardType.SPELL,
            cost=7, spell_school=school, metadata=CardMetadata(False, (CardClass.NEUTRAL,), None)))
    if waiting:
        def wait(c):
            if c.event.player_id != c.player_id:
                return ()
            deck = tuple(reversed(c.state.players[c.player_id].deck))
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue',
                (ReorderZone(c.player_id, Zone.DECK, deck), GainArmor(c.player_id, 1))),), c.source_id),)
        r.register_behavior('k03.test.wait', wait)
        r.register_card(CardDefinition('k03.test.wait', 'Draw observer', CardType.MINION, health=5,
            triggers=(TriggerSpec('card_drawn', 'k03.test.wait'),)))
    return r


class ConstructedEconomyCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = registry()
        cls.batch = load_batch()

    def game(self, hand=(), *, board=(), enemy=(), deck=(), enemy_deck=(),
             mana=20, weapon=None, enemy_weapon=None, custom_registry=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('test.hero', hand=hand, board=board, deck=deck,
                mana=mana, max_mana=mana, mana_cap=mana, weapon_card_id=weapon),
            PlayerSetup('test.hero', board=enemy, deck=enemy_deck, weapon_card_id=enemy_weapon),
        ), seed=19), custom_registry or self.registry)

    def play(self, game, cid, target=None):
        eid = next(e for e in game.state.players[1].hand if game.state.entities[e].card_id == cid)
        game.apply(PlayCard(1, eid, target_id=target))
        return eid

    def test_all_32_complete_roots_execute_paid_bodies_and_required_triggers(self):
        self.assertEqual(len(self.batch['cards']), 32)
        deck = ('k03.test.frost', 'k03.test.fire', 'TLC_248', 'k03.test.beast',
                'k03.test.dragon', 'k03.test.murloc', 'CORE_CS2_182')
        for row in self.batch['cards']:
            raw, recipe = row['record'], row['recipe']
            with self.subTest(cid=raw['id']):
                g = self.game((raw['id'], 'k03.test.kill', 'k03.test.hit'),
                    board=('CORE_CS2_182',), deck=deck,
                    weapon=None if raw['type'] == 'WEAPON' else 'EDR_253')
                target = (g.state.players[1].board[0] if recipe['target'] == 'minion'
                          else g.state.players[2].hero_id if recipe['target'] == 'character' else None)
                eid = self.play(g, raw['id'], target)
                expected = 20-recipe['cost']+(1 if raw['id'] == 'CORE_EX1_169' else 0)
                self.assertEqual(g.state.players[1].mana, expected)
                if recipe['trigger'] == 'self_damaged':
                    self.play(g, 'k03.test.hit', eid)
                elif recipe['trigger'] == 'friendly_hero_attack':
                    g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
                if 'deathrattle' in recipe['bodies']:
                    self.play(g, 'k03.test.kill', eid)
                self.assertEqual(sum(e.kind == 'card_played' and e.source_id == eid for e in g.events), 1)
                self.assertIsNone(g.state.pending_choice)

    def test_batch_pins_latest_source_identity_and_current_series_metadata(self):
        # Full-source equality belongs to the batch audit; normal tests work
        # from committed full record pins without an ignored downloaded catalog.
        self.assertEqual(self.batch['source_version'], '37.0.0.255026')
        self.assertEqual(self.batch['source_commit'], 'be4ef28ef9bd9e613045d495138061ba31a6d2f9')
        for row in self.batch['cards']:
            self.assertIn(row['record']['card_set_id'], (1637, 1946, 1957, 1988))
        self.assertEqual(self.registry.card('CORE_EX1_012').metadata.deck_identity, 'EX1_012')
        self.assertEqual(self.registry.card('RLK_511').metadata.runes.frost, 1)

    def test_shield_block_applies_five_armor_and_one_real_draw(self):
        g = self.game(('CORE_EX1_606',), deck=('CORE_CS2_182',))
        source = self.play(g, 'CORE_EX1_606')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 5)
        self.assertEqual(g.state.players[1].mana, 18)
        self.assertEqual([(d.source_id, d.card_id, d.outcome) for d in g.state.draw_history],
                         [(source, 'CORE_CS2_182', 'hand')])

    def test_both_baron_bodies_and_armor_battlecry_deathrattle_are_complete(self):
        g = self.game(('RLK_708', 'k03.test.kill'), deck=('CORE_CS2_182',)*3)
        eid = self.play(g, 'RLK_708')
        self.assertEqual(len(g.state.draw_history), 1)
        self.play(g, 'k03.test.kill', eid)
        self.assertEqual(len(g.state.draw_history), 2)
        g = self.game(('CORE_RLK_657', 'k03.test.kill'))
        eid = self.play(g, 'CORE_RLK_657')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 6)
        self.play(g, 'k03.test.kill', eid)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 12)

    def test_silenced_deathrattle_and_summon_do_not_execute_extra_draws(self):
        g = self.game(('k03.test.silence', 'k03.test.kill', 'k03.test.summon', 'k03.test.kill'),
            board=('CORE_EX1_012',), deck=('CORE_CS2_182',)*3)
        source = g.state.players[1].board[0]
        self.play(g, 'k03.test.silence', source)
        self.play(g, 'k03.test.kill', source)
        self.play(g, 'k03.test.summon')
        self.assertEqual(len(g.state.draw_history), 0)
        summoned = g.state.players[1].board[0]
        self.play(g, 'k03.test.kill', summoned)
        self.assertEqual(len(g.state.draw_history), 1)

    def test_acolyte_draws_on_lethal_damage_but_not_prevented_or_other_damage(self):
        g = self.game(('k03.test.shield', 'k03.test.hit', 'k03.test.hit', 'CORE_CS2_029'),
            board=('CORE_EX1_007', 'CORE_CS2_182'), deck=('CORE_CS2_182',)*4)
        source, other = g.state.players[1].board
        self.play(g, 'k03.test.shield', source)
        self.play(g, 'k03.test.hit', source)
        self.play(g, 'k03.test.hit', other)
        self.assertEqual(len(g.state.draw_history), 0)
        self.play(g, 'CORE_CS2_029', source)
        self.assertEqual(len(g.state.draw_history), 1)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)

    def test_innervate_exceeds_growth_cap_and_expires_on_current_turn_end(self):
        g = self.game(('CORE_EX1_169',), mana=10)
        self.play(g, 'CORE_EX1_169')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].max_mana,
                          g.state.players[1].temporary_mana), (11, 10, 1))
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].temporary_mana, 0)
        self.assertEqual(g.state.players[1].mana, 10)

    def test_overload_and_spell_damage_use_existing_accounts_and_next_turn_lock(self):
        g = self.game(('CS3_007', 'CORE_EX1_238', 'CORE_EX1_250'), mana=10)
        self.play(g, 'CS3_007')
        self.play(g, 'CORE_EX1_238', g.state.players[2].hero_id)
        self.play(g, 'CORE_EX1_250')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].mana), (4, 3))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual((g.state.players[1].overload_owed, g.state.players[1].overload_locked,
                          g.state.players[1].mana), (0, 4, 6))

    def test_body_bagger_grants_one_corpse_without_a_death(self):
        g = self.game(('RLK_503',))
        self.play(g, 'RLK_503')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 1)
        self.assertEqual(len(g.state.death_history), 0)

    def test_tutors_match_school_kind_and_threshold_and_skip_missing_without_fatigue(self):
        cases = (('RLK_511', 'k03.test.frost'), ('FIR_929', 'k03.test.fire'),
                 ('EDR_485', 'TLC_248'), ('EDR_571', 'k03.test.fire'))
        for source, wanted in cases:
            with self.subTest(source=source):
                g = self.game(('k03.test.kill',), board=(source,),
                    deck=('CORE_CS2_182', wanted))
                self.play(g, 'k03.test.kill', g.state.players[1].board[0])
                self.assertEqual([d.card_id for d in g.state.draw_history], [wanted])
                self.assertEqual(len(g.state.players[1].deck), 1)
                g = self.game(('k03.test.kill',), board=(source,))
                self.play(g, 'k03.test.kill', g.state.players[1].board[0])
                self.assertEqual(len(g.state.draw_history), 0)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 30)

    def test_curator_sequentially_draws_one_of_each_tribe(self):
        g = self.game(('CORE_KAR_061',), deck=('k03.test.dragon', 'CORE_CS2_182',
            'k03.test.murloc', 'k03.test.beast'))
        self.play(g, 'CORE_KAR_061')
        self.assertEqual([d.card_id for d in g.state.draw_history],
            ['k03.test.beast', 'k03.test.dragon', 'k03.test.murloc'])
        self.assertEqual(len(g.state.players[1].deck), 1)

    def test_bottom_draw_preserves_top_and_uses_real_draw_burn_and_fatigue(self):
        g = self.game(('TIME_023',), deck=('CORE_CS2_182', 'k03.test.beast', 'k03.test.dragon'))
        top = g.state.players[1].deck[0]
        self.play(g, 'TIME_023')
        self.assertEqual([d.card_id for d in g.state.draw_history], ['k03.test.dragon', 'k03.test.beast'])
        self.assertEqual(g.state.players[1].deck, [top])
        g = self.game(('TIME_023',)+('CORE_CS2_182',)*9, deck=('k03.test.beast', 'k03.test.dragon'))
        self.play(g, 'TIME_023')
        self.assertEqual([d.outcome for d in g.state.draw_history], ['hand', 'burned'])
        g = self.game(('TIME_023',))
        self.play(g, 'TIME_023')
        self.assertEqual([d.outcome for d in g.state.draw_history], ['fatigue', 'fatigue'])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, 27)

    def test_draw_to_three_and_outcast_use_original_hand_position(self):
        g = self.game(('TIME_601',), deck=('CORE_CS2_182',)*5)
        self.play(g, 'TIME_601')
        self.assertEqual(len(g.state.players[1].hand), 3)
        for cid, expected in (('CORE_BT_491', 2), ('CORE_BT_480', 1)):
            with self.subTest(cid=cid):
                g = self.game((cid, 'CORE_CS2_182'), deck=('CORE_CS2_182',)*4)
                self.play(g, cid)
                self.assertEqual(len(g.state.draw_history), expected)
                g = self.game(('CORE_CS2_182', cid, 'CORE_CS2_182'), deck=('CORE_CS2_182',)*4)
                self.play(g, cid)
                self.assertEqual(len(g.state.draw_history), expected-1)

    def test_hero_attack_trigger_uses_controller_and_includes_last_weapon_charge(self):
        g = self.game((), board=('CORE_NX2_028', 'JAIL_872'), deck=('CORE_CS2_182',)*5, weapon='EDR_253')
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(len(g.state.draw_history), 3)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 4)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        before = len(g.state.draw_history)
        weapon = g.state.players[1].weapon_id
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertEqual(len(g.state.draw_history)-before, 3)
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        g = self.game(('k03.test.transfer',), board=('JAIL_872',),
            enemy_deck=('CORE_CS2_182',)*3, enemy_weapon='EDR_253')
        source = g.state.players[1].board[0]
        self.play(g, 'k03.test.transfer', source)
        g.apply(EndTurn(1))
        g.apply(Attack(2, g.state.players[2].hero_id, g.state.players[1].hero_id))
        self.assertEqual([(d.player_id, d.source_id) for d in g.state.draw_history if d.source_id == source],
                         [(2, source)])
        self.assertEqual((g.state.entities[source].owner, g.state.entities[source].controller), (1, 2))

    def test_transferred_deathrattle_draws_for_controller_and_copy_has_new_source(self):
        g = self.game(('k03.test.transfer', 'k03.test.kill'), board=('CORE_EX1_096',),
            enemy_deck=('CORE_CS2_182',))
        eid = g.state.players[1].board[0]
        self.play(g, 'k03.test.transfer', eid)
        self.play(g, 'k03.test.kill', eid)
        self.assertEqual([(d.player_id, d.source_id) for d in g.state.draw_history], [(2, eid)])
        g = self.game(('k03.test.copy', 'k03.test.kill'), board=('CORE_EX1_096',), deck=('CORE_CS2_182',))
        self.play(g, 'k03.test.copy', g.state.players[1].board[0])
        copied = g.state.players[1].board[1]
        self.play(g, 'k03.test.kill', copied)
        self.assertEqual(g.state.draw_history[0].source_id, copied)

    def test_buffs_damage_and_temporary_attack_keep_targets_and_one_payment(self):
        g = self.game(('CORE_BT_292', 'CORE_CS2_004', 'CORE_BT_035', 'CORE_AT_064'),
            board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*4)
        target = g.state.players[1].board[0]
        self.play(g, 'CORE_BT_292', target); self.play(g, 'CORE_CS2_004', target)
        self.assertEqual((g.state.entities[target].attack, g.state.entities[target].max_health), (6, 8))
        self.play(g, 'CORE_BT_035')
        hero = g.state.players[1].hero_id
        self.assertEqual(g.state.entities[hero].attack, 2)
        self.play(g, 'CORE_AT_064', g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[hero].armor, 3)
        self.assertEqual(g.state.players[1].mana, 13)
        self.assertEqual(len(g.state.draw_history), 3)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[hero].attack, 0)
        g = self.game(('CORE_BT_292',))
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g, 'CORE_BT_292', g.state.players[1].hero_id)
        self.assertEqual(g.snapshot(), before)

    def test_bottom_continuation_waits_reselects_current_bottom_and_restores_privately(self):
        g = self.game(('TIME_023',), board=('k03.test.wait',),
            deck=('CORE_CS2_182', 'k03.test.beast', 'k03.test.dragon'), custom_registry=registry(waiting=True))
        self.play(g, 'TIME_023')
        self.assertEqual([d.card_id for d in g.state.draw_history], ['k03.test.dragon'])
        self.assertEqual(g.for_player(2).legal_actions()['observation']['pending_choice'], {'player_id': 1})
        snapshot = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snapshot, registry(waiting=True))
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry(waiting=True)).snapshot(), snapshot)
        while g.state.pending_choice is not None:
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('continue',)))
            restored.apply(SelectChoice(1, restored.state.pending_choice.id, ('continue',)))
            self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual([d.card_id for d in g.state.draw_history], ['k03.test.dragon', 'CORE_CS2_182'])
        self.assertEqual([g.state.entities[e].card_id for e in g.state.players[1].deck], ['k03.test.beast'])
        self.assertEqual(g.state.players[1].mana, 17)
        self.assertEqual(replay(build_replay(g), registry(waiting=True)).snapshot(), g.snapshot())

    def test_tutor_randomness_replays_and_tampered_pin_remains_an_error(self):
        g = self.game(('k03.test.kill',), board=('FIR_929',),
            deck=('CORE_CS2_029', 'k03.test.fire', 'CORE_CS2_182'))
        self.play(g, 'k03.test.kill', g.state.players[1].board[0])
        self.assertIn(g.state.draw_history[0].card_id, ('CORE_CS2_029', 'k03.test.fire'))
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), g.snapshot())
        data = load_batch(); data['cards'][0]['record']['text'] += 'unreviewed'
        with TemporaryDirectory() as folder:
            path = Path(folder)/'tampered.json'; path.write_text(json.dumps(data), encoding='utf-8')
            with patch('hs_sim.cards.economy_cards.BATCH_PATH', path), self.assertRaises(TargetValidationError):
                load_batch()
        with self.assertRaises(ValueError):
            EconomyStep('invented_resource', 1)


if __name__ == '__main__':
    unittest.main()
