"""Real hand mixing preserves physical quotas, residence and hidden boundaries."""
from dataclasses import asdict
from functools import lru_cache
import json
from random import Random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.fill_board_hand_quest_cards import HAND as QUEST
from hs_sim.cards.joint_hand_shuffle_card import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, RevealHandCard)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.joint_hand_shuffle import ShuffleHandsTogether, mixed_order
from hs_sim.engine.model import CostSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.zones import CardReference, FillHandWithCard

P = 'joint.hand.test.'
A, B, C = (P + x for x in ('a', 'b', 'c'))
MIX, FULL, BUFF, REVEAL, WAIT_BEFORE, LATE_FAIL, UNKNOWN, RESIZE = (
    P + x for x in ('mix', 'full', 'buff', 'reveal', 'wait_before', 'late_fail', 'unknown', 'resize'))
WATCH, FAIL_WATCH, PASS = (P + x for x in ('watch', 'fail_watch', 'pass'))
FILL = P + 'fill'


@lru_cache(maxsize=None)
def registry(role):
    assert role in ('writer', 'reader')
    r = build_registry()
    def fail(c):
        raise ResolutionError('Deliberate joint hand failure')
    r.register_behavior(P + 'fail', fail)
    def options(c):
        return RequestChoice(c.player_id, (
            ChoiceOption('ok', 'Continue', (GainArmor(c.player_id, 1),)),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))), c.source_id)
    def other(c):
        return c.state.entities[c.state.players[3 - c.player_id].hand[-1]]
    def observe(c, failing=False):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != CARD or c.event.player_id != c.player_id:
            return ()
        arrivals = [eid for eid in c.state.players[c.player_id].hand
            if hand_entry(c.state, c.state.entities[eid].hand_entry_id).from_zone == Zone.HAND]
        if not arrivals or c.event.target_id != arrivals[0]:
            return ()
        return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),) if failing else (options(c),)
    scripts = {
        MIX: lambda c: (ShuffleHandsTogether(c.player_id, c.source_id),),
        FULL: lambda c: (FillHandWithCard(c.player_id, A, c.source_id), ShuffleHandsTogether(c.player_id, c.source_id)),
        FILL: lambda c: (FillHandWithCard(c.player_id, A, c.source_id),),
        BUFF: lambda c: (BuffStoredCard(CardReference.capture(other(c)), attack=4, health=5,
            cost=CostSpec(delta=-1), source_id=c.source_id),),
        REVEAL: lambda c: (RevealHandCard(other(c).id, (c.player_id,)),),
        WAIT_BEFORE: lambda c: (options(c), ShuffleHandsTogether(c.player_id, c.source_id)),
        LATE_FAIL: lambda c: (ShuffleHandsTogether(c.player_id, c.source_id), InvokeBehavior(P + 'fail', c.source_id, c.player_id)),
        UNKNOWN: lambda c: (ShuffleHandsTogether(c.player_id, 999999),),
        RESIZE: lambda c: (SetHandCapacity(1, 1), SetHandCapacity(2, 1)),
        PASS: lambda c: (GainArmor(c.player_id, 1),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    for cid, cost, attack, health in ((A, 2, 2, 3), (B, 3, 3, 4), (C, 4, 4, 5)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=attack, health=health))
    for cid, failing in ((WATCH, False), (FAIL_WATCH, True)):
        r.register_behavior(cid, lambda c, failing=failing: observe(c, failing))
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec('card_moved_to_hand', cid),)))
    r.validate()
    r.freeze()
    return r


