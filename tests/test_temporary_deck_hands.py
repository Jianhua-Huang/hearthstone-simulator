"""One temporary physical deck hand: leases, real start, return and privacy."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CostSpec, EndTurn, Game, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, ModifyCost, RequestChoice, ReturnToHand)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.hand_upgrades import UpgradeHandCard
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.temporary_hands import ReturnTemporaryHand, validate_boundary
from hs_sim.engine.temporary_deck_hands import (ExpireTemporaryDeckHands, ReplaceHandWithTemporaryDeckCards,
    TemporaryDeckHandReplacement, due_start, expire_start)
from hs_sim.engine.turn_scheduling import QueueTurns, SkipTurns
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard, ReorderZone
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

PASSAGE = 'SCH_305'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/temporary-deck-hands.json'
PIN = 'e306aedf519d27c65c47986d83aac1623401f380941bdfbd41033a3f5cb7e1e8'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete temporary deck hand raw changed')
    for row in raw['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Temporary deck hand original row changed')
    return raw


def registry(scripts=(), watch=None, fault=False):
    r = opening_registry(); row = evidence()['records'][0]['data']
    def passage(c):
        work = (ReplaceHandWithTemporaryDeckCards(c.player_id, 4, c.source_id),)
        return work + ((AddToDeck(1, 'card.1'), AddToHand(1, 'missing.after.passage')) if fault else ())
    r.register_behavior('passage', passage)
    r.register_card(CardDefinition(PASSAGE, row['name'], CardType.SPELL, cost=row['cost'], on_play='passage',
        metadata=metadata(CardClass.ROGUE, rarity=Rarity.EPIC)))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    if watch:
        event, card_id, callback = watch
        def filtered(c):
            if c.event.player_id != 1:
                return ()
            if card_id is not None and (c.event.target_id is None or c.state.entities[c.event.target_id].card_id != card_id):
                return ()
            return callback(c)
        r.register_behavior('watch', filtered)
        r.register_card(CardDefinition('watch', 'watch', CardType.MINION, health=4,
            triggers=(TriggerSpec(event, 'watch'),), metadata=metadata()))
    return r


def expire_probe(r, work):
    due = due_start(r.state)
    if not due:
        return expire_start(r, work)
    # A trusted test handler pauses before the existing private return work.
    # Its repeat sees completed history, so there is no hidden mutable counter.
    source = r.state.temporary_hands[due[-1] - 1].request.source_id
    return [RequestChoice(r.state.active_player, (ChoiceOption('go', 'Continue'),), source), *expire_start(r, work)]


def mechanics(probe=False):
    value = default_mechanics('temporary-deck-start-probe-v1' if probe else CORE_EFFECTS_VERSION)
    if probe:
        value._handlers[ExpireTemporaryDeckHands] = expire_probe
    return value


class TemporaryDeckHandTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []; self.options = {}; self.probe = False
    def script(self, name, callback):
        self.scripts.append((name, callback))
    def game(self, hand=(PASSAGE, 'card.1', 'card.2'), deck=('card.3', 'card.4', 'card.5', 'card.6', 'card.7', 'card.8'), board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', deck=('card.20',) * 8, mana=10, max_mana=10)), seed=79),
            registry(self.scripts, **self.options), mechanics=mechanics(self.probe))
    def play(self, g, cid=PASSAGE):
        source = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == cid)
        g.apply(PlayCard(1, source)); return source
    def wait(self, c):
        return (RequestChoice(1, (ChoiceOption('go', 'Continue'),), c.source_id),)
    def watch(self, event='turn_started', card=None, callback=None):
        self.options['watch'] = (event, card, callback or self.wait)
    def next_owner(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
    def choose(self, g):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, ('go',)))
    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(self.scripts, **self.options), mechanics=mechanics(self.probe))
        self.assertEqual(restored.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options), mechanics=mechanics(self.probe)).snapshot(), saved)
        return restored
    def invalid(self, g, change):
        bad = self.portable(g)
        with self.assertRaises(ValueError):
            change(bad); validate_boundary(bad)

    def test_real_passage_moves_four_original_deck_entities_and_saves_remaining_hand(self):
        g = self.game(); held = tuple(g.state.players[1].hand[1:]); deck = tuple(g.state.players[1].deck)
        source = self.play(g); root = g.state.temporary_hands[0]
        self.assertIsInstance(root, TemporaryDeckHandReplacement); self.assertEqual(root.request.source_id, source)
        self.assertEqual(tuple(ref.entity_id for ref in root.originals), held)
        self.assertEqual(set(g.state.players[1].hand) | set(g.state.players[1].deck), set(deck))
        self.assertEqual(len(root.borrowed), 4); self.assertEqual(g.state.players[1].mana, 8)
        self.assertTrue(all(g.state.entities[eid].zone == Zone.SETASIDE for eid in held))
        self.assertTrue(all(g.state.entities[eid].origin_entity_id is None for eid in g.state.players[1].hand))
        self.assertFalse(g.state.draw_history); self.assertFalse(g.state.death_history); self.portable(g)

    def test_full_raw_keeps_five_rows_but_only_real_spell_is_executable(self):
        raw = evidence(); extracted = {row['id']: row for row in json.loads((FIXTURE.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8'))}
        self.assertEqual(len(raw['records']), 5)
        for row in raw['records']:
            self.assertEqual(row['data'], extracted[row['id']])
        self.assertEqual(raw['records'][0]['data']['cost'], 2)
        self.assertIn('4 cards', raw['records'][0]['data']['text_en'])
        self.assertTrue(all(row['id'] not in registry().cards for row in raw['records'][1:]))

    def test_temporary_hand_stays_during_opponent_turn_then_returns_before_start_draw(self):
        self.watch(); g = self.game(board=('watch',)); held = tuple(g.state.players[1].hand[1:]); self.play(g)
        borrowed = tuple(g.state.players[1].hand); g.apply(EndTurn(1))
        self.assertEqual(tuple(g.state.players[1].hand), borrowed); self.assertEqual(g.state.temporary_hands[0].phase, 'active')
        g.apply(EndTurn(2)); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(tuple(g.state.players[1].hand), held); self.assertEqual(g.state.temporary_hands[0].phase, 'completed')
        self.assertTrue(set(borrowed) <= set(g.state.players[1].deck))
        self.assertEqual([row.player_id for row in g.state.draw_history], [2]); self.portable(g)

    def test_second_seat_uses_its_own_physical_hand_deck_and_start_clock(self):
        g = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=('card.10',), deck=('card.20',) * 5),
            PlayerSetup('warrior.hero', hand=(PASSAGE, 'card.1', 'card.2'), deck=('card.3', 'card.4', 'card.5', 'card.6'),
                        mana=10, max_mana=10)), active_player=2, seed=79), registry(), mechanics=mechanics())
        held = tuple(g.state.players[2].hand[1:]); other_hand = tuple(g.state.players[1].hand)
        g.apply(PlayCard(2, g.state.players[2].hand[0])); root = g.state.temporary_hands[0]
        self.assertEqual(root.request.player_id, 2); self.assertEqual(tuple(g.state.players[1].hand), other_hand)
        g.apply(EndTurn(2)); self.assertEqual(g.state.temporary_hands[0].phase, 'active')
        g.apply(EndTurn(1)); self.assertEqual(g.state.temporary_hands[0].returned, held)
        self.assertEqual(tuple(g.state.players[2].hand[:2]), held); self.portable(g)

    def test_empty_deck_still_saves_originals_without_sampling_or_fatigue(self):
        g = self.game(deck=()); before = g._rng.getstate(); self.play(g)
        self.assertFalse(g.state.players[1].hand); self.assertFalse(g.state.temporary_hands[0].borrowed)
        self.assertEqual(g._rng.getstate(), before); self.assertFalse(g.state.draw_history); self.portable(g)

    def test_short_deck_moves_all_distinct_physical_cards_without_replacements(self):
        g = self.game(deck=('card.3', 'card.3')); originals = tuple(g.state.players[1].deck); self.play(g)
        self.assertEqual(set(g.state.players[1].hand), set(originals)); self.assertEqual(len(set(g.state.players[1].hand)), 2)
        self.assertFalse(g.state.players[1].deck); self.assertFalse(g.state.draw_history); self.portable(g)

    def test_ten_original_hand_cards_do_not_burn_temporary_materialization(self):
        g = self.game(hand=(PASSAGE,) + ('card.1',) * 9); self.play(g)
        self.assertEqual(len(g.state.temporary_hands[0].originals), 9); self.assertEqual(len(g.state.players[1].hand), 4)
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events)); self.portable(g)

    def test_current_original_hand_order_is_saved_after_reordering(self):
        self.script('order', lambda c: (ReorderZone(1, Zone.HAND, tuple(reversed(c.state.players[1].hand))),))
        self.watch(); g = self.game(hand=('order', PASSAGE, 'card.1', 'card.2'), board=('watch',)); self.play(g, 'order')
        held = tuple(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id != PASSAGE)
        self.play(g); self.next_owner(g); self.assertEqual(tuple(g.state.players[1].hand), held); self.portable(g)

    def test_original_and_borrowed_cost_materials_survive_without_copying(self):
        self.script('cost', lambda c: (ModifyCost(c.state.players[1].hand[-1], CostSpec(delta=-1)),
            ModifyCost(c.state.players[1].deck[0], CostSpec(delta=-1))))
        self.watch(); g = self.game(hand=('cost', PASSAGE, 'card.1'), deck=('card.3',), board=('watch',))
        original = g.state.players[1].hand[-1]; borrowed = g.state.players[1].deck[0]
        self.play(g, 'cost'); self.play(g); self.assertEqual(g.state.entities[borrowed].cost, 0)
        self.next_owner(g); self.assertEqual(g.state.entities[original].cost, 0); self.assertEqual(g.state.entities[borrowed].cost, 0); self.portable(g)

    def test_generated_card_is_retained_when_original_borrowed_cards_return(self):
        self.script('add', lambda c: (AddToHand(1, 'card.9'),)); self.watch()
        g = self.game(deck=('add', 'card.3', 'card.4', 'card.5'), board=('watch',)); held = tuple(g.state.players[1].hand[1:])
        self.play(g); self.play(g, 'add'); new = g.state.players[1].hand[-1]; self.next_owner(g)
        self.assertEqual(tuple(g.state.players[1].hand), (new, *held)); self.assertNotIn(new, g.state.temporary_hands[0].removed); self.portable(g)

    def test_later_actual_draw_has_new_acquisition_and_is_retained(self):
        self.script('draw', lambda c: (Draw(1),)); self.watch()
        g = self.game(deck=('draw', 'card.3', 'card.4', 'card.5', 'card.6'), board=('watch',)); self.play(g)
        if not any(g.state.entities[eid].card_id == 'draw' for eid in g.state.players[1].hand):
            self.fail('Pinned seed must select the draw probe')
        self.play(g, 'draw'); drawn = g.state.draw_history[-1].entity_id; self.next_owner(g)
        self.assertIn(drawn, g.state.players[1].hand); self.assertNotIn(drawn, g.state.temporary_hands[0].removed); self.portable(g)

    def test_copy_of_original_borrowed_card_is_retained(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(next(c.state.entities[eid] for eid in c.state.players[1].hand if c.state.entities[eid].card_id == 'card.3')), 1, source_id=c.source_id),))
        self.watch(); g = self.game(deck=('copy', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g)
        original = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.3')
        self.play(g, 'copy'); copy = g.state.players[1].hand[-1]; self.next_owner(g)
        self.assertIn(copy, g.state.players[1].hand); self.assertIn(original, g.state.players[1].deck)
        self.assertNotIn(copy, g.state.temporary_hands[0].removed); self.portable(g)

    def test_played_then_returned_minion_is_not_recaptured_by_old_lease(self):
        self.script('bounce', lambda c: (ReturnToHand(next(eid for eid in c.state.players[1].board if c.state.entities[eid].card_id == 'card.3')),))
        self.watch(); g = self.game(deck=('bounce', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g)
        body = self.play(g, 'card.3'); self.play(g, 'bounce'); self.next_owner(g)
        self.assertIn(body, g.state.players[1].hand); self.assertNotIn(body, g.state.temporary_hands[0].removed); self.portable(g)

    def test_same_entity_moved_out_and_drawn_again_has_a_new_lease(self):
        def move_draw(c):
            entity = next(c.state.entities[eid] for eid in c.state.players[1].hand if c.state.entities[eid].card_id == 'card.3')
            return (MoveCard(CardReference.capture(entity), 1, Zone.DECK, position='top'), Draw(1))
        self.script('move_draw', move_draw); self.watch()
        g = self.game(deck=('move_draw', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g)
        body = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.3')
        self.play(g, 'move_draw'); self.next_owner(g); self.assertIn(body, g.state.players[1].hand)
        self.assertNotIn(body, g.state.temporary_hands[0].removed); self.portable(g)

    def test_played_borrowed_minion_remains_on_board(self):
        self.watch(); g = self.game(deck=('card.3',), board=('watch',)); self.play(g); body = self.play(g, 'card.3')
        self.next_owner(g); self.assertIn(body, g.state.players[1].board); self.assertFalse(g.state.temporary_hands[0].removed); self.portable(g)

    def test_borrowed_face_upgrade_in_the_same_hand_preserves_original_entry_lease(self):
        def upgrade(c):
            entity = next(c.state.entities[eid] for eid in c.state.players[1].hand if c.state.entities[eid].card_id == 'card.3')
            return (UpgradeHandCard(CardReference.capture(entity), 'card.30', c.source_id),)
        self.script('upgrade', upgrade); self.watch()
        g = self.game(deck=('upgrade', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g)
        body = next(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.3')
        entry = g.state.entities[body].hand_entry_id; self.play(g, 'upgrade')
        self.assertEqual(g.state.entities[body].hand_entry_id, entry); self.next_owner(g)
        self.assertIn(body, g.state.players[1].deck); self.assertIn(body, g.state.temporary_hands[0].removed)
        self.assertEqual(g.state.entities[body].card_id, 'card.30'); self.portable(g)

    def test_empty_original_hand_still_returns_borrowed_cards_before_default_draw(self):
        self.watch(); g = self.game(hand=(PASSAGE,), board=('watch',)); self.play(g); self.next_owner(g)
        self.assertFalse(g.state.players[1].hand); self.assertFalse(g.state.temporary_hands[0].returned)
        self.assertEqual(len(g.state.temporary_hands[0].removed), 4); self.portable(g)

    def test_same_mechanism_twice_keeps_parent_lease_across_private_child_storage(self):
        self.watch(); g = self.game(deck=(PASSAGE, 'card.3', 'card.4', 'card.5'), board=('watch',)); held = tuple(g.state.players[1].hand[1:])
        self.play(g); self.play(g); self.next_owner(g)
        self.assertEqual(tuple(g.state.players[1].hand), held)
        first, second = g.state.temporary_hands; self.assertEqual(len(first.removed), 3); self.assertFalse(second.borrowed)
        self.assertEqual([dict(e.data)['hand_id'] for e in g.events if e.kind == 'temporary_deck_hand_restored'], [2, 1]); self.portable(g)

    def test_retained_cards_take_capacity_and_original_overflow_uses_ordinary_burn(self):
        self.script('fill', lambda c: tuple(AddToHand(1, 'card.9') for _ in range(7))); self.watch()
        g = self.game(hand=(PASSAGE, 'card.1', 'card.2', 'card.10', 'card.11', 'card.12'),
                      deck=('fill', 'card.3', 'card.4', 'card.5'), board=('watch',)); originals = tuple(g.state.players[1].hand[1:])
        self.play(g); self.play(g, 'fill'); retained = tuple(eid for eid in g.state.players[1].hand if g.state.entities[eid].card_id == 'card.9')
        self.next_owner(g); root = g.state.temporary_hands[0]
        self.assertEqual(root.returned, originals[:3]); self.assertEqual(root.burned, originals[3:])
        self.assertEqual(tuple(g.state.players[1].hand), (*retained, *originals[:3])); self.assertFalse(g.state.death_history); self.portable(g)

    def test_no_remaining_borrowed_card_does_not_shuffle_or_consume_rng_at_return(self):
        self.script('consume', lambda c: ()); self.watch(); g = self.game(deck=('consume',) * 4, board=('watch',)); self.play(g)
        for _ in range(4): self.play(g, 'consume')
        before = g._rng.getstate(); self.next_owner(g); root = g.state.temporary_hands[0]
        self.assertFalse(root.removed); self.assertEqual(root.return_rng_before, root.return_rng_after)
        self.assertEqual(g._rng.getstate(), before); self.assertFalse(any(e.kind == 'deck_shuffled' for e in g.events)); self.portable(g)

    def test_deadline_waits_for_actual_owner_start_after_extra_opponent_turn(self):
        self.script('queue', lambda c: (QueueTurns((2,), c.source_id),)); self.watch()
        g = self.game(deck=('queue', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g); self.play(g, 'queue')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual((g.state.turn, g.state.active_player), (3, 2))
        self.assertEqual(g.state.temporary_hands[0].phase, 'active'); self.portable(g)
        g.apply(EndTurn(2)); self.assertEqual((g.state.turn, g.state.active_player), (4, 1))
        self.assertEqual(g.state.temporary_hands[0].phase, 'completed'); self.portable(g)

    def test_skipped_owner_slot_does_not_expire_before_real_owner_start(self):
        self.script('skip', lambda c: (SkipTurns(1, 1, c.source_id),)); self.watch()
        g = self.game(deck=('skip', 'card.3', 'card.4', 'card.5'), board=('watch',)); self.play(g); self.play(g, 'skip')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.assertEqual(g.state.active_player, 2)
        self.assertEqual(g.state.temporary_hands[0].phase, 'active'); self.portable(g)
        g.apply(EndTurn(2)); self.assertEqual(g.state.temporary_hands[0].phase, 'completed'); self.portable(g)

    def test_materialization_wait_restores_all_original_candidates_without_resampling(self):
        self.watch('card_moved_to_hand', 'card.3'); g = self.game(deck=('card.3', 'card.4'), board=('watch',)); self.play(g)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_start_publication_wait_restores_before_default_draw_once(self):
        self.watch(); g = self.game(board=('watch',)); self.play(g); self.next_owner(g); restored = self.portable(g)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual([row.player_id for row in g.state.draw_history], [2, 1]); self.portable(g)

    def test_private_return_wait_keeps_complete_due_work_and_fresh_restore(self):
        self.probe = True; g = self.game(); self.play(g); self.next_owner(g)
        self.assertIsNotNone(g.state.pending_choice); self.assertEqual(g.state.temporary_hands[0].phase, 'active')
        restored = self.portable(g); self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_actual_start_continuation_cannot_lose_expiry_or_publication(self):
        self.probe = True; g = self.game(); self.play(g); self.next_owner(g)
        def cut(bad):
            bad._frame = replace(bad._frame, prefix=tuple(w for w in bad._frame.prefix if type(w) is not ExpireTemporaryDeckHands),
                continuation=tuple(w for w in bad._frame.continuation if type(w) is not ExpireTemporaryDeckHands))
        self.invalid(g, cut)
        def cut_publication(bad):
            from hs_sim.engine.resolver import BeginTurnEvents
            bad._frame = replace(bad._frame, prefix=tuple(w for w in bad._frame.prefix if type(w) is not BeginTurnEvents),
                continuation=tuple(w for w in bad._frame.continuation if type(w) is not BeginTurnEvents))
        self.invalid(g, cut_publication)

    def test_original_return_shuffle_receipt_cannot_change_deck_order(self):
        self.watch(); g = self.game(board=('watch',)); self.play(g); self.next_owner(g)
        self.invalid(g, lambda bad: bad._state.temporary_hands.__setitem__(0,
            replace(bad._state.temporary_hands[0], return_deck_after=tuple(reversed(bad._state.temporary_hands[0].return_deck_after)))))

    def test_late_acceptance_failure_rolls_back_payment_originals_sampling_and_rng(self):
        self.options['fault'] = True; g = self.game(); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.after.passage'): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_return_reaction_failure_rolls_back_entire_start_and_shuffle(self):
        self.watch('card_moved_to_hand', 'card.1', lambda c: (AddToDeck(1, 'card.1'), AddToHand(1, 'missing.after.return')))
        g = self.game(board=('watch',)); self.play(g); g.apply(EndTurn(1)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.after.return'): g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(), before)

    def test_terminal_game_marks_saved_group_ended_and_leaves_originals_private(self):
        self.script('lethal', lambda c: (Damage(c.state.players[2].hero_id, 30, c.source_id),))
        g = self.game(deck=('lethal',)); self.play(g); self.play(g, 'lethal')
        self.assertEqual(g.state.status, 'finished'); self.assertEqual(g.state.temporary_hands[0].phase, 'ended'); self.portable(g)

    def test_private_return_before_next_start_is_rejected(self):
        self.script('early', lambda c: (ReturnTemporaryHand(1),)); g = self.game(deck=('early',)); self.play(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'genuine next owner start'): self.play(g, 'early')
        self.assertEqual(g.snapshot(), before)

    def test_invalid_count_owner_bool_and_missing_source_are_rejected(self):
        for args in ((True, 4, 1), (1, True, 1), (1, -1, 1), (1, 4, False)):
            with self.subTest(args=args), self.assertRaises(ValueError): ReplaceHandWithTemporaryDeckCards(*args)
        for name, request in (('wrong', lambda c: ReplaceHandWithTemporaryDeckCards(2, 4, c.source_id)),
                              ('large', lambda c: ReplaceHandWithTemporaryDeckCards(1, 11, c.source_id)),
                              ('missing', lambda c: ReplaceHandWithTemporaryDeckCards(1, 4, 999999))):
            self.script(name, lambda c, request=request: (request(c),)); g = self.game(hand=(name,)); before = g.snapshot()
            with self.subTest(name=name), self.assertRaises(ResolutionError): self.play(g, name)
            self.assertEqual(g.snapshot(), before)

    def test_original_acceptance_sampling_and_creation_interval_cannot_be_changed(self):
        g = self.game(); self.play(g)
        self.invalid(g, lambda bad: bad._state.temporary_hands.__setitem__(0,
            replace(bad._state.temporary_hands[0], deck_basis=tuple(reversed(bad._state.temporary_hands[0].deck_basis)))))
        self.invalid(g, lambda bad: bad._state.temporary_hands.__setitem__(0,
            replace(bad._state.temporary_hands[0], owner_turn_id=999999)))

    def test_entire_history_and_original_acquisition_cannot_be_lost(self):
        g = self.game(); self.play(g)
        self.invalid(g, lambda bad: bad._state.temporary_hands.clear())
        def acquisition(bad):
            root = bad._state.temporary_hands[0]
            bad._state.temporary_hands[0] = replace(root, borrowed=(replace(root.borrowed[0], hand_entry_id=root.originals[0].hand_entry_id), *root.borrowed[1:]))
        self.invalid(g, acquisition)

    def test_schema165_rejects_previous_engine_and_malformed_union_record(self):
        g = self.game(); self.play(g); saved = g.snapshot()
        self.assertEqual((saved['schema_version'], g.ruleset.id, g.mechanics.version), (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        for version in (1, 163, 164, 217, True):
            bad = json.loads(json.dumps(saved)); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
        bad = json.loads(json.dumps(saved)); bad['state']['temporary_hands'][0]['request']['source_player_id'] = 2
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_players_never_receive_private_originals_candidate_basis_or_rng_receipts(self):
        g = self.game(); self.play(g); before = g.snapshot()
        for player in (1, 2):
            view = json.dumps(g.observe(player)); events = g.player_events(player)
            self.assertNotIn('"card.1"', view)
            for key in ('temporary_hands', 'deck_basis', 'rng_before', 'owner_turn_id', 'originals', 'borrowed', 'SETASIDE'):
                self.assertNotIn(key, view)
            self.assertFalse(any(row['kind'].startswith('temporary_deck_hand_') for row in events))
        self.assertEqual(g.snapshot(), before); self.portable(g)


if __name__ == '__main__':
    unittest.main()
