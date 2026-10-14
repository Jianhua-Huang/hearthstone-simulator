"""Independent contract checks for transactions, isolation and extension boundaries."""

from copy import deepcopy
from dataclasses import dataclass, replace
import json
import unittest

from hs_sim.engine import (
    Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Registry, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SnapshotError, TriggerSpec, UnsupportedDefinitionError, Zone,
)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import Damage, DamageBatch, Effect, GainArmor, RandomDamage
from hs_sim.engine.model import validate_invariants
from hs_sim.engine.resolver import default_mechanics, settle_health_batch
from hs_sim.engine.serialization import canonical_hash


@dataclass(frozen=True)
class Unregistered(Effect):
    pass


@dataclass(frozen=True)
class TwinArmor(Effect):
    player_id: int


@dataclass(frozen=True)
class FailingEffect(Effect):
    pass


@dataclass(frozen=True)
class Loop(Effect):
    pass


def registry_with(*cards, behaviors=None, target_rules=None):
    registry = Registry("safety-fixture-v1")
    for name, handler in (behaviors or {}).items():
        registry.register_behavior(name, handler)
    for name, handler in (target_rules or {}).items():
        registry.register_target_rule(name, handler)
    definitions = (
        CardDefinition("HERO", "Fixture hero", CardType.HERO, health=30),
        CardDefinition("BODY", "Fixture minion", CardType.MINION, attack=2, health=3),
        CardDefinition("IMMUNE", "Fixture immune", CardType.MINION, health=3,
                       keywords=(Keyword.IMMUNE,)),
        *cards,
    )
    for definition in definitions:
        registry.register_card(definition)
    return registry


def spell(behavior="effect", *, targeted=False, target_rule="any_character"):
    return CardDefinition("SPELL", "Fixture spell", CardType.SPELL, cost=2,
                          on_play=behavior, requires_target=targeted,
                          target_rule=target_rule)


def game_with(registry, *, hand=("SPELL",), mechanics=None, ruleset=None):
    return Game.from_scenario(
        Scenario((
            PlayerSetup("HERO", deck=("BODY",), hand=hand, board=("BODY",),
                        max_mana=10, mana=10),
            PlayerSetup("HERO", deck=("BODY",), board=("BODY", "IMMUNE")),
        ), seed=19), registry, mechanics=mechanics, ruleset=ruleset,
    )


def play_first(game):
    return PlayCard(1, game.state.players[1].hand[0])


def rehash(snapshot):
    """Separate invariant/schema checks from the accidental-corruption digest."""
    snapshot["state_hash"] = canonical_hash({key: snapshot[key] for key in (
        "ruleset", "registry_fingerprint", "mechanics_version", "state", "rng_state", "resolution_frame", "match_setup", "generation_context", "information",
    )})
    snapshot["events_hash"] = canonical_hash(snapshot["events"])
    return snapshot