class JointHandShuffleTests(unittest.TestCase):
    def game(self, hand=(CARD, A, B), *, enemy_hand=(A, B, C), board=(), seed=258,
            capacity=10, active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, board=board, deck=(A,) * 20,
                mana=10, max_mana=10, hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(B,) * 20,
                mana=10, max_mana=10, hero_power_card_id='HERO_08bp')),
            seed=seed, active_player=active), registry('writer'), Ruleset(max_hand=capacity))

    def play(self, g, card=CARD):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(pid, eid))
        return eid

    def hands(self, g):
        return tuple(tuple(g.state.players[pid].hand) for pid in (1, 2))

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        other = Game.from_snapshot(snapshot, registry('reader'))
        self.assertEqual(other.snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry('reader')).snapshot(), snapshot)
        return other

    def no_draw_burn_copy(self, g):
        self.assertFalse(g.state.draw_history)
        self.assertFalse(g.state.discard_history)
        self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.deck_shuffle_history)
        self.assertFalse(any(e.kind in ('card_drawn', 'card_discarded', 'card_burned') for e in g.events))

    def source_game(self, card, transfer):
        for seed in range(258, 290):
            g = self.game(enemy_hand=(card, A, B), seed=seed)
            eid = g.state.players[2].hand[0]
            rng = Random()
            rng.setstate(g._rng.getstate())
            left = tuple(g.state.players[1].hand[1:])
            chosen = mixed_order(rng, left, tuple(g.state.players[2].hand))[:len(left)]
            if (eid in chosen) == transfer:
                return g, eid
        self.fail('Could not locate a deterministic native-source fixture')

    def test_a00_complete_source_two_primary_faces_and_uninvented_printed_body(self):
        package = load_batch()
        row = package['cards'][0]['record']
        self.assertEqual((row['id'], row['cost'], row['attack'], row['health']), (CARD, 8, 5, 5))
        self.assertEqual(len(package['official_observations']), 2)
        self.assertEqual(registry('writer').card(CARD).metadata.tribes, ())

    def test_a01_paid_battlecry_preserves_unequal_counts_original_cards_and_owners(self):
        g = self.game()
        left, right = self.hands(g)
        original = set(left[1:] + right)
        count = len(g.state.entities)
        root = self.play(g)
        now = self.hands(g)
        self.assertEqual(tuple(map(len, now)), (2, 3))
        self.assertEqual(set(now[0] + now[1]), original)
        self.assertEqual(len(g.state.entities), count)
        self.assertIn(root, g.state.players[1].board)
        self.assertEqual(g.state.players[1].mana, 2)
        self.assertTrue(set(now[0]) & set(right))
        self.assertTrue(set(now[1]) & set(left[1:]))
        for pid, hand in enumerate(now, 1):
            for eid in hand:
                self.assertEqual(g.state.entities[eid].controller, pid)
                self.assertEqual(g.state.entities[eid].owner, 1 if eid in left else 2)
        self.no_draw_burn_copy(g)
        self.portable(g)

    def test_a02_second_player_and_duplicate_printed_faces_keep_every_physical_copy(self):
        g = self.game(hand=(A,) * 4, enemy_hand=(CARD, A, A), active=2)
        originals = set(g.state.players[1].hand + g.state.players[2].hand[1:])
        enemy_old = set(g.state.players[1].hand)
        self.play(g)
        now = self.hands(g)
        self.assertEqual(tuple(map(len, now)), (4, 2))
        self.assertEqual(set(now[0] + now[1]), originals)
        self.assertEqual(len(set(now[0] + now[1])), 6)
        self.assertTrue(set(now[1]) & enemy_old)
        self.no_draw_burn_copy(g)
        self.portable(g)

    def test_a03_two_full_hands_exchange_reserved_slots_without_order_dependent_burns(self):
        for capacity in (4, 10):
            with self.subTest(capacity=capacity):
                g = self.game((FULL,) + (A,) * (capacity - 1), enemy_hand=(B,) * capacity, capacity=capacity)
                self.play(g, FULL)
                self.assertEqual(tuple(map(len, self.hands(g))), (capacity, capacity))
                self.assertEqual(len(set(sum(self.hands(g), ()))), capacity * 2)
                self.no_draw_burn_copy(g)
                self.portable(g)

    def test_a04_held_excess_after_capacity_reduction_retains_its_existing_slot_quota(self):
        g = self.game((CARD, RESIZE, A, B), enemy_hand=(A, B, C))
        self.play(g, RESIZE)
        self.play(g)
        self.assertEqual(tuple(map(len, self.hands(g))), (2, 3))
        self.assertEqual((g.state.players[1].hand_cap, g.state.players[2].hand_cap), (1, 1))
        self.no_draw_burn_copy(g)
        self.portable(g)

    def test_a05_zero_or_one_total_card_has_no_random_or_acquisition_work(self):
        for enemy in ((), (B,)):
            with self.subTest(enemy=enemy):
                g = self.game((CARD,), enemy_hand=enemy)
                rng = g._rng.getstate()
                entries = len(g.state.hand_entries)
                self.play(g)
                self.assertFalse(g.state.players[1].hand)
                self.assertEqual(len(g.state.players[2].hand), len(enemy))
                self.assertEqual(g._rng.getstate(), rng)
                self.assertEqual(len(g.state.hand_entries), entries)
                self.assertFalse(any(e.kind == 'hand_reordered' for e in g.events))

    def test_a06_single_nonempty_hand_reorders_without_fabricating_new_entries(self):
        g = self.game((CARD,), enemy_hand=(A, B, C))
        old = self.hands(g)[1]
        old_entries = {i: g.state.entities[i].hand_entry_id for i in old}
        rng = g._rng.getstate()
        self.play(g)
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(set(g.state.players[2].hand), set(old))
        self.assertNotEqual(tuple(g.state.players[2].hand), old)
        self.assertEqual({i: g.state.entities[i].hand_entry_id for i in old}, old_entries)
        self.assertNotEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_b00_only_crossing_cards_receive_new_acquisitions_and_residence_epochs(self):
        g = self.game()
        before = {i: (g.state.entities[i].controller, g.state.entities[i].zone_epoch,
            g.state.entities[i].hand_entry_id) for i in sum(self.hands(g), ())}
        entries = len(g.state.hand_entries)
        root = self.play(g)
        crossed = []
        for eid, (pid, epoch, entry) in before.items():
            if eid == root:
                continue
            e = g.state.entities[eid]
            if e.controller == pid:
                self.assertEqual((e.zone_epoch, e.hand_entry_id), (epoch, entry))
            else:
                crossed.append(eid)
                self.assertEqual(e.zone_epoch, epoch + 1)
                self.assertGreater(e.hand_entry_id, entries)
                self.assertEqual(hand_entry(g.state, e.hand_entry_id).from_zone, Zone.HAND)
        self.assertEqual(len(g.state.hand_entries) - entries, len(crossed))
        self.assertEqual(len([e for e in g.events if e.kind == 'card_moved_to_hand']), len(crossed))

    def test_b01_current_hand_enchantments_costs_and_original_physical_material_are_preserved(self):
        from hs_sim.engine.costs import local_cost
        g = self.game((BUFF, CARD, A, B))
        target = g.state.players[2].hand[-1]
        self.play(g, BUFF)
        before = asdict(g.state.entities[target])
        price = local_cost(g.state.entities[target])[0]
        self.play(g)
        after = asdict(g.state.entities[target])
        for key in ('controller', 'zone_epoch', 'hand_entry_id'):
            before.pop(key)
            after.pop(key)
        self.assertEqual(after, before)
        self.assertEqual(local_cost(g.state.entities[target])[0], price)
        self.portable(g)

    def test_b02_random_hidden_positions_retire_all_old_handles_and_opponent_knowledge(self):
        g = self.game((REVEAL, CARD, A, B))
        self.play(g, REVEAL)
        participants = set(sum(self.hands(g), ())) - {
            i for i in g.state.players[1].hand if g.state.entities[i].card_id == CARD}
        old = {pid: {eid: g._information.players[pid].refs[str(eid)] for eid in participants} for pid in (1, 2)}
        self.play(g)
        for pid in (1, 2):
            knowledge = g._information.players[pid]
            self.assertTrue(all(knowledge.refs[str(eid)] != old[pid][eid] for eid in participants))
            self.assertTrue(all(str(eid) not in knowledge.known for eid in g.state.players[3 - pid].hand))
            view = g.for_player(pid).observe()['observation']
            other = view['players'][2 - pid]
            self.assertTrue(all(x['card_id'] is None for x in other['hand']))
            wire = json.dumps(view) + json.dumps(g.player_events(pid))
            for key in ('"hand_entries"', '"hand_entry_id"', '"zone_epoch"', '"rng_state"'):
                self.assertNotIn(key, wire)
        self.portable(g)

    def test_b03_real_rat_burglar_takes_only_cards_actually_transferred_to_the_opponent(self):
        g = self.game(board=('JAIL_205',))
        original_own = set(g.state.players[1].hand[1:])
        self.play(g)
        own = tuple(g.state.players[1].hand)
        take = tuple(i for i in g.state.players[2].hand if i in original_own)
        retained = tuple(i for i in g.state.players[2].hand if i not in original_own)
        self.assertTrue(take)
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand, list(own + take))
        self.assertTrue(all(i in g.state.players[2].hand for i in retained))
        self.portable(g)

    def test_b04_real_full_then_empty_quest_never_observes_an_artificial_empty_hand(self):
        g = self.game((QUEST, CARD, FILL) + (A,) * 7)
        quest = self.play(g, QUEST)
        self.play(g, FILL)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(g.state.entities[quest].quest_progress.value, 1)
        self.play(g)
        self.assertEqual(len(g.state.players[1].hand), 9)
        self.assertEqual(g.state.entities[quest].quest_progress.value, 1)
        self.assertIn(quest, g.state.players[1].quests)
        self.portable(g)

    def test_c00_real_native_shifter_transfers_and_runs_at_its_new_holder_start(self):
        g, eid = self.source_game('TIME_876', True)
        old = next(a for a in g.state.entities[eid].abilities if a.kind == 'defining_hand_source')
        self.play(g)
        e = g.state.entities[eid]
        binding = next(a for a in e.abilities if a.kind == 'defining_hand_source')
        self.assertEqual((e.owner, e.controller), (2, 1))
        self.assertNotEqual(binding.id, old.id)
        self.assertEqual(binding.defining_card_id, 'TIME_876')
        self.portable(g)
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        binding = next(a for a in g.state.entities[eid].abilities if a.kind == 'defining_hand_source')
        self.assertEqual(binding.progress_completions, 1)
        self.assertTrue(all(g.events[int(key.split(':')[1]) - 1].player_id == 1 for key in binding.progress_keys))
        self.portable(g)

    def test_c01_retained_native_shifter_keeps_source_identity_and_original_acquisition(self):
        g, eid = self.source_game('TIME_876', False)
        before = g.state.entities[eid]
        ability = next(a for a in before.abilities if a.kind == 'defining_hand_source')
        entry, epoch = before.hand_entry_id, before.zone_epoch
        self.play(g)
        now = g.state.entities[eid]
        self.assertEqual((now.controller, now.hand_entry_id, now.zone_epoch), (2, entry, epoch))
        self.assertEqual(next(a for a in now.abilities if a.kind == 'defining_hand_source'), ability)
        self.portable(g)

    def test_c02_real_continuous_mirror_uses_new_opponent_after_batch_allocation(self):
        g, eid = self.source_game('DINO_407', True)
        self.play(g)
        e = g.state.entities[eid]
        ability = next(a for a in e.abilities if a.kind == 'hand_mirror')
        self.assertEqual((e.owner, e.controller), (2, 1))
        self.assertEqual((e.card_id, ability.hand_mirror.player_id, ability.hand_mirror.play_id), ('DINO_407', 1, None))
        self.portable(g)

    def test_c03_passive_summon_does_not_invent_a_battlecry(self):
        g = self.game((PASS, A), board=(CARD,))
        old = tuple(g.state.players[2].hand)
        rng = g._rng.getstate()
        self.play(g, PASS)
        self.assertEqual(tuple(g.state.players[2].hand), old)
        self.assertEqual(g._rng.getstate(), rng)
        self.assertFalse(any(e.kind == 'hand_reordered' for e in g.events))

    def test_c04_real_shifter_keeps_duplicate_hand_minions_as_distinct_random_candidates(self):
        g = self.game(('TIME_876',), enemy_hand=(A, A, B))
        eid = g.state.players[1].hand[0]
        g.apply(EndTurn(1))
        candidates = tuple(g.state.players[2].hand)
        self.assertEqual([g.state.entities[i].card_id for i in candidates], [A, A, B, B])
        rng = Random()
        rng.setstate(g._rng.getstate())
        expected = g.state.entities[rng.sample(candidates, 1)[0]].card_id
        g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[eid].card_id, expected)
        self.assertEqual(g._rng.getstate(), rng.getstate())
        self.portable(g)

    def test_d00_pending_before_mix_restores_typed_effect_and_only_then_consumes_randomness(self):
        g = self.game((WAIT_BEFORE, A, B))
        rng = g._rng.getstate()
        self.play(g, WAIT_BEFORE)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g._rng.getstate(), rng)
        other = self.portable(g)
        for game in (g, other):
            q = game.state.pending_choice
            game.apply(SelectChoice(q.player_id, q.id, ('ok',)))
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertNotEqual(g._rng.getstate(), rng)
        self.assertEqual(tuple(map(len, self.hands(g))), (2, 3))

    def test_d01_pending_after_mix_sees_complete_hands_and_never_shuffles_again(self):
        g = self.game(board=(WATCH,))
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(tuple(map(len, self.hands(g))), (2, 3))
        other = self.portable(g)
        before = g.snapshot()
        q = g.state.pending_choice
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(q.player_id, q.id, ('fail',)))
        self.assertEqual(g.snapshot(), before)
        rng, hands, entries = g._rng.getstate(), self.hands(g), len(g.state.hand_entries)
        for game in (g, other):
            q = game.state.pending_choice
            game.apply(SelectChoice(q.player_id, q.id, ('ok',)))
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g._rng.getstate(), self.hands(g), len(g.state.hand_entries)), (rng, hands, entries))

    def test_d02_late_effect_failure_rolls_back_randomness_cards_knowledge_and_acquisitions(self):
        g = self.game((LATE_FAIL, A, B))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, LATE_FAIL)
        self.assertEqual(g.snapshot(), before)

    def test_d03_transfer_reaction_failure_rolls_back_the_whole_paid_battlecry(self):
        g = self.game(board=(FAIL_WATCH,))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_d04_real_repeat_source_recalculates_the_two_original_hands_and_pays_once(self):
        g = self.game(board=('TIME_064',))
        self.play(g)
        self.assertEqual(len([e for e in g.events if e.kind == 'hand_reordered']), 4)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.players[1].mana, 2)
        self.assertEqual(tuple(map(len, self.hands(g))), (2, 3))
        self.portable(g)

    def test_e00_invalid_requests_and_unknown_source_never_start_random_work(self):
        for args in ((True, 1), (0, 1), (1, True), (1, 0), (1, None)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ShuffleHandsTogether(*args)
        g = self.game((UNKNOWN, A, B))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, UNKNOWN)
        self.assertEqual(g.snapshot(), before)

    def test_e01_random_guarantees_reject_nonexchange_and_avoidable_identity_permutations(self):
        class Scripted:
            def __init__(self, orders):
                self.orders = iter(orders)
                self.calls = 0
            def shuffle(self, values):
                self.calls += 1
                values[:] = next(self.orders)
        rng = Scripted(((1, 2, 3, 4), (2, 1, 4, 3), (3, 1, 4, 2)))
        self.assertEqual(mixed_order(rng, (1, 2), (3, 4)), (3, 1, 4, 2))
        self.assertEqual(rng.calls, 3)
        rng = Scripted(((1, 2), (2, 1)))
        self.assertEqual(mixed_order(rng, (), (1, 2)), (2, 1))
        rng = Scripted(())
        self.assertEqual(mixed_order(rng, (), (1,)), (1,))
        self.assertEqual(rng.calls, 0)


if __name__ == '__main__':
    unittest.main()
