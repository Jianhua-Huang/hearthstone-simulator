from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
import json
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.past_hand_shuffle_card import CARD, OUTCAST, SHUFFLE, load_batch, register_past_hand_shuffle_card
from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario, TriggerSpec, Zone
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (
    ChangeControl, ChoiceOption, Destroy, InvokeBehavior, RequestChoice, RevealHandCard, Silence,
)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hand_keywords import GrantStoredKeyword
from hs_sim.engine.hand_order import ShuffleHand
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardClass, CardMetadata, CostSpec, TargetMode, TargetSpec
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.zones import CardReference, ModifyStoredCost, ReorderZone
from tools import card_batch as batch


P = 'test.k468.'
HERO, OTHER_HERO, A, B, C, WEAPON, LOCATION, WATCH = (P+s for s in ('hero', 'other_hero', 'a', 'b', 'c', 'weapon', 'location', 'watch'))
NOOP, SHIFT, OTHER_SHIFT, REVERSE, DECORATE, REVEAL, WAIT, DOUBLE, BAD, FAIL, KILL, SILENCE, TAKE, AUTO = (
    P+s for s in ('noop', 'shift', 'other_shift', 'reverse', 'decorate', 'reveal', 'wait', 'double', 'bad', 'fail', 'kill', 'silence', 'take', 'auto'))
COUNTER = 'CORE_EX1_287'
CONTEXT = GenerationContext('k468-explicit-hand-order', 'experimental')


@lru_cache(None)
def complete_registry():
    return build_registry()


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = build_registry() if mode == 'counter' else Registry('k468-'+mode)
    if mode != 'counter':
        register_past_hand_shuffle_card(r)
    for cid, card_class in ((HERO, CardClass.DEMON_HUNTER), (OTHER_HERO, CardClass.MAGE)):
        r.register_card(CardDefinition(cid, cid, CardType.HERO, health=50,
            metadata=CardMetadata(False, (card_class,), None)))
    for cid in (A, B, C):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=4))
    def fail(c):
        raise ResolutionError('K468 deliberate late hand-order failure')
    def decorate(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == A)
        return tuple(effect for ref in refs for effect in (
            BuffStoredCard(ref, 2, 3, c.source_id), ModifyStoredCost(ref, CostSpec(delta=2), c.source_id),
            GrantStoredKeyword(ref, Keyword.TAUNT, c.source_id)))
    scripts = {
        NOOP: lambda c: (), SHIFT: lambda c: (ShuffleHand(c.player_id, c.source_id),),
        OTHER_SHIFT: lambda c: (ShuffleHand(3-c.player_id, c.source_id),),
        REVERSE: lambda c: (ReorderZone(c.player_id, Zone.HAND, tuple(reversed(c.state.players[c.player_id].hand))),),
        DECORATE: decorate,
        REVEAL: lambda c: tuple(RevealHandCard(i) for i in c.state.players[c.player_id].hand),
        WAIT: lambda c: (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', (ShuffleHand(c.player_id, c.source_id),)),), c.source_id),),
        DOUBLE: lambda c: (ShuffleHand(c.player_id, c.source_id), RequestChoice(c.player_id,
            (ChoiceOption('continue', 'Continue'),), c.source_id), ShuffleHand(c.player_id, c.source_id)),
        BAD: lambda c: (ShuffleHand(c.player_id, 999999),), FAIL: fail,
        KILL: lambda c: (Destroy(c.target_id, c.source_id),), SILENCE: lambda c: (Silence(c.target_id),),
        TAKE: lambda c: (ChangeControl(c.target_id, 2),),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(TargetMode.REQUIRED, (Zone.BOARD,), (CardType.MINION,)) if cid in (KILL, SILENCE, TAKE) else None))
    r.register_card(CardDefinition(WEAPON, WEAPON, CardType.WEAPON, attack=2, durability=3))
    r.register_card(CardDefinition(LOCATION, LOCATION, CardType.LOCATION, durability=2, on_use=NOOP))
    r.register_behavior(AUTO, lambda c: (CastSpell(c.player_id, NOOP, c.source_id),))
    r.register_card(CardDefinition(AUTO, AUTO, CardType.MINION, attack=1, health=1, battlecry=AUTO))
    def watch(c):
        e = c.event
        if mode == 'fail' and e.kind == 'hand_reordered':
            return (InvokeBehavior(FAIL, c.source_id, c.player_id),)
        if mode == 'wait' and e.kind == 'hand_reordered':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(FAIL, c.source_id, c.player_id),))), c.source_id),)
        return ()
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.WEAPON, durability=50,
        triggers=(TriggerSpec('hand_reordered', WATCH),)))
    r.register_pool(PoolDefinition('constructed.past.cards', 'k468-eldritch-only', CONTEXT.target_id,
        CONTEXT.mode, (PoolMember(CARD),), complete=True))
    r.validate()
    return r


class PastHandShuffleTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, hand=(), board=(), *, enemy_hand=(), enemy_board=(), mode='normal', seed=468):
        self.mode = mode
        return Game.from_scenario(Scenario((
            PlayerSetup(HERO, hand=hand, board=board, deck=(NOOP,)*8, mana=10, max_mana=10,
                weapon_card_id=WATCH if mode in ('wait', 'fail') else None),
            PlayerSetup(OTHER_HERO, hand=enemy_hand, board=enemy_board, deck=(NOOP,)*8, mana=10, max_mana=10)),
            seed=seed, generation_context=CONTEXT), fixture(mode))

    def orders(self, g, player=1):
        return [e for e in g.events if e.kind == 'hand_reordered' and e.player_id == player]

    def hand_materials(self, g, player=1):
        return {i: asdict(g.state.entities[i]) for i in g.state.players[player].hand}

    def test_full_source_row_and_two_complete_primary_faces(self):
        d = load_batch(); raw = d['dependencies'][0]['record']
        self.assertEqual((raw['id'], len(d['official_observations'])), (CARD, 2))
        for o in d['official_observations']:
            self.assertEqual(batch.sha(Path(o['response_file'])), o['response_sha256'])
            batch.check_face(raw, o['face'], o['locale'])
        self.assertEqual(batch.sha(Path(d['source']['path'])), d['source']['sha256'])
        self.assertFalse(d['cn_calibrated']); self.assertFalse(d['formal_pool_complete'])

    def test_constructed_registration_keeps_both_real_native_entries(self):
        c = complete_registry().card(CARD)
        self.assertEqual((c.cost, c.attack, c.health, c.on_play), (1, 1, 3, OUTCAST))
        self.assertEqual(set(c.keywords), {Keyword.OUTCAST, Keyword.SPELLBURST})
        self.assertEqual(c.limited_triggers[0].behavior_id, SHUFFLE)

    def test_real_left_and_right_outcast_each_shuffle_remaining_hand_and_pay_once(self):
        for hand in ((CARD, A, B, C), (A, B, C, CARD)):
            g = self.game(hand); original = set(g.state.players[1].hand)-{self.entity(g, CARD).id}
            self.play(g, CARD)
            self.assertEqual(set(g.state.players[1].hand), original); self.assertEqual(len(self.orders(g)), 1)
            self.assertEqual((g.state.players[1].mana, len(g.state.play_history)), (9, 1))
            self.assertEqual(self.orders(g)[0].source_id, self.entity(g, CARD, zone='board').id)

    def test_middle_play_has_no_outcast_shuffle_and_uses_no_rng(self):
        g = self.game((A, CARD, B)); rng = g.snapshot()['rng_state']; before = g.state.players[1].hand
        source = self.play(g, CARD)
        self.assertEqual(g.state.players[1].hand, [i for i in before if i != source])
        self.assertEqual(g.snapshot()['rng_state'], rng); self.assertFalse(self.orders(g))

    def test_empty_and_singleton_remaining_hand_do_not_consume_rng(self):
        for hand in ((CARD,), (CARD, A)):
            g = self.game(hand); rng = g.snapshot()['rng_state']; self.play(g, CARD)
            self.assertEqual(g.snapshot()['rng_state'], rng); self.assertEqual(len(self.orders(g)), 1)

    def test_duplicate_cards_remain_distinct_physical_members_with_no_new_entries(self):
        g = self.game((CARD, A, A, B, A)); source = self.entity(g, CARD).id
        refs = {i: CardReference.capture(g.state.entities[i]) for i in g.state.players[1].hand if i != source}
        before_entries = len(g.state.hand_entries); self.play(g, CARD)
        self.assertEqual({i: CardReference.capture(g.state.entities[i]) for i in g.state.players[1].hand}, refs)
        self.assertEqual(len(g.state.hand_entries), before_entries)

    def test_stats_cost_keywords_and_exact_remaining_materials_are_preserved(self):
        g = self.game((DECORATE, CARD, A, B, WEAPON, LOCATION)); self.play(g, DECORATE)
        before = self.hand_materials(g); before.pop(self.entity(g, CARD).id); self.play(g, CARD)
        self.assertEqual(self.hand_materials(g), before)
        a = self.entity(g, A); self.assertEqual((a.attack, a.health, a.cost), (3, 7, 2)); self.assertIn(Keyword.TAUNT, a.keywords)

    def test_only_selected_players_hand_reorders_and_no_draw_discard_or_deck_shuffle_occurs(self):
        g = self.game((SHIFT, A, B, C), enemy_hand=(A, B)); enemy = self.hand_materials(g, 2)
        deck = tuple(g.state.players[1].deck); self.play(g, SHIFT)
        self.assertEqual(self.hand_materials(g, 2), enemy); self.assertEqual(tuple(g.state.players[1].deck), deck)
        self.assertFalse(g.state.draw_history); self.assertFalse(g.state.discard_history)
        self.assertFalse(any(e.kind in ('deck_shuffled', 'card_added_to_hand', 'card_moved_to_hand') for e in g.events))

    def test_public_request_can_shuffle_other_player_without_transferring_any_card(self):
        g = self.game((OTHER_SHIFT, A, B), enemy_hand=(A, B, C)); own = set(g.state.players[1].hand)-{self.entity(g, OTHER_SHIFT).id}
        enemy = self.hand_materials(g, 2); self.play(g, OTHER_SHIFT)
        self.assertEqual(set(g.state.players[1].hand), own); self.assertEqual(self.hand_materials(g, 2), enemy)
        self.assertEqual((len(self.orders(g)), len(self.orders(g, 2))), (0, 1))

    def test_uniform_permutation_may_be_identity_and_still_retires_hidden_tracking(self):
        found = None
        for seed in range(12):
            g = self.game((REVEAL, CARD, A, B), seed=seed); self.play(g, REVEAL)
            before = [i for i in g.state.players[1].hand if g.state.entities[i].card_id != CARD]
            simulated = random.Random(); simulated.setstate(g._rng.getstate()); permutation = list(before); simulated.shuffle(permutation)
            if permutation == before:
                found = g; break
        self.assertIsNotNone(found); g = found
        old = {i: g._information.players[2].refs[str(i)] for i in before}; rng = g.snapshot()['rng_state']
        self.play(g, CARD); self.assertEqual(g.state.players[1].hand, before)
        self.assertNotEqual(g.snapshot()['rng_state'], rng)
        self.assertTrue(all(g._information.players[2].refs[str(i)] != old[i] for i in before))

    def test_random_hand_shuffle_retires_opponent_knowledge_but_keeps_owner_faces(self):
        g = self.game((REVEAL, CARD, A, B, C)); self.play(g, REVEAL)
        participants = [i for i in g.state.players[1].hand if g.state.entities[i].card_id != CARD]
        self.assertTrue(all(str(i) in g._information.players[2].known for i in participants))
        old = {i: g._information.players[2].refs[str(i)] for i in participants}; self.play(g, CARD)
        self.assertTrue(all(str(i) not in g._information.players[2].known for i in participants))
        self.assertTrue(all(g._information.players[2].refs[str(i)] != old[i] for i in participants))
        self.assertTrue(all(g._information.players[1].known[str(i)] == g.state.entities[i].card_id for i in participants))

    def test_singleton_known_card_retains_valid_tracking_without_random_work(self):
        g = self.game((REVEAL, CARD, A)); self.play(g, REVEAL); eid = self.entity(g, A).id
        old = g._information.players[2].refs[str(eid)]; rng = g.snapshot()['rng_state']; self.play(g, CARD)
        self.assertEqual(g._information.players[2].refs[str(eid)], old)
        self.assertEqual(g._information.players[2].known[str(eid)], A); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_spellburst_after_middle_play_shuffles_once_and_second_spell_does_not(self):
        g = self.game((A, CARD, NOOP, NOOP, B, C)); self.play(g, CARD); self.assertFalse(self.orders(g))
        self.play(g, NOOP); self.assertEqual(len(self.orders(g)), 1)
        rng = g.snapshot()['rng_state']; self.play(g, NOOP)
        self.assertEqual(len(self.orders(g)), 1); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_outcast_does_not_consume_independent_spellburst(self):
        g = self.game((CARD, A, B, NOOP, C)); self.play(g, CARD); self.assertEqual(len(self.orders(g)), 1)
        self.play(g, NOOP); self.assertEqual(len(self.orders(g)), 2)

    def test_ordinary_board_entry_keeps_spellburst_without_running_outcast(self):
        g = self.game((NOOP, A, B, C), board=(CARD,)); self.assertFalse(self.orders(g)); self.play(g, NOOP)
        self.assertEqual(len(self.orders(g)), 1)

    def test_automatic_spell_preserves_spellburst_for_later_manual_cast(self):
        g = self.game((AUTO, NOOP, A, B, C), board=(CARD,)); self.play(g, AUTO)
        self.assertFalse(self.orders(g)); self.assertEqual([x.origin for x in g.state.cast_history], ['effect'])
        self.play(g, NOOP); self.assertEqual(len(self.orders(g)), 1)

    def test_silence_and_spell_kill_prevent_stale_spellburst(self):
        for action in (SILENCE, KILL):
            g = self.game((action, NOOP, A, B), board=(CARD,)); source = self.entity(g, CARD, zone='board').id
            self.play(g, action, source); self.play(g, NOOP); self.assertFalse(self.orders(g))

    def test_transferred_source_uses_new_controllers_spell_and_hand(self):
        g = self.game((TAKE, A, B), board=(CARD,), enemy_hand=(NOOP, A, B, C))
        source = self.entity(g, CARD, zone='board').id; self.play(g, TAKE, source); self.assertFalse(self.orders(g))
        own = self.hand_materials(g); g.apply(EndTurn(1)); self.play(g, NOOP, player=2)
        self.assertEqual(self.hand_materials(g), own); self.assertEqual((len(self.orders(g)), len(self.orders(g, 2))), (0, 1))

    def test_real_counterspell_does_not_consume_spellburst_before_later_success(self):
        g = self.game((NOOP, NOOP, A, B, C), board=(CARD,), enemy_hand=(COUNTER,), mode='counter')
        g.apply(EndTurn(1)); self.play(g, COUNTER, player=2); g.apply(EndTurn(2))
        self.play(g, NOOP); self.assertTrue(g.state.play_history[-1].countered); self.assertFalse(self.orders(g))
        self.play(g, NOOP); self.assertEqual(len(self.orders(g)), 1)

    def test_wait_before_public_shuffle_restores_typed_new_effect_and_current_hand(self):
        g = self.game((WAIT, A, B, C)); self.play(g, WAIT); rng = g.snapshot()['rng_state']
        g = self.portable(g); self.choose(g)
        self.assertEqual(len(self.orders(g)), 1); self.assertNotEqual(g.snapshot()['rng_state'], rng)

    def test_wait_after_outcast_keeps_committed_order_rng_and_single_payment(self):
        g = self.game((CARD, A, B, C), mode='wait'); self.play(g, CARD)
        before = tuple(g.state.players[1].hand); rng = g.snapshot()['rng_state']; g = self.portable(g); self.choose(g)
        self.assertEqual(tuple(g.state.players[1].hand), before); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual((len(self.orders(g)), g.state.players[1].mana), (1, 9))

    def test_wait_after_spellburst_restores_consumed_use_and_does_not_shuffle_again(self):
        g = self.game((NOOP, NOOP, A, B, C), board=(CARD,), mode='wait'); self.play(g, NOOP)
        g = self.portable(g); self.choose(g); rng = g.snapshot()['rng_state']; self.play(g, NOOP)
        self.assertEqual(len(self.orders(g)), 1); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_two_real_operations_resume_second_new_effect_without_resampling_first(self):
        g = self.game((DOUBLE, A, A, B, C)); self.play(g, DOUBLE)
        self.assertEqual(len(self.orders(g)), 1); rng = g.snapshot()['rng_state']; g = self.portable(g); self.choose(g)
        self.assertEqual(len(self.orders(g)), 2); self.assertNotEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(len(g.state.players[1].hand), 4)

    def test_late_outcast_failure_restores_payment_hand_rng_knowledge_and_history(self):
        g = self.game((CARD, A, B, C), mode='fail'); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, CARD)
        self.assertEqual(g.snapshot(), snap)

    def test_late_spellburst_failure_restores_original_unused_trigger_and_spell(self):
        g = self.game((NOOP, A, B, C), board=(CARD,), mode='fail'); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, NOOP)
        self.assertEqual(g.snapshot(), snap)

    def test_pending_choice_failure_preserves_committed_permutation_and_waiting_root(self):
        g = self.game((CARD, A, B, C), mode='wait'); self.play(g, CARD); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), snap); self.choose(g); self.assertEqual(len(self.orders(g)), 1)

    def test_old_explicit_reorder_is_deterministic_and_keeps_previous_event_shape(self):
        g = self.game((REVERSE, A, B, C)); original = g.state.players[1].hand[1:]; rng = g.snapshot()['rng_state']
        self.play(g, REVERSE); self.assertEqual(g.state.players[1].hand, list(reversed(original)))
        self.assertEqual(g.snapshot()['rng_state'], rng); self.assertIsNone(self.orders(g)[0].source_id)

    def test_finite_request_invalid_types_unknown_source_and_codec(self):
        for args in ((True,), (3,), (1, True), (1, 0)):
            with self.assertRaises(ValueError): ShuffleHand(*args)
        g = self.game((BAD, A, B)); snap = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, BAD)
        self.assertEqual(g.snapshot(), snap)
        codec = FrameCodec(g.mechanics, g.registry); request = ShuffleHand(1, g.state.players[1].hero_id)
        self.assertEqual(codec.decode(codec.encode(request)), request)

    def test_previous_schema_rejected_and_players_never_receive_internal_rng_or_queue(self):
        g = self.game((CARD, A, B, C)); self.play(g, CARD); snap = g.snapshot(); old = deepcopy(snap); old['schema_version'] = 550
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())
        self.assertEqual(g.snapshot(), snap); g = self.portable(g)
        for player in (1, 2):
            visible = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'source_allocation', 'submitted_cost'):
                self.assertNotIn('"'+key+'"', visible)


if __name__ == '__main__':
    unittest.main()
