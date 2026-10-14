"""Attachment and death-history schemas, independent of effect resolution."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from hs_sim.engine.model import (
    AbilityInstance, CardDefinition, CardType, DeathCause, DeathRecord, Enchantment, Entity,
    GameState, Keyword, OwnerTurnRecord, PlayerState, Zone, validate_invariants,
)
from hs_sim.engine.registry import Registry
from hs_sim.engine.serialization import state_from_dict, state_to_dict


def make_registry():
    registry = Registry("attachment-schema-fixture-v1")
    registry.register_behavior("noop", lambda context: ())
    registry.register_card(CardDefinition("hero", "英雄", CardType.HERO, health=30))
    registry.register_card(CardDefinition("minion", "随从", CardType.MINION, attack=2, health=3))
    registry.register_card(CardDefinition("other", "变形随从", CardType.MINION, attack=1, health=1))
    registry.freeze()
    return registry


def make_state():
    return GameState(
        players={1: PlayerState(1, 1, board=[3]), 2: PlayerState(2, 2)},
        entities={
            1: Entity(1, "hero", 1, 1, Zone.HERO, base_health=30, kind=CardType.HERO),
            2: Entity(2, "hero", 2, 2, Zone.HERO, base_health=30, kind=CardType.HERO),
            3: Entity(
                3, "minion", 1, 1, Zone.BOARD, base_attack=2, base_health=3,
                entered_order=1, board_presence_id=1, attack_bonus=2, health_bonus=1,
                keywords={Keyword.REBORN},
                enchantments=[Enchantment(1, source_id=1, attack=2, health=1,
                                          expires_turn=5, label="测试增益")],
                abilities=[
                    AbilityInstance(2, "keyword", source_id=3, origin="printed", keyword=Keyword.REBORN),
                    AbilityInstance(3, "deathrattle", source_id=1, behavior_id="noop", deathrattle_grant_card_id="hero"),
                ],
            ),
        },
        turn=4, next_entity_id=4, next_order=2, next_attachment_id=4,
        # Schema-only synthetic ledger; no Game event provenance is claimed.
        owner_turn_history=[
            OwnerTurnRecord(1, 2, 1, 1, None, 0, 0, "scenario",
                closed_action=0, closed_event=1, end_event=1, end_action=0),
            OwnerTurnRecord(2, 1, 1, 2, None, 0, 1, "actual",
                closed_action=0, closed_event=3, publication_event=2,
                publication_action=0, end_event=3, end_action=0),
            OwnerTurnRecord(3, 2, 2, 3, 1, 0, 3, "actual",
                closed_action=0, closed_event=5, publication_event=4,
                publication_action=0, end_event=5, end_action=0),
            OwnerTurnRecord(4, 1, 2, 4, 2, 0, 5, "actual",
                publication_event=6, publication_action=0),
        ],
    )


def record_for(state, **changes):
    entity = state.entities[3]
    record = DeathRecord(
        id=1, batch=1, entity_id=entity.id, card_id=entity.card_id,
        owner=entity.owner, controller=entity.controller, position=0,
        turn=3, attack=entity.attack, max_health=entity.max_health, damage=4,
        base_attack=entity.base_attack, base_health=entity.base_health,
        base_cost=entity.base_cost, keywords=tuple(sorted(entity.keywords)),
        cause=DeathCause('health_state','fixture',entity.id,entity.card_id,entity.controller,
                         entity.zone_epoch,entity.entered_order,3,1),
        abilities=tuple(entity.abilities), enchantments=tuple(entity.enchantments),
    )
    return replace(record, **changes)


def with_history():
    state = make_state()
    state.death_history = [record_for(state)]
    state.next_death_id = state.next_death_batch = 2
    return state


class AttachmentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.registry = make_registry()

    def test_json_round_trip_restores_nested_immutable_types(self):
        state = with_history()
        validate_invariants(state, self.registry)
        payload = state_to_dict(state)
        self.assertEqual(json.loads(json.dumps(payload)), payload)

        def assert_primitives(value):
            self.assertIn(type(value), (dict, list, str, int, bool, type(None)))
            if type(value) is dict:
                self.assertTrue(all(type(key) is str for key in value))
                for item in value.values():
                    assert_primitives(item)
            elif type(value) is list:
                for item in value:
                    assert_primitives(item)

        assert_primitives(payload)
        restored = state_from_dict(payload)
        self.assertEqual(restored, state)
        self.assertIsInstance(restored.entities[3].abilities[0].keyword, Keyword)
        self.assertIsInstance(restored.death_history[0], DeathRecord)
        self.assertIsInstance(restored.death_history[0].abilities, tuple)
        self.assertIsInstance(restored.death_history[0].enchantments[0], Enchantment)
        self.assertIsInstance(restored.death_history[0].keywords[0], Keyword)
        validate_invariants(restored, self.registry)

    def test_import_and_export_share_no_mutable_state(self):
        original = with_history()
        payload = state_to_dict(original)
        restored = state_from_dict(payload)
        payload["entities"]["3"]["abilities"][0]["consumed"] = True
        payload["players"]["1"]["board"].clear()
        payload["death_history"][0]["enchantments"][0]["attack"] = 100
        self.assertEqual(restored, original)
        restored.entities[3].abilities.clear()
        restored.entities[3].enchantments.clear()
        restored.players[1].board.clear()
        restored.death_history.clear()
        self.assertEqual(len(original.entities[3].abilities), 2)
        self.assertEqual(len(original.death_history), 1)

    def test_frozen_records_cannot_be_mutated(self):
        state = with_history()
        for item, field in ((state.entities[3].abilities[0], "consumed"),
                            (state.entities[3].enchantments[0], "attack"),
                            (state.death_history[0], "attack")):
            with self.subTest(type=type(item).__name__), self.assertRaises(FrozenInstanceError):
                setattr(item, field, 99)
        ability = state.entities[3].abilities[0]
        consumed = replace(ability, consumed=True)
        self.assertFalse(ability.consumed)
        self.assertTrue(consumed.consumed)
        self.assertEqual(consumed.id, ability.id)

    def test_all_ability_variants_are_explicitly_typed(self):
        variants = (
            AbilityInstance(1, "keyword", keyword=Keyword.REBORN),
            AbilityInstance(2, "trigger", behavior_id="noop", event="minion_died"),
            AbilityInstance(3, "deathrattle", behavior_id="noop"),
            AbilityInstance(4, "on_play", behavior_id="noop"),
            AbilityInstance(5, "aura", attack=-1, include_self=True),
        )
        state = make_state()
        state.entities[3].enchantments.clear()
        state.entities[3].abilities = list(variants)
        state.next_attachment_id = 6
        validate_invariants(state, self.registry)
        self.assertEqual(state_from_dict(state_to_dict(state)), state)

    def test_invalid_or_ambiguous_ability_fields_are_rejected(self):
        invalid = (
            {"kind": "unknown"}, {"kind": []},
            {"kind": "keyword"}, {"kind": "keyword", "keyword": "reborn"},
            {"kind": "keyword", "keyword": Keyword.REBORN, "event": "hit"},
            {"kind": "keyword", "keyword": Keyword.REBORN, "behavior_id": "noop"},
            {"kind": "keyword", "keyword": Keyword.REBORN, "attack": 1},
            {"kind": "trigger", "behavior_id": "noop"},
            {"kind": "trigger", "event": "hit"},
            {"kind": "deathrattle", "behavior_id": "noop", "event": "hit"},
            {"kind": "on_play", "behavior_id": "noop", "include_self": True},
            {"kind": "aura", "keyword": Keyword.REBORN},
            {"kind": "aura", "behavior_id": "noop"},
            {"kind": "aura", "origin": "copied"},
            {"kind": "aura", "consumed": 1},
            {"kind": "aura", "attack": True},
            {"kind": "aura", "expires_turn": 0},
        )
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                AbilityInstance(1, **row)

    def test_enchantment_numeric_and_boolean_fields_are_strict(self):
        invalid = ({"id": True}, {"source_id": 0}, {"attack": 1.5},
                   {"health": True}, {"cost": "-1"}, {"expires_turn": False},
                   {"remove_on_silence": 1}, {"label": ""})
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(ValueError):
                Enchantment(**{"id": 1, **row})
        self.assertEqual(Enchantment(1, attack=-2, health=-1, cost=-3).cost, -3)

    def test_unknown_and_missing_json_fields_are_rejected_at_every_level(self):
        original = state_to_dict(with_history())
        paths = ((), ("players", "1"), ("entities", "3"),
                 ("entities", "3", "abilities", 0),
                 ("entities", "3", "enchantments", 0),
                 ("death_history", 0))
        for path in paths:
            for operation in ("unknown", "missing"):
                payload = deepcopy(original)
                row = payload
                for key in path:
                    row = row[key]
                if operation == "unknown":
                    row["unexpected"] = None
                else:
                    del row[next(iter(row))]
                with self.subTest(path=path, operation=operation), self.assertRaises(ValueError):
                    state_from_dict(payload)

    def test_malformed_nested_json_is_rejected(self):
        cases = (
            (("entities", "3", "abilities"), {}),
            (("entities", "3", "enchantments"), None),
            (("entities", "3", "keywords"), ["reborn", "reborn"]),
            (("entities", "3", "keywords"), [{}]),
            (("entities", "3", "silenced"), 1),
            (("entities", "3", "origin_entity_id"), False),
            (("entities", "3", "abilities", 0, "keyword"), "unknown"),
            (("entities", "3", "enchantments", 0, "health"), True),
            (("death_history", 0, "abilities"), ()),
            (("death_history", 0, "keywords"), ["unknown"]),
            (("death_history", 0, "position"), -1),
            (("players", "1", "board"), [True]),
            (("next_death_id",), True),
        )
        for path, value in cases:
            payload = state_to_dict(with_history())
            row = payload
            for key in path[:-1]:
                row = row[key]
            row[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                state_from_dict(payload)

    def test_entity_and_player_keys_must_be_canonical_positive_ids(self):
        for collection in ("players", "entities"):
            for key in ("01", "+1", " 1", "-1", "0", 1, "x"):
                payload = state_to_dict(make_state())
                payload[collection][key] = payload[collection].pop("1")
                with self.subTest(collection=collection, key=key), self.assertRaises(ValueError):
                    state_from_dict(payload)

    def test_current_attachment_ids_are_unique_across_entities_and_kinds(self):
        for duplicate in (Enchantment(2), Enchantment(1)):
            state = make_state()
            state.entities[1].enchantments.append(duplicate)
            with self.subTest(id=duplicate.id), self.assertRaisesRegex(ValueError, "globally unique"):
                validate_invariants(state, self.registry)

    def test_attachment_counter_includes_history_even_after_removal(self):
        state = with_history()
        state.entities[3].abilities.clear()
        state.entities[3].enchantments.clear()
        state.next_attachment_id = 3
        with self.assertRaisesRegex(ValueError, "historical"):
            validate_invariants(state, self.registry)
        state.next_attachment_id = 4
        validate_invariants(state, self.registry)

    def test_missing_source_origin_and_behavior_references_are_rejected(self):
        cases = (
            lambda state: state.entities[3].enchantments.__setitem__(0, Enchantment(1, source_id=99)),
            lambda state: setattr(state.entities[3], "origin_entity_id", 99),
            lambda state: state.entities[3].abilities.__setitem__(1, AbilityInstance(3, "deathrattle", behavior_id="absent")),
            lambda state: state.death_history.__setitem__(0, replace(state.death_history[0], abilities=(AbilityInstance(4, "deathrattle", behavior_id="absent"),))),
        )
        for mutate in cases:
            state = with_history()
            mutate(state)
            with self.assertRaises(ValueError):
                validate_invariants(state, self.registry)

    def test_death_record_preserves_original_identity_after_transform(self):
        state = with_history()
        state.entities[3].card_id = "other"
        state.entities[3].controller = 2
        state.players[1].board.remove(3)
        state.players[2].board.append(3)
        validate_invariants(state, self.registry)
        self.assertEqual(state.death_history[0].card_id, "minion")
        self.assertEqual(state.death_history[0].controller, 1)

    def test_death_history_references_and_sequence_are_validated(self):
        cases = (
            {"entity_id": 99}, {"entity_id": 1}, {"card_id": "absent"}, {"card_id": "hero"},
            {"turn": 5}, {"id": 2}, {"batch": 2},
        )
        for changes in cases:
            state = with_history()
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                state.death_history[0] = replace(state.death_history[0], **changes)
                validate_invariants(state, self.registry)
        state = with_history()
        state.death_history.append(replace(state.death_history[0], id=2))
        state.next_death_id = 3
        with self.assertRaisesRegex(ValueError, "twice"):
            validate_invariants(state, self.registry)

    def test_same_entity_may_have_multiple_historical_deaths(self):
        state = with_history()
        state.death_history.append(replace(state.death_history[0], id=2, batch=2, turn=4))
        state.next_death_id = state.next_death_batch = 3
        validate_invariants(state, self.registry)
        self.assertEqual(state_from_dict(state_to_dict(state)), state)

    def test_death_record_nested_values_must_be_immutable_and_unambiguous(self):
        original = record_for(make_state())
        cases = ({"abilities": []}, {"keywords": [Keyword.REBORN]},
                 {"enchantments": [Enchantment(1)]},
                 {"keywords": (Keyword.REBORN, Keyword.REBORN)},
                 {"enchantments": (Enchantment(2),)}, {"owner": True})
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(original, **changes)


if __name__ == "__main__":
    unittest.main()
