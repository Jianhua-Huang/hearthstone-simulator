"""Exact old guard obligations, using genuinely submitted public paid roots."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

import test_m5_owner_turn_history as fixtures
from hs_sim.engine import CardDefinition, CardType, Game, Registry, SnapshotError, SpellSchool
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.serialization import canonical_hash, state_from_dict, state_to_dict

OBSERVATIONS = []
MESSAGE = 'Current-hand submitted price differs from its accepted face or clock'


class CurrentHandGuardTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry
    portable = fixtures.OwnerTurnActionTests.portable

    def waiting(self, kind):
        self.r = fixtures.registry()
        for name in ('guard-a', 'guard-b'):
            kwargs = {'health':4, 'battlecry':'choice'} if kind == CardType.MINION else {
                'on_play':'choice', 'spell_school':SpellSchool.ARCANE}
            self.r.register_card(CardDefinition(name, name, kind, cost=2,
                metadata=fixtures.metadata(('dragon',) if kind == CardType.MINION else ()), **kwargs))
        g = self.game(('guard-a', 'guard-b'))
        self.end(g)
        self.end(g)
        self.play(g, 'guard-a')
        p, = g.state.play_history
        self.assertEqual((p.turn, p.action, p.submitted_cost.turn, p.submitted_cost.action), (3, 3, 3, 3))
        self.assertEqual(p.submitted_cost.quote_origin, 'current_hand')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(p.completed)
        return g, p

    def altered(self, p, axis):
        receipt = p.submitted_cost
        if axis in ('turn', 'action'):
            return replace(receipt, **{axis:getattr(receipt, axis)-1})
        quote = receipt.quote
        # Two required identity copies form one quoted-face axis; actual accepted face stays guard-a.
        quote = replace(quote, quote_input=replace(quote.quote_input, card_id='guard-b'),
                        intrinsic=replace(quote.intrinsic, card_id='guard-b'))
        validate_cost_quote_fact(self.r, quote)
        return replace(receipt, quote=quote)

    def test_genuine_minion_and_spell_positive_constructor_codecs_and_portability(self):
        for kind in (CardType.MINION, CardType.SPELL):
            with self.subTest(kind=kind):
                g, p = self.waiting(kind)
                self.assertEqual(replace(p), p)
                codec = FrameCodec(g.mechanics, self.r)
                self.assertEqual(codec.decode(codec.encode(p)), p)
                self.assertEqual(state_from_dict(state_to_dict(g.state)), g.state)
                self.portable(g)
                self.choose(g)
                self.assertTrue(g.state.play_history[0].completed)
                self.portable(g)

    def test_constructor_rejects_each_earlier_current_hand_clock(self):
        for kind in (CardType.MINION, CardType.SPELL):
            for axis in ('turn', 'action'):
                with self.subTest(kind=kind, axis=axis):
                    g, p = self.waiting(kind)
                    receipt = self.altered(p, axis)
                    with self.assertRaisesRegex(ValueError, MESSAGE):
                        replace(p, submitted_cost=receipt)

    def test_frame_codec_rejects_each_earlier_current_hand_clock(self):
        for kind in (CardType.MINION, CardType.SPELL):
            for axis in ('turn', 'action'):
                with self.subTest(kind=kind, axis=axis):
                    g, p = self.waiting(kind)
                    codec = FrameCodec(g.mechanics, self.r)
                    wire = codec.encode(p)
                    wire['fields']['submitted_cost'] = codec.encode(self.altered(p, axis))
                    with self.assertRaisesRegex(ValueError, MESSAGE): codec.decode(wire)

    def test_state_codec_rejects_each_earlier_current_hand_clock(self):
        for kind in (CardType.MINION, CardType.SPELL):
            for axis in ('turn', 'action'):
                with self.subTest(kind=kind, axis=axis):
                    g, p = self.waiting(kind)
                    wire = state_to_dict(g.state)
                    wire['play_history'][0]['submitted_cost'][axis] -= 1
                    with self.assertRaisesRegex(ValueError, MESSAGE): state_from_dict(wire)

    def test_constructor_rejects_different_individually_valid_quoted_face(self):
        for kind in (CardType.MINION, CardType.SPELL):
            with self.subTest(kind=kind):
                g, p = self.waiting(kind)
                with self.assertRaisesRegex(ValueError, MESSAGE): replace(p, submitted_cost=self.altered(p, 'face'))

    def test_frame_codec_rejects_different_individually_valid_quoted_face(self):
        for kind in (CardType.MINION, CardType.SPELL):
            with self.subTest(kind=kind):
                g, p = self.waiting(kind)
                codec = FrameCodec(g.mechanics, self.r)
                wire = codec.encode(p)
                wire['fields']['submitted_cost'] = codec.encode(self.altered(p, 'face'))
                with self.assertRaisesRegex(ValueError, MESSAGE): codec.decode(wire)

    def test_state_codec_rejects_different_individually_valid_quoted_face(self):
        for kind in (CardType.MINION, CardType.SPELL):
            with self.subTest(kind=kind):
                g, p = self.waiting(kind)
                self.altered(p, 'face')
                wire = state_to_dict(g.state)
                quote = wire['play_history'][0]['submitted_cost']['quote']
                quote['quote_input']['card_id'] = 'guard-b'
                quote['intrinsic']['card_id'] = 'guard-b'
                with self.assertRaisesRegex(ValueError, MESSAGE): state_from_dict(wire)

    def test_complete_game_boundary_observation_is_separate_from_constructor_obligation(self):
        for kind in (CardType.MINION, CardType.SPELL):
            g, p = self.waiting(kind)
            self.choose(g)
            p = g.state.play_history[0]
            for axis in ('turn', 'action', 'face'):
                wire = deepcopy(g.snapshot())
                receipt = wire['state']['play_history'][0]['submitted_cost']
                if axis == 'face':
                    self.altered(p, axis)
                    receipt['quote']['quote_input']['card_id'] = 'guard-b'
                    receipt['quote']['intrinsic']['card_id'] = 'guard-b'
                else: receipt[axis] -= 1
                wire['state_hash'] = canonical_hash({k:v for k,v in wire.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                try:
                    restored = Game.from_snapshot(wire, self.fresh_registry())
                except SnapshotError as exc:
                    OBSERVATIONS.append({'kind':kind.value, 'axis':axis, 'boundary':'complete Game.from_snapshot',
                        'outcome':'rejected', 'reason':str(exc)})
                else:
                    self.assertEqual(restored.snapshot(), wire)
                    OBSERVATIONS.append({'kind':kind.value, 'axis':axis, 'boundary':'complete Game.from_snapshot',
                        'outcome':'accepted', 'reason':None})

    def test_registry_original_explicit_type_guard_and_legal_positive(self):
        r = Registry('guard-type-input')
        r.register_card(CardDefinition('legal', 'legal', CardType.MINION, health=1))
        self.assertEqual(r.card('legal').id, 'legal')
        for invalid in (None, {}):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'definition must be a CardDefinition'):
                    r.register_card(invalid)

    def test_complete_game_rejects_each_current_hand_cardface_and_clock_axis(self):
        for kind in (CardType.MINION, CardType.SPELL):
            g, p = self.waiting(kind)
            self.choose(g)
            p = g.state.play_history[0]
            for axis in ('turn', 'action', 'face'):
                with self.subTest(kind=kind, axis=axis):
                    wire = deepcopy(g.snapshot())
                    receipt = wire['state']['play_history'][0]['submitted_cost']
                    if axis == 'face':
                        self.altered(p, axis)
                        receipt['quote']['quote_input']['card_id'] = 'guard-b'
                        receipt['quote']['intrinsic']['card_id'] = 'guard-b'
                    else: receipt[axis] -= 1
                    wire['state_hash'] = canonical_hash({k:v for k,v in wire.items()
                        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                    with self.assertRaisesRegex(SnapshotError, MESSAGE):
                        Game.from_snapshot(wire, self.fresh_registry())
