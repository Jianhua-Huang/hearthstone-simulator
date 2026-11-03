"""Private choice encoding reuse never escapes into mutable runtime or exports."""
from dataclasses import dataclass
import unittest
from unittest.mock import patch

from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
                           Registry, ResolutionError, Scenario, SelectChoice)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption, Effect, GainArmor, RequestChoice
from hs_sim.engine.resolver import default_mechanics
import test_assemble_offers as assembly
from test_performance_frame_metadata import game as simple_game


@dataclass(frozen=True)
class ExternalAsk(Effect):
    player_id: int


@dataclass(frozen=True)
class ExternalPayload:
    number: int


def states(value):
    found = []
    if type(value) is dict:
        if set(value) == {'state'}: found.append(value['state'])
        else:
            for child in value.values(): found.extend(states(child))
    elif type(value) is list:
        for child in value: found.extend(states(child))
    return found


class ChoiceEncodingPerformanceTests(unittest.TestCase):
    def test_readonly_encoding_reuses_frozen_history_but_public_branches_detach(self):
        from hs_sim.engine import EndTurn
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.serialization import _state_to_dict_legacy
        from test_performance_end_turn_proofs import ending
        g = ending(); g.apply(EndTurn(1))
        resolver = Resolution(g)
        first, second = resolver.capture_state(), resolver.capture_state()
        self.assertTrue(first.end_turn_batches)
        self.assertIs(first.end_turn_batches[0], second.end_turn_batches[0])
        codec = FrameCodec(g.mechanics, g.registry)
        wire = codec.encode_runtime((first, second), readonly=True)
        rows = [row['state'] for row in wire['tuple']]
        self.assertEqual(rows, [_state_to_dict_legacy(first), _state_to_dict_legacy(second)])
        # Special event fields have their own row; generic cached records must
        # remain the ordinary dataclass wire when reached through another field.
        first.armor_gain_history.append(first.end_turn_batches[0])
        self.assertEqual(codec.encode_runtime(first, readonly=True)['state'], _state_to_dict_legacy(first))
        public = codec.encode_runtime((first, second))
        left, right = [row['state'] for row in public['tuple']]
        left['end_turn_batches'][0]['subjects'].clear()
        self.assertEqual(right, _state_to_dict_legacy(second))

    def test_readonly_encoding_does_not_retain_frozen_records_until_gc(self):
        import gc, weakref
        from hs_sim.engine.effects import GainArmor
        g = simple_game(); codec = FrameCodec(g.mechanics, g.registry)
        enabled = gc.isenabled(); gc.disable()
        try:
            record = GainArmor(1, 3); reference = weakref.ref(record)
            g._state.armor_gain_history.append(record)
            wire = codec.encode_runtime((g._state,), readonly=True)
            g._state.armor_gain_history.clear(); del record
            self.assertIsNone(reference())
            self.assertEqual(wire['tuple'][0]['state']['armor_gain_history'], [{'player_id': 1, 'amount': 3}])
        finally:
            if enabled: gc.enable()

    def game(self):
        return assembly.AssembleOfferTests().game(hand=('repeat',))

    def test_private_aliases_export_independent_snapshot_branches(self):
        g = self.game(); g.apply(PlayCard(1, g._state.players[1].hand[0]))
        cached = states(g._encoded_frame())
        pair = next((a, b) for a in range(len(cached)) for b in range(a+1, len(cached))
                    if cached[a] is cached[b])
        snapshot = g.snapshot(); clone = g.clone(); exported = states(snapshot['resolution_frame'])
        left, right = (exported[index] for index in pair)
        self.assertIsNot(left, right)
        original = right['players']['1']['mana']
        left['players']['1']['mana'] = -999
        self.assertEqual(right['players']['1']['mana'], original)
        self.assertEqual(g.snapshot(), clone.snapshot())
        self.assertEqual(g.snapshot()['resolution_frame'], FrameCodec(g.mechanics, g.registry).encode(g._frame))

    def test_native_memo_is_reused_only_inside_one_choice_preparation(self):
        g = self.game(); calls = []; original = FrameCodec.encode_runtime
        def encode(codec, value, **kwargs):
            memo = kwargs.get('_state_memo')
            calls.append((memo, None if memo is None else len(memo)))
            return original(codec, value, **kwargs)
        with patch.object(FrameCodec, 'encode_runtime', encode):
            g.apply(PlayCard(1, g._state.players[1].hand[0]))
            first = calls[-2:]; calls.clear()
            choice = g._state.pending_choice
            g.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
            second = calls[-2:]
        self.assertIsNotNone(first[0][0]); self.assertIs(first[0][0], first[1][0])
        self.assertEqual(first[0][1], 0); self.assertGreater(first[1][1], 0)
        self.assertIsNot(first[0][0], second[0][0])
        self.assertEqual(second[0][1], 0)
        self.assertEqual(g.snapshot()['resolution_frame'], FrameCodec(g.mechanics, g.registry).encode(g._frame))

    def test_default_runtime_export_keeps_independent_branches(self):
        g = simple_game(); codec = FrameCodec(g.mechanics, g.registry)
        wire = codec.encode_runtime((g._state, g._state))
        first, second = (row['state'] for row in wire['tuple'])
        self.assertIsNot(first, second)
        first['players']['1']['hand'].clear()
        self.assertTrue(second['players']['1']['hand'])
        self.assertTrue(g._state.players[1].hand)

    def test_foreign_payload_invalidates_captured_state_memo(self):
        g = simple_game(); mechanics = default_mechanics()
        mechanics.register_payload_type(ExternalPayload)
        codec = FrameCodec(mechanics, g.registry); original = codec.encode
        old = g._state.players[1].mana
        def encode(value, depth=0):
            if type(value) is ExternalPayload: g._state.players[1].mana = old-1
            return original(value, depth)
        with patch.object(codec, 'encode', side_effect=encode):
            wire = codec.encode_runtime((g._state, ExternalPayload(1), g._state), readonly=True, _state_memo={})
        self.assertEqual(wire['tuple'][0]['state']['players']['1']['mana'], old)
        self.assertEqual(wire['tuple'][2]['state']['players']['1']['mana'], old-1)

    def test_external_handler_does_not_reuse_native_suspension_memo(self):
        registry = Registry('external-choice-encoding')
        registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        registry.register_behavior('ask', lambda c: (ExternalAsk(c.player_id),))
        registry.register_card(CardDefinition('ask', 'Ask', CardType.SPELL, on_play='ask'))
        def ask(resolver, effect):
            from hs_sim.engine.choices import request_choice
            return request_choice(resolver, RequestChoice(effect.player_id,
                (ChoiceOption('ok', 'OK', (GainArmor(effect.player_id, 1),)),)))
        mechanics = default_mechanics(); mechanics.register(ExternalAsk, ask)
        g = Game.from_scenario(Scenario((PlayerSetup('hero', hand=('ask',)), PlayerSetup('hero')), seed=1),
                               registry, mechanics=mechanics)
        calls = []; original = FrameCodec.encode_runtime
        def encode(codec, value, **kwargs):
            calls.append(kwargs.get('_state_memo'))
            return original(codec, value, **kwargs)
        with patch.object(FrameCodec, 'encode_runtime', encode):
            g.apply(PlayCard(1, g._state.players[1].hand[0]))
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(value is None for value in calls))
        restored = Game.from_snapshot(g.snapshot(), registry, mechanics=mechanics)
        self.assertEqual(restored.snapshot(), g.snapshot())

    def test_failed_frame_encoding_rolls_back_and_next_attempt_is_clean(self):
        g = self.game(); before = g.snapshot(); control = g.clone()
        command = PlayCard(1, g._state.players[1].hand[0]); original = FrameCodec.encode_runtime
        def encode(codec, value, **kwargs):
            from hs_sim.engine.resolver import ResolutionFrame
            if type(value) is ResolutionFrame: raise ValueError('injected frame encoding failure')
            return original(codec, value, **kwargs)
        with patch.object(FrameCodec, 'encode_runtime', encode), self.assertRaisesRegex(ResolutionError, 'injected'):
            g.apply(command)
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.apply(command), control.apply(command))
        self.assertEqual(g.snapshot(), control.snapshot())


if __name__ == '__main__':
    unittest.main()
