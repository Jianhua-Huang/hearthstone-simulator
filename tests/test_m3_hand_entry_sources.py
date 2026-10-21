"""Direct producer identities on the existing successful hand-acquisition ledger."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, HandDerivativeSpec,
    Keyword, PlayCard, PlayerSetup, Scenario, SelectChoice, ShatterSpec, SnapshotError, Zone)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Destroy, Draw, InvokeBehavior,
    RequestChoice, ReturnToHand)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_combinations import HandCombinationProfile
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.joint_hand_shuffle import ShuffleHandsTogether
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.temporary_cards import CreateTemporaryCard
from hs_sim.engine.temporary_deck_hands import ReplaceHandWithTemporaryDeckCards
from hs_sim.engine.temporary_hands import ReplaceHandWithTemporaryCopy
from hs_sim.engine.future_hand_returns import SendHandMinionsFuture
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard

P = 'fixture.hand.entry.source.'
A, B, CHILD, MINI, LEFT, RIGHT, COMBINED = (P+x for x in ('a', 'b', 'child', 'mini', 'left', 'right', 'combined'))


def fixture():
    r = build_registry()
    for cid in (A, B, LEFT, RIGHT, COMBINED):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=3))
    r.register_card(CardDefinition(MINI, MINI, CardType.MINION, cost=1, attack=1, health=1,
        keywords=(Keyword.MINI,)))
    r.register_hand_combination(HandCombinationProfile(COMBINED, LEFT, RIGHT))
    r.register_behavior(CHILD, lambda c: ())
    r.register_card(CardDefinition(CHILD, CHILD, CardType.SPELL, on_play=CHILD))
    for cid, keyword, derivative, kind in ((P+'twin', Keyword.TWINSPELL, CHILD, CardType.SPELL),
            (P+'miniature', Keyword.MINIATURIZE, MINI, CardType.MINION)):
        r.register_behavior(cid, lambda c: ())
        r.register_card(CardDefinition(cid, cid, kind, on_play=cid if kind == CardType.SPELL else None,
            attack=1 if kind == CardType.MINION else 0, health=3 if kind == CardType.MINION else 0,
            keywords=(keyword,), hand_derivatives=(HandDerivativeSpec(keyword, derivative),)))
    for cid in (P+'splitL', P+'splitR', P+'split'):
        r.register_behavior(cid, lambda c: ())
        root = cid == P+'split'
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,),
            shatter=ShatterSpec(P+'splitL', P+'splitR') if root else None))
    def ref(c, pid=None, zone=Zone.HAND):
        pid = c.player_id if pid is None else pid
        return CardReference.capture(next(c.state.entities[i] for i in getattr(c.state.players[pid], zone.value)
            if c.state.entities[i].card_id == A))
    def fail(c): raise ResolutionError('Hand entry deliberate late failure')
    r.register_behavior(P+'fail', fail)
    scripts = {
        'get': lambda c: (AddToHand(c.player_id, A, c.source_id),),
        'double_get': lambda c: (AddToHand(c.player_id, A, c.source_id), AddToHand(c.player_id, A, c.source_id)),
        'unsourced': lambda c: (AddToHand(c.player_id, A),),
        'draw': lambda c: (Draw(c.player_id, 1, c.source_id),),
        'foreign_draw': lambda c: (Draw(3-c.player_id, 1, c.source_id),),
        'auto_twin': lambda c: (CastSpell(c.player_id, P+'twin', c.source_id),),
        'copy': lambda c: (CopyCard(ref(c, 3-c.player_id), c.player_id, source_id=c.source_id),),
        'move': lambda c: (MoveCard(ref(c, 3-c.player_id), c.player_id, Zone.HAND, source_id=c.source_id),),
        'roundtrip': lambda c: (MoveCard(ref(c), c.player_id, Zone.DECK, position='top', source_id=c.source_id),
            Draw(c.player_id, 1, c.source_id)),
        'same_hand': lambda c: (MoveCard(ref(c), c.player_id, Zone.HAND, source_id=c.source_id),),
        'shuffle': lambda c: (ShuffleHandsTogether(c.player_id, c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id, source_id=c.source_id, lock_next_owner_turn=True),),
        'bounce_unsourced': lambda c: (ReturnToHand(c.target_id),),
        'destroy': lambda c: (Destroy(c.target_id),),
        'transform': lambda c: (TransformStoredCard(ref(c), B, source_id=c.source_id),),
        'temporary': lambda c: (CreateTemporaryCard(c.player_id, A, c.state.turn, source_id=c.source_id),),
        'replace_copy': lambda c: (ReplaceHandWithTemporaryCopy(c.player_id, 3-c.player_id, c.source_id),),
        'replace_deck': lambda c: (ReplaceHandWithTemporaryDeckCards(c.player_id, 2, c.source_id),),
        'future': lambda c: (SendHandMinionsFuture(c.player_id, c.source_id),),
        'split_get': lambda c: (AddToHand(c.player_id, P+'split', c.source_id),),
        'pair_get': lambda c: (AddToHand(c.player_id, LEFT, c.source_id), AddToHand(c.player_id, RIGHT, c.source_id)),
        'wait': lambda c: (AddToHand(c.player_id, A, c.source_id), RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue'), ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))),
            c.source_id)),
        'late_fail': lambda c: (AddToHand(c.player_id, A, c.source_id), InvokeBehavior(P+'fail', c.source_id, c.player_id)),
        'invalid_source': lambda c: (AddToHand(c.player_id, A, 999999),),
    }
    for key, body in scripts.items():
        cid = P+key
        r.register_behavior(cid, body)
        if key == 'future':
            r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=3, battlecry=cid))
        else:
            r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
                requires_target=key in ('bounce', 'bounce_unsourced', 'destroy')))
    r.register_card(CardDefinition(P+'producer', P+'producer', CardType.MINION,
        attack=1, health=3, battlecry=P+'get'))
    return r


class HandEntrySourceTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy_hand=(), enemy_board=(), deck=(A,)*8, actor=1):
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=deck, mana=10, max_mana=10)
        other = PlayerSetup('HERO_01', hand=enemy_hand, board=enemy_board, deck=(A,)*8, mana=10, max_mana=10)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own), active_player=actor, seed=352), fixture())

    def play(self, g, name, target=None):
        pid = g.state.active_player
        source = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == P+name)
        g.apply(PlayCard(pid, source, target)); return source

    def current(self, g, pid=1, card=A):
        return next(g.state.entities[i] for i in g.state.players[pid].hand if g.state.entities[i].card_id == card)

    def row(self, g, entity): return hand_entry(g.state, entity.hand_entry_id)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, fixture())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), fixture()).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in ('"hand_entries"', '"hand_entry_id"', '"rng_state"', '"resolution_frame"'):
                self.assertNotIn(private, public)
        return restored

    def test_initial_hands_have_explicit_no_producer(self):
        g = self.game((A,), enemy_hand=(A,))
        self.assertTrue(all(x.reason == 'scenario' and x.source_id is None for x in g.state.hand_entries))
        self.portable(g)

    def test_created_cards_use_request_source_and_unsourced_stays_none(self):
        g = self.game((P+'get', P+'unsourced'))
        source = self.play(g, 'get'); first = self.current(g)
        self.assertEqual(self.row(g, first).source_id, source)
        self.play(g, 'unsourced')
        rows = [self.row(g, g.state.entities[i]) for i in g.state.players[1].hand]
        self.assertEqual([x.source_id for x in rows], [source, None]); self.portable(g)

    def test_sourced_draw_records_actual_request_for_each_recipient(self):
        g = self.game((P+'draw', P+'foreign_draw'))
        own = self.play(g, 'draw'); foreign = self.play(g, 'foreign_draw')
        self.assertEqual(self.row(g, self.current(g)).source_id, own)
        self.assertEqual(self.row(g, self.current(g, 2)).source_id, foreign)
        self.assertEqual([(x.player_id, x.source_id) for x in g.state.draw_history], [(1, own), (2, foreign)])
        self.portable(g)

    def test_natural_turn_draw_is_explicitly_unsourced(self):
        g = self.game(); g.apply(EndTurn(1))
        row = self.row(g, self.current(g, 2))
        self.assertEqual(row.reason, 'draw'); self.assertIsNone(row.source_id); self.portable(g)

    def test_copy_producer_differs_from_copied_origin(self):
        g = self.game((P+'copy',), enemy_hand=(A,))
        original = self.current(g, 2).id; source = self.play(g, 'copy'); copy = self.current(g)
        self.assertEqual(copy.origin_entity_id, original)
        self.assertEqual(self.row(g, copy).source_id, source)
        self.assertNotEqual(source, original); self.portable(g)

    def test_foreign_hand_transfer_reacquires_same_entity_for_new_player(self):
        g = self.game((P+'move',), enemy_hand=(A,))
        before = self.current(g, 2); original = self.row(g, before); source = self.play(g, 'move')
        after = self.row(g, self.current(g))
        self.assertEqual(after.entity_id, before.id); self.assertNotEqual(after.id, original.id)
        self.assertEqual((after.player_id, after.from_zone, after.source_id), (1, Zone.HAND, source))
        self.assertIsNone(g.state.hand_entries[original.id-1].source_id); self.portable(g)

    def test_reentry_changes_source_without_rewriting_old_entry(self):
        g = self.game((P+'get', P+'roundtrip'))
        old_source = self.play(g, 'get'); old = self.row(g, self.current(g))
        new_source = self.play(g, 'roundtrip'); new = self.row(g, self.current(g))
        self.assertEqual((old.source_id, new.source_id), (old_source, new_source))
        self.assertEqual(old.entity_id, new.entity_id)
        self.assertEqual(g.state.hand_entries[old.id-1], old); self.portable(g)

    def test_joint_shuffle_uses_original_source_only_for_actual_transfers(self):
        g = self.game((P+'shuffle',)+(A,)*4, enemy_hand=(B,)*3)
        original = tuple(g.state.hand_entries); source = self.play(g, 'shuffle')
        transferred = g.state.hand_entries[len(original):]
        self.assertTrue(transferred)
        self.assertTrue(all(x.source_id == source and x.from_zone == Zone.HAND for x in transferred))
        self.assertEqual(tuple(g.state.hand_entries[:len(original)]), original)
        self.assertEqual((len(g.state.players[1].hand), len(g.state.players[2].hand)), (4, 3))
        self.portable(g)

    def test_sourced_board_return_and_no_source_api_are_distinct(self):
        for name in ('bounce', 'bounce_unsourced'):
            with self.subTest(name=name):
                g = self.game((P+name,), board=(A,)); target = g.state.players[1].board[0]
                source = self.play(g, name, target); row = self.row(g, self.current(g))
                self.assertEqual((row.reason, row.from_zone), ('return', Zone.BOARD))
                self.assertEqual(row.source_id, source if name == 'bounce' else None)
                self.portable(g)

    def test_physical_source_survives_death_and_is_not_replaced_by_last_actor(self):
        g = self.game((P+'producer', P+'destroy'))
        source = self.play(g, 'producer'); original = self.row(g, self.current(g))
        self.play(g, 'destroy', source)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.row(g, self.current(g)), original)
        self.assertEqual(original.source_id, source); self.portable(g)

    def test_burn_and_same_hand_noop_create_no_successful_entry(self):
        g = self.game((P+'double_get',)+(A,)*9); before = len(g.state.hand_entries)
        source = self.play(g, 'double_get')
        self.assertEqual(len(g.state.hand_entries), before+1)
        self.assertEqual(g.state.hand_entries[-1].source_id, source)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 1)
        g = self.game((P+'same_hand', A)); before = tuple(g.state.hand_entries)
        self.play(g, 'same_hand'); self.assertEqual(tuple(g.state.hand_entries), before); self.portable(g)

    def test_stored_transform_preserves_original_entry_face_and_source(self):
        g = self.game((P+'get', P+'transform')); source = self.play(g, 'get')
        before = self.row(g, self.current(g)); count = len(g.state.hand_entries)
        self.play(g, 'transform'); entity = self.current(g, card=B)
        self.assertEqual(len(g.state.hand_entries), count)
        self.assertEqual(self.row(g, entity), before); self.assertEqual(before.source_id, source)
        self.assertEqual(before.card_id, A); self.portable(g)

    def test_temporary_creation_keeps_producer_separate_from_lifetime(self):
        g = self.game((P+'temporary',)); source = self.play(g, 'temporary'); entity = self.current(g)
        self.assertEqual(self.row(g, entity).source_id, source)
        self.assertEqual(entity.hand_lifetime.source_id, source); self.portable(g)

    def test_temporary_copies_and_original_returns_have_same_actual_producer(self):
        g = self.game((P+'replace_copy', A), enemy_hand=(B,)); original = self.current(g).id
        source = self.play(g, 'replace_copy')
        self.assertEqual(self.row(g, self.current(g, card=B)).source_id, source)
        self.portable(g); g.apply(EndTurn(1))
        row = self.row(g, self.current(g)); self.assertEqual((row.entity_id, row.source_id), (original, source))
        self.portable(g)

    def test_temporary_physical_deck_hand_and_return_keep_request_source(self):
        g = self.game((P+'replace_deck', A)); original = self.current(g).id
        source = self.play(g, 'replace_deck')
        self.assertTrue(all(self.row(g, g.state.entities[i]).source_id == source for i in g.state.players[1].hand))
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        restored = g.state.entities[original]
        self.assertEqual(self.row(g, restored).source_id, source); self.portable(g)

    def test_future_original_hand_return_uses_original_request(self):
        g = self.game((P+'future', A)); original = self.current(g).id
        source = self.play(g, 'future'); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[original].zone, Zone.HAND)
        self.assertEqual(self.row(g, g.state.entities[original]).source_id, source); self.portable(g)

    def test_printed_derivative_direct_producer_is_original_played_entity(self):
        for name, child in (('twin', CHILD), ('miniature', MINI)):
            with self.subTest(name=name):
                g = self.game((P+name,)); source = self.play(g, name)
                self.assertEqual(self.row(g, self.current(g, card=child)).source_id, source); self.portable(g)

    def test_automatic_twin_derivative_uses_actual_spell_not_outer_caller(self):
        g = self.game((P+'auto_twin',)); caller = self.play(g, 'auto_twin')
        actual = next(x for x in g.state.cast_history if x.card_id == P+'twin')
        self.assertNotEqual(actual.source_id, caller)
        self.assertEqual(self.row(g, self.current(g, card=CHILD)).source_id, actual.source_id)
        self.portable(g)

    def test_shatter_fragments_use_native_split_source_and_merge_is_a_new_entry(self):
        g = self.game((P+'split_get', CHILD)); source = self.play(g, 'split_get')
        root = next(x for x in g.state.hand_entries if x.card_id == P+'split')
        self.assertEqual(root.source_id, source)
        parts = [x for x in g.state.hand_entries if x.reason == 'shatter']
        self.assertEqual([x.source_id for x in parts], [root.entity_id, root.entity_id])
        g.apply(PlayCard(1, self.current(g, card=CHILD).id))
        merge = next(x for x in reversed(g.state.hand_entries) if x.reason == 'recombine')
        event = next(x for x in reversed(g.events) if x.kind == 'cards_recombined')
        self.assertEqual(merge.source_id, event.source_id); self.portable(g)

    def test_native_pair_result_uses_its_original_ordered_carrier(self):
        g = self.game((P+'pair_get',)); source = self.play(g, 'pair_get')
        left = next(x for x in g.state.hand_entries if x.card_id == LEFT)
        right = next(x for x in g.state.hand_entries if x.card_id == RIGHT)
        result = self.row(g, self.current(g, card=COMBINED))
        self.assertEqual((left.source_id, right.source_id), (source, source))
        self.assertEqual(result.source_id, left.entity_id); self.portable(g)

    def test_second_seat_generated_entry_uses_actor_without_changing_receiver(self):
        g = self.game((P+'get',), actor=2); source = self.play(g, 'get')
        row = self.row(g, self.current(g, 2))
        self.assertEqual((row.player_id, row.source_id), (2, source)); self.portable(g)

    def test_waiting_restore_clone_replay_and_late_failure_preserve_source(self):
        g = self.game((P+'wait',)); source = self.play(g, 'wait'); waiting = g.snapshot()
        self.assertEqual(self.row(g, self.current(g)).source_id, source)
        other = self.portable(g)
        q = other.state.pending_choice
        with self.assertRaises(ResolutionError): other.apply(SelectChoice(q.player_id, q.id, ('fail',)))
        self.assertEqual(other.snapshot(), waiting)
        g.apply(SelectChoice(q.player_id, q.id, ('ok',))); self.portable(g)

    def test_entire_action_failure_does_not_leave_phantom_acquisition(self):
        g = self.game((P+'late_fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'late_fail')
        self.assertEqual(g.snapshot(), before)

    def test_unknown_request_source_rolls_back_without_entry(self):
        g = self.game((P+'invalid_source',)); before = g.snapshot()
        with self.assertRaises((ResolutionError, ValueError)): self.play(g, 'invalid_source')
        self.assertEqual(g.snapshot(), before)

    def test_current_snapshot_requires_explicit_typed_existing_source(self):
        g = self.game((P+'get',)); self.play(g, 'get'); saved = g.snapshot()
        for bad_source in (999999, True, 0, '1'):
            with self.subTest(bad_source=bad_source):
                bad = deepcopy(saved); bad['state']['hand_entries'][-1]['source_id'] = bad_source
                bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture())
        bad = deepcopy(saved); del bad['state']['hand_entries'][-1]['source_id']
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture())
        row = g.state.hand_entries[0]
        with self.assertRaises(ValueError): replace(row, source_id=row.entity_id)
        old = deepcopy(saved); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture())


if __name__ == '__main__': unittest.main()