class TransactionSafetyTests(unittest.TestCase):
    def assert_rolled_back(self, game, action, error):
        before = game.snapshot()
        history, origin = game.history, game.origin
        with self.assertRaises(error):
            game.apply(action)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.history, history)
        self.assertEqual(game.origin, origin)

    def test_illegal_actions_preserve_all_transaction_state(self):
        registry = registry_with(spell(), behaviors={"effect": lambda context: ()})
        game = game_with(registry, hand=("BODY", "SPELL"))
        state = game.state
        player = state.players[1]
        cases = (
            EndTurn(2),
            PlayCard(1, player.hand[0], position=99),
            PlayCard(1, player.hand[1], position=0),
            PlayCard(1, player.hand[1], target_id=player.hero_id),
            PlayCard(1, 999999),
            Attack(1, player.board[0], player.hero_id),
        )
        for action in cases:
            with self.subTest(action=action):
                self.assert_rolled_back(game, action, IllegalAction)

    def test_behavior_exception_after_card_commit_rolls_back(self):
        def fail(context):
            context.state.players[1].mana = 0
            raise RuntimeError("intentional plugin exception")
        registry = registry_with(spell(), behaviors={"effect": fail})
        game = game_with(registry, hand=("BODY", "SPELL"))
        game.apply(play_first(game))
        self.assertTrue(game.history)
        self.assertTrue(game.events)
        self.assert_rolled_back(game, play_first(game), ResolutionError)

    def test_random_consumption_damage_and_extension_exception_roll_back(self):
        observed = []
        def plan(context):
            candidates = tuple(context.state.players[2].board)
            return (RandomDamage(candidates, 1), FailingEffect())
        def fail(resolution, effect):
            observed.append((resolution.game._rng.getstate(),
                             deepcopy(resolution.state), len(resolution.game._events)))
            raise RuntimeError("failure after random choice")
        registry = registry_with(spell(), behaviors={"effect": plan})
        mechanics = default_mechanics("failure-fixture-v1")
        mechanics.register(FailingEffect, fail)
        game = game_with(registry, mechanics=mechanics)
        initial_rng = game._rng.getstate()
        self.assert_rolled_back(game, play_first(game), ResolutionError)
        self.assertEqual(len(observed), 1)
        self.assertNotEqual(observed[0][0], initial_rng)
        self.assertGreater(observed[0][2], 0)

    def test_unbounded_effect_chain_stops_and_rolls_back(self):
        seen = []
        def loop(resolution, effect):
            seen.append(1)
            resolution.emit("loop_advanced")
            return (Loop(),)
        registry = registry_with(spell(), behaviors={"effect": lambda context: (Loop(),)})
        mechanics = default_mechanics("loop-fixture-v1").register(Loop, loop)
        game = game_with(registry, mechanics=mechanics,
                         ruleset=Ruleset(max_resolution_steps=12))
        self.assert_rolled_back(game, play_first(game), ResolutionLimitExceeded)
        self.assertGreater(len(seen), 0)
        self.assertLessEqual(len(seen), 12)

    def test_infinite_yielding_behavior_hits_budget_and_rolls_back(self):
        produced = []
        def endless(context):
            while True:
                produced.append(1)
                yield GainArmor(context.player_id, 1)
        registry = registry_with(spell(), behaviors={"effect": endless})
        game = game_with(registry, ruleset=Ruleset(max_resolution_steps=12))
        self.assert_rolled_back(game, play_first(game), ResolutionLimitExceeded)
        self.assertGreater(len(produced), 0)
        self.assertLessEqual(len(produced), 13)

    def test_unknown_effect_and_non_effect_outputs_are_rejected(self):
        for output in ((Unregistered(),), (object(),), None):
            with self.subTest(output=output):
                registry = registry_with(spell(), behaviors={
                    "effect": lambda context, output=output: output,
                })
                game = game_with(registry)
                self.assert_rolled_back(game, play_first(game), ResolutionError)

    def test_custom_effect_handler_expands_to_existing_primitives(self):
        registry = registry_with(spell(), behaviors={
            "effect": lambda context: (TwinArmor(context.player_id),),
        })
        mechanics = default_mechanics("twin-armor-v1").register(
            TwinArmor, lambda resolution, effect: (
                GainArmor(effect.player_id, 2), GainArmor(effect.player_id, 3),
            ),
        )
        game = game_with(registry, mechanics=mechanics)
        result = game.apply(play_first(game))
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual(hero.armor, 5)
        self.assertEqual([e.amount for e in result.events if e.kind == "armor_gained"], [2, 3])
        restored = Game.from_snapshot(game.snapshot(), registry, mechanics)
        self.assertEqual(restored.state_hash(), game.state_hash())

    def test_replacing_damage_batch_changes_spell_damage_and_combat(self):
        intercepted = []
        def prevent_batch(resolution, effect):
            intercepted.append(effect.hits)
            resolution.emit("custom_damage_prevented", amount=len(effect.hits))
            # Replacing the damage strategy still owns original combat acceptance
            # and finish. Use shared settlement, not another registered handler.
            from hs_sim.engine.equipment import validate_exchange
            from hs_sim.engine.cleave import validate_combat_hits
            from hs_sim.engine.hero_attack_history import accept as accept_hero
            from hs_sim.engine.character_attacks import accept as accept_character
            validate_exchange(resolution, effect.combat)
            validate_combat_hits(resolution.state, effect)
            accept_hero(resolution, effect.combat)
            accept_character(resolution, effect.combat)
            return settle_health_batch(resolution,
                tuple(replace(hit, amount=0) for hit in effect.hits), effect.combat)
        registry = registry_with(spell(), behaviors={
            "effect": lambda context: (Damage(context.state.players[2].board[0], 1),),
        })
        mechanics = default_mechanics("custom-v2").replace(DamageBatch, prevent_batch)
        game = game_with(registry, mechanics=mechanics)
        state = game.state
        attacker, defender = state.players[1].board[0], state.players[2].board[0]
        game.apply(play_first(game))
        game.apply(Attack(1, attacker, defender))
        self.assertEqual([len(hits) for hits in intercepted], [1, 2])
        self.assertEqual(intercepted[0][0].target_id, defender)
        self.assertEqual({hit.target_id for hit in intercepted[1]}, {attacker, defender})
        self.assertEqual(game.state.entities[attacker].damage, 0)
        self.assertEqual(game.state.entities[defender].damage, 0)
        self.assertEqual(game.state.entities[attacker].attacks_this_turn, 1)
        self.assertEqual(sum(event.kind == "custom_damage_prevented" for event in game.events), 2)
        self.assertEqual(sum(event.kind == "attack_finished" for event in game.events), 1)
        row = game.state.character_attack_history[-1]
        self.assertIsNotNone(row.combat)
        self.assertEqual(row.terminal.status, "completed")
        saved = game.snapshot()
        self.assertEqual(Game.from_snapshot(saved, registry, mechanics).snapshot(), saved)
        self.assertEqual(game.clone().snapshot(), saved)
        with self.assertRaises(ValueError):
            default_mechanics().replace(DamageBatch, prevent_batch)
        with self.assertRaises(ValueError):
            mechanics.replace(DamageBatch, prevent_batch)

    def test_behavior_context_mutation_does_not_change_live_state(self):
        def mutate_detached_context(context):
            context.state.players[1].mana = 0
            context.state.entities[context.state.players[2].hero_id].damage = 99
            context.state.players[2].board.clear()
            return (GainArmor(1, 1),)
        registry = registry_with(spell(), behaviors={"effect": mutate_detached_context})
        game = game_with(registry)
        game.apply(play_first(game))
        state = game.state
        self.assertEqual(state.players[1].mana, 8)
        self.assertEqual(state.entities[state.players[2].hero_id].damage, 0)
        self.assertEqual(len(state.players[2].board), 2)

    def test_mid_resolution_public_operations_are_rejected_and_rolled_back(self):
        operations = (
            ("snapshot", lambda game: game.snapshot()),
            ("clone", lambda game: game.clone()),
            ("validate", lambda game: game.validate(EndTurn(1))),
            ("legal_actions", lambda game: game.legal_actions()),
            ("apply", lambda game: game.apply(EndTurn(1))),
        )
        for name, operation in operations:
            with self.subTest(operation=name):
                registry = registry_with(spell(), behaviors={
                    "effect": lambda context: (TwinArmor(context.player_id),),
                })
                def during_resolution(resolution, effect, operation=operation):
                    operation(resolution.game)
                    return (GainArmor(1, 5),)
                mechanics = default_mechanics("boundary-fixture-v1").register(TwinArmor, during_resolution)
                game = game_with(registry, mechanics=mechanics)
                self.assert_rolled_back(game, play_first(game), ResolutionError)
                self.assertEqual(game.clone().snapshot(), game.snapshot())
                self.assertIn(EndTurn(1), game.legal_actions())
                game.apply(EndTurn(1))
                self.assertEqual(game.state.active_player, 2)

    def test_emitted_event_payload_and_each_behavior_context_are_detached(self):
        observed = []
        def inspect_and_mutate_event(context):
            detail = dict(context.event.data)["detail"]
            observed.append(detail["nested"]["value"])
            detail["nested"]["value"] = 100
            return ()
        watcher = CardDefinition("WATCHER", "Fixture watcher", CardType.MINION, health=3,
                                 triggers=(TriggerSpec("extension_event", "inspect_event"),))
        registry = registry_with(spell(), watcher, behaviors={
            "effect": lambda context: (TwinArmor(context.player_id),),
            "inspect_event": inspect_and_mutate_event,
        })
        def emit_nested(resolution, effect):
            detail = {"nested": {"value": 1}}
            event = resolution.emit("extension_event", detail=detail)
            detail["nested"]["value"] = 999
            source_id = resolution.state.players[1].graveyard[-1]
            return (resolution.call("inspect_event", source_id, 1, event=event),)
        mechanics = default_mechanics("event-context-v1").register(TwinArmor, emit_nested)
        game = Game.from_scenario(Scenario((
            PlayerSetup("HERO", hand=("SPELL",), board=("WATCHER", "WATCHER"),
                        max_mana=10, mana=10),
            PlayerSetup("HERO"),
        )), registry, mechanics=mechanics)
        game.apply(play_first(game))
        self.assertEqual(observed, [1, 1, 1])
        event = next(event for event in game.events if event.kind == "extension_event")
        self.assertEqual(dict(event.data)["detail"]["nested"]["value"], 1)


