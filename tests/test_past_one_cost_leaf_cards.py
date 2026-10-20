"""Real historical leaf bodies and a deliberately finite Flashback experiment."""
from dataclasses import asdict
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.past_one_cost_leaf_cards import (
    SQUIRE, RAVEN, SKYTALON, ARCHER, TROGG, KNIGHT, DEPENDENCIES, load_batch)
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, TriggerSpec, UseHeroPower)
from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from tools.card_batch import check_face

HOLY = 'CORE_CS2_004'
FLASHBACK = 'TIME_711'
WATCH = 'fixture.past_one_cost_leaves.watch'
CONTEXT = GenerationContext('k323-six-leaf-experiment', 'experimental')


@lru_cache(maxsize=None)
def fixture(wait=False):
    registry = build_registry()
    registry.register_pool(PoolDefinition('constructed.past.cards', 'explicit-six-leaves-v1',
        CONTEXT.target_id, CONTEXT.mode, tuple(PoolMember(cid) for cid in DEPENDENCIES), complete=True))
    if wait:
        def observe(c):
            if c.event.kind != 'minion_summoned' or c.event.player_id != c.player_id: return ()
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        registry.register_behavior(WATCH, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit summon observer', CardType.MINION,
            health=20, triggers=(TriggerSpec('minion_summoned', WATCH),)))
    registry.validate()
    return registry


class PastOneCostLeafTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = fixture.__wrapped__()

    def game(self, hand=(), board=(), *, deck=(), enemy_hand=(), enemy_board=(), wait=False, seed=323):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if wait else ())+board,
                deck=deck, hero_power_card_id='HERO_08bp', mana=10, max_mana=10),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board,
                hero_power_card_id='HERO_08bp', mana=10, max_mana=10)),
            seed=seed, generation_context=CONTEXT), fixture(wait))

    def play(self, game, cid, *, player=1, target=None):
        source = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(player, source, target)); return source

    def portable(self, game, reader=None):
        registry = reader or self.reader; saved = game.snapshot()
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)

    def test_six_full_rows_twelve_primary_faces_and_exact_printed_metadata(self):
        data = load_batch(); registry = fixture()
        self.assertEqual(len(data['dependencies']), 6)
        self.assertEqual(len(data['official_observations']), 12)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        rows = {r['record']['id']: r['record'] for r in data['dependencies']}
        for cid, raw in rows.items():
            card = registry.card(cid)
            self.assertEqual((card.cost, card.attack, card.health), (raw['cost'], raw['attack'], raw['health']))
            self.assertEqual(asdict(card.metadata), asdict(metadata_from_record(raw)))
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']], observation['face'], observation['locale'])

    def test_three_printed_bodies_use_real_paid_minion_entry(self):
        for cid, attack, health, keywords in ((SQUIRE, 1, 1, {Keyword.DIVINE_SHIELD}),
                (RAVEN, 2, 2, set()), (SKYTALON, 2, 1, {Keyword.RUSH})):
            with self.subTest(card=cid):
                game = self.game((cid,)); eid = self.play(game, cid)
                entity = game.state.entities[eid]
                self.assertIn(eid, game.state.players[1].board)
                self.assertEqual((entity.attack, entity.health, game.state.players[1].mana), (attack, health, 9))
                self.assertTrue(keywords <= entity.keywords)

    def test_actual_shield_absorbs_damage_and_rush_keeps_hero_restriction(self):
        game = self.game((SQUIRE,)); eid = self.play(game, SQUIRE); game.apply(EndTurn(1))
        game.apply(UseHeroPower(2, game.state.players[2].hero_power_id, target_id=eid))
        self.assertEqual(game.state.entities[eid].health, 1)
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[eid].keywords)
        game = self.game((SKYTALON,), enemy_board=(RAVEN,)); eid = self.play(game, SKYTALON)
        saved = game.snapshot()
        with self.assertRaises(IllegalAction): game.apply(Attack(1, eid, game.state.players[2].hero_id))
        self.assertEqual(game.snapshot(), saved)
        target = game.state.players[2].board[0]; game.apply(Attack(1, eid, target))
        self.assertEqual((game.state.players[1].board, game.state.players[2].board), ([], []))

    def test_archer_requires_owner_inspire_and_current_empty_hand(self):
        for hand, expected in (((), 27), ((RAVEN,), 29)):
            with self.subTest(hand=hand):
                game = self.game(hand, (ARCHER,)); enemy = game.state.players[2].hero_id
                game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, target_id=enemy))
                self.assertEqual(game.state.entities[enemy].health, expected)
        game = self.game(board=(ARCHER,)); game.apply(EndTurn(1))
        before = game.state.entities[game.state.players[2].hero_id].health
        game.apply(UseHeroPower(2, game.state.players[2].hero_power_id, target_id=game.state.players[1].hero_id))
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, before)

    def test_trogg_responds_to_each_opponent_spell_and_summons_fresh_printed_bodies(self):
        game = self.game((HOLY,), (TROGG,), deck=(RAVEN,), enemy_hand=('GAME_005', 'GAME_005'))
        original = game.state.players[1].board[0]
        self.play(game, HOLY, target=original)
        self.assertEqual(game.state.players[1].board, [original])
        self.assertEqual(game.state.entities[original].health, 4)
        game.apply(EndTurn(1)); self.play(game, 'GAME_005', player=2)
        self.assertEqual(len(game.state.players[1].board), 2)
        self.play(game, 'GAME_005', player=2)
        self.assertEqual(len(game.state.players[1].board), 4)
        self.assertTrue(all(game.state.entities[i].card_id == TROGG for i in game.state.players[1].board))
        self.assertTrue(all(game.state.entities[i].health == 2 for i in game.state.players[1].board if i != original))
        self.portable(game)

    def test_full_board_trogg_summon_does_not_cancel_original_spell(self):
        game = self.game(board=(TROGG,)+(RAVEN,)*6, enemy_hand=('GAME_005',))
        game.apply(EndTurn(1)); before = game._rng.getstate(); self.play(game, 'GAME_005', player=2)
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(game._rng.getstate(), before)
        self.assertTrue(game.state.cast_history[-1].completed)

    def test_knight_draws_one_original_physical_holy_spell(self):
        game = self.game((KNIGHT,), deck=(HOLY, RAVEN, HOLY))
        originals = {i for i in game.state.players[1].deck if game.state.entities[i].card_id == HOLY}
        self.play(game, KNIGHT)
        self.assertEqual(len(game.state.players[1].hand), 1)
        self.assertIn(game.state.players[1].hand[0], originals)
        self.assertEqual(len(originals & set(game.state.players[1].deck)), 1)
        self.assertEqual(len(game.state.cast_history), 0)

    def test_knight_empty_or_nonmatching_deck_skips_fatigue_and_randomness(self):
        for deck in ((), (RAVEN,)):
            with self.subTest(deck=deck):
                game = self.game((KNIGHT,), deck=deck); before = game._rng.getstate()
                self.play(game, KNIGHT)
                self.assertEqual(game.state.players[1].hand, [])
                self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 30)
                self.assertEqual(game._rng.getstate(), before)

    def test_flashback_real_combo_uses_all_six_declared_leaves_without_battlecries(self):
        game = self.game(('GAME_005', FLASHBACK), deck=(HOLY,))
        self.play(game, 'GAME_005'); self.play(game, FLASHBACK)
        batch, = game.state.pool_summon_history
        self.assertEqual(len(batch.selected), 2)
        self.assertEqual({m.card_id for m in batch.spec.basis.candidates}, set(DEPENDENCIES))
        self.assertEqual(len(batch.spec.basis.candidates), 6)
        self.assertEqual(game.state.players[1].hand, [])
        for eid in game.state.players[1].board:
            entity = game.state.entities[eid]; printed = fixture().card(entity.card_id)
            self.assertEqual(entity.attack, printed.attack+1)
        self.portable(game)

    def test_flashback_wait_resumes_original_second_entry_once_and_replays(self):
        game = self.game(('GAME_005', FLASHBACK), wait=True)
        self.play(game, 'GAME_005'); self.play(game, FLASHBACK)
        reader = fixture.__wrapped__(True); waits = 0
        while game.state.pending_choice is not None:
            waits += 1; self.assertLessEqual(waits, 2); self.portable(game, reader)
            game = Game.from_snapshot(game.snapshot(), reader)
            q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, ('continue',)))
        self.assertEqual(waits, 2)
        batch, = game.state.pool_summon_history
        self.assertEqual((len(batch.selected), len(batch.entry_root_ids), batch.status), (2, 2, 'completed'))
        self.assertEqual(len(game.state.players[1].board), 3)
        self.portable(game, reader)


if __name__ == '__main__': unittest.main()
