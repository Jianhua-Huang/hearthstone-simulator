"""Real hand/deck consumers, original physical operands and ordinary recovery."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.native_past_entry_grant_cards import FLASHBACK, POOL_ID
from hs_sim.cards.past_hand_deck_movement_cards import INSPECTOR, FINLEY, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    EndTurn, Game, PlayerSetup, Scenario, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Draw, InvokeBehavior,
    ModifyCost, RequestChoice, RevealHandCard)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.zones import CardReference, MoveCard, ReorderZone

P = 'k474.'
LOW, HIGH, ZERO, SPELL, NOOP, DISCOUNT, LOCAL, REVERSE, REVEAL, STEAL, WATCH, FAIL = (
    P+s for s in ('low', 'high', 'zero', 'spell', 'noop', 'discount', 'local', 'reverse', 'reveal', 'steal', 'watch', 'fail'))
CONTEXT = GenerationContext('k474-finite-only-two-hand-deck-leaves', 'experimental')
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=(), factions=(), subtypes=())


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version = 'k474-'+mode
    for cid, cost in ((LOW, 2), (HIGH, 8), (ZERO, 0)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=1, health=5, metadata=META))
    r.register_behavior(SPELL, lambda c: ())
    r.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, cost=3, on_play=SPELL, metadata=META))
    def own(c, cid): return next(c.state.entities[eid] for eid in c.state.players[c.player_id].hand
        if c.state.entities[eid].card_id == cid)
    def fail(c): raise ResolutionError('K474 deliberate late original movement failure')
    def local(c):
        hand = own(c, HIGH)
        deck = c.state.entities[c.state.players[c.player_id].deck[-1]]
        return (ModifyCost(hand.id, CostSpec(set_to=0), c.source_id),
            ModifyCost(deck.id, CostSpec(delta=-1), c.source_id))
    scripts = {
        NOOP: lambda c: (),
        DISCOUNT: lambda c: (AddCostModifier(c.player_id, CostSpec(set_to=0, card_ids=(HIGH,)),
            uses_remaining=1, source_id=c.source_id),),
        LOCAL: local,
        REVERSE: lambda c: (ReorderZone(c.player_id, Zone.HAND,
            tuple(reversed(c.state.players[c.player_id].hand))),),
        REVEAL: lambda c: (RevealHandCard(own(c, HIGH).id),),
        STEAL: lambda c: (MoveCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]),
            c.player_id, Zone.HAND, source_id=c.source_id),),
        FAIL: fail,
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META))
    def watch(c):
        e = c.event
        event = {'start_wait':'battlecry_started', 'shuffle_wait':'card_moved_to_deck',
            'exit_wait':'card_moved_to_deck', 'entry_wait':'card_moved_to_hand',
            'draw_fail':'card_drawn', 'entry_fail':'card_moved_to_hand'}.get(mode)
        if e.kind != event: return ()
        if e.kind == 'battlecry_started' and c.state.entities[e.source_id].card_id not in (INSPECTOR, FINLEY): return ()
        if mode in ('draw_fail', 'entry_fail'): return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        # Wait once on the first relevant publication; later captured moves
        # continue normally and retain their original physical references.
        if e.kind == 'card_moved_to_deck' and c.state.entities[e.target_id].card_id != HIGH: return ()
        if e.kind == 'card_moved_to_hand' and c.state.entities[e.target_id].card_id != ZERO: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=META,
        triggers=tuple(TriggerSpec(e, WATCH) for e in ('battlecry_started', 'card_moved_to_deck',
            'card_moved_to_hand', 'card_drawn'))))
    r.register_pool(PoolDefinition(POOL_ID, 'k474-bounded-two-real-leaves', CONTEXT.target_id,
        CONTEXT.mode, (PoolMember(INSPECTOR), PoolMember(FINLEY)), complete=True))
    r.validate(); return r


class PastHandDeckMovementTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), *, deck=(HIGH, LOW, ZERO), board=(), enemy_hand=(), mode='normal', seed=474):
        self.mode = mode
        if mode != 'normal': board = (*board, WATCH)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=hand, deck=deck, board=board, mana=20, max_mana=20, mana_cap=20),
            PlayerSetup('HERO_08', hand=enemy_hand, deck=(LOW,)*5, mana=20, max_mana=20, mana_cap=20)),
            seed=seed, generation_context=CONTEXT), fixture(mode))

    def no_draw(self, g):
        self.assertFalse(g.state.draw_history)
        self.assertFalse(any(e.kind in ('card_drawn', 'card_discarded', 'card_destroyed_in_deck', 'fatigue') for e in g.events))
    def first_shuffle(self, g): return g.state.deck_shuffle_history[0].first_card.entity_id

    def test_two_complete_original_rows_four_strict_primary_faces_and_all_native_stats(self):
        data = load_batch(); rows = {x['record']['id']:x['record'] for x in data['dependencies']}
        self.assertEqual((set(rows), len(data['official_observations'])), ({INSPECTOR, FINLEY}, 4))
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']), face['response_sha256'])
            batch.check_face(rows[face['card_id']], face['face'], face['locale'])
        for cid in rows:
            card = fixture().card(cid); self.assertEqual((card.cost, card.attack, card.health), (1, 1, 3))
            self.assertIsNotNone(card.battlecry)
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])

    def test_inspector_real_entry_selects_only_lowest_remaining_physical_card_and_pays_once(self):
        g = self.game((INSPECTOR, LOW, HIGH)); chosen = self.entity(g, LOW).id
        source = self.play(g, INSPECTOR)
        self.assertEqual(self.first_shuffle(g), chosen)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].board), (19, [source]))
        self.assertEqual((len(g.state.deck_shuffle_history), len(g.state.draw_history)), (1, 1))
        self.assertEqual(g.state.deck_shuffle_history[0].source.entity_id, source)

    def test_inspector_empty_remaining_hand_still_draws_without_shuffle_or_rng(self):
        g = self.game((INSPECTOR,)); top = g.state.players[1].deck[0]; rng = g._rng.getstate()
        self.play(g, INSPECTOR); self.assertEqual(g.state.players[1].hand, [top])
        self.assertFalse(g.state.deck_shuffle_history); self.assertEqual(g._rng.getstate(), rng)

    def test_inspector_empty_hand_and_deck_still_attempts_draw_and_fatigues(self):
        g = self.game((INSPECTOR,), deck=()); self.play(g, INSPECTOR)
        self.assertFalse(g.state.deck_shuffle_history); self.assertEqual(g.state.players[1].fatigue, 1)

    def test_inspector_empty_deck_shuffles_and_draws_back_the_same_physical_card(self):
        g = self.game((INSPECTOR, LOW), deck=()); original = self.entity(g, LOW).id
        epoch = g.state.entities[original].zone_epoch; self.play(g, INSPECTOR)
        self.assertEqual(g.state.players[1].hand, [original]); self.assertFalse(g.state.players[1].deck)
        self.assertEqual(g.state.entities[original].zone_epoch, epoch+2)

    def test_inspector_current_local_cost_beats_printed_cost(self):
        g = self.game((LOCAL, INSPECTOR, HIGH, LOW)); chosen = self.entity(g, HIGH).id
        self.play(g, LOCAL); self.play(g, INSPECTOR); self.assertEqual(self.first_shuffle(g), chosen)

    def test_inspector_external_one_use_cost_quote_is_not_consumed_by_comparison(self):
        g = self.game((DISCOUNT, INSPECTOR, HIGH, LOW)); chosen = self.entity(g, HIGH).id
        self.play(g, DISCOUNT); self.play(g, INSPECTOR)
        self.assertEqual(self.first_shuffle(g), chosen)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)

    def test_inspector_unique_minimum_only_consumes_original_random_insertion_rng(self):
        g = self.game((INSPECTOR, LOW, HIGH)); rng = Random(); rng.setstate(g._rng.getstate())
        rng.randrange(len(g.state.players[1].deck)+1); self.play(g, INSPECTOR)
        self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_inspector_tied_minimum_samples_physical_cards_once_before_original_insertion(self):
        g = self.game((INSPECTOR, LOW, LOW, HIGH)); candidates = tuple(g.state.players[1].hand[1:3])
        rng = Random(); rng.setstate(g._rng.getstate()); chosen = rng.choice(candidates)
        rng.randrange(len(g.state.players[1].deck)+1); self.play(g, INSPECTOR)
        self.assertEqual(self.first_shuffle(g), chosen); self.assertEqual(g._rng.getstate(), rng.getstate())

    def test_inspector_compares_spells_and_weapons_as_well_as_minions(self):
        g = self.game((INSPECTOR, SPELL, 'CS2_106', HIGH)); chosen = self.entity(g, 'CS2_106').id
        self.play(g, INSPECTOR); self.assertEqual(self.first_shuffle(g), chosen)

    def test_inspector_shuffle_is_not_discard_death_or_destruction(self):
        g = self.game((INSPECTOR, LOW)); self.play(g, INSPECTOR)
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind in ('card_discarded', 'card_destroyed_in_deck') for e in g.events))

    def test_inspector_benefits_actual_opponent_controller_and_leaves_my_cards_alone(self):
        g = self.game((HIGH,), enemy_hand=(INSPECTOR, LOW)); own = tuple(g.state.players[1].hand)
        g.apply(EndTurn(1)); self.play(g, INSPECTOR, player=2)
        self.assertEqual(tuple(g.state.players[1].hand), own)
        self.assertEqual(g.state.deck_shuffle_history[-1].player_id, 2)

    def test_real_brann_repeats_inspector_on_the_new_hand_but_pays_once(self):
        g = self.game((INSPECTOR, LOW), deck=(), board=('LOE_077',)); physical = self.entity(g, LOW).id
        self.play(g, INSPECTOR); self.assertEqual(g.state.players[1].hand, [physical])
        self.assertEqual((len(g.state.deck_shuffle_history), len(g.state.draw_history), g.state.players[1].mana), (2, 2, 19))

    def test_inspector_full_deck_uses_original_failed_admission_then_draws_without_false_shuffle_credit(self):
        g = self.game((INSPECTOR, ZERO), deck=(LOW,)*99); outgoing = self.entity(g, ZERO).id
        self.play(g, INSPECTOR); self.assertEqual(g.state.entities[outgoing].zone, Zone.GRAVEYARD)
        self.assertFalse(g.state.deck_shuffle_history); self.assertEqual(len(g.state.players[1].deck), 98)

    def test_finley_real_entry_uses_original_hand_slots_and_original_bottom_objects(self):
        g = self.game((FINLEY, LOW, HIGH), deck=(SPELL, ZERO, LOW)); held = tuple(g.state.players[1].hand[1:])
        deck = tuple(g.state.players[1].deck); rng = g._rng.getstate(); source = self.play(g, FINLEY)
        self.assertEqual(g.state.players[1].hand, list(reversed(deck[-2:])))
        self.assertEqual(g.state.players[1].deck, list(deck[:-2]+tuple(reversed(held))))
        self.assertEqual(g.state.players[1].board, [source]); self.assertEqual(g.state.players[1].mana, 19)
        self.assertEqual(g._rng.getstate(), rng); self.assertFalse(g.state.deck_shuffle_history); self.no_draw(g)

    def test_finley_uses_current_hand_order_after_explicit_reordering_not_entry_chronology(self):
        g = self.game((REVERSE, FINLEY, LOW, HIGH)); self.play(g, REVERSE)
        held = tuple(e for e in g.state.players[1].hand if g.state.entities[e].card_id != FINLEY)
        self.play(g, FINLEY); self.assertEqual(tuple(g.state.players[1].deck[-2:]), tuple(reversed(held)))

    def test_finley_empty_hand_does_not_move_any_deck_card(self):
        g = self.game((FINLEY,)); deck = list(g.state.players[1].deck); self.play(g, FINLEY)
        self.assertEqual(g.state.players[1].deck, deck); self.assertFalse(g.state.players[1].hand); self.no_draw(g)

    def test_finley_empty_deck_takes_no_newly_inserted_cards_and_does_not_fatigue(self):
        g = self.game((FINLEY, LOW, HIGH), deck=()); held = tuple(g.state.players[1].hand[1:])
        self.play(g, FINLEY); self.assertEqual(tuple(g.state.players[1].deck), tuple(reversed(held)))
        self.assertFalse(g.state.players[1].hand); self.no_draw(g)

    def test_finley_short_deck_takes_only_original_bottom_group(self):
        g = self.game((FINLEY, LOW, HIGH, ZERO), deck=(SPELL,)); old = g.state.players[1].deck[0]
        held = tuple(g.state.players[1].hand[1:]); self.play(g, FINLEY)
        self.assertEqual(g.state.players[1].hand, [old]); self.assertEqual(tuple(g.state.players[1].deck), tuple(reversed(held)))

    def test_finley_full_hand_releases_old_slots_before_original_bottom_arrives(self):
        g = self.game((FINLEY,)+(LOW,)*9, deck=(HIGH,)*12); old = tuple(g.state.players[1].deck)
        self.play(g, FINLEY); self.assertEqual(g.state.players[1].hand, list(reversed(old[-9:])))
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events))

    def test_finley_moves_both_current_local_materials_without_creating_copies(self):
        g = self.game((LOCAL, FINLEY, HIGH)); held = self.entity(g, HIGH).id; incoming = g.state.players[1].deck[-1]
        allocations = g.state.next_entity_id; self.play(g, LOCAL); self.play(g, FINLEY)
        self.assertEqual((g.state.entities[held].cost, g.state.entities[incoming].cost), (0, 0))
        self.assertEqual(g.state.next_entity_id, allocations)

    def test_finley_same_named_cards_keep_distinct_original_physical_identities(self):
        g = self.game((FINLEY, LOW, LOW), deck=(HIGH, HIGH)); held = tuple(g.state.players[1].hand[1:]); deck = tuple(g.state.players[1].deck)
        self.play(g, FINLEY); self.assertEqual(tuple(g.state.players[1].hand), tuple(reversed(deck)))
        self.assertEqual(tuple(g.state.players[1].deck), tuple(reversed(held)))

    def test_finley_hand_entries_are_actual_moves_with_updated_original_epochs(self):
        g = self.game((FINLEY, LOW)); incoming = g.state.players[1].deck[-1]; epoch = g.state.entities[incoming].zone_epoch
        self.play(g, FINLEY); e = g.state.entities[incoming]; entry = g.state.hand_entries[e.hand_entry_id-1]
        self.assertEqual((e.zone_epoch, entry.from_zone, entry.reason), (epoch+1, Zone.DECK, 'move')); self.no_draw(g)

    def test_real_brann_repeats_finley_with_fresh_groups_and_swaps_back_once(self):
        g = self.game((FINLEY, LOW, HIGH), deck=(SPELL, ZERO), board=('LOE_077',))
        held = list(g.state.players[1].hand[1:]); deck = list(g.state.players[1].deck)
        self.play(g, FINLEY); self.assertEqual(g.state.players[1].hand, held); self.assertEqual(g.state.players[1].deck, deck)
        self.assertEqual(g.state.players[1].mana, 19); self.no_draw(g)

    def test_finley_full_deck_policy_remains_original_per_move_admission_and_is_uncalibrated(self):
        g = self.game((FINLEY, LOW, HIGH), deck=(ZERO,)*99); held = tuple(g.state.players[1].hand[1:]); old = tuple(g.state.players[1].deck)
        self.play(g, FINLEY); self.assertEqual(g.state.players[1].hand, list(reversed(old[-2:])))
        self.assertEqual(len(g.state.players[1].deck), 97)
        self.assertTrue(all(g.state.entities[eid].zone == Zone.GRAVEYARD for eid in held))
        self.assertIn('99-card exchange capacity behavior', load_batch()['uncalibrated'])

    def test_finley_preserves_actual_card_owner_when_returning_a_stolen_hand_card(self):
        g = self.game((STEAL, FINLEY), enemy_hand=(HIGH,)); original = g.state.players[2].hand[0]
        self.play(g, STEAL); self.play(g, FINLEY)
        self.assertEqual((g.state.entities[original].owner, g.state.entities[original].controller), (2, 1))

    def test_real_flashback_summons_both_registered_leaves_without_their_battlecries(self):
        g = self.game((NOOP, FLASHBACK, HIGH)); self.play(g, NOOP); held = self.entity(g, HIGH).id
        deck = list(g.state.players[1].deck); self.play(g, FLASHBACK)
        self.assertEqual(g.state.players[1].hand, [held]); self.assertEqual(g.state.players[1].deck, deck)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertTrue(all(g.state.entities[i].card_id in (INSPECTOR, FINLEY) for i in g.state.players[1].board))
        self.assertFalse(g.state.battlecry_history); self.assertFalse(g.state.draw_history)

    def test_pending_new_selector_restores_before_it_executes_without_repaying(self):
        g = self.game((INSPECTOR, LOW), mode='start_wait'); self.play(g, INSPECTOR); other = self.portable(g)
        self.choose(g); self.choose(other); self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual((g.state.players[1].mana, len(g.state.deck_shuffle_history)), (19, 1))

    def test_pending_shuffle_restores_before_original_draw_without_reshuffle(self):
        g = self.game((INSPECTOR, HIGH), mode='shuffle_wait'); self.play(g, INSPECTOR); other = self.portable(g)
        rng = g._rng.getstate(); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g._rng.getstate(), rng)
        self.assertEqual(len(g.state.deck_shuffle_history), 1)

    def test_finley_pending_exit_keeps_original_bottom_without_recapture(self):
        g = self.game((FINLEY, LOW, HIGH), mode='exit_wait'); old = tuple(g.state.players[1].deck)
        self.play(g, FINLEY); other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(g.state.players[1].hand, list(reversed(old[-2:])))

    def test_finley_pending_entry_resumes_without_duplicate_acquisition(self):
        g = self.game((FINLEY, LOW), mode='entry_wait'); self.play(g, FINLEY); count = len(g.state.hand_entries)
        other = self.portable(g); self.choose(g); self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(g.state.hand_entries), count)

    def test_late_inspector_draw_failure_rolls_back_shuffle_cost_payment_and_rng(self):
        g = self.game((INSPECTOR, HIGH), mode='draw_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, INSPECTOR)
        self.assertEqual(g.snapshot(), before)

    def test_late_finley_entry_failure_rolls_back_both_physical_groups_and_histories(self):
        g = self.game((FINLEY, LOW, HIGH), mode='entry_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, FINLEY)
        self.assertEqual(g.snapshot(), before)

    def test_failed_waiting_choice_preserves_same_original_shuffle_and_draw_boundary(self):
        g = self.game((INSPECTOR, HIGH), mode='shuffle_wait'); self.play(g, INSPECTOR); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), before); self.choose(g)

    def test_finley_conceals_previously_revealed_hand_and_keeps_incoming_cards_private(self):
        g = self.game((REVEAL, FINLEY, HIGH)); self.play(g, REVEAL); self.play(g, FINLEY)
        other = json.dumps(g.for_player(2).observe()['observation']['players'])
        for value in (HIGH, ZERO, 'rng_state', 'resolution_frame'): self.assertNotIn('"'+value+'"', other)

    def test_current_restore_rejects_previous_schema_explicitly(self):
        g = self.game((INSPECTOR,)); saved = g.snapshot(); saved['schema_version'] -= 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture())


if __name__ == '__main__': unittest.main()
