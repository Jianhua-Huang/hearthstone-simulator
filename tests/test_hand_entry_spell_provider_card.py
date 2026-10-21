"""Real Proto-Pandaren over complete explicit fixture pools and physical entries."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.hand_entry_spell_provider_card import CARD, BODY, POOL, QUERY, load_batch, register_hand_entry_spell_provider_card
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, GenerationContext, PlayCard,
    PlayerSetup, Ruleset, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy, Draw,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import EVENT, from_event, publish, validate_publications
from hs_sim.engine.hero_health_history import effective_events
from hs_sim.engine.model import CardClass, CardMetadata, Keyword, LimitedTriggerSpec, Rarity, RewindSpec, Zone
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember, resolve_candidates, sample_candidates
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import BehaviorCall, Resolution
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from tools.card_batch import check_face

P = 'fixture.hand.provider.'
FILL, OTHER, S, T, UNKNOWN, WATCH = (P+x for x in ('fill', 'other', 's', 't', 'unknown', 'watch'))
CTX = GenerationContext('fixture-hand-provider', 'experimental')


@lru_cache(maxsize=None)
def fixture(mode=None, unknown=False, role='writer'):
    if role not in ('writer', 'reader'): raise ValueError('Independent fixture registry required')
    r = build_registry(); register_hand_entry_spell_provider_card(r)
    meta = CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON)
    for cid in (FILL, OTHER):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1, health=3, metadata=meta))
    for cid in (S, T):
        r.register_behavior(cid, lambda c: (Draw(c.player_id, 1, c.source_id),))
        d = CardDefinition(cid, cid, CardType.SPELL, cost=1, on_play=cid,
            metadata=replace(meta, collectible=True, classes=(CardClass.MAGE,)))
        r.register_card(d); r.register_pool_card(PoolCard.from_definition(d))
    members = (S, T)
    if unknown:
        r.register_pool_card(PoolCard(UNKNOWN, CardType.SPELL, 1,
            replace(meta, collectible=True, classes=(CardClass.MAGE,))))
        members += (UNKNOWN,)
    r.register_pool(PoolDefinition(POOL, 'hand-provider-fixture-v1', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    def ref(c, pid=None):
        pid = c.player_id if pid is None else pid
        return CardReference.capture(next(c.state.entities[i] for i in c.state.players[pid].hand
            if c.state.entities[i].card_id == FILL))
    def fail(c): raise ResolutionError('Hand provider deliberate failure')
    r.register_behavior(P+'fail', fail)
    scripts = {
        'get': lambda c: (AddToHand(c.player_id, FILL, c.source_id),),
        'rewind': lambda c: (AddToHand(c.player_id, FILL, c.source_id),),
        'draw': lambda c: (Draw(c.player_id, 1, c.source_id),),
        'gift': lambda c: (AddToHand(3-c.player_id, FILL, c.source_id),),
        'double': lambda c: (AddToHand(c.player_id, FILL, c.source_id), AddToHand(c.player_id, FILL, c.source_id)),
        'copy': lambda c: (CopyCard(ref(c, 3-c.player_id), c.player_id, source_id=c.source_id),),
        'move': lambda c: (MoveCard(ref(c, 3-c.player_id), c.player_id, Zone.HAND, source_id=c.source_id),),
        'same': lambda c: (MoveCard(ref(c), c.player_id, Zone.HAND, source_id=c.source_id),),
        'transform': lambda c: (TransformStoredCard(ref(c), OTHER, source_id=c.source_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'destroy': lambda c: (Destroy(c.target_id),),
        'bad': lambda c: (InvokeBehavior(BODY, c.source_id, c.player_id),),
    }
    for key, body in scripts.items():
        cid = P+key; r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            requires_target=key in ('bounce', 'silence', 'destroy'), metadata=meta,
            keywords=(Keyword.REWIND,) if key == 'rewind' else (), rewind=RewindSpec(1) if key == 'rewind' else None))
    if mode:
        def eligible(c):
            entry = from_event(c.state, c.event)
            if entry.player_id != c.player_id: return False
            source = c.state.entities.get(entry.source_id)
            return source is not None and source.card_id == (CARD if mode == 'delivery' else P+'get')
        r.register_trigger_condition(P+'eligible', eligible)
        def wait(c):
            source = next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == CARD)
            return (RequestChoice(c.player_id, (
                ChoiceOption('ok', 'Continue'),
                ChoiceOption('kill', 'Remove original observer', (Destroy(source),)),
                ChoiceOption('take', 'Transfer original observer', (ChangeControl(source, 3-c.player_id),)),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),)),
            ), c.source_id),)
        r.register_behavior(P+'wait', wait)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30, metadata=meta,
            limited_triggers=(LimitedTriggerSpec(EVENT, P+'wait', condition_id=P+'eligible'),)))
    return r


class HandEntrySpellProviderTests(unittest.TestCase):
    def game(self, hand=(P+'get',), board=None, enemy_hand=(), enemy_board=(), mode=None, unknown=False, actor=1, capacity=10):
        self.config = (mode, unknown); self.actor = actor
        if board is None: board = ((WATCH,) if mode else ())+(CARD,)
        own = PlayerSetup('HERO_08', hand=hand, board=board, deck=(FILL,)*12, mana=20, max_mana=20, mana_cap=20)
        other = PlayerSetup('HERO_01', hand=enemy_hand, board=enemy_board, deck=(FILL,)*12, mana=20, max_mana=20, mana_cap=20)
        return Game.from_scenario(Scenario((own, other) if actor == 1 else (other, own), active_player=actor,
            seed=353, generation_context=CTX), fixture(mode, unknown), Ruleset(max_hand=capacity))

    def play(self, g, cid='get', target=None):
        cid = P+cid if not cid.startswith((P, 'BE_')) else cid
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid, target)); return eid

    def names(self, g, pid=1):
        s = g.state; return [s.entities[i].card_id for i in s.players[pid].hand]

    def generated(self, g):
        s = g.state
        return [e for e in g.events if e.kind == 'card_created' and e.source_id in s.entities and s.entities[e.source_id].card_id == CARD]

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot())); other = Game.from_snapshot(snap, fixture(*self.config, 'reader'))
        self.assertEqual(other.snapshot(), snap); self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), fixture(*self.config, 'reader')).snapshot(), snap)
        validate_publications(g)
        s = g.state
        self.assertEqual(len([e for e in effective_events(g.events) if e.kind == EVENT]), len([r for r in s.hand_entries if r.reason != 'scenario']))
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe())+json.dumps(g.player_events(pid))
            for private in ('"hand_entry_hash"', '"hand_entry_id"', '"hand_entries"', '"resolution_frame"', '"rng_state"', 'hand_card_entered'):
                self.assertNotIn(private, public)
        return other

    def test_complete_raw_primary_faces_and_actual_neutral_epic_without_invented_tribe(self):
        data = load_batch(); raw = data['cards'][0]['record']
        for face in data['official_observations']:
            check_face(raw, face['face'], face['locale'], {'~GAMEPLAY_ASPROXY_BE_997': ''})
        d = fixture().card(CARD)
        self.assertEqual((d.cost, d.attack, d.health), (2, 3, 2))
        self.assertEqual(d.metadata.classes, (CardClass.NEUTRAL,)); self.assertEqual(d.metadata.rarity, Rarity.EPIC)
        self.assertFalse(d.metadata.tribes)
        from hs_sim.cards import build_registry as assembled
        self.assertEqual(assembled().card(CARD), d)

    def test_actual_paid_minion_entry_does_not_trigger_from_old_initial_hand(self):
        g = self.game(hand=(CARD,), board=()); rng = g._rng.getstate(); source = self.play(g, CARD)
        self.assertEqual(g.state.players[1].mana, 18); self.assertIn(source, g.state.players[1].board)
        self.assertFalse(self.generated(g)); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_generated_hand_card_gives_both_spells_once_and_excludes_own_output(self):
        g = self.game(); self.play(g)
        made = self.generated(g); self.assertEqual([e.player_id for e in made], [1, 2])
        self.assertEqual((len(self.names(g)), len(self.names(g, 2))), (2, 1))
        self.assertTrue(all(g.state.entities[e.target_id].card_id in (S, T) for e in made)); self.portable(g)

    def test_draw_entry_uses_same_success_fact_and_no_extra_draws(self):
        g = self.game((P+'draw',)); self.play(g, 'draw')
        self.assertEqual(len(g.state.draw_history), 1); self.assertEqual(len(self.generated(g)), 2); self.portable(g)

    def test_natural_turn_draw_also_triggers_for_new_active_owner(self):
        g = self.game(hand=(), board=(), enemy_board=(CARD,)); g.apply(EndTurn(1))
        self.assertEqual([e.player_id for e in self.generated(g)], [2, 1]); self.portable(g)

    def test_opponent_only_receiving_a_card_does_not_trigger_own_observer(self):
        g = self.game((P+'gift',)); rng = g._rng.getstate(); self.play(g, 'gift')
        self.assertFalse(self.generated(g)); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_current_copy_and_hand_transfer_are_real_entries(self):
        for name in ('copy', 'move'):
            with self.subTest(name=name):
                g = self.game((P+name,), enemy_hand=(FILL,)); old = g.state.players[2].hand[0]
                source = self.play(g, name); self.assertEqual(len(self.generated(g)), 2)
                entry = next(r for r in g.state.hand_entries if r.source_id == source and r.reason != 'scenario')
                self.assertEqual(entry.player_id, 1)
                if name == 'move': self.assertEqual(entry.entity_id, old)
                else: self.assertEqual(g.state.entities[entry.entity_id].origin_entity_id, old)
                self.portable(g)

    def test_successful_board_return_triggers_without_guessing_a_source(self):
        g = self.game((P+'bounce',), board=(CARD, FILL)); target = g.state.players[1].board[1]
        self.play(g, 'bounce', target); self.assertEqual(len(self.generated(g)), 2)
        row = next(r for r in g.state.hand_entries if r.entity_id == target)
        self.assertEqual(row.reason, 'return'); self.assertIsNone(row.source_id); self.portable(g)

    def test_stored_transform_and_same_hand_move_do_not_invent_entries(self):
        for name in ('transform', 'same'):
            with self.subTest(name=name):
                g = self.game((P+name, FILL)); initial = tuple(g.state.hand_entries); rng = g._rng.getstate()
                self.play(g, name); self.assertEqual(tuple(g.state.hand_entries), initial)
                self.assertFalse(self.generated(g)); self.assertEqual(g._rng.getstate(), rng); self.portable(g)

    def test_silenced_or_removed_observer_does_not_generate(self):
        for name in ('silence', 'destroy', 'bounce'):
            with self.subTest(name=name):
                g = self.game((P+name, P+'get')); source = g.state.players[1].board[0]
                self.play(g, name, source); self.play(g)
                self.assertFalse(self.generated(g)); self.portable(g)

    def test_actual_overflow_creates_no_entry_and_does_not_retrigger(self):
        g = self.game((P+'double', FILL), enemy_hand=(FILL, FILL), capacity=2)
        self.play(g, 'double')
        self.assertEqual(len(self.generated(g)), 2)
        # First real entry fills the only slot; its generated own spell and the
        # second external request burn. Enemy output also burns, with no entry.
        self.assertEqual(len([e for e in g.events if e.kind == EVENT]), 1)
        self.assertEqual(len([e for e in g.events if e.kind == 'card_burned']), 3); self.portable(g)

    def test_random_generation_uses_two_independent_original_pool_draws(self):
        from random import Random
        g = self.game(); local = Random(); local.setstate(g._rng.getstate())
        candidates = resolve_candidates(g.registry, CTX, POOL, QUERY)
        expected = tuple(sample_candidates(local, candidates, 1, replacement=True)[0] for _ in range(2))
        self.play(g); actual = tuple(g.state.entities[e.target_id].card_id for e in self.generated(g))
        self.assertEqual(actual, expected); self.assertEqual(g._rng.getstate(), local.getstate()); self.portable(g)

    def test_generated_spell_later_played_draws_from_its_own_new_source(self):
        g = self.game(); self.play(g)
        spell = next(cid for cid in self.names(g) if cid in (S, T)); source = self.play(g, spell)
        self.assertEqual(len(self.generated(g)), 4)
        self.assertTrue(any(r.reason == 'draw' and r.source_id == source for r in g.state.hand_entries)); self.portable(g)

    def test_two_same_owner_physical_observers_exclude_only_their_own_sources(self):
        g = self.game(board=(CARD, CARD), capacity=3); sources = set(g.state.players[1].board); self.play(g)
        self.assertEqual(len(self.names(g)), 3)
        self.assertEqual({e.source_id for e in self.generated(g)}, sources); self.portable(g)

    def test_opposing_identical_observers_trigger_from_the_other_physical_source(self):
        g = self.game(enemy_board=(CARD,), capacity=3); self.play(g)
        self.assertEqual((len(self.names(g)), len(self.names(g, 2))), (3, 3))
        self.assertEqual(len({e.source_id for e in self.generated(g)}), 2); self.portable(g)

    def test_second_seat_owns_first_output_and_preserves_receiver_scope(self):
        g = self.game(actor=2); self.play(g)
        self.assertEqual([e.player_id for e in self.generated(g)], [2, 1]); self.portable(g)

    def choose(self, g, key):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def test_wait_before_body_restores_original_event_source_and_fails_atomically(self):
        g = self.game(mode='initial'); self.play(g); waiting = g.snapshot(); self.assertFalse(self.generated(g))
        other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), waiting)
        self.choose(g, 'ok'); self.assertEqual(len(self.generated(g)), 2); self.portable(g)

    def test_accepted_body_keeps_original_owner_after_observer_dies_or_transfers(self):
        for option in ('kill', 'take'):
            with self.subTest(option=option):
                g = self.game(mode='initial'); self.play(g); self.choose(g, option)
                self.assertEqual([e.player_id for e in g.events if e.kind == 'card_created' and e.source_id ==
                    next(i for i,e in g.state.entities.items() if e.card_id == CARD)], [1, 2]); self.portable(g)

    def test_wait_after_first_output_resumes_without_duplicate_card_or_rng(self):
        g = self.game(mode='delivery'); self.play(g); self.assertEqual(len(self.generated(g)), 1)
        waiting = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(other, 'fail')
        self.assertEqual(other.snapshot(), waiting)
        self.choose(g, 'ok'); self.assertEqual(len(self.generated(g)), 2); self.portable(g)

    def test_unknown_eligible_spell_rolls_back_instead_of_cropping_the_complete_pool(self):
        g = self.game(unknown=True); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_direct_body_without_original_event_is_explicit_failure(self):
        g = self.game((P+'bad',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'bad')
        self.assertEqual(g.snapshot(), before)

    def test_actual_rewind_retires_old_notifications_and_runs_new_panda_body(self):
        g = self.game((P+'rewind',)); self.play(g, 'rewind')
        old = tuple(r.entity_id for r in g.state.hand_entries if r.reason != 'scenario')
        self.assertEqual(len(old), 3); self.portable(g)
        self.choose(g, 'retry'); self.assertIsNone(g.state.pending_choice)
        current = tuple(r.entity_id for r in g.state.hand_entries if r.reason != 'scenario')
        self.assertEqual(len(current), 3); self.assertTrue(set(old).isdisjoint(current))
        self.assertEqual(len([e for e in g.events if e.kind == EVENT]), 6)
        self.assertEqual(len([e for e in effective_events(g.events) if e.kind == EVENT]), 3)
        self.portable(g)

    def test_fake_or_duplicate_native_publication_is_rejected(self):
        g = self.game(); self.play(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): Resolution(g).emit(EVENT, player_id=1)
        row = next(x for x in g.state.hand_entries if x.reason != 'scenario')
        with self.assertRaises(ValueError): publish(Resolution(g), row.id)
        self.assertEqual(g.snapshot(), before)

    def reject(self, snap):
        snap['events_hash'] = canonical_hash(snap['events'])
        snap['state_hash'] = canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error: Game.from_snapshot(snap, fixture(*self.config, 'reader'))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_rehashed_changed_source_hash_missing_or_duplicate_receipt_is_rejected(self):
        g = self.game(); self.play(g); saved = g.snapshot()
        index = next(i for i,e in enumerate(saved['events']) if e['kind'] == EVENT)
        bad = deepcopy(saved); row_id = bad['events'][index]['data']['hand_entry_id']
        bad['state']['hand_entries'][row_id-1]['source_id'] = g.state.players[2].hero_id; self.reject(bad)
        bad = deepcopy(saved); bad['events'][index]['data']['hand_entry_hash'] = '0'*64; self.reject(bad)
        bad = deepcopy(saved); bad['events'][index]['kind'] = 'fixture.not-an-entry'; self.reject(bad)
        bad = deepcopy(saved); event = deepcopy(bad['events'][index]); event['sequence'] = len(bad['events'])+1
        bad['events'].append(event); self.reject(bad)
        old = deepcopy(saved); old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture(*self.config, 'reader'))

    def test_waiting_captured_hand_source_cannot_be_replaced(self):
        from hs_sim.engine.continuations import FrameCodec
        g = self.game(mode='initial'); self.play(g)
        call = next(w for w in (*g._frame.prefix, *g._frame.continuation) if type(w) is BehaviorCall and w.behavior_id == BODY)
        state = deepcopy(call.context.state); row = from_event(state, call.context.event)
        state.hand_entries[row.id-1] = replace(row, source_id=state.players[2].hero_id)
        bad = replace(call, context=replace(call.context, state=state))
        with self.assertRaises(ValueError): FrameCodec(g.mechanics, g.registry).encode(bad)

    def test_temporary_copy_notifications_capture_the_complete_original_replacement(self):
        from test_temporary_hand_basics import TemporaryHandTests, ILLUCIA
        probe = TemporaryHandTests(); probe.setUp()
        def observer(c):
            entry = from_event(c.state, c.event)
            source = c.state.entities.get(entry.source_id)
            if entry.reason != 'created' or source is None or source.card_id != ILLUCIA: return ()
            if not c.state.temporary_hands:
                raise ResolutionError('Hand notification preceded original replacement acceptance')
            root = c.state.temporary_hands[-1]
            if tuple(c.state.players[entry.player_id].hand) != root.introduced:
                raise ResolutionError('Hand notification captured only a partial replacement')
            return ()
        probe.watch(EVENT, callback=observer); g = probe.game(board=('watch',)); probe.play(g)
        root = g.state.temporary_hands[-1]
        self.assertEqual(len([e for e in g.events if e.kind == EVENT and e.source_id == root.request.source_id]), len(root.introduced))
        probe.portable(g)

    def test_starting_hand_copy_notifications_capture_the_complete_original_group(self):
        from test_starting_hand_basics import StartingHandTests, FINS
        probe = StartingHandTests(); probe.setUp()
        def observer(c):
            entry = from_event(c.state, c.event); source = c.state.entities.get(entry.source_id)
            if entry.reason != 'created' or source is None or source.card_id != FINS: return ()
            if not c.state.temporary_hands:
                raise ResolutionError('Starting copy notification preceded original group acceptance')
            root = c.state.temporary_hands[-1]
            if tuple(c.state.players[entry.player_id].hand) != root.introduced:
                raise ResolutionError('Starting copy notification captured an incomplete group')
            return ()
        probe.options['watch'] = (EVENT, observer); g = probe.ready(probe.game()); probe.play(g)
        root = g.state.temporary_hands[-1]
        self.assertEqual(len([e for e in g.events if e.kind == EVENT and e.source_id == root.request.source_id]), len(root.introduced))
        probe.portable(g)


if __name__ == '__main__': unittest.main()
