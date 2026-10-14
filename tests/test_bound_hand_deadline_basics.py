"""An original hand's nonmoving deadline and directly affected boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    ResolutionError, Scenario, ScheduleHandRemoval, SelectChoice, SnapshotError,
    SpellSchool, TriggerSpec, Zone, QueueTurns, SkipTurns)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy,
    RequestChoice, ReturnToHand, InvokeBehavior)
from hs_sim.engine.hand_deadlines import ExpireHandDeadline, ended_count
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'TID_718'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/bound-hand-deadline-basics.json'
PIN = '8fe25c8eb09dee87830c854db7401842bdbd1dc02a43e160aa1897f337ca9c13'


def evidence():
    data = json.loads(SUPPORT.read_bytes())
    if canonical_digest(data) != PIN or [r['id'] for r in data['records']] != [NATIVE, 'TID_718e']:
        raise ValueError('Complete hand deadline evidence changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete source or enchantment row changed')
    return {r['id']: r['data'] for r in data['records']}


def pause(player=1, effects=()):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', effects),))


def registry(scripts=(), watchers=()):
    r = opening_registry()
    raw = evidence()[NATIVE]
    r.register_behavior('deadline.native', lambda c: (ScheduleHandRemoval(3-c.player_id, 3, c.source_id, retirement='destroy'),))
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.SPELL, cost=raw['cost'],
        spell_school=SpellSchool.FIRE, on_play='deadline.native', metadata=metadata_from_record(raw)))
    for count in (1, 2, 3):
        name = 'mark.' + str(count)
        r.register_behavior(name, lambda c, n=count: (ScheduleHandRemoval(3-c.player_id, n, c.source_id),))
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    r.register_behavior('mark.self', lambda c: (ScheduleHandRemoval(c.player_id, 1, c.source_id),))
    r.register_card(CardDefinition('mark.self', 'Own hand deadline', CardType.SPELL,
        on_play='mark.self', metadata=metadata()))
    r.register_card(CardDefinition('mark.body', 'Independent source', CardType.MINION, health=3,
        battlecry='mark.1', metadata=metadata()))
    r.register_behavior('no.op', lambda c: ())
    r.register_card(CardDefinition('plain.spell', 'Private plain spell', CardType.SPELL,
        on_play='no.op', metadata=metadata()))
    r.register_card(CardDefinition('plain.weapon', 'Private plain weapon', CardType.WEAPON,
        attack=2, durability=2, metadata=metadata()))
    r.register_card(CardDefinition('plain.location', 'Private plain location', CardType.LOCATION,
        durability=2, on_use='no.op', metadata=metadata()))
    r.register_card(CardDefinition('plain.hero', 'Private hero card', CardType.HERO, health=30,
        hero_card=True, initial_hero_power='mage.power', metadata=metadata()))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    for name, event, callback in watchers:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.MINION, health=5,
            triggers=(TriggerSpec(event, name),), metadata=metadata()))
    return r


class BoundHandDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.watchers = []

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def watch(self, name, event, callback):
        self.watchers.append((name, event, callback))

    def game(self, hand=('mark.1',), enemy_hand=('card.1', 'card.2'), board=(), enemy_board=(), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.30',)*8, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.31',)*8, mana=10, max_mana=10)),
            seed=83, active_player=active), registry(self.scripts, self.watchers))

    def play(self, g, card='mark.1'):
        player = g.state.active_player
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(player, source))
        return source

    def end(self, g):
        g.apply(EndTurn(g.state.active_player))

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(self.scripts, self.watchers))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, self.watchers)).snapshot(), saved)
        return restored

    def reject(self, saved):
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), registry(self.scripts, self.watchers))

    def wire_nodes(self, value, name):
        found = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + name):
                found.append(value)
            for child in value.values():
                found.extend(self.wire_nodes(child, name))
        elif isinstance(value, list):
            for child in value:
                found.extend(self.wire_nodes(child, name))
        return found

    def due_wait(self):
        self.watch('end.wait', 'turn_ended', lambda c: (pause(),) if c.event.player_id == 2 else ())
        g = self.game(board=('end.wait',))
        self.play(g); self.end(g); self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        return g

    def test_request_is_strict_typed_positive_owner_end_count(self):
        for args in ((True, 1), (0, 1), (3, 1), (1, True), (1, 0), (1, -1), (1, 1.0), (1, '1'), (1, 1, True), (1, 1, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ScheduleHandRemoval(*args)

    def test_full_raw_pin_native_definition_and_evidence_only_enchantment(self):
        rows = evidence()
        all_rows = json.loads((SUPPORT.parents[1] / 'extracted/cards.json').read_bytes())
        for cid, row in rows.items():
            self.assertEqual(row, next(r for r in all_rows if r['id'] == cid))
        r = registry()
        self.assertEqual((r.card(NATIVE).kind, r.card(NATIVE).cost, r.card(NATIVE).spell_school),
            (CardType.SPELL, 4, SpellSchool.FIRE))
        self.assertNotIn('TID_718e', r.cards)
        self.assertIn('3 turns', rows[NATIVE]['text_en'])

    def test_complete_original_hand_of_all_playable_types_removed_without_death(self):
        g = self.game(enemy_hand=('card.1', 'plain.spell', 'plain.weapon', 'plain.location', 'plain.hero'))
        original = tuple(g.state.players[2].hand); rng = g._rng.getstate()
        self.play(g); root = g.state.hand_deadlines[0]
        self.assertEqual(tuple(t.entity_id for t in root.targets), original)
        self.assertEqual(tuple(g.state.players[2].hand), original)
        self.end(g); self.end(g)
        self.assertEqual(g.state.hand_deadlines[0].removed, original)
        self.assertTrue(all(g.state.entities[i].zone == Zone.SETASIDE for i in original))
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind in ('card_discarded', 'card_destroyed_in_deck') for e in g.events))
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_native_three_target_ends_preserves_payment_and_later_draws(self):
        g = self.game((NATIVE,)); original = tuple(g.state.players[2].hand)
        self.play(g, NATIVE)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual(len(g.state.cast_history), 1)
        for n in range(1, 4):
            self.end(g); self.end(g)
            self.assertEqual(ended_count(g.state, 2), n)
            self.assertEqual(g.state.hand_deadlines[0].expired_event is not None, n == 3)
        self.assertEqual(g.state.hand_deadlines[0].removed, original)
        self.assertTrue(all(i not in original for i in g.state.players[2].hand))
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in original))
        self.assertEqual(len(g.state.hand_deadlines[0].destruction_events), len(original))
        self.assertTrue(g.state.players[2].hand)
        self.portable(g)

    def test_empty_original_root_does_not_mark_future_draw_or_consume_rng(self):
        g = self.game(enemy_hand=()); rng = g._rng.getstate()
        self.play(g); self.assertEqual(g.state.hand_deadlines[0].targets, ())
        self.end(g); drawn = tuple(g.state.players[2].hand); self.end(g)
        self.assertEqual(tuple(g.state.players[2].hand), drawn)
        self.assertFalse(g.state.hand_deadlines[0].removed)
        self.assertIsNotNone(g.state.hand_deadlines[0].expired_event)
        self.assertFalse(any(e.kind == 'cards_removed_from_game' for e in g.events))
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_second_player_and_own_hand_use_the_actual_target_owner(self):
        g = self.game(('card.1',), enemy_hand=('mark.1',), active=2)
        original = tuple(g.state.players[1].hand); self.play(g); self.end(g)
        self.assertIsNone(g.state.hand_deadlines[0].expired_event)
        self.end(g); self.assertEqual(g.state.hand_deadlines[0].removed, original)
        own = self.game(('mark.self', 'card.2')); original = tuple(own.state.players[1].hand[1:])
        self.play(own, 'mark.self'); self.end(own)
        self.assertEqual(own.state.hand_deadlines[0].removed, original)
        self.portable(g); self.portable(own)

    def test_true_extra_turns_advance_and_skipped_slots_do_not(self):
        self.script('extra', lambda c: (QueueTurns((2,), c.source_id),))
        self.script('skip', lambda c: (SkipTurns(2, 1, c.source_id),))
        g = self.game(('mark.2', 'extra')); self.play(g, 'mark.2'); self.play(g, 'extra')
        self.end(g); self.end(g)
        self.assertEqual(g.state.active_player, 2)
        self.assertIsNone(g.state.hand_deadlines[0].expired_event)
        self.end(g); self.assertIsNotNone(g.state.hand_deadlines[0].expired_event)
        h = self.game(('mark.1', 'skip')); self.play(h); self.play(h, 'skip'); self.end(h)
        self.assertEqual((h.state.active_player, ended_count(h.state, 2)), (1, 0))
        self.assertIsNone(h.state.hand_deadlines[0].expired_event)
        self.end(h); self.end(h); self.assertIsNotNone(h.state.hand_deadlines[0].expired_event)
        self.portable(g); self.portable(h)

    def test_new_acquisitions_and_actual_copy_are_distinct_original_targets(self):
        self.script('copy', lambda c: (CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]), 2),
            AddToHand(2, 'card.1')))
        g = self.game(('mark.1', 'copy'), enemy_hand=('card.1',)); original = g.state.players[2].hand[0]
        self.play(g); self.play(g, 'copy'); later = tuple(g.state.players[2].hand[1:])
        self.end(g); self.end(g)
        self.assertEqual(g.state.hand_deadlines[0].removed, (original,))
        self.assertTrue(all(i in g.state.players[2].hand for i in later))
        self.assertEqual(g.state.entities[later[0]].origin_entity_id, original)
        self.portable(g)

    def test_played_original_is_not_removed_from_board(self):
        g = self.game(); self.play(g); self.end(g); body = self.play(g, 'card.1'); self.end(g)
        self.assertIn(body, g.state.players[2].board)
        self.assertNotIn(body, g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_returned_same_physical_card_does_not_reacquire_original_deadline(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[2].board[0]),))
        g = self.game(enemy_hand=('card.1', 'bounce')); body = g.state.players[2].hand[0]
        self.play(g); epoch = g.state.hand_deadlines[0].targets[0].zone_epoch
        self.end(g); self.play(g, 'card.1'); self.play(g, 'bounce'); self.end(g)
        self.assertIn(body, g.state.players[2].hand)
        self.assertGreater(g.state.entities[body].zone_epoch, epoch)
        self.assertNotIn(body, g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_hand_transform_invalidates_original_face_reference(self):
        self.script('transform', lambda c: (TransformCapturedMinion(
            CardReference.capture(c.state.entities[c.state.players[2].hand[0]]), 'card.3'),))
        g = self.game(('mark.1', 'transform')); target = g.state.players[2].hand[0]
        self.play(g); self.play(g, 'transform'); self.end(g); self.end(g)
        self.assertIn(target, g.state.players[2].hand)
        self.assertEqual(g.state.entities[target].card_id, 'card.3')
        self.assertNotIn(target, g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_departure_to_deck_invalidates_original_hand_reference(self):
        self.script('move', lambda c: (MoveCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]),
            2, Zone.DECK, position='bottom'),))
        g = self.game(('mark.1', 'move')); target = g.state.players[2].hand[0]
        self.play(g); self.play(g, 'move'); self.end(g); self.end(g)
        self.assertIn(target, g.state.players[2].deck)
        self.assertNotIn(target, g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_source_death_does_not_cancel_independent_accepted_deadline(self):
        self.script('kill', lambda c: (Destroy(c.state.players[1].board[0]),))
        g = self.game(('mark.body', 'kill')); source = self.play(g, 'mark.body')
        self.play(g, 'kill'); self.end(g); self.end(g)
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertTrue(g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_independent_same_due_roots_close_in_order_without_duplicate_removal(self):
        g = self.game(('mark.1', 'mark.1')); original = tuple(g.state.players[2].hand)
        self.play(g); self.play(g); self.end(g); self.end(g)
        self.assertEqual([r.removed for r in g.state.hand_deadlines], [original, ()])
        self.assertEqual([dict(e.data)['deadline_id'] for e in g.events if e.kind == 'hand_deadline_expired'], [1, 2])
        self.assertEqual(sum(e.kind == 'cards_removed_from_game' for e in g.events), 1)
        self.portable(g)

    def test_later_accepted_root_keeps_its_own_later_end_count(self):
        g = self.game(('mark.2', 'mark.2')); self.play(g, 'mark.2'); self.end(g); self.end(g)
        self.play(g, 'mark.2')
        self.assertEqual([r.owner_ends_at_accept for r in g.state.hand_deadlines], [0, 1])
        self.end(g); self.end(g)
        self.assertEqual([r.expired_event is not None for r in g.state.hand_deadlines], [True, False])
        self.end(g); self.end(g)
        self.assertTrue(all(r.expired_event is not None for r in g.state.hand_deadlines))
        self.portable(g)

    def test_wait_before_acceptance_captures_choice_acquired_card(self):
        self.script('before', lambda c: (pause(effects=(AddToHand(2, 'card.3'),)), ScheduleHandRemoval(2, 1, c.source_id)))
        g = self.game(('before',)); self.play(g, 'before')
        self.assertFalse(g.state.hand_deadlines); restored = self.portable(g)
        self.choose(g); self.choose(restored); self.assertEqual(g.snapshot(), restored.snapshot())
        added = g.state.players[2].hand[-1]
        self.assertIn(added, [t.entity_id for t in g.state.hand_deadlines[0].targets])
        self.end(g); self.end(g); self.assertIn(added, g.state.hand_deadlines[0].removed)
        self.portable(g)

    def test_wait_after_acceptance_preserves_original_group(self):
        self.script('after', lambda c: (ScheduleHandRemoval(2, 1, c.source_id), pause(effects=(AddToHand(2, 'card.3'),))))
        g = self.game(('after',)); self.play(g, 'after'); original = tuple(g.state.players[2].hand)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); added = g.state.players[2].hand[-1]
        self.end(g); self.end(g)
        self.assertEqual(g.state.hand_deadlines[0].removed, original)
        self.assertIn(added, g.state.players[2].hand)
        self.portable(g)

    def test_due_end_choice_keeps_original_expiry_restore_clone_and_replay(self):
        g = self.due_wait(); original = tuple(t.entity_id for t in g.state.hand_deadlines[0].targets)
        self.assertTrue(all(i in g.state.players[2].hand for i in original))
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.hand_deadlines[0].removed, original)
        self.assertEqual(g.state.active_player, 1)
        self.portable(g)

    def test_removal_reaction_wait_occurs_after_atomic_deadline_closure(self):
        self.watch('removal.wait', 'cards_removed_from_game', lambda c: (pause(),))
        g = self.game(board=('removal.wait',)); self.play(g); self.end(g); self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertIsNotNone(g.state.hand_deadlines[0].expired_event)
        self.assertTrue(g.state.hand_deadlines[0].removed)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_deadline_created_by_end_reaction_excludes_already_published_end(self):
        self.watch('create.at.end', 'turn_ended', lambda c: (ScheduleHandRemoval(2, 1, c.source_id),)
            if c.event.player_id == 2 and not c.state.hand_deadlines else ())
        g = self.game((), board=('create.at.end',)); self.end(g); self.end(g)
        self.assertEqual(g.state.hand_deadlines[0].owner_ends_at_accept, 1)
        self.assertIsNone(g.state.hand_deadlines[0].expired_event)
        self.portable(g); self.end(g); self.end(g)
        self.assertIsNotNone(g.state.hand_deadlines[0].expired_event)
        self.portable(g)

    def test_late_action_failure_rolls_back_entire_end_and_deadline(self):
        self.watch('removal.fault', 'cards_removed_from_game', lambda c: (AddToHand(1, 'missing.deadline'),))
        g = self.game(board=('removal.fault',)); self.play(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.deadline'):
            self.end(g)
        self.assertEqual(g.snapshot(), before)

    def test_failed_choice_restores_due_end_frame_and_can_continue(self):
        self.script('selection.fault', lambda c: (AddToHand(1, 'missing.deadline'),))
        self.watch('end.fault.choice', 'turn_ended', lambda c: (RequestChoice(1, (
            ChoiceOption('bad', 'Fail', (InvokeBehavior('selection.fault', c.source_id, c.player_id),)), ChoiceOption('ok', 'Continue'))),)
            if c.event.player_id == 2 else ())
        g = self.game(board=('end.fault.choice',)); self.play(g); self.end(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.deadline'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertTrue(g.state.hand_deadlines[0].removed)

    def test_public_countdowns_preserve_opaque_enemy_slots_and_hide_receipts(self):
        g = self.game(('mark.2',), enemy_hand=('plain.spell', 'plain.weapon')); self.play(g, 'mark.2')
        for viewer in (1, 2):
            observed = g.observe(viewer)
            enemy_or_own = observed['players'][1]['hand']
            self.assertTrue(all(v['hand_deadlines'] == [2] for v in enemy_or_own))
        private = json.dumps([g.observe(1), g.player_events(1), g.for_player(1).legal_actions()], ensure_ascii=False)
        for text in ('Private plain spell', 'plain.spell', 'plain.weapon', 'deadline_id', 'owner_ends_at_accept',
                     'hand_deadline_armed', 'source_card_id', 'zone_epoch'):
            self.assertNotIn(text, private)
        self.end(g); self.assertEqual(g.observe(1)['players'][1]['hand'][0]['hand_deadlines'], [2])
        self.end(g); self.assertEqual(g.observe(1)['players'][1]['hand'][0]['hand_deadlines'], [1])

    def test_player_projections_are_pure_and_no_stale_countdown_after_departure(self):
        g = self.game(); self.play(g); before = g.snapshot()
        for p in (1, 2):
            g.observe(p); g.player_events(p); g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(), before)
        self.end(g); body = self.play(g, 'card.1')
        self.assertNotIn('hand_deadlines', next(v for v in g.observe(1)['players'][1]['board']
            if v['card_id'] == 'card.1'))
        self.assertIn(body, g.state.players[2].board)

    def test_snapshot_schema_and_public_payload_roundtrip_are_explicit(self):
        g = self.game(); self.play(g)
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (265, 'prototype-v302', CORE_EFFECTS_VERSION))
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        request = ScheduleHandRemoval(2, 3, g.state.hand_deadlines[0].request.source_id)
        wire = codec.encode(request); self.assertEqual(codec.decode(wire), request)
        for field, value in (('owner_ends', True), ('player_id', 3), ('invented', 0)):
            bad = deepcopy(wire); bad['fields'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                codec.decode(bad)
        for schema in (1, 215, 217):
            saved = g.snapshot(); saved['schema_version'] = schema
            self.reject(saved)

    def test_rehashed_history_rejects_malformed_request_reference_and_original_counter(self):
        g = self.game(); self.play(g)
        changes = (lambda r: r['request'].update(owner_ends=True),
            lambda r: r.update(owner_ends_at_accept=1),
            lambda r: r['targets'][0].update(player_id=1),
            lambda r: r['targets'][0].update(card_id='missing.card'),
            lambda r: r['targets'][0].update(zone_epoch=999),
            lambda r: r['targets'].append(deepcopy(r['targets'][0])),
            lambda r: r.update(extra=True))
        for change in changes:
            saved = g.snapshot(); change(saved['state']['hand_deadlines'][0]); self.reject(saved)

    def test_rehashed_snapshot_cannot_drop_root_or_borrow_closure_receipt(self):
        g = self.game(('mark.1', 'mark.1')); self.play(g); self.play(g); self.end(g); self.end(g)
        saved = g.snapshot(); saved['state']['hand_deadlines'].clear(); self.reject(saved)
        saved = g.snapshot(); roots = saved['state']['hand_deadlines']
        roots[1]['expired_event'] = roots[0]['expired_event']; self.reject(saved)
        saved = g.snapshot(); saved['state']['hand_deadlines'][0]['removed'].reverse(); self.reject(saved)

    def test_due_continuation_cannot_omit_or_duplicate_original_expiry(self):
        g = self.due_wait()
        for mode in ('drop', 'duplicate'):
            saved = g.snapshot()
            node = self.wire_nodes(saved['resolution_frame'], 'ExpireHandDeadline')[0]
            if mode == 'drop':
                node['type'] = 'hs_sim.engine.effects.AddToHand'
                node['fields'] = {'player_id': 1, 'card_id': 'card.1', 'source_id': None,
                    'revealed_to': {'tuple': []}, 'cost': None, 'expires_turn': None,
                    'spell_repeat': None, 'choose_branch': None}
            else:
                def duplicate(value):
                    if isinstance(value, list) and any(v is node for v in value):
                        value.append(deepcopy(node)); return True
                    if isinstance(value, (dict, list)):
                        return any(duplicate(v) for v in (value.values() if isinstance(value, dict) else value))
                    return False
                self.assertTrue(duplicate(saved['resolution_frame']))
            self.reject(saved)

    def test_due_continuation_cannot_change_original_end_or_root_identity(self):
        g = self.due_wait()
        for field, value in (('owner_end_event', 1), ('deadline_id', 2)):
            saved = g.snapshot(); self.wire_nodes(saved['resolution_frame'], 'ExpireHandDeadline')[0]['fields'][field] = value
            self.reject(saved)

    def test_terminal_end_reaction_stops_expiry_and_retains_private_original_root(self):
        self.watch('end.lethal', 'turn_ended', lambda c: (Damage(c.state.players[1].hero_id, 30, c.source_id),)
            if c.event.player_id == 2 else ())
        g = self.game(board=('end.lethal',)); original = tuple(g.state.players[2].hand)
        self.play(g); self.end(g); self.end(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertIsNone(g.state.hand_deadlines[0].expired_event)
        self.assertTrue(all(i in g.state.players[2].hand for i in original))
        self.assertFalse(any(e.kind == 'hand_deadline_expired' for e in g.events))
        self.portable(g)

    def test_unknown_source_fails_without_accepting_any_deadline(self):
        self.script('bad.source', lambda c: (ScheduleHandRemoval(2, 1, 99999),))
        g = self.game(('bad.source',)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'source does not exist'):
            self.play(g, 'bad.source')
        self.assertEqual(g.snapshot(), before)