class IsolationAndSchemaTests(unittest.TestCase):
    def fixture(self):
        registry = registry_with(spell(), behaviors={"effect": lambda context: (GainArmor(1, 1),)})
        return registry, game_with(registry)

    def test_state_snapshot_history_and_origin_outputs_are_detached(self):
        _, game = self.fixture()
        game.apply(play_first(game))
        before = game.snapshot()
        state = game.state
        state.players[1].board.clear()
        state.entities[state.players[1].hero_id].damage = 999
        snapshot = game.snapshot()
        snapshot["state"]["players"]["1"]["board"].clear()
        history = game.history
        history[0]["action"]["player_id"] = 2
        origin = game.origin
        origin["state"]["players"]["1"]["hand"].clear()
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.history[0]["action"]["player_id"], 1)
        self.assertTrue(game.origin["state"]["players"]["1"]["hand"])

    def test_restored_state_does_not_alias_input_snapshot_zone_lists(self):
        registry, game = self.fixture()
        snapshot = game.snapshot()
        restored = Game.from_snapshot(snapshot, registry)
        before = restored.snapshot()
        snapshot["state"]["players"]["1"]["board"].clear()
        snapshot["state"]["players"]["1"]["hand"].clear()
        snapshot["state"]["players"]["1"]["deck"].clear()
        snapshot["state"]["players"]["1"]["graveyard"].append(999999)
        self.assertEqual(restored.snapshot(), before)

    def test_restored_nested_event_payload_does_not_alias_input_snapshot(self):
        registry = registry_with(spell(), behaviors={
            "effect": lambda context: (TwinArmor(context.player_id),),
        })
        def emit_nested(resolution, effect):
            resolution.emit("extension_event", detail={"values": [1, {"count": 2}]})
        mechanics = default_mechanics("nested-event-v1").register(TwinArmor, emit_nested)
        game = game_with(registry, mechanics=mechanics)
        game.apply(play_first(game))
        snapshot = game.snapshot()
        restored = Game.from_snapshot(snapshot, registry, mechanics)
        before = restored.snapshot()
        event = next(event for event in snapshot["events"] if event["kind"] == "extension_event")
        event["data"]["detail"]["values"][1]["count"] = 99
        self.assertEqual(restored.snapshot(), before)

    def test_clone_forks_state_rng_events_and_history(self):
        registry = registry_with(spell(), behaviors={
            "effect": lambda context: (RandomDamage(tuple(context.state.players[2].board), 1),),
        })
        game = game_with(registry)
        clone = game.clone()
        original = game.snapshot()
        clone.apply(play_first(clone))
        self.assertEqual(game.snapshot(), original)
        self.assertEqual(game.history, [])
        game.apply(play_first(game))
        self.assertEqual(game.snapshot(), clone.snapshot())
        clone.apply(EndTurn(1))
        self.assertNotEqual(game.state_hash(), clone.state_hash())

    def test_snapshot_json_round_trip_preserves_state_and_event_hashes(self):
        registry, game = self.fixture()
        game.apply(play_first(game))
        encoded = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(encoded, registry)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(restored.history, [])
        self.assertEqual(restored.origin, restored.snapshot())

    def test_snapshot_invariants_reject_consistently_rehashed_corruption(self):
        registry, game = self.fixture()
        def duplicate_zone(snapshot):
            player = snapshot["state"]["players"]["1"]
            player["hand"].append(player["board"][0])
        def wrong_controller(snapshot):
            entity_id = snapshot["state"]["players"]["1"]["board"][0]
            snapshot["state"]["entities"][str(entity_id)]["controller"] = 2
        def dead_board(snapshot):
            entity_id = snapshot["state"]["players"]["1"]["board"][0]
            snapshot["state"]["entities"][str(entity_id)]["damage"] = 100
        def boolean_id(snapshot):
            snapshot["state"]["active_player"] = True
        def reused_id(snapshot):
            snapshot["state"]["next_entity_id"] = 1
        for mutation in (duplicate_zone, wrong_controller, dead_board, boolean_id, reused_id):
            with self.subTest(mutation=mutation.__name__):
                snapshot = game.snapshot()
                mutation(snapshot)
                with self.assertRaises(SnapshotError):
                    Game.from_snapshot(rehash(snapshot), registry)

    def test_finished_game_requires_a_winner(self):
        registry, game = self.fixture()
        state = game.state
        state.status = "finished"
        state.winner = None
        with self.assertRaises(ValueError):
            validate_invariants(state, registry)

    def test_action_schema_rejects_boolean_ids_unknown_and_missing_fields(self):
        bad = (
            {"type": "end_turn", "player_id": True},
            {"type": "play_card", "player_id": 1, "entity_id": 1, "position": False},
            {"type": "attack", "player_id": 1, "attacker_id": 2},
            {"type": "end_turn", "player_id": 1, "target_id": 2},
            {"type": "unknown", "player_id": 1},
            ["end_turn", 1],
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                action_from_dict(value)
        for action in (EndTurn(1), PlayCard(1, 2, 3, 0), Attack(1, 2, 3)):
            self.assertEqual(action_from_dict(action_to_dict(action)), action)

    def test_scenario_schema_rejects_malformed_values(self):
        scenario = Scenario((PlayerSetup("HERO"), PlayerSetup("HERO")))
        encoded = json.loads(json.dumps(scenario.to_dict()))
        self.assertEqual(Scenario.from_dict(encoded), scenario)
        bad_inputs = (
            {**encoded, "unexpected": 1},
            {**encoded, "seed": True},
            {**encoded, "active_player": False},
            {"players": [{"hero_card_id": "HERO", "mana": -1}, {"hero_card_id": "HERO"}]},
            {"players": [{"hero_card_id": "HERO", "hand": "BODY"}, {"hero_card_id": "HERO"}]},
        )
        for value in bad_inputs:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                Scenario.from_dict(value)

    def test_ruleset_subclasses_cannot_lose_their_policy_on_snapshot_restore(self):
        class ReverseOrder(Ruleset):
            def entity_order(self, state, entity_ids):
                return list(reversed(super().entity_order(state, entity_ids)))
        registry = registry_with(spell(), behaviors={"effect": lambda context: ()})
        with self.assertRaises(ValueError):
            game_with(registry, ruleset=ReverseOrder())


class RegistryAndTargetTests(unittest.TestCase):
    def test_missing_behavior_and_target_rule_fail_before_game_creation(self):
        for definition in (
            spell("missing"),
            replace(spell(None, targeted=True), target_rule="missing"),
        ):
            with self.subTest(definition=definition):
                registry = registry_with(definition)
                with self.assertRaises(UnsupportedDefinitionError):
                    game_with(registry)

    def test_registry_and_mechanics_freeze_after_game_creation(self):
        registry = registry_with(spell(), behaviors={"effect": lambda context: ()})
        mechanics = default_mechanics()
        game_with(registry, mechanics=mechanics)
        with self.assertRaises(ValueError):
            registry.register_behavior("late", lambda context: ())
        with self.assertRaises(ValueError):
            mechanics.register(Unregistered, lambda resolution, effect: ())
        with self.assertRaises(TypeError):
            registry.cards["NEW"] = spell()

    def test_target_rule_controls_legal_actions_without_mutating_state(self):
        def enemy_minion(context):
            target = context.state.entities[context.target_id]
            accepted = target.zone == Zone.BOARD and target.controller != context.player_id
            context.state.players[1].hand.clear()
            target.damage = 999
            return accepted
        registry = registry_with(spell(targeted=True, target_rule="enemy_minion"),
                                 behaviors={"effect": lambda context: (Damage(context.target_id, 1),)},
                                 target_rules={"enemy_minion": enemy_minion})
        game = game_with(registry)
        before = game.snapshot()
        actions = game.legal_actions()
        plays = [action for action in actions if isinstance(action, PlayCard)]
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0].target_id, game.state.players[2].board[0])
        for action in actions:
            game.validate(action)
        self.assertEqual(game.snapshot(), before)
        game.apply(plays[0])
        self.assertEqual(game.state.entities[plays[0].target_id].damage, 1)

    def test_target_rule_requires_a_boolean_result(self):
        registry = registry_with(spell(targeted=True, target_rule="broken"),
                                 behaviors={"effect": lambda context: ()},
                                 target_rules={"broken": lambda context: "yes"})
        game = game_with(registry)
        action = PlayCard(1, game.state.players[1].hand[0], game.state.players[2].hero_id)
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            game.validate(action)
        self.assertEqual(game.snapshot(), before)

    def test_target_rule_runtime_error_is_wrapped_without_side_effects(self):
        def fail(context):
            context.state.players[1].mana = 0
            context.state.entities[context.target_id].damage = 999
            raise RuntimeError("broken target rule")
        registry = registry_with(spell(targeted=True, target_rule="raises"),
                                 behaviors={"effect": lambda context: ()},
                                 target_rules={"raises": fail})
        game = game_with(registry)
        action = PlayCard(1, game.state.players[1].hand[0], game.state.players[2].hero_id)
        before, history = game.snapshot(), game.history
        rng = game._rng.getstate()
        for operation in (game.validate, game.apply):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ResolutionError) as caught:
                    operation(action)
                self.assertIsInstance(caught.exception.__cause__, RuntimeError)
                self.assertEqual(game.snapshot(), before)
                self.assertEqual(game._rng.getstate(), rng)
                self.assertEqual(game.history, history)


