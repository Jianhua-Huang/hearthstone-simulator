"""Existing owner-clock freeze policy through physical control and return paths."""
from copy import deepcopy
import json
import unittest

import test_freeze_prevention_basics as native
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction,
    PlayCard, PlayerSetup, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, GainArmor, InvokeBehavior,
    RemoveEnchantment, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def registry():
    r = native.registry()
    def take(c): return ChangeControl(c.target_id, c.player_id)
    def fail(c): raise ResolutionError('Deliberate control continuation failure')
    def remove(c):
        return tuple(RemoveEnchantment(c.target_id, e.id) for e in c.state.entities[c.target_id].enchantments
            if e.control_return_player_id is not None)
    def wait(c):
        return (RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Take', (take(c),)),
            ChoiceOption('bad', 'Fail after take', (take(c), InvokeBehavior('clock.fail', c.source_id, c.player_id))),
        ), c.source_id),)
    r.register_behavior('clock.fail', fail)
    for name, body in (
        ('clock.take', lambda c: (take(c),)),
        ('clock.give', lambda c: (ChangeControl(c.target_id, 3-c.player_id),)),
        ('clock.borrow', lambda c: (ChangeControl(c.target_id, c.player_id, True, c.source_id),)),
        ('clock.remove', remove), ('clock.wait', wait),
    ):
        r.register_behavior(name, body)
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=1, on_play=name, requires_target=True))
    def observe(c):
        entity = c.state.entities[c.event.target_id]
        return (GainArmor(c.player_id, entity.frozen_until_owner_turn),) if (
            c.event.player_id == c.player_id and entity.frozen) else ()
    r.register_behavior('clock.observe', observe)
    r.register_card(CardDefinition('clock.observer', 'Control clock observer', CardType.MINION, health=5,
        triggers=(TriggerSpec('control_changed', 'clock.observe'),)))
    return r


