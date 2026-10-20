"""Friendly current-turn zero price over complete original physical deaths."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.black_empire_death_condition_cards import CAVERN, BEAST, PROFILE, ROOTS, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, Keyword,
    MinionDeathCostSpec, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.costs import (capture_cost_input, capture_generated_quote_fact,
    capture_quote_fact, quote_unselected_cost)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption,
    Damage, Destroy, DestroyBatch, ModifyCost, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.minion_death_costs import validate_fact
from hs_sim.engine.model import CardClass, CardMetadata
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from tools.card_batch import check_face

P = 'fixture.black_empire_death_conditions.'
KILL, KILL_BOTH, HURT, ACQUIRE, LOCAL, EXTERNAL, TAKE, GIVE, RETURN, MORPH, REMOVE, BREAK, DEMOLISH, VICTIM, LOCATION, WATCH = (
    P+n for n in ('kill', 'kill_both', 'hurt', 'acquire', 'local', 'external', 'take', 'give',
        'return', 'morph', 'remove', 'break', 'demolish', 'victim', 'location', 'watch'))
COIN, RAVEN, DAGGER, PROTOTYPE = 'GAME_005', 'KAR_300', 'CS2_082', 'BE_207'
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    registry = build_registry()
    def held(c):
        return next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == CAVERN)
    bodies = {P+'noop': lambda c: (), KILL: lambda c: (Destroy(c.target_id, c.source_id),),
        KILL_BOTH: lambda c: (DestroyBatch(tuple(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].card_id == VICTIM), c.source_id),),
        HURT: lambda c: (Damage(c.state.players[c.player_id].hero_id, 12, c.source_id),),
        ACQUIRE: lambda c: (AddToHand(c.player_id, CAVERN, c.source_id),),
        LOCAL: lambda c: (ModifyCost(held(c), CostSpec(set_to=4), c.source_id),),
        EXTERNAL: lambda c: (AddCostModifier(c.player_id, CostSpec(delta=1, card_ids=(CAVERN,)), source_id=c.source_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, c.player_id),),
        GIVE: lambda c: (ChangeControl(c.target_id, 3-c.player_id),),
        RETURN: lambda c: (ReturnToHand(c.target_id),), MORPH: lambda c: (Transform(c.target_id, RAVEN),),
        REMOVE: lambda c: (RemoveFromGame((MinionReference.capture(c.state.entities[c.target_id]),), c.source_id),),
        BREAK: lambda c: (Destroy(c.state.players[c.player_id].weapon_id, c.source_id),),
        DEMOLISH: lambda c: (DestroyLocation(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].kind == CardType.LOCATION), c.source_id),)}
    for cid, body in bodies.items(): registry.register_behavior(cid, body)
    for cid in bodies:
        if cid == P+'noop': continue
        target = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)) if cid in (KILL, TAKE, GIVE, RETURN, MORPH, REMOVE) else None
        registry.register_card(CardDefinition(cid, 'Explicit test operation', CardType.SPELL,
            metadata=META, on_play=cid, targeting=target))
    registry.register_card(CardDefinition(VICTIM, 'Explicit original victim', CardType.MINION,
        health=2, metadata=META))
    registry.register_card(CardDefinition(LOCATION, 'Explicit uncounted location', CardType.LOCATION,
        durability=2, on_use=P+'noop', metadata=META))
    if mode != 'normal':
        def observe(c):
            if mode == 'wait_death':
                if dict(c.event.data)['death_id'] != 1: return ()
                options = (ChoiceOption('continue', 'Finish original death notifications'),)
            else:
                source = c.state.entities.get(c.event.source_id)
                if source is None or source.card_id != CAVERN: return ()
                original = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == VICTIM)
                options = (ChoiceOption('kill', 'Destroy later friendly minion', (Destroy(original, c.source_id),)),)
            return (RequestChoice(c.player_id, options, c.source_id),)
        registry.register_behavior(WATCH, observe)
        registry.register_card(CardDefinition(WATCH, 'Explicit original-window observer', CardType.MINION,
            health=10, metadata=META, triggers=(TriggerSpec('minion_died' if mode == 'wait_death' else 'damage_dealt', WATCH),)))
    registry.validate()
    return registry


class BlackEmpireDeathConditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.readers = {}

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), mana=10, weapon=None, mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=((WATCH,) if mode != 'normal' else ())+board,
                deck=(COIN,)*8, mana=mana, max_mana=10, weapon_card_id=weapon, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=(COIN,)*8,
                mana=10, max_mana=10, hero_power_card_id='HERO_08bp')), seed=328), fixture(mode))

    def play(self, game, cid, target=None, player=1):
        eid = next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == cid)
        game.apply(PlayCard(player, eid, target_id=target)); return eid

    def board(self, game, cid, player=1):
        return next(i for i in game.state.players[player].board if game.state.entities[i].card_id == cid)

    def subject(self, game, player=1):
        return next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == CAVERN)

    def price(self, game, player=1):
        return quote_unselected_cost(game.state, game.registry, game.state.entities[self.subject(game, player)]).amount

    def fact(self, game):
        return capture_quote_fact(game.state, game.registry, capture_cost_input(game.state.entities[self.subject(game)]))

    def portable(self, game, mode='normal'):
        if mode not in self.readers: self.readers[mode] = fixture.__wrapped__(mode)
        saved = game.snapshot(); registry = self.readers[mode]
        self.assertEqual(game.clone().snapshot(), saved)
        self.assertEqual(Game.from_snapshot(saved, registry).snapshot(), saved)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(game.for_player(player).observe())+json.dumps(game.player_events(player))
            self.assertNotIn('"minion_deaths"', public); self.assertNotIn('"rng_state"', public)
        return Game.from_snapshot(saved, registry)

    def choose(self, game, key):
        q = game.state.pending_choice; game.apply(SelectChoice(q.player_id, q.id, (key,)))

    def test_two_complete_source_rows_four_primary_faces_and_exact_metadata(self):
        data = load_batch(); registry = fixture(); rows = {x['record']['id']: x['record'] for x in data['cards']}
        self.assertEqual(tuple(rows), ROOTS); self.assertEqual(len(data['official_observations']), 4)
        for cid, raw in rows.items(): self.assertEqual(asdict(registry.card(cid).metadata), asdict(metadata_from_record(raw)))
        for observation in data['official_observations']:
            check_face(rows[observation['card_id']], observation['face'], observation['locale'])
        self.assertEqual(registry.card(CAVERN).minion_death_cost, MinionDeathCostSpec(PROFILE))
        self.assertIn(Keyword.LIFESTEAL, registry.card(CAVERN).keywords)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_new_zero_formula_and_both_old_per_occurrence_formulas_remain_distinct(self):
        spec = MinionDeathCostSpec(PROFILE)
        self.assertEqual([spec.price(2, n) for n in (0, 1, 2, 3)], [2, 0, 0, 0])
        for profile in ('cost.minion-deaths-friendly-game-v1', 'cost.minion-deaths-both-turn-v1'):
            self.assertEqual([MinionDeathCostSpec(profile).price(2, n) for n in (0, 1, 2, 3)], [2, 1, 0, 0])
        for before, quantity in ((True, 1), (2, False), (-1, 0), (2, -1)):
            with self.subTest(values=(before, quantity)), self.assertRaises(ValueError): spec.price(before, quantity)

    def test_no_death_or_only_enemy_death_keeps_printed_two(self):
        game = self.game((CAVERN, KILL), enemy_board=(VICTIM,))
        self.assertEqual(self.price(game), 2)
        self.play(game, KILL, self.board(game, VICTIM, 2)); self.assertEqual(self.price(game), 2)
        fact = self.fact(game).intrinsic.minion_deaths
        self.assertEqual((fact.quantity, fact.after, len(fact.records)), (0, 2, 1))

    def test_one_friendly_death_zero_payment_actual_damage_lifesteal_and_other_player(self):
        game = self.game((HURT, KILL, CAVERN), (VICTIM,), enemy_hand=(CAVERN,), mana=0)
        self.play(game, HURT); self.play(game, KILL, self.board(game, VICTIM))
        self.assertEqual((self.price(game), self.price(game, 2)), (0, 2))
        self.play(game, CAVERN, game.state.players[2].hero_id)
        self.assertEqual((game.state.players[1].mana, game.state.play_history[-1].cost), (0, 0))
        self.assertEqual((game.state.entities[game.state.players[1].hero_id].health,
            game.state.entities[game.state.players[2].hero_id].health), (20, 28))
        self.portable(game)

    def test_acquisition_after_friendly_death_uses_original_history(self):
        game = self.game((KILL, ACQUIRE), (VICTIM,))
        self.play(game, KILL, self.board(game, VICTIM)); self.play(game, ACQUIRE)
        self.assertEqual(self.price(game), 0)

    def test_global_turn_scope_counts_own_death_on_opponent_turn_then_resets(self):
        game = self.game((CAVERN,), (VICTIM,), enemy_hand=(KILL, CAVERN))
        game.apply(EndTurn(1)); self.play(game, KILL, self.board(game, VICTIM), player=2)
        self.assertEqual((self.price(game), self.price(game, 2)), (0, 2))
        game.apply(EndTurn(2)); self.assertEqual(self.price(game), 2)

    def test_death_time_controller_in_both_directions_defines_friendly(self):
        for operation, own_board, enemy_board, expected in ((GIVE, (VICTIM,), (), (2, 0)),
                (TAKE, (), (VICTIM,), (0, 2))):
            with self.subTest(operation=operation):
                game = self.game((operation, KILL, CAVERN), own_board, enemy_board=enemy_board, enemy_hand=(CAVERN,))
                target = self.board(game, VICTIM, 1 if own_board else 2)
                self.play(game, operation, target); self.play(game, KILL, target)
                self.assertEqual((self.price(game), self.price(game, 2)), expected)

    def test_non_death_zone_changes_never_qualify(self):
        for operation in (RETURN, MORPH, REMOVE):
            with self.subTest(operation=operation):
                game = self.game((operation, CAVERN), (VICTIM,))
                self.play(game, operation, self.board(game, VICTIM))
                self.assertEqual((self.price(game), len(game.state.death_history)), (2, 0))

    def test_weapon_and_location_deaths_stay_in_complete_unselected_prefix(self):
        game = self.game((BREAK, DEMOLISH, CAVERN), (LOCATION,), weapon=DAGGER)
        self.play(game, BREAK); self.play(game, DEMOLISH)
        fact = self.fact(game).intrinsic.minion_deaths
        self.assertEqual((self.price(game), fact.quantity, len(fact.records)), (2, 0, 2))
        with self.assertRaises(ValueError):
            validate_fact(game.registry, game.registry.card(CAVERN),
                replace(fact, selected_ids=(2,), quantity=1, after=0))

    def test_reborn_both_original_deaths_count_and_equal_zero_cannot_hide_selection(self):
        game = self.game((KILL, KILL, CAVERN), (PROTOTYPE,))
        self.play(game, KILL, self.board(game, PROTOTYPE)); self.play(game, KILL, self.board(game, PROTOTYPE))
        fact = self.fact(game).intrinsic.minion_deaths
        self.assertEqual((fact.quantity, fact.after, fact.selected_ids), (2, 0, (1, 2)))
        shortened = replace(fact, selected_ids=(1,), quantity=1)
        self.assertEqual(shortened.after, 0)
        with self.assertRaises(ValueError): validate_fact(game.registry, game.registry.card(CAVERN), shortened)
        swapped = replace(fact, spec=MinionDeathCostSpec('cost.minion-deaths-both-turn-v1'))
        with self.assertRaises(ValueError): validate_fact(game.registry, game.registry.card(CAVERN), swapped)

    def test_formula_relation_and_original_turn_cannot_be_forged_at_equal_price(self):
        game = self.game((KILL, CAVERN), enemy_board=(VICTIM,))
        self.play(game, KILL, self.board(game, VICTIM, 2)); fact = self.fact(game).intrinsic.minion_deaths
        with self.assertRaises(ValueError): replace(fact, selected_ids=(1,), quantity=1, after=0)
        own = self.game((KILL, CAVERN), (VICTIM,)); self.play(own, KILL, self.board(own, VICTIM))
        original = self.fact(own).intrinsic.minion_deaths
        with self.assertRaises(ValueError): replace(original, after=1)
        with self.assertRaises(ValueError): replace(original, turn=original.turn+1)

    def test_generated_and_physical_quotes_share_zero_fact_and_are_pure(self):
        game = self.game((KILL, CAVERN), (VICTIM,)); self.play(game, KILL, self.board(game, VICTIM))
        saved = game.snapshot()
        for _ in range(3):
            generated = capture_generated_quote_fact(game.state, game.registry, 1, CAVERN)
            self.assertEqual(generated.amount, 0)
            self.assertEqual(generated.intrinsic.minion_deaths, self.fact(game).intrinsic.minion_deaths)
        self.assertEqual(game.snapshot(), saved)

    def test_local_and_external_layers_follow_zero_intrinsic_and_pay_final_quote(self):
        game = self.game((KILL, LOCAL, EXTERNAL, CAVERN), (VICTIM,))
        self.play(game, KILL, self.board(game, VICTIM)); self.play(game, LOCAL); self.play(game, EXTERNAL)
        fact = self.fact(game); self.assertEqual((fact.intrinsic.minion_deaths.after, fact.amount), (0, 5))
        self.play(game, CAVERN, game.state.players[2].hero_id)
        self.assertEqual((game.state.players[1].mana, game.state.play_history[-1].cost), (5, 5))

    def test_pending_complete_death_batch_is_visible_before_remaining_notifications(self):
        game = self.game((KILL_BOTH, CAVERN), (VICTIM, VICTIM), mode='wait_death')
        self.play(game, KILL_BOTH); self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual((self.fact(game).intrinsic.minion_deaths.quantity, self.price(game)), (2, 0))
        game = self.portable(game, 'wait_death'); self.choose(game, 'continue')
        self.assertEqual(len(game.state.death_history), 2)
        self.portable(game, 'wait_death')

    def test_later_death_changes_other_card_quote_without_refunding_accepted_payment(self):
        game = self.game((CAVERN, CAVERN), (VICTIM,), mode='wait_damage')
        original = self.play(game, CAVERN, game.state.players[2].hero_id)
        self.assertIsNotNone(game.state.pending_choice); self.assertEqual(game.state.players[1].mana, 8)
        game = self.portable(game, 'wait_damage'); self.choose(game, 'kill')
        record = next(r for r in game.state.play_history if r.source_id == original)
        self.assertEqual((record.cost, record.submitted_cost.quote.intrinsic.minion_deaths.quantity), (2, 0))
        self.assertEqual((game.state.players[1].mana, self.price(game)), (8, 0))
        self.portable(game, 'wait_damage')

    def test_beast_no_friendly_death_does_not_attack_or_consume_rng(self):
        for enemy_dies in (False, True):
            with self.subTest(enemy_dies=enemy_dies):
                game = self.game((KILL, BEAST), enemy_board=(VICTIM,) if enemy_dies else ())
                if enemy_dies: self.play(game, KILL, self.board(game, VICTIM, 2))
                rng = game._rng.getstate(); self.play(game, BEAST)
                self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30)
                self.assertEqual(game._rng.getstate(), rng)

    def test_beast_actual_friendly_death_enables_one_forced_attack(self):
        game = self.game((KILL, BEAST), (VICTIM,)); self.play(game, KILL, self.board(game, VICTIM))
        source = self.play(game, BEAST)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 23)
        self.assertEqual((game.state.entities[source].attack, game.state.entities[source].health), (7, 5))

    def test_beast_previous_turn_death_does_not_enable_current_battlecry(self):
        game = self.game((KILL, BEAST), (VICTIM,)); self.play(game, KILL, self.board(game, VICTIM))
        game.apply(EndTurn(1)); game.apply(EndTurn(2)); self.play(game, BEAST)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30)

    def test_second_player_beast_uses_own_current_deaths_and_attacks_own_enemy(self):
        game = self.game(enemy_hand=(KILL, BEAST), enemy_board=(VICTIM,))
        game.apply(EndTurn(1)); self.play(game, KILL, self.board(game, VICTIM, 2), player=2)
        self.play(game, BEAST, player=2)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].health, 23)
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].health, 30)

    def test_other_mechanics_identity_is_rejected_without_changing_saved_layout(self):
        game = self.game((CAVERN,)); saved = deepcopy(game.snapshot()); saved['mechanics_version'] = 'other-original-engine'
        with self.assertRaisesRegex(SnapshotError, 'Mechanics version mismatch'):
            Game.from_snapshot(saved, fixture())


if __name__ == '__main__': unittest.main()
