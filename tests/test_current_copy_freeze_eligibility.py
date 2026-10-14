"""Current-copy status eligibility and original event boundaries through public actions."""
from copy import deepcopy
import json
import unittest

import test_freeze_prevention_basics as native
from hs_sim.engine import (CardDefinition, CardType, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, SummonCause, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def registry():
    r = native.registry()
    def copy(c, mode='current'):
        return CopyMinion(c.target_id, c.player_id, mode=mode, cause=SummonCause.capture(c))
    def fail(c):
        raise ResolutionError('Deliberate copy continuation failure')
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Copy', (copy(c),)),
            ChoiceOption('bad', 'Fail after copy', (copy(c), InvokeBehavior('cf.fail', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior('cf.fail', fail)
    for name, body in (('cf.current', lambda c: (copy(c),)),
                       ('cf.base', lambda c: (copy(c, 'base'),)), ('cf.wait', wait)):
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1,
            on_play=name, requires_target=True))
    r.register_behavior('cf.observe-thaw', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('cf.observer', 'Thaw observer', CardType.MINION, health=5,
        triggers=(TriggerSpec('unfrozen', 'cf.observe-thaw'),)))
    return r


class CurrentCopyFreezeEligibilityTests(unittest.TestCase):
    def game(self, *, protected=True, card='cf.current'):
        g = Game.from_scenario(Scenario((
            PlayerSetup('fp.hero', hand=('fp.op.freeze', card),
                board=((native.NATIVE,) if protected else ()) + ('cf.observer',),
                max_mana=10, mana=10),
            PlayerSetup('fp.hero', board=('fp.body',)),
        ), seed=413), registry())
        enemy = g.state.players[2].board[0]
        self.play(g, 'fp.op.freeze', enemy)
        self.assertTrue(g.state.entities[enemy].frozen)
        return g, enemy

    def play(self, g, card, target):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(1, source, target))

    def copied(self, g):
        return next(g.state.entities[i] for i in g.state.players[1].board
            if g.state.entities[i].card_id == 'fp.body')

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return saved

    def assert_no_phantom_thaw(self, g):
        self.assertFalse(any(e.kind == 'unfrozen' for e in g.events))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            self.assertNotIn('card_summon_history', view)
            self.assertNotIn('frozen_until_owner_turn', view)

    def test_protected_copy_does_not_emit_thaw_or_trigger_observer(self):
        g, enemy = self.game()
        self.play(g, 'cf.current', enemy)
        copy = self.copied(g)
        self.assertFalse(copy.frozen)
        self.assertIsNone(copy.frozen_until_owner_turn)
        self.assertIn(native.FLAG, copy.keywords)
        self.assertNotEqual(copy.id, enemy)
        self.assertEqual(copy.origin_entity_id, enemy)
        self.assertTrue(g.state.entities[enemy].frozen)
        self.assertEqual(g.state.players[1].mana, 9)
        self.assert_no_phantom_thaw(g)
        self.portable(g)

    def test_unprotected_copy_keeps_freeze_with_new_owner_deadline(self):
        g, enemy = self.game(protected=False)
        self.play(g, 'cf.current', enemy)
        copy = self.copied(g)
        self.assertTrue(copy.frozen)
        self.assertEqual(copy.frozen_until_owner_turn, 2)
        self.assertEqual(g.state.entities[enemy].frozen_until_owner_turn, 1)
        self.assert_no_phantom_thaw(g)
        self.portable(g)

    def test_base_copy_does_not_inherit_frozen_status(self):
        g, enemy = self.game(protected=False, card='cf.base')
        self.play(g, 'cf.base', enemy)
        self.assertFalse(self.copied(g).frozen)
        self.assertTrue(g.state.entities[enemy].frozen)
        self.assert_no_phantom_thaw(g)
        self.portable(g)

    def test_waiting_copy_restores_and_failed_choice_preserves_paid_prefix(self):
        g, enemy = self.game(card='cf.wait')
        self.play(g, 'cf.wait', enemy)
        self.assertEqual(g.state.players[1].mana, 9)
        saved = self.portable(g)
        choice = g.state.pending_choice
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(choice.player_id, choice.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved)
        restored, cloned = Game.from_snapshot(saved, registry()), g.clone()
        for branch in (g, restored, cloned):
            branch.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
            self.assertFalse(self.copied(branch).frozen)
            self.assert_no_phantom_thaw(branch)
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.snapshot(), cloned.snapshot())

    def test_prior_core_event_semantics_are_not_silently_restored(self):
        g, enemy = self.game()
        saved = deepcopy(g.snapshot())
        saved['mechanics_version']['version'] = 'core-effects-v284'
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised:
            Game.from_snapshot(saved, registry())
        self.assertIn('Mechanics version mismatch', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
