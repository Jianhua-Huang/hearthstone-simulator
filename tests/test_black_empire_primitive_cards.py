"""Real announced Black Empire roots through shared resource and lifecycle paths."""
from dataclasses import asdict
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.black_empire_primitive_cards import (ANVIL, HERALD, RAY, PROTOTYPE,
    SERVANT, WYRM, KNIGHT, VANGUARD, ANIMATOR, WARBAND, CULTIST, ANOMALY, GOLEM, ROOTS, load_batch)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor, RequestChoice, Silence)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from tools.card_batch import check_face

P = 'fixture.black_empire_primitives.'
KILL, HURT, ARMOR, QUIET, SPAWN, DUMMY, WATCH = (P+n for n in ('kill', 'hurt', 'armor', 'quiet', 'spawn', 'dummy', 'watch'))
RAVEN, COIN, FIRE, DAGGER = 'KAR_300', 'GAME_005', 'CORE_CS2_029', 'CS2_082'


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    bodies = {
        KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 10, c.source_id),),
        ARMOR: lambda c: (GainArmor(c.player_id, 4),),
        QUIET: lambda c: (Silence(c.target_id),),
        SPAWN: lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial(RAVEN),), SummonCause.capture(c)),),
    }
    for cid, body in bodies.items():
        registry.register_behavior(cid, body)
        target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid in (KILL, QUIET) else None
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL, on_play=cid, targeting=target))
    registry.register_card(CardDefinition(DUMMY, 'Explicit combat probe', CardType.MINION, attack=1, health=10))
    if mode != 'normal':
        def observe(c):
            if c.event.player_id != c.player_id: return ()
            if mode == 'wait_armor' and c.event.kind == 'armor_gained' or mode == 'wait_draw' and c.event.kind == 'card_drawn':
                return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
            return ()
        body = WATCH+'.'+mode; registry.register_behavior(body, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit continuation observer', CardType.MINION, health=20,
            triggers=(TriggerSpec('armor_gained' if mode == 'wait_armor' else 'card_drawn', body),)))
    registry.validate()
    return registry


class BlackEmpirePrimitiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.readers = {'normal': fixture.__wrapped__()}

    def game(self, hand=(), board=(), *, deck=(), enemy_hand=(), enemy_board=(), armor=0, mana=10,
            weapon=None, mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if mode != 'normal' else ())+board,
                deck=deck, armor=armor, mana=mana, max_mana=10, weapon_card_id=weapon, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, mana=10, max_mana=10, hero_power_card_id='HERO_08bp')),
            seed=325), fixture(mode))

    def play(self, game, cid, *, target=None, player=1):
        eid = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(player, eid, target_id=target)); return eid

    def board(self, game, cid, player=1):
        return next(i for i in game.state.players[player].board if game.state.entities[i].card_id == cid)

    def price(self, game, eid): return quote_unselected_cost(game.state, game.registry, game.state.entities[eid]).amount

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        registry = self.readers[mode]; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        return Game.from_snapshot(saved, registry)

    def test_thirteen_complete_records_twenty_six_primary_faces_and_exact_metadata(self):
        data = load_batch(); registry = fixture()
        self.assertEqual(tuple(r['record']['id'] for r in data['cards']), ROOTS)
        self.assertEqual(len(data['official_observations']), 26)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        records = {r['record']['id']: r['record'] for r in data['cards']}
        for cid, raw in records.items():
            self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(raw)))
            self.assertEqual(registry.card(cid).cost, raw['cost'])
        for o in data['official_observations']:
            raw = records[o['card_id']]
            check_face(raw, o['face'], o['locale'], numeric_normalizations={'attack': 0} if raw['id'] == PROTOTYPE else None)
            if raw['type'] == 'SPELL': self.assertEqual(o['face']['spellSchoolId'], raw['tags']['SPELL_SCHOOL'])
        self.assertEqual(registry.card(PROTOTYPE).attack, 0)

    def test_printed_poisonous_and_lifesteal_bodies_use_real_paid_entry(self):
        for cid, keyword in ((RAY, Keyword.POISONOUS), (KNIGHT, Keyword.LIFESTEAL)):
            with self.subTest(card=cid):
                game = self.game((cid,)); eid = self.play(game, cid)
                self.assertIn(eid, game.state.players[1].board)
                self.assertIn(keyword, game.state.entities[eid].keywords)
                self.assertEqual(game.state.players[1].mana, 10-fixture().card(cid).cost)

    def test_ray_poisonous_kills_a_surviving_combat_target(self):
        game = self.game(board=(RAY,), enemy_board=(DUMMY,))
        target = game.state.players[2].board[0]
        game.apply(Attack(1, self.board(game, RAY), target))
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(game.state.players[1].board), 1)

    def test_knight_lifesteal_uses_actual_combat_damage(self):
        game = self.game((HURT,), (KNIGHT,), enemy_board=(DUMMY,)); self.play(game, HURT)
        game.apply(Attack(1, self.board(game, KNIGHT), game.state.players[2].board[0]))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 23)

    def test_prototype_both_natural_deaths_buff_only_original_hand_minions(self):
        game = self.game((PROTOTYPE, KILL, KILL, RAVEN, COIN)); self.play(game, PROTOTYPE)
        original = self.board(game, PROTOTYPE); self.play(game, KILL, target=original)
        returned = self.board(game, PROTOTYPE); self.assertNotEqual(returned, original)
        self.assertEqual(game.state.entities[returned].health, 1)
        self.assertNotIn(Keyword.REBORN, game.state.entities[returned].keywords)
        self.play(game, KILL, target=returned)
        raven = next(game.state.entities[i] for i in game.state.players[1].hand if game.state.entities[i].card_id == RAVEN)
        self.assertEqual((raven.attack, raven.health), (4, 4))
        self.assertEqual(game.state.players[1].board, [])
        self.assertTrue(all(game.state.entities[i].attack == 0 for i in game.state.players[1].hand if game.state.entities[i].kind == CardType.SPELL))
        self.portable(game)

    def test_golem_reborn_and_original_deathrattles_heal_hero_twice(self):
        game = self.game((HURT, GOLEM, KILL, KILL)); self.play(game, HURT); self.play(game, GOLEM)
        first = self.board(game, GOLEM); self.play(game, KILL, target=first)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 23)
        second = self.board(game, GOLEM); self.assertEqual(game.state.entities[second].health, 1)
        self.play(game, KILL, target=second)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 26)
        self.assertEqual(game.state.players[1].board, [])

    def test_vanguard_original_battlecry_and_deathrattle_each_gain_three_armor(self):
        game = self.game((VANGUARD, KILL)); source = self.play(game, VANGUARD)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.assertIn(Keyword.TAUNT, game.state.entities[source].keywords)
        self.play(game, KILL, target=source)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 6)

    def test_servant_silences_original_minion_and_empty_board_keeps_body(self):
        game = self.game((SERVANT,), enemy_board=(RAY,)); target = game.state.players[2].board[0]
        self.play(game, SERVANT, target=target)
        self.assertNotIn(Keyword.POISONOUS, game.state.entities[target].keywords)
        game = self.game((SERVANT,)); source = self.play(game, SERVANT)
        self.assertIn(source, game.state.players[1].board)

    def test_herald_checks_current_equipment_and_gains_original_stats_and_rush(self):
        for weapon, stats, rush in ((None, (3, 3), False), (DAGGER, (4, 4), True)):
            with self.subTest(weapon=weapon):
                game = self.game((HERALD,), weapon=weapon); eid = self.play(game, HERALD)
                entity = game.state.entities[eid]
                self.assertEqual((entity.attack, entity.health), stats)
                self.assertEqual(Keyword.RUSH in entity.keywords, rush)

    def test_wyrm_only_grows_for_another_own_played_minion(self):
        game = self.game((WYRM, SPAWN, COIN, RAVEN)); source = self.play(game, WYRM)
        self.assertEqual(game.state.entities[source].health, 1)
        self.play(game, SPAWN); self.play(game, COIN)
        self.assertEqual(game.state.entities[source].health, 1)
        self.play(game, RAVEN); self.assertEqual(game.state.entities[source].health, 2)

    def test_warband_draws_once_for_another_play_not_self_or_summon(self):
        game = self.game((WARBAND, SPAWN, RAVEN), deck=(RAVEN,)); self.play(game, WARBAND)
        self.assertEqual(len(game.state.players[1].deck), 1)
        self.play(game, SPAWN); self.assertEqual(len(game.state.players[1].deck), 1)
        self.play(game, RAVEN); self.assertEqual(len(game.state.players[1].deck), 0)
        self.assertEqual(len(game.state.players[1].hand), 1)

    def test_animator_draws_once_per_positive_own_gain_and_ignores_opponent(self):
        game = self.game((ARMOR,), (ANIMATOR,), deck=(RAVEN, RAVEN), enemy_hand=(ARMOR,))
        self.play(game, ARMOR)
        self.assertEqual((len(game.state.players[1].hand), len(game.state.players[1].deck)), (1, 1))
        game.apply(EndTurn(1)); self.play(game, ARMOR, player=2)
        self.assertEqual((len(game.state.players[1].hand), len(game.state.players[1].deck)), (1, 1))

    def test_cultist_symmetric_spell_quotes_retire_through_original_silence(self):
        game = self.game((QUIET, FIRE, RAVEN), (CULTIST,), enemy_hand=(FIRE, RAVEN))
        own = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == FIRE)
        enemy = next(i for i in game.state.players[2].hand if game.state.entities[i].card_id == FIRE)
        self.assertEqual((self.price(game, own), self.price(game, enemy)), (5, 5))
        self.assertTrue(all(self.price(game, i) == 1 for p in (1, 2) for i in game.state.players[p].hand if game.state.entities[i].card_id == RAVEN))
        self.play(game, QUIET, target=self.board(game, CULTIST))
        self.assertEqual((self.price(game, own), self.price(game, enemy)), (4, 4))

    def test_anvil_pays_armor_with_zero_mana_and_attack_expires_at_turn_end(self):
        game = self.game((ANVIL,), armor=2, mana=0); self.play(game, ANVIL)
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual((hero.armor, hero.attack, game.state.players[1].mana), (0, 4, 0))
        game.apply(EndTurn(1)); self.assertEqual(game.state.entities[hero.id].attack, 0)

    def test_insufficient_armor_rejects_before_payment_even_with_full_mana(self):
        game = self.game((ANVIL,), armor=1); saved = game.snapshot()
        with self.assertRaises(IllegalAction): self.play(game, ANVIL)
        self.assertEqual(game.snapshot(), saved)

    def test_anomaly_requires_enemy_then_freezes_gains_armor_and_draws_original_card(self):
        game = self.game((ANOMALY,), deck=(RAVEN,)); source = game.state.players[1].hand[0]
        saved = game.snapshot()
        with self.assertRaises(IllegalAction): game.apply(PlayCard(1, source, target_id=game.state.players[1].hero_id))
        self.assertEqual(game.snapshot(), saved)
        original = game.state.players[1].deck[0]; target = game.state.players[2].hero_id
        self.play(game, ANOMALY, target=target)
        self.assertTrue(game.state.entities[target].frozen)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.assertEqual(game.state.players[1].hand, [original])

    def test_anomaly_armor_wait_restores_before_its_one_remaining_draw(self):
        game = self.game((ANOMALY,), deck=(RAVEN,), mode='wait_armor')
        self.play(game, ANOMALY, target=game.state.players[2].hero_id)
        self.assertIsNotNone(game.state.pending_choice); self.assertEqual(game.state.players[1].hand, [])
        game = self.portable(game, 'wait_armor'); q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, ('continue',)))
        self.assertEqual(len(game.state.players[1].hand), 1)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.portable(game, 'wait_armor')

    def test_warband_draw_notification_wait_resumes_the_same_completed_play(self):
        game = self.game((RAVEN,), (WARBAND,), deck=(RAVEN,), mode='wait_draw')
        self.play(game, RAVEN); self.assertIsNotNone(game.state.pending_choice)
        game = self.portable(game, 'wait_draw'); q = game.state.pending_choice
        game.apply(SelectChoice(q.player_id, q.id, ('continue',)))
        self.assertEqual((len(game.state.players[1].hand), len(game.state.players[1].deck)), (1, 0))
        self.portable(game, 'wait_draw')


if __name__ == '__main__': unittest.main()