class ControlFreezeClockTests(unittest.TestCase):
    def game(self, cards=('clock.take',), *, own=False, protected=False, full_enemy=False):
        g = Game.from_scenario(Scenario((
            PlayerSetup('fp.hero', hand=('fp.op.freeze', *cards),
                board=((native.NATIVE,) if protected else ()) + (('fp.body',) if own else ()) + ('clock.observer',),
                deck=('fp.body',)*8, max_mana=10, mana=10),
            PlayerSetup('fp.hero', board=('fp.body',)*(7 if full_enemy else 0 if own else 1),
                deck=('fp.body',)*8, max_mana=10, mana=10),
        ), seed=507), registry())
        player = 1 if own else 2
        target = next(i for i in g.state.players[player].board if g.state.entities[i].card_id == 'fp.body')
        return g, target

    def play(self, g, card, target):
        actor = g.state.active_player
        source = next(i for i in g.state.players[actor].hand if g.state.entities[i].card_id == card)
        return g.apply(PlayCard(actor, source, target))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        for player in (1, 2):
            view = json.dumps(g.for_player(player).observe())
            self.assertNotIn('frozen_until_owner_turn', view)
            self.assertNotIn('control_return_player_id', view)
        return saved

    def test_permanent_take_rebinds_clock_and_misses_the_next_real_opportunity(self):
        g, target = self.game()
        self.play(g, 'fp.op.freeze', target)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 1)
        self.play(g, 'clock.take', target)
        entity = g.state.entities[target]
        self.assertEqual((entity.owner, entity.controller, entity.frozen_until_owner_turn), (2, 1, 2))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(sum(e.kind == 'frozen' for e in g.events), 1)
        self.assertFalse(any(e.kind == 'unfrozen' for e in g.events))
        g.apply(EndTurn(1)); self.assertTrue(g.state.entities[target].frozen)
        g.apply(EndTurn(2))
        with self.assertRaises(IllegalAction): g.apply(Attack(1, target, g.state.players[2].hero_id))
        g.apply(EndTurn(1)); self.assertFalse(g.state.entities[target].frozen)
        self.portable(g)

    def test_give_uses_new_opponents_clock_after_old_attack_is_spent(self):
        g, target = self.game(('clock.give',), own=True)
        g.apply(Attack(1, target, g.state.players[2].hero_id))
        self.play(g, 'fp.op.freeze', target)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 2)
        self.play(g, 'clock.give', target)
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].frozen_until_owner_turn), (2, 1))
        self.assertEqual(g.state.entities[target].attacks_this_turn, 1)
        g.apply(EndTurn(1)); self.assertTrue(g.state.entities[target].frozen)
        g.apply(EndTurn(2)); self.assertFalse(g.state.entities[target].frozen)
        self.portable(g)

    def test_natural_temporary_return_rebinds_after_all_expiry_work(self):
        g, target = self.game(('clock.borrow',))
        self.play(g, 'clock.borrow', target); self.play(g, 'fp.op.freeze', target)
        self.assertEqual(g.state.entities[target].frozen_until_owner_turn, 2)
        g.apply(EndTurn(1))
        self.assertEqual((g.state.entities[target].controller, g.state.entities[target].frozen_until_owner_turn), (2, 1))
        self.assertTrue(g.state.entities[target].frozen)
        g.apply(EndTurn(2)); self.assertFalse(g.state.entities[target].frozen)
        self.portable(g)

    def test_manual_return_marker_removal_rebinds_without_reacquiring_entity(self):
        g, target = self.game(('clock.borrow', 'clock.remove'))
        self.play(g, 'clock.borrow', target); self.play(g, 'fp.op.freeze', target)
        presence = g.state.entities[target].board_presence_id
        self.play(g, 'clock.remove', target)
        entity = g.state.entities[target]
        self.assertEqual((entity.owner, entity.controller, entity.board_presence_id, entity.frozen_until_owner_turn), (2, 2, presence, 1))
        self.assertFalse(any(e.kind == 'unfrozen' for e in g.events))
        self.portable(g)

    def test_waiting_transfer_recovers_and_failure_rolls_back_clock_and_payment(self):
        g, target = self.game(('clock.wait',))
        self.play(g, 'fp.op.freeze', target); self.play(g, 'clock.wait', target)
        saved = self.portable(g); choice = g.state.pending_choice
        self.assertEqual(g.state.players[1].mana, 9)
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(choice.player_id, choice.id, ('bad',)))
        self.assertEqual(g.snapshot(), saved)
        restored, cloned = Game.from_snapshot(saved, registry()), g.clone()
        for branch in (g, restored, cloned):
            branch.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
            self.assertEqual(branch.state.entities[target].frozen_until_owner_turn, 2)
            self.assertEqual(branch.state.entities[branch.state.players[1].hero_id].armor, 2)
            self.portable(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.snapshot(), cloned.snapshot())

    def test_unfrozen_transfer_does_not_invent_status_or_thaw(self):
        g, target = self.game()
        self.play(g, 'clock.take', target)
        self.assertFalse(g.state.entities[target].frozen)
        self.assertFalse(any(e.kind in ('frozen', 'unfrozen') for e in g.events))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.portable(g)

    def test_same_controller_noop_keeps_original_frozen_deadline(self):
        g, target = self.game(own=True)
        g.apply(Attack(1, target, g.state.players[2].hero_id)); self.play(g, 'fp.op.freeze', target)
        before = g.state.entities[target]
        self.play(g, 'clock.take', target)
        after = g.state.entities[target]
        self.assertEqual((after.controller, after.entered_order, after.frozen_until_owner_turn),
                         (before.controller, before.entered_order, before.frozen_until_owner_turn))
        self.assertFalse(any(e.kind == 'control_changed' for e in g.events)); self.portable(g)

    def test_full_destination_failure_keeps_original_clock_and_physical_owner(self):
        g, target = self.game(('clock.give',), own=True, full_enemy=True)
        g.apply(Attack(1, target, g.state.players[2].hero_id)); self.play(g, 'fp.op.freeze', target)
        before = g.state.entities[target]
        self.play(g, 'clock.give', target)
        after = g.state.entities[target]
        self.assertEqual((after.owner, after.controller, after.frozen_until_owner_turn), (before.owner, before.controller, before.frozen_until_owner_turn))
        self.assertTrue(any(e.kind == 'control_change_failed' for e in g.events)); self.portable(g)

    def test_current_destination_protection_clears_real_freeze_only_once(self):
        g, target = self.game(protected=True)
        self.play(g, 'fp.op.freeze', target); self.play(g, 'clock.take', target)
        self.assertFalse(g.state.entities[target].frozen)
        self.assertIsNone(g.state.entities[target].frozen_until_owner_turn)
        self.assertIn(native.FLAG, g.state.entities[target].keywords)
        self.assertEqual(sum(e.kind == 'unfrozen' and e.target_id == target for e in g.events), 1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.portable(g)

    def test_previous_control_clock_semantics_are_explicitly_rejected(self):
        g, target = self.game()
        saved = deepcopy(g.snapshot()); saved['mechanics_version']['version'] = 'core-effects-v285'
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as raised: Game.from_snapshot(saved, registry())
        self.assertIn('Mechanics version mismatch', str(raised.exception))


if __name__ == '__main__': unittest.main()