class CapturedEventPlayerBoundaryTests(unittest.TestCase):
    def test_nullable_event_player_round_trips_without_inventing_an_actor(self):
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.model import Event
        codec = FrameCodec(default_mechanics(), registry_with())
        for player in (None, 1, 2):
            with self.subTest(player=player):
                event = Event(1, 1, 'attack_finished', source_id=1, target_id=2, player_id=player)
                self.assertEqual(codec.decode(codec.encode(event)), event)

    def test_nullable_event_does_not_relax_invalid_players_or_required_commands(self):
        from hs_sim.engine.continuations import FrameCodec
        from hs_sim.engine.resolver import EndTurnPhase
        from hs_sim.engine.model import Event
        codec = FrameCodec(default_mechanics(), registry_with())
        for player in (True, False, 0, 3, '1'):
            with self.subTest(event_player=player):
                encoded = codec.encode(Event(1, 1, 'attack_finished', player_id=1))
                encoded['event']['player_id'] = player
                with self.assertRaises(ValueError): codec.decode(encoded)
        for player in (None, True, False, 0, 3, '1'):
            with self.subTest(command_player=player):
                encoded = codec.encode(EndTurnPhase(1))
                encoded['fields']['player_id'] = player
                with self.assertRaises(ValueError): codec.decode(encoded)

if __name__ == "__main__":
    unittest.main()


