"""Real completed Gauntlet attacks and shared actual non-damage conversion."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.constructed import build_registry
from hs_sim.cards.health_armor_conversion_card import CARD, load_batch
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, Zone)
from hs_sim.engine.armor_gains import gained_this_turn
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor, Heal, InvokeBehavior,
    RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_loss import ConvertHeroHealthToArmor, SetHeroHealth
from hs_sim.engine.model import (CardClass, CardMetadata, HealthLossFloorSpec,
    HealthLossReplacementSpec, TriggerSpec)
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import check_face

P = 'fixture.health_armor.'
BODY, GUARD, WAIT, FAULT, CANCEL, LOW, QUEUE, ZERO, BAD = (P+x for x in
    ('body', 'guard', 'wait', 'fault', 'cancel', 'low', 'queue', 'zero', 'bad'))
IMMUNE, FLOOR = P+'immune_hero', P+'floor_hero'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
COIN = 'GAME_005'


@lru_cache(maxsize=None)
def fixture(role='writer'):
    if role not in ('writer', 'reader'):
        raise ValueError('Independent registry role required')
    r = build_registry()
    def fail(c):
        raise ResolutionError('Explicit conversion reaction failure')
    r.register_behavior(P+'fail', fail)
    def wait(c):
        if c.event.player_id != c.player_id:
            return ()
        hero = c.state.players[c.player_id].hero_id
        return (RequestChoice(c.player_id, (ChoiceOption('heal', 'Heal', (Heal(hero, 7, c.source_id),)),
            ChoiceOption('fail', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(P+'fail', c.source_id, c.player_id)))), c.source_id),)
    r.register_behavior(P+'wait', wait)
    r.register_behavior(P+'fault', lambda c: (InvokeBehavior(P+'fail', c.source_id, c.player_id),))
    r.register_behavior(P+'cancel', lambda c: (Destroy(c.event.target_id, c.source_id),))
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, attack=3, health=20, metadata=META))
    r.register_card(CardDefinition(GUARD, GUARD, CardType.MINION, health=5,
        health_loss_replacements=(HealthLossReplacementSpec(),), metadata=META))
    for cid, event, behavior in ((WAIT, 'health_lost', 'wait'), (FAULT, 'health_lost', 'fault'),
            (CANCEL, 'attack_declared', 'cancel')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec(event, P+behavior),), metadata=META))
    r.register_card(replace(r.card('HERO_01'), id=IMMUNE, keywords=(Keyword.IMMUNE, Keyword.DIVINE_SHIELD)))
    r.register_card(replace(r.card('HERO_01'), id=FLOOR, health_loss_floors=(HealthLossFloorSpec(28),)))
    bodies = {
        LOW: lambda c: (SetHeroHealth(c.state.players[c.player_id].hero_id, 3, c.source_id),),
        QUEUE: lambda c: (RequestChoice(c.player_id, (ChoiceOption('ok', 'Convert'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),
            ConvertHeroHealthToArmor(c.player_id, 5, c.source_id)),
        ZERO: lambda c: (ConvertHeroHealthToArmor(c.player_id, 0, c.source_id),),
        BAD: lambda c: (ConvertHeroHealthToArmor(c.player_id, 5, 999999),),
    }
    for cid, body in bodies.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META))
    return r


class HealthArmorConversionTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), armor=0, hero='HERO_01', weapon=None, enemy_weapon=None):
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=hand, board=board,
            weapon_card_id=weapon, deck=(COIN,)*6, mana=10, max_mana=10, armor=armor),
            PlayerSetup('HERO_08', board=enemy, weapon_card_id=enemy_weapon,
                deck=(COIN,)*6, mana=10, max_mana=10)), seed=344), fixture())

    def hero(self, g, p=1):
        return g.state.entities[g.state.players[p].hero_id]

    def play(self, g, cid):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, eid))
        return eid

    def attack(self, g, target=None, p=1):
        g.apply(Attack(p, self.hero(g, p).id, target or self.hero(g, 3-p).id))

    def events(self, g, kind):
        return [e for e in g.events if e.kind == kind]

    def choose(self, g, option):
        g.apply(SelectChoice(1, g.state.pending_choice.id, (option,)))

    def portable(self, g):
        saved = g.snapshot()
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(saved)), fixture('reader')).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture('reader')).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for private in ('"resolution_frame"', '"hero_health_change_history"', '"armor_gain_history"',
                    '"rng_state"', 'ConvertHeroHealthToArmor', 'hero_health_transition'):
                self.assertNotIn(private, public)

    def test_complete_original_and_two_full_primary_faces(self):
        d = load_batch(); raw = d['cards'][0]['record']; card = fixture().card(CARD)
        self.assertEqual((card.cost, card.attack, card.durability, card.metadata.classes), (1, 2, 2, ('warrior',)))
        self.assertEqual(len(d['official_observations']), 2)
        for face in d['official_observations']:
            check_face(raw, face['face'], face['locale'])

    def test_native_hand_equipping_only_pays_mana_then_actual_attack_converts(self):
        g = self.game((CARD,), armor=9); weapon = self.play(g, CARD)
        self.assertEqual((g.state.players[1].mana, self.hero(g).health, self.hero(g).armor), (9, 30, 9))
        self.assertFalse(self.events(g, 'health_lost'))
        self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health, self.hero(g).armor), (25, 30, 14))
        self.assertEqual(g.state.entities[weapon].durability, 1)
        loss = self.events(g, 'health_lost')
        self.assertEqual([(e.source_id, e.amount) for e in loss], [(weapon, 5)])
        self.assertFalse(self.events(g, 'health_spent'))
        self.assertFalse(self.events(g, 'armor_consumed'))
        self.assertTrue(gained_this_turn(g.state, 1))

    def test_retaliation_stays_combat_damage_and_conversion_is_separate_actual_loss(self):
        g = self.game(enemy=(BODY,), weapon=CARD)
        self.attack(g, g.state.players[2].board[0])
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (22, 5))
        self.assertEqual([e.amount for e in self.events(g, 'health_lost')], [5])
        self.assertEqual([e.amount for e in self.events(g, 'damage_dealt') if e.target_id == self.hero(g).id], [3])
        self.assertEqual(len(g.state.hero_health_change_history), 2)

    def test_friendly_minion_attack_does_not_convert_owner_hero(self):
        g = self.game(board=(BODY,), weapon=CARD)
        g.apply(Attack(1, g.state.players[1].board[0], self.hero(g, 2).id))
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (30, 0))
        self.assertFalse(self.events(g, 'health_lost'))

    def test_opponent_hero_attack_only_converts_their_own_account(self):
        g = self.game(weapon=CARD, enemy_weapon=CARD)
        g.apply(EndTurn(1)); self.attack(g, p=2)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (28, 0))
        self.assertEqual((self.hero(g, 2).health, self.hero(g, 2).armor), (25, 5))

    def test_cancelled_declaration_never_converts(self):
        g = self.game(board=(CANCEL,), enemy=(BODY,), weapon=CARD)
        self.attack(g, g.state.players[2].board[0])
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (30, 0))
        self.assertFalse(self.events(g, 'attack_finished'))
        self.assertFalse(self.events(g, 'health_lost'))

    def test_last_durability_still_rewards_original_weapon_completion(self):
        g = self.game(weapon=CARD); weapon = g.state.players[1].weapon_id
        self.attack(g); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (20, 10))
        self.assertEqual(g.state.entities[weapon].zone, Zone.GRAVEYARD)
        self.assertEqual([e.amount for e in self.events(g, 'health_lost')], [5, 5])
        self.portable(g)

    def test_low_health_is_not_given_an_invented_one_health_floor(self):
        g = self.game((LOW,), weapon=CARD); self.play(g, LOW); self.attack(g)
        self.assertEqual((g.state.status, g.state.winner), ('finished', 2))
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (-2, 5))
        self.portable(g)

    def test_existing_explicit_floor_only_converts_actual_debit(self):
        g = self.game(hero=FLOOR, weapon=CARD); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (28, 2))
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (28, 2))
        self.assertEqual([e.amount for e in self.events(g, 'armor_gained')], [2])

    def test_existing_loss_replacement_does_not_invent_converted_health(self):
        g = self.game(board=(GUARD,), weapon=CARD); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).max_health, self.hero(g).armor), (35, 35, 0))
        self.assertFalse(self.events(g, 'armor_gained'))
        self.assertFalse(gained_this_turn(g.state, 1))
        self.portable(g)

    def test_immunity_shield_and_existing_armor_do_not_absorb_direct_conversion(self):
        g = self.game(hero=IMMUNE, armor=7, weapon=CARD); self.attack(g)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (25, 12))
        self.assertIn(Keyword.DIVINE_SHIELD, self.hero(g).keywords)
        self.assertFalse(self.events(g, 'shield_lost'))

    def test_committed_conversion_wait_restore_late_failure_and_healing_do_not_reprice(self):
        g = self.game(board=(WAIT,), weapon=CARD); self.attack(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (25, 5))
        self.portable(g); saved = g.snapshot(); restored = Game.from_snapshot(saved, fixture('reader'))
        with self.assertRaises(ResolutionError):
            self.choose(restored, 'fail')
        self.assertEqual(restored.snapshot(), saved)
        self.choose(g, 'heal'); self.choose(restored, 'heal')
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (30, 5))
        self.portable(g)

    def test_failed_attack_reaction_rolls_back_attack_wear_loss_and_armor(self):
        g = self.game(board=(FAULT,), weapon=CARD); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.attack(g)
        self.assertEqual(g.snapshot(), saved)

    def test_typed_queued_conversion_restores_and_executes_once(self):
        g = self.game((QUEUE,)); self.play(g, QUEUE)
        self.assertIn('ConvertHeroHealthToArmor', json.dumps(g.snapshot()['resolution_frame']))
        self.portable(g)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), fixture('reader'))
        for game in (g, restored): self.choose(game, 'ok')
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (25, 5))

    def test_zero_request_has_no_new_loss_gain_or_occurrence(self):
        g = self.game((ZERO,), armor=4); self.play(g, ZERO)
        self.assertEqual((self.hero(g).health, self.hero(g).armor), (30, 4))
        self.assertFalse(g.state.hero_health_change_history)
        self.assertFalse(g.state.armor_gain_history)
        self.assertFalse(self.events(g, 'health_lost'))

    def test_invalid_amount_player_or_source_is_rejected_and_unknown_source_rolls_back(self):
        for args in [(True, 5, 1), (0, 5, 1), (1, True, 1), (1, -1, 1), (1, 5, None), (1, 5, True)]:
            with self.subTest(args=args), self.assertRaises(ValueError): ConvertHeroHealthToArmor(*args)
        g = self.game((BAD,)); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, BAD)
        self.assertEqual(g.snapshot(), saved)
