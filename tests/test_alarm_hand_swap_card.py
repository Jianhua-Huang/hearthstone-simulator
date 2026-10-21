"""Paid Alarm entry and physical start-of-turn exchanges through native recruits."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.alarm_hand_swap_card import CARD, load_batch
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, LaunchStarship, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage, Destroy,
    Freeze, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.minion_hand_swaps import SwapWithOpponentHand
from hs_sim.engine.model import AppendageSpec, CostSpec, SummonQuantitySpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'alarm.hand.test.'
A, B, FILL, BODY, LIMB, DOUBLE = (P + x for x in ('a', 'b', 'fill', 'body', 'limb', 'double'))
PREP, QUIET, KILL, CHANGE, STEAL, STALE, WAIT, WATCH, RETURN_WATCH, FAIL_WATCH = (
    P + x for x in ('prep', 'quiet', 'kill', 'change', 'steal', 'stale', 'wait', 'watch', 'return_watch', 'fail_watch'))
BREAK_PIECE, RETURN_SHIP = P + 'break_piece', P + 'return_ship'


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    r.register_behavior(P + 'armor', lambda c: (GainArmor(c.player_id, 9),))
    r.register_behavior(P + 'pass', lambda c: ())
    r.register_card(CardDefinition(A, A, CardType.MINION, cost=5, attack=2, health=4,
        battlecry=P + 'armor', deathrattle=P + 'armor'))
    r.register_card(CardDefinition(B, B, CardType.MINION, cost=2, attack=3, health=3))
    r.register_card(CardDefinition(LIMB, LIMB, CardType.MINION, attack=1, health=2))
    r.register_card(CardDefinition(BODY, BODY, CardType.MINION, attack=4, health=6,
        keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec(LIMB),), battlecry=P + 'armor'))
    r.register_card(CardDefinition(DOUBLE, DOUBLE, CardType.MINION, health=5,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_card(CardDefinition(FILL, FILL, CardType.SPELL, on_play=P + 'pass'))
    def source(c):
        return next(c.state.entities[i] for pid in (1, 2) for i in c.state.players[pid].board
            if c.state.entities[i].card_id == CARD)
    def request(c):
        e = source(c)
        return SwapWithOpponentHand(MinionReference.capture(e),
            replace(SummonCause.capture(c), source=SourceAllocationFact.capture(c.state, e),
                origin='card_effect', cast_id=None, cast_card_id=None))
    def prep(c):
        target = next(c.state.entities[i] for i in c.state.players[2].hand
            if c.state.entities[i].kind == CardType.MINION)
        e = source(c)
        return (BuffStoredCard(CardReference.capture(target), 4, 3, c.source_id, cost=CostSpec(delta=-1)),
            Buff(e.id, 3, 4, c.source_id), Damage(e.id, 1, c.source_id), Freeze(e.id, c.source_id))
    def stale(c):
        effect = request(c)
        return (Transform(effect.minion.entity_id, B), effect)
    def options(c, effects=()):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue', effects),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id)
    scripts = {
        PREP: prep, QUIET: lambda c: (Silence(source(c).id),), KILL: lambda c: (Destroy(source(c).id, c.source_id),),
        CHANGE: lambda c: (Transform(source(c).id, B),), STEAL: lambda c: (ChangeControl(source(c).id, c.player_id),),
        STALE: stale, WAIT: lambda c: (options(c, (request(c),)),),
        BREAK_PIECE: lambda c: (Destroy(c.state.players[c.player_id].board[0], c.source_id),),
        RETURN_SHIP: lambda c: tuple(ReturnToHand(i) for i in c.state.players[c.player_id].board
            if r.card(c.state.entities[i].card_id).starship_for),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    def fail(c):
        raise ResolutionError('Deliberate swap reaction failure')
    r.register_behavior(P + 'fail', fail)
    def watch(c, event, failing=False):
        roots = c.state.card_summon_history
        if c.event.kind != event or not roots or roots[-1].request.materials[0].swap_minion is None:
            return ()
        material = roots[-1].request.materials[0]
        old, incoming = c.state.entities[material.swap_minion.entity_id], c.state.entities[material.reference.entity_id]
        if (old.zone, old.controller, incoming.zone, incoming.controller) != (Zone.HAND, 2, Zone.BOARD, 1):
            raise ResolutionError('Swap published an intermediate allocation')
        return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),) if failing else (options(c),)
    for cid, event, failing in ((WATCH, 'minion_summoned', False),
            (RETURN_WATCH, 'card_returned', False), (FAIL_WATCH, 'card_returned', True)):
        r.register_behavior(cid, lambda c, event=event, failing=failing: watch(c, event, failing))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5, triggers=(TriggerSpec(event, cid),)))
    r.validate(); r.freeze()
    return r


class AlarmHandSwapTests(unittest.TestCase):
    def game(self, hand=(CARD,), *, enemy_hand=(A,), board=(), enemy_board=(), active=1, capacity=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,) * 25, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, board=enemy_board, deck=(FILL,) * 25, mana=10, max_mana=10,
                hero_power_card_id='HERO_08bp')), active_player=active, seed=260), registry('writer'), Ruleset(max_hand=capacity))
    def play(self, g, cid=CARD):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid)); return eid
    def end(self, g):
        g.apply(EndTurn(g.state.active_player))
    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))
    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(snap, registry('reader'))
        self.assertEqual(other.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry('reader')).snapshot(), snap)
        return other

    def test_a00_complete_source_zero_attack_metadata_and_evidence_only(self):
        data = load_batch(); raw = data['cards'][0]['record']; card = registry('writer').card(CARD)
        self.assertEqual((raw['cost'], raw['attack'], raw['health']), (3, None, 3))
        self.assertNotIn('ATK', raw['tags']); self.assertEqual(card.metadata.tribes, ('mech',))
        self.assertEqual((card.cost, card.attack, card.health), (3, 0, 3))
        self.assertEqual({x['face']['attack'] for x in data['official_observations']}, {0})
        self.assertNotIn('JAIL_502e', registry('writer').cards)

    def test_a01_paid_entry_then_only_owner_start_moves_two_originals_without_battlecry(self):
        g = self.game(); partner = g.state.players[2].hand[0]; source = self.play(g)
        self.assertEqual(g.state.players[1].mana, 7); self.end(g)
        self.assertIn(source, g.state.players[1].board); self.assertIn(partner, g.state.players[2].hand)
        self.end(g)
        self.assertIn(source, g.state.players[2].hand); self.assertIn(partner, g.state.players[1].board)
        self.assertEqual((g.state.entities[source].owner, g.state.entities[source].controller), (1, 2))
        self.assertEqual((g.state.entities[partner].owner, g.state.entities[partner].controller), (2, 1))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(len(g.state.play_history), 1); self.assertFalse(g.state.death_history)
        root = g.state.card_summon_history[-1]
        self.assertEqual(root.deliveries[0].entity.entity_id, partner)
        self.assertEqual(root.request.materials[0].swap_minion.entity_id, source)
        self.assertEqual(hand_entry(g.state, g.state.entities[source].hand_entry_id).reason, 'return')
        self.assertEqual(hand_entry(g.state, g.state.entities[source].hand_entry_id).source_id, source)
        self.portable(g)

    def test_a02_full_boards_and_full_opposing_hand_reserve_both_existing_slots(self):
        g = self.game(board=(B,) * 6, enemy_board=(B,) * 7, enemy_hand=(A,) + (FILL,) * 9)
        partner = g.state.players[2].hand[0]; source = self.play(g); self.end(g)
        before = len([e for e in g.events if e.kind == 'card_burned']); self.end(g)
        self.assertEqual(len(g.state.players[1].board), 7); self.assertEqual(len(g.state.players[2].hand), 10)
        self.assertEqual(g.state.players[1].board[-1], partner); self.assertIn(source, g.state.players[2].hand)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), before)

    def test_a03_no_minion_or_empty_hand_keeps_source_and_rng(self):
        for hand in ((), (FILL, FILL)):
            with self.subTest(hand=hand):
                g = self.game(enemy_hand=hand); source = self.play(g); self.end(g); rng = g._rng.getstate(); self.end(g)
                self.assertIn(source, g.state.players[1].board); self.assertEqual(g._rng.getstate(), rng)
                self.assertFalse(g.state.card_summon_history)

    def test_a04_same_name_physical_minions_each_keep_one_random_weight(self):
        g = self.game(enemy_hand=(A, A, A, B, FILL)); originals = tuple(g.state.players[2].hand[:4])
        self.play(g); self.end(g); rng = Random(); rng.setstate(g._rng.getstate()); expected = rng.choice(originals); self.end(g)
        self.assertEqual(g.state.players[1].board, [expected]); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertTrue(all(i in g.state.players[2].hand for i in originals if i != expected))

    def test_b00_hand_buffs_remain_incoming_outgoing_damage_buffs_freeze_and_cost_reset(self):
        g = self.game((CARD, PREP)); partner = g.state.players[2].hand[0]; source = self.play(g); self.play(g, PREP)
        old_entry = g.state.entities[partner].hand_entry_id; self.end(g); self.end(g)
        incoming, returned = g.state.entities[partner], g.state.entities[source]
        self.assertEqual((incoming.attack, incoming.health, incoming.hand_entry_id), (6, 7, old_entry))
        self.assertEqual((returned.attack, returned.health, returned.damage, returned.base_cost), (0, 3, 0, 3))
        self.assertIsNone(returned.frozen_until_owner_turn); self.assertFalse(returned.enchantments)
        self.assertNotEqual(returned.hand_entry_id, old_entry)

    def test_b01_departed_silenced_or_transformed_source_has_no_start_effect(self):
        for operation in (QUIET, KILL, CHANGE):
            with self.subTest(operation=operation):
                g = self.game((CARD, operation)); self.play(g); self.play(g, operation); self.end(g)
                rng = g._rng.getstate(); self.end(g)
                self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.card_summon_history)

    def test_b02_current_controller_uses_its_own_start_and_opposing_hand(self):
        g = self.game((STEAL,), board=(), enemy_board=(CARD,)); source = g.state.players[2].board[0]
        self.play(g, STEAL); self.end(g); self.assertIn(source, g.state.players[1].board); self.end(g)
        self.assertIn(source, g.state.players[2].hand); self.assertEqual(g.state.card_summon_history[-1].request.player_id, 1)
        self.assertEqual(g.state.entities[source].owner, 2)

    def test_b03_second_player_first_global_turn_obeys_owner_event_without_parity(self):
        g = self.game((A,), enemy_hand=(CARD,), active=2); source = self.play(g); self.end(g)
        self.assertIn(source, g.state.players[2].board); self.end(g)
        self.assertIn(source, g.state.players[1].hand); self.assertEqual(g.state.card_summon_history[-1].request.player_id, 2)

    def test_b04_replacement_occupies_original_middle_board_position(self):
        g = self.game((), board=(B, CARD, B)); source = g.state.players[1].board[1]; partner = g.state.players[2].hand[0]
        before = list(g.state.players[1].board); self.end(g); self.end(g)
        self.assertEqual(g.state.players[1].board, [before[0], partner, before[2]])
        self.assertIn(source, g.state.players[2].hand)

    def test_c00_multiplier_moves_one_original_and_copies_immutable_extra_without_extra_return(self):
        g = self.game(board=(DOUBLE,)); partner = g.state.players[2].hand[0]; source = self.play(g); self.end(g); self.end(g)
        root = g.state.card_summon_history[-1]; bodies = [d.entity.entity_id for d in root.deliveries]
        self.assertEqual(root.plan.total, 2); self.assertEqual(bodies[0], partner); self.assertNotEqual(bodies[1], partner)
        self.assertEqual([g.state.entities[i].owner for i in bodies], [2, 1])
        self.assertEqual(g.state.players[2].hand.count(source), 1)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_returned']), 1)

    def test_c01_full_board_multiplier_keeps_first_swap_and_reports_failed_extra(self):
        g = self.game(board=(DOUBLE,) + (B,) * 5); source = self.play(g); self.end(g); self.end(g)
        root = g.state.card_summon_history[-1]
        self.assertEqual([x.outcome for x in root.deliveries], ['delivered', 'board_full'])
        self.assertEqual(len(g.state.players[1].board), 7); self.assertIn(source, g.state.players[2].hand)

    def test_c02_colossal_partner_uses_existing_expansion_without_battlecry(self):
        g = self.game(enemy_hand=(BODY,)); partner = g.state.players[2].hand[0]; self.play(g); self.end(g); self.end(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [BODY, LIMB])
        self.assertEqual(g.state.players[1].board[0], partner)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertTrue(g.state.colossal_history[-1].completed)

    def test_c03_two_real_alarms_requery_after_first_swap_without_retriggering_new_arrivals(self):
        g = self.game((), board=(CARD, CARD), enemy_hand=(A, B)); sources = list(g.state.players[1].board)
        self.end(g); rng = Random(); rng.setstate(g._rng.getstate()); pool = list(g.state.players[2].hand[:2])
        first = rng.choice(pool); pool.remove(first); pool.append(sources[0]); second = rng.choice(pool); self.end(g)
        self.assertEqual([x.deliveries[0].entity.entity_id for x in g.state.card_summon_history], [first, second])
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.assertEqual(len(g.state.card_summon_history), 2)

    def test_d00_real_return_and_summon_reactions_see_complete_swap_wait_and_resume(self):
        for watcher in (WATCH, RETURN_WATCH):
            with self.subTest(watcher=watcher):
                g = self.game(board=(watcher,)); source = self.play(g); self.end(g); self.end(g)
                self.assertIsNotNone(g.state.pending_choice); self.assertIn(source, g.state.players[2].hand)
                other = self.portable(g); self.choose(g); self.choose(other)
                self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.card_summon_history[-1].status, 'completed')

    def test_d01_waiting_before_random_choice_restores_original_request_and_hidden_information(self):
        g = self.game((WAIT,), board=(CARD,), enemy_hand=(A, B, B)); self.play(g, WAIT)
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        for pid in (1, 2):
            wire = json.dumps(g.for_player(pid).observe()) + json.dumps(g.player_events(pid))
            for key in ('"swap_minion"', '"materials"', '"rng_before"', '"cause"', '"reference"'):
                self.assertNotIn(key, wire)
        actor_hand = g.observe(1)['players'][1]['hand']
        self.assertFalse(any(row.get('card_id') in (A, B) for row in actor_hand))

    def test_d02_late_return_reaction_failure_rolls_back_complete_turn_swap_and_random(self):
        g = self.game(board=(FAIL_WATCH,), enemy_hand=(A, B)); self.play(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate swap reaction failure'): self.end(g)
        self.assertEqual(g.snapshot(), before)

    def test_d03_failed_choice_after_swap_keeps_original_pending_boundary(self):
        g = self.game(board=(WATCH,)); self.play(g); self.end(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Deliberate swap reaction failure'): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)

    def test_e00_stale_board_incarnation_does_not_swap_or_draw_random(self):
        g = self.game((STALE,), board=(CARD,)); rng = g._rng.getstate(); self.play(g, STALE)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.card_summon_history)
        self.assertEqual(len(g.state.players[2].hand), 1)

    def test_e01_strict_causing_player_and_saved_partner_cannot_borrow_another_source(self):
        g = self.game(); self.play(g); self.end(g); self.end(g)
        root = g.state.card_summon_history[-1]; ref = root.request.materials[0].swap_minion
        with self.assertRaisesRegex(ValueError, 'original board source'):
            SwapWithOpponentHand(ref, replace(root.request.cause, player_id=2))
        snap = g.snapshot(); item = snap['state']['card_summon_history'][-1]['request']['materials'][0]
        item['swap_minion']['entity_id'] = g.state.players[1].hero_id
        payload_keys = ('ruleset', 'registry_fingerprint', 'mechanics_version', 'state', 'rng_state',
            'resolution_frame', 'rewind_session', 'match_setup', 'generation_context', 'information')
        snap['state_hash'] = canonical_digest({k: snap[k] for k in payload_keys})
        with self.assertRaises(ValueError): Game.from_snapshot(snap, registry('reader'))

    def test_e02_real_magnetic_and_starship_piece_candidates_are_not_pruned_or_played(self):
        for cid in ('BOT_563', 'SC_403a'):
            with self.subTest(cid=cid):
                g = self.game(enemy_hand=(cid,)); partner = g.state.players[2].hand[0]
                self.play(g); self.end(g); self.end(g)
                self.assertEqual(g.state.players[1].board, [partner])
                self.assertEqual(g.state.entities[partner].card_id, cid)
                self.assertEqual(len(g.state.play_history), 1)

    def test_e03_real_launched_returned_ship_and_extra_preserve_full_composition(self):
        from hs_sim.engine.starships import construction
        g = self.game(board=(DOUBLE,), enemy_board=('SC_403a',),
            enemy_hand=(BREAK_PIECE, RETURN_SHIP), active=2)
        self.play(g, BREAK_PIECE); ship = construction(g.state, 2)
        g.apply(LaunchStarship(2, ship.id)); partner = g.state.players[2].board[-1]
        self.play(g, RETURN_SHIP); original = g.state.entities[partner]
        self.assertTrue(original.components); components = original.components
        self.end(g); self.play(g); self.end(g); self.end(g)
        root = g.state.card_summon_history[-1]
        self.assertEqual(root.deliveries[0].entity.entity_id, partner)
        self.assertEqual(len(root.deliveries), 2)
        for delivery in root.deliveries:
            self.assertEqual(g.state.entities[delivery.entity.entity_id].components, components)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
