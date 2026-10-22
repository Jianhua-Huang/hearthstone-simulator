"""Actual dual source declarations and their native bodies in assembled faces."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import assemble_dual_native_followups as cards
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID
from hs_sim.engine import (
    CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
    Scenario, SelectChoice, UseHeroPower, Zone,
)
from hs_sim.engine.assemble_faces import AssembleRecipe, DUAL_TIMING, printed_face
from hs_sim.engine.assemble_offers import ResolveAssemble
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import ChangeControl, Damage, DamageBatch
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_draw_armor_heal_fragments import (
    fixture as base_fixture, COIN, DECK, KILL, MUTE, S1, S2, S3, UNIT, WATCH, META,
)

GUARD, NEGOTIATOR, VENDOR, BELIEVER, THASSARIAN = cards.SOURCES
LOOT, BEETLE, ARCANE = 'CORE_EX1_096', 'CORE_LOOT_413', 'CORE_CS2_023'
PREFIXES = {'battlecry': 'CORE_GIL_622', 'deathrattle': LOOT,
    'end_turn': 'BE_152', 'start_turn': 'CORE_NEW1_021'}
P = 'k416.'
GIVE, DOUBLE_KILL, UNKNOWN = (P + name for name in ('give', 'double_kill', 'unknown_three_spell'))
CTX = GenerationContext('k416-native-dual-followups', 'experimental')


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = base_fixture.__wrapped__('no_pool', role)
    registry._version += '.k416.' + mode
    registry.register_behavior(GIVE, lambda c: (ChangeControl(c.target_id, 3-c.player_id),))

    def double_kill(c):
        board = c.state.players[c.player_id].board
        left = board[board.index(c.target_id)-1]
        return (DamageBatch((Damage(left, 99, c.source_id, DamageKind.EFFECT),
            Damage(c.target_id, 99, c.source_id, DamageKind.EFFECT))),)

    registry.register_behavior(DOUBLE_KILL, double_kill)
    for cid in (GIVE, DOUBLE_KILL):
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            metadata=META, requires_target=True))
    if mode == 'missing_source':
        registry._assemble_templates.pop(VENDOR)
    # These are explicit, complete test domains. They do not assert the formal
    # Standard or Assemble pools, which remain independently unverified.
    registry.register_pool(PoolDefinition(POOL_ID, 'k416-three-real-sources', CTX.target_id,
        CTX.mode, (PoolMember(VENDOR, 1000), PoolMember(LOOT), PoolMember(BEETLE)), complete=True))
    if mode != 'no_cast_pool':
        members = (PoolMember(ARCANE),)
        if mode == 'unknown_spell':
            registry.register_pool_card(replace(registry.pool_card(ARCANE), card_id=UNKNOWN))
            members += (PoolMember(UNKNOWN),)
        registry.register_pool(PoolDefinition('constructed.cards', 'k416-one-real-three-cost-spell',
            CTX.target_id, CTX.mode, members, complete=True))
    registry.validate()
    return registry


class AssembleDualNativeFollowupTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', seed=416):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', hand=hand, board=board,
                deck=DECK + (COIN,) * 10, mana=30, max_mana=30, mana_cap=30),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', board=enemy,
                deck=(S1, S2, S3) + (COIN,) * 20, mana=30, max_mana=30, mana_cap=30)),
            seed=seed, generation_context=CTX), fixture(mode))

    def play(self, game, cid, target=None, position=None):
        player = game.state.active_player
        source = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(player, source, target, position))
        return source

    def drawn(self, game, player=1):
        return [row for row in game.state.draw_history if row.player_id == player]

    def hero(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id]

    def power_price(self, game, player=1):
        power = game.state.entities[game.state.players[player].hero_power_id]
        return quote_cost(game.state, game.registry, power).amount

    def choose(self, game, option='ok'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def portable(self, game, mode='normal'):
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, game.registry)
        saved = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(saved, reader)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(game), reader).snapshot(), saved)
        for pid in (1, 2):
            visible = json.dumps(game.for_player(pid).observe()) + json.dumps(game.player_events(pid))
            for field in ('rng_state', 'behavior_id', 'definition_sha256', 'source_allocation'):
                self.assertNotIn('"' + field + '"', visible)
        return restored

    def test_a_five_whole_sources_ten_full_faces_and_original_native_reconstruction(self):
        data = cards.load_batch()
        registry = fixture()
        rows = {row['record']['id']: row for row in data['existing_dependencies']}
        self.assertEqual(tuple(rows), cards.SOURCES)
        self.assertEqual(len(data['official_observations']), 10)
        for obs in data['official_observations']:
            row = rows[obs['card_id']]
            check_face(row['record'], obs['face'], obs['locale'])
            self.assertEqual(sha(Path(obs['response_file'])), obs['response_sha256'])
        for cid, row in rows.items():
            original = registry.card(cid)
            template = registry.assemble_templates[cid]
            self.assertEqual(canonical_digest(asdict(original)), row['definition_sha256'])
            self.assertEqual(template.prefix.timing, DUAL_TIMING)
            self.assertEqual(printed_face(original, template.prefix, template.suffix, cid), original)
            self.assertEqual(original.battlecry, original.deathrattle)
            self.assertEqual(template.suffix.behavior_id, original.battlecry)
            self.assertEqual(set(template.suffix.allowed_timings), set(PREFIXES))

    def test_b_every_new_dual_prefix_executes_one_paid_battlecry_and_natural_deathrattle(self):
        for donor in cards.SOURCES:
            with self.subTest(donor=donor):
                cid = AssembleRecipe(LOOT, donor, 'top').card_id
                game = self.game((cid, KILL))
                source = self.play(game, cid)
                self.assertEqual(len(self.drawn(game)), 1)
                self.assertEqual(game.state.players[1].mana, 30-game.registry.card(cid).cost)
                self.play(game, KILL, source)
                self.assertEqual(len(self.drawn(game)), 2)
                self.assertEqual(len(game.state.battlecry_history), 1)
                self.assertEqual(len(game.state.deathrattle_history), 1)

    def test_c_five_real_suffix_bodies_execute_in_all_four_declared_contexts(self):
        # Direct Scenario recipes test the execution ABI; formal offer legality
        # is tested separately through the native producer below.
        for donor in cards.SOURCES:
            for timing, primary in PREFIXES.items():
                with self.subTest(donor=donor, timing=timing):
                    cid = AssembleRecipe(primary, donor, 'bottom').card_id
                    game = self.game((cid, KILL), board=(UNIT, UNIT))
                    left, right = game.state.players[1].board
                    source = self.play(game, cid, position=1)
                    if timing == 'deathrattle':
                        self.play(game, KILL, source)
                    elif timing == 'end_turn':
                        game.apply(EndTurn(1))
                    elif timing == 'start_turn':
                        game.apply(EndTurn(1))
                        game.apply(EndTurn(2))
                    normal_own_draw = int(timing == 'start_turn')
                    normal_enemy_draw = int(timing in ('end_turn', 'start_turn'))
                    if donor == GUARD:
                        self.assertEqual([(game.state.entities[i].attack, game.state.entities[i].health)
                            for i in (left, right)], [(2, 22), (2, 22)])
                    elif donor == NEGOTIATOR:
                        expected_casts = ([KILL] if timing == 'deathrattle' else []) + [ARCANE]
                        self.assertEqual([row.card_id for row in game.state.cast_history], expected_casts)
                        self.assertEqual(len(self.drawn(game)), 2 + normal_own_draw)
                    elif donor == VENDOR:
                        self.assertEqual(len(self.drawn(game)), 1 + normal_own_draw)
                        self.assertEqual(len(self.drawn(game, 2)), 1 + normal_enemy_draw)
                    elif donor == BELIEVER:
                        self.assertEqual(self.power_price(game), 0)
                    elif donor == THASSARIAN:
                        self.assertEqual(self.hero(game, 2).health, 28)
                    self.assertEqual(game.state.hero_power_history, [])

    def test_d_guard_natural_death_keeps_original_neighbors_and_does_not_shift_to_a_survivor(self):
        cid = AssembleRecipe(LOOT, GUARD, 'bottom').card_id
        game = self.game((cid, DOUBLE_KILL), board=(UNIT, UNIT, UNIT))
        left, right, far = game.state.players[1].board
        source = self.play(game, cid, position=1)
        self.play(game, DOUBLE_KILL, source)
        record = next(row for row in game.state.death_history if row.entity_id == source)
        self.assertEqual(tuple(ref.entity_id for ref in record.adjacent_minions), (left, right))
        self.assertEqual(game.state.entities[left].zone, Zone.GRAVEYARD)
        self.assertEqual((game.state.entities[right].attack, game.state.entities[far].attack), (2, 0))

    def test_e_deathrattle_after_transfer_draws_for_actual_receiver_first(self):
        cid = AssembleRecipe(LOOT, VENDOR, 'bottom').card_id
        game = self.game((cid, GIVE, KILL))
        source = self.play(game, cid)
        self.play(game, GIVE, source)
        self.play(game, KILL, source)
        self.assertEqual([row.player_id for row in game.state.draw_history], [2, 1])
        self.assertEqual(game.state.deathrattle_history[-1].capture.player_id, 2)

    def test_f_next_power_zero_survives_source_death_and_is_consumed_by_one_real_power(self):
        cid = AssembleRecipe(PREFIXES['battlecry'], BELIEVER, 'bottom').card_id
        game = self.game((cid, KILL))
        source = self.play(game, cid)
        self.play(game, KILL, source)
        self.assertEqual(self.power_price(game), 0)
        before = game.state.players[1].mana
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, self.hero(game, 2).id))
        self.assertEqual(game.state.players[1].mana, before)
        self.assertEqual(game.state.hero_power_history[-1].cost, 0)
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        self.assertEqual(self.power_price(game), 2)

    def test_g_thassarian_prefix_preserves_reborn_without_another_battlecry(self):
        cid = AssembleRecipe(LOOT, THASSARIAN, 'top').card_id
        game = self.game((cid, KILL, KILL))
        source = self.play(game, cid)
        self.assertIn(Keyword.REBORN, game.state.entities[source].keywords)
        self.play(game, KILL, source)
        reborn, = game.state.players[1].board
        self.assertNotEqual(reborn, source)
        self.assertEqual(game.state.entities[reborn].health, 1)
        self.assertEqual(len(game.state.battlecry_history), 1)
        self.play(game, KILL, reborn)
        self.assertEqual(game.state.players[1].board, [])
        self.assertEqual(len(self.drawn(game)), 3)

    def test_h_both_dual_windows_pause_restore_replay_and_failed_resume_remains_atomic(self):
        cid = AssembleRecipe(LOOT, VENDOR, 'top').card_id
        game = self.game((cid, KILL), board=(WATCH,))
        source = self.play(game, cid)
        for phase in ('battlecry', 'deathrattle'):
            if phase == 'deathrattle':
                self.play(game, KILL, source)
            self.assertIsNotNone(game.state.pending_choice)
            restored = self.portable(game)
            before = game.snapshot()
            with self.assertRaisesRegex(ResolutionError, 'assembled draw observer fault'):
                self.choose(game, 'fault')
            self.assertEqual(game.snapshot(), before)
            for branch in (game, restored):
                self.choose(branch)
            self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(len(self.drawn(game)), 2)
        self.assertEqual(len(game.state.battlecry_history), 1)
        self.assertEqual(len(game.state.deathrattle_history), 1)

    def test_i_real_flesh_entry_offers_new_dual_source_and_retains_both_windows(self):
        game = self.game((FLESH, KILL))
        self.play(game, FLESH)
        offer = next(effect.offer for option in game._frame.options for effect in option.effects
            if isinstance(effect, ResolveAssemble))
        self.assertEqual(offer.primary_card_id, VENDOR)
        self.assertIn(VENDOR, offer.primary_candidates)
        cid = AssembleRecipe(VENDOR, LOOT, 'bottom').card_id
        choice = game.state.pending_choice
        option = next(option for option in choice.options if option.card_id == cid)
        self.choose(game, option.id)
        before = game.state.players[1].mana
        source = self.play(game, cid)
        self.assertEqual(game.state.players[1].mana, before-game.registry.card(VENDOR).cost)
        self.play(game, KILL, source)
        self.assertEqual(len(self.drawn(game)), 2)
        self.assertEqual(game.state.card_discovery_history, [])
        self.portable(game)

    def test_j_missing_native_source_template_rolls_back_the_whole_real_entry(self):
        game = self.game((FLESH,), mode='missing_source')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, FLESH)
        self.assertEqual(game.snapshot(), before)

    def test_k_missing_constructed_cast_domain_does_not_fall_back_to_an_experiment(self):
        cid = AssembleRecipe(PREFIXES['battlecry'], NEGOTIATOR, 'bottom').card_id
        game = self.game((cid,), mode='no_cast_pool')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, cid)
        self.assertEqual(game.snapshot(), before)

    def test_l_unknown_qualified_three_cost_spell_is_not_removed_before_sampling(self):
        cid = AssembleRecipe(PREFIXES['battlecry'], NEGOTIATOR, 'bottom').card_id
        game = self.game((cid,), mode='unknown_spell')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, cid)
        self.assertEqual(game.snapshot(), before)

    def test_m_changed_full_source_pin_or_missing_nested_body_rejects_before_installing_any_template(self):
        for mutation in ('definition', 'nested_body'):
            registry = fixture.__wrapped__()
            for cid in cards.SOURCES:
                registry._assemble_templates.pop(cid)
            before = set(registry.assemble_templates)
            if mutation == 'definition':
                registry._cards[VENDOR] = replace(registry.card(VENDOR), health=4)
            else:
                registry._behaviors.pop('cards.native_random_damage.thassarian_current')
            with self.assertRaises((TargetValidationError, UnsupportedDefinitionError)):
                cards.register_assemble_dual_native_followups(registry)
            self.assertEqual(set(registry.assemble_templates), before)


if __name__ == '__main__':
    unittest.main()
