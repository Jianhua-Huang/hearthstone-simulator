"""Native deck event listeners reuse stored progress and exact physical entry."""
from dataclasses import fields, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, EndTurn, Game,
    HandProgressSpec, Keyword, PlayCard, PlayerSetup, Rarity, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (ChoiceOption, Destroy, Draw, GainArmor,
    InvokeBehavior, RequestChoice, Summon)
from hs_sim.engine.hand_progress import AdvanceHandProgress, progress_ability
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.play_history import play_record
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.tribes import normalized
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, MoveCard, ReorderZone
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

NATIVE = 'CFM_637'
PATH = Path(__file__).resolve().parents[1] / 'data/support/deck-self-listener-basics.json'
PIN = 'f02357858cad5c2dbdc6660934a1a2657731b7a772229e58b112b76861c413e1'


def evidence():
    data = json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Deck self listener evidence changed')
    row = data['records'][0]
    if canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Deck self listener raw row changed')
    return row['data']


def own_pirate(c):
    if c.event is None or c.event.kind != 'card_played':
        return False
    play = play_record(c.state, dict(c.event.data)['play_id'])
    face = play.played_face
    if not (play.completed and not play.interrupted and
            play.player_id == c.player_id and play.kind == CardType.MINION):
        return False
    if face.metadata is None:
        raise ResolutionError('Played Pirate condition requires frozen minion tribe metadata')
    return normalized(face.metadata.tribes).matches_any(('pirate',))


def registry():
    r = Registry('isolated-deck-self-listener-basics-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=60, metadata=metadata()))
    for cid, tribes in (('plain', ()), ('pirate', ('pirate',)), ('all', ('all',))):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=1, health=5,
            metadata=metadata(tribes=tribes)))
    r.register_card(CardDefinition('unknown', 'Missing tribe metadata probe', CardType.MINION,
        attack=1, health=5))
    r.register_trigger_condition('own.pirate', own_pirate)
    spec = HandProgressSpec('event', on_complete='native.summon', repeat=True,
        event='card_played', condition_id='own.pirate', zone=Zone.DECK)
    r.register_behavior('native.summon', lambda c: (
        SummonStoredCard(CardReference.capture(c.state.entities[c.source_id]), c.player_id),))
    raw = evidence()
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], hand_progress=spec,
        metadata=metadata(CardClass.NEUTRAL, rarity=Rarity.LEGENDARY, tribes=('pirate',))))

    def source(c, zone=Zone.DECK):
        return next(c.state.entities[i] for i in getattr(c.state.players[c.player_id], zone.value)
                    if c.state.entities[i].card_id == NATIVE)

    def fault(c):
        raise RuntimeError('Deliberate deck listener fault')

    r.register_behavior('fault', fault)
    scripts = {
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'summon': lambda c: (Summon(c.player_id, 'pirate'),),
        'add': lambda c: (AddToDeck(c.player_id, NATIVE, 'bottom', c.source_id),),
        'copy': lambda c: (CopyCard(CardReference.capture(source(c)), c.player_id,
            Zone.DECK, position='bottom', source_id=c.source_id),),
        'buff': lambda c: (BuffStoredCard(CardReference.capture(source(c)), 3, 3, source_id=c.source_id),),
        'transfer': lambda c: (MoveCard(CardReference.capture(source(c)), 2, Zone.DECK, 'bottom', source_id=c.source_id),),
        'back': lambda c: (MoveCard(CardReference.capture(source(c, Zone.HAND)), c.player_id,
            Zone.DECK, 'bottom', source_id=c.source_id),),
        'clear': lambda c: tuple(Destroy(i, c.source_id) for i in c.state.players[c.player_id].board[:2]),
    }
    for cid, body in scripts.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))

    def options(c):
        return (ChoiceOption('ok', 'Continue'), ChoiceOption('fault', 'Fail',
            (InvokeBehavior('fault', c.source_id, c.player_id),)))

    def wait(c):
        return (RequestChoice(c.player_id, options(c), c.source_id),)

    def first(c):
        return (own_pirate(c) and
                sum(p.completed and p.kind == CardType.MINION and p.player_id == c.player_id
                    for p in c.state.play_history) == 1)

    def leave(c, back=False):
        if not first(c):
            return ()
        work = (MoveCard(CardReference.capture(source(c)), c.player_id, Zone.HAND, source_id=c.source_id),)
        if back:
            work += (InvokeBehavior('back', c.source_id, c.player_id),)
        return (*work, *wait(c))

    watchers = {
        'wait': lambda c: wait(c) if first(c) else (),
        'leave': lambda c: leave(c),
        'roundtrip': lambda c: leave(c, True),
        'reorder': lambda c: (ReorderZone(c.player_id, Zone.DECK,
            tuple(reversed(c.state.players[c.player_id].deck))),) if first(c) else (),
        'insert': lambda c: (AddToDeck(c.player_id, NATIVE, 'bottom', c.source_id),) if first(c) else (),
        'grow': lambda c: (BuffStoredCard(CardReference.capture(source(c)), 3, 3,
            source_id=c.source_id),) if first(c) else (),
        'latefault': lambda c: (InvokeBehavior('fault', c.source_id, c.player_id),)
            if c.event.source_id is not None and c.state.entities[c.event.source_id].card_id == NATIVE else (),
    }
    for cid, body in watchers.items():
        r.register_behavior('watch.' + cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=5,
            triggers=(TriggerSpec('minion_summoned' if cid == 'latefault' else 'card_played',
                                  'watch.' + cid),), metadata=metadata()))
    r.register_behavior('held.grow', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('held', 'Hand order probe', CardType.MINION, health=5,
        hand_progress=HandProgressSpec('event', event='card_played', on_complete='held.grow',
            repeat=True, condition_id='own.pirate'), metadata=metadata()))
    return r


class DeckSelfListenerTests(unittest.TestCase):
    def game(self, hand=('pirate',), *, deck=(NATIVE, 'plain'), board=(),
             enemy_hand=(), enemy_deck=('plain',), active_player=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, deck=enemy_deck, mana=10, max_mana=10),
        ), seed=55, active_player=active_player), registry())

    def ids(self, g, zone=Zone.DECK, player=1):
        return [i for i in getattr(g.state.players[player], zone.value)
                if g.state.entities[i].card_id == NATIVE]

    def play(self, g, cid='pirate', player=None):
        player = g.state.active_player if player is None else player
        eid = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, eid))
        return eid

    def choose(self, g, name='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (name,)))

    def portable(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        h = Game.from_snapshot(s, registry())
        self.assertEqual(h.snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), s)
        return h

    def rehash(self, s):
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def test_complete_raw_pin_and_exact_native_deck_declaration(self):
        raw = evidence()
        original = next(r for r in json.loads(
            (PATH.parents[1] / 'extracted/cards.json').read_text(encoding='utf-8')) if r['id'] == NATIVE)
        self.assertEqual(raw, original)
        card = registry().card(NATIVE)
        self.assertEqual((card.cost, card.attack, card.health), (1, 1, 1))
        self.assertEqual((card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            ((CardClass.NEUTRAL,), Rarity.LEGENDARY, ('pirate',)))
        self.assertEqual((card.hand_progress.zone, card.hand_progress.event,
            card.hand_progress.goal, card.hand_progress.repeat), (Zone.DECK, 'card_played', 1, True))
        self.assertNotIn(Keyword.CHARGE, card.keywords)
        self.assertNotIn('MAW_031', registry().cards)

    def test_native_summons_original_deck_entity_without_extra_payment_or_play(self):
        g = self.game()
        original = self.ids(g)[0]
        allocator = g.state.next_entity_id
        rng = g._rng.getstate()
        source = self.play(g)
        self.assertEqual(g.state.players[1].board, [source, original])
        self.assertEqual(g.state.next_entity_id, allocator)
        self.assertEqual((g.state.entities[original].owner, g.state.entities[original].controller,
            g.state.entities[original].zone), (1, 1, Zone.BOARD))
        self.assertEqual(g.state.players[1].mana, 9)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual(g.state.cast_history, [])
        self.assertEqual(g.state.draw_history, [])
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_native_in_hand_does_not_listen_to_pirate_play(self):
        g = self.game(('pirate', NATIVE), deck=('plain',))
        original = self.ids(g, Zone.HAND)[0]
        self.play(g)
        self.assertEqual(self.ids(g, Zone.HAND), [original])
        self.assertEqual(self.ids(g, Zone.BOARD), [])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_completions, 0)

    def test_native_manual_hand_play_has_no_extra_self_summon(self):
        g = self.game((NATIVE,), deck=('plain',))
        original = self.play(g, NATIVE)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
        self.assertEqual(len(g.state.play_history), 1)

    def test_opponent_pirate_play_does_not_activate_own_deck_listener(self):
        g = self.game((), enemy_hand=('pirate',), active_player=2)
        original = self.ids(g)[0]
        self.play(g, player=2)
        self.assertEqual(self.ids(g), [original])
        self.assertEqual(self.ids(g, Zone.BOARD), [])

    def test_nonpirate_play_does_not_advance_native_listener(self):
        g = self.game(('plain',))
        original = self.ids(g)[0]
        self.play(g, 'plain')
        self.assertEqual(self.ids(g), [original])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_keys, ())

    def test_missing_played_minion_metadata_is_an_error_not_a_nonpirate(self):
        g = self.game(('unknown',))
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'frozen minion tribe metadata'):
            self.play(g, 'unknown')
        self.assertEqual(g.snapshot(), before)

    def test_summoned_pirate_is_not_a_played_pirate(self):
        g = self.game(('summon',))
        original = self.ids(g)[0]
        self.play(g, 'summon')
        self.assertEqual(self.ids(g), [original])
        self.assertEqual(self.ids(g, Zone.BOARD), [])

    def test_frozen_all_tribe_minion_qualifies_as_a_pirate(self):
        g = self.game(('all',))
        original = self.ids(g)[0]
        self.play(g, 'all')
        self.assertEqual(self.ids(g, Zone.BOARD), [original])

    def test_each_existing_physical_deck_copy_listens_independently(self):
        g = self.game(deck=(NATIVE, 'plain', NATIVE))
        originals = self.ids(g)
        abilities = [progress_ability(g.state.entities[i]).id for i in originals]
        self.assertEqual(len(set(abilities)), 2)
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), originals)
        self.assertEqual(self.ids(g), [])
        self.portable(g)

    def test_full_board_failure_keeps_listener_eligible_for_a_later_play(self):
        g = self.game(('pirate', 'clear', 'pirate'), board=('plain',) * 6)
        original = self.ids(g)[0]
        self.play(g)
        ability = progress_ability(g.state.entities[original])
        self.assertEqual(self.ids(g), [original])
        self.assertFalse(ability.consumed)
        self.assertEqual(ability.progress_completions, 1)
        self.play(g, 'clear')
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_completions, 2)

    def test_last_slot_moves_first_captured_source_and_leaves_second_in_deck(self):
        g = self.game(deck=(NATIVE, NATIVE), board=('plain',) * 5)
        originals = self.ids(g)
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), originals[:1])
        self.assertEqual(self.ids(g), originals[1:])

    def test_current_deck_local_growth_survives_exact_physical_entry(self):
        g = self.game(('buff', 'pirate'))
        original = self.ids(g)[0]
        self.play(g, 'buff')
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
        self.assertEqual((g.state.entities[original].attack, g.state.entities[original].health), (4, 4))
        self.portable(g)

    def test_growth_after_capture_is_read_by_existing_physical_summon(self):
        g = self.game(board=('grow',))
        original = self.ids(g)[0]
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
        self.assertEqual((g.state.entities[original].attack, g.state.entities[original].health), (4, 4))

    def test_original_hand_listeners_keep_their_position_before_deck_listeners(self):
        g = self.game(('pirate', 'held'))
        self.play(g)
        armor = next(e.sequence for e in g.events if e.kind == 'armor_gained')
        summoned = next(e.sequence for e in g.events if e.kind == 'minion_summoned'
            and e.source_id in self.ids(g, Zone.BOARD))
        self.assertLess(armor, summoned)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)

    def test_reordered_deck_does_not_change_already_captured_source_order(self):
        g = self.game(deck=(NATIVE, NATIVE), board=('reorder',) + ('plain',) * 4)
        originals = self.ids(g)
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), originals[:1])
        self.assertEqual(self.ids(g), originals[1:])

    def test_source_created_after_capture_does_not_retroactively_listen(self):
        g = self.game(('pirate', 'pirate'), deck=(), board=('insert',))
        self.play(g)
        originals = self.ids(g)
        self.assertEqual(len(originals), 1)
        self.assertEqual(self.ids(g, Zone.BOARD), [])
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), originals)

    def test_new_source_added_to_deck_listens_without_an_opening_hook(self):
        g = self.game(('add', 'pirate'), deck=('plain',))
        self.play(g, 'add')
        original = self.ids(g)[0]
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])

    def test_current_deck_copy_preserves_native_zone_with_independent_identity(self):
        g = self.game(('copy', 'pirate'))
        original = self.ids(g)[0]
        self.play(g, 'copy')
        copies = self.ids(g)
        self.assertEqual(len(copies), 2)
        self.assertEqual(copies[0], original)
        self.assertEqual([progress_ability(g.state.entities[i]).hand_progress.zone for i in copies],
            [Zone.DECK, Zone.DECK])
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), copies)
        self.portable(g)

    def test_drawn_native_stops_listening_in_its_new_hand_residence(self):
        g = self.game(('draw', 'pirate'))
        original = self.ids(g)[0]
        old = progress_ability(g.state.entities[original]).id
        self.play(g, 'draw')
        self.assertNotEqual(progress_ability(g.state.entities[original]).id, old)
        self.play(g)
        self.assertEqual(self.ids(g, Zone.HAND), [original])
        self.assertEqual(self.ids(g, Zone.BOARD), [])

    def test_current_controller_is_used_after_cross_player_deck_transfer(self):
        g = self.game(('transfer',), enemy_hand=('pirate',))
        original = self.ids(g)[0]
        self.play(g, 'transfer')
        self.assertEqual(self.ids(g, player=2), [original])
        g.apply(EndTurn(1))
        self.play(g, player=2)
        self.assertEqual(self.ids(g, Zone.BOARD, 2), [original])
        e = g.state.entities[original]
        self.assertEqual((e.owner, e.controller), (1, 2))
        self.portable(g)

    def test_deck_candidate_and_zone_restore_through_waiting_clone_and_replay(self):
        g = self.game(board=('wait',))
        original = self.ids(g)[0]
        self.play(g)
        work = next(w for w in (*g._frame.prefix, *g._frame.continuation)
            if type(w) is AdvanceHandProgress and w.candidate.source_id == original)
        self.assertEqual(work.candidate.ability_id, progress_ability(g.state.entities[original]).id)
        h = self.portable(g)
        self.choose(g)
        self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot())
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
        self.portable(g)

    def test_candidate_leaving_deck_before_execution_is_skipped(self):
        g = self.game(board=('leave',))
        original = self.ids(g)[0]
        self.play(g)
        h = self.portable(g)
        self.choose(g)
        self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot())
        self.assertEqual(self.ids(g, Zone.HAND), [original])
        self.assertEqual(self.ids(g, Zone.BOARD), [])

    def test_departure_and_return_renews_identity_and_invalidates_old_witness(self):
        g = self.game(('pirate', 'pirate'), board=('roundtrip',))
        original = self.ids(g)[0]
        old = progress_ability(g.state.entities[original]).id
        self.play(g)
        new = progress_ability(g.state.entities[original]).id
        self.assertNotEqual(old, new)
        h = self.portable(g)
        self.choose(g)
        self.choose(h)
        self.assertEqual(g.snapshot(), h.snapshot())
        self.assertEqual(self.ids(g), [original])
        self.assertEqual(progress_ability(g.state.entities[original]).progress_keys, ())
        self.play(g)
        self.assertEqual(self.ids(g, Zone.BOARD), [original])

    def test_failed_choice_rolls_back_pending_deck_candidates_and_rng(self):
        g = self.game(board=('wait',))
        self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), before)
        self.choose(g)
        self.assertEqual(len(self.ids(g, Zone.BOARD)), 1)

    def test_late_summon_reaction_failure_rolls_back_entire_original_action(self):
        g = self.game(board=('latefault',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_deck_listener_bookkeeping_does_not_create_private_progress_events(self):
        g = self.game()
        self.play(g)
        self.assertFalse(any(e.kind in ('hand_progressed', 'hand_card_upgraded') for e in g.events))
        self.assertEqual(g.state.death_history, [])

    def test_default_hand_zone_and_existing_candidate_shape_are_preserved(self):
        spec = registry().card('held').hand_progress
        self.assertEqual(spec.zone, Zone.HAND)
        g = self.game(board=('wait',))
        self.play(g)
        work = next(w for w in (*g._frame.prefix, *g._frame.continuation) if type(w) is AdvanceHandProgress)
        self.assertEqual([f.name for f in fields(type(work.candidate))],
            ['source_id', 'ability_id', 'player_id'])

    def test_typed_zone_roundtrip_and_unknown_zone_rejection(self):
        g = self.game()
        spec = g.registry.card(NATIVE).hand_progress
        codec = FrameCodec(g.mechanics, g.registry)
        wire = codec.encode(spec)
        self.assertEqual(codec.decode(wire), spec)
        wire['fields']['zone']['value'] = 'unknown'
        with self.assertRaises(ValueError):
            codec.decode(wire)

    def test_deck_profile_rejects_unrequested_progress_and_upgrade_shapes(self):
        spec = registry().card(NATIVE).hand_progress
        for changes in ({'zone': 'deck'}, {'zone': Zone.GRAVEYARD},
                {'kind': 'infuse', 'event': None}, {'goal': 2}, {'repeat': False},
                {'upgrade_card_id': 'plain'}, {'on_progress': 'native.summon'},
                {'on_complete': None}, {'amount_basis': 'event_amount'}, {'health_to_durability': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(spec, **changes)

    def test_deck_native_source_kind_must_be_an_ordinary_minion(self):
        r = registry()
        spec = r.card(NATIVE).hand_progress
        for kind in (CardType.SPELL, CardType.WEAPON, CardType.HERO):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                r.validate_hand_progress(spec, kind)
        r.validate_hand_progress(spec, CardType.MINION)

    def test_strict_snapshot_requires_zone_and_rejects_invalid_saved_zone(self):
        g = self.game()
        original = self.ids(g)[0]
        for value in (None, 'board', 'unknown', True):
            s = g.snapshot()
            ability = next(a for a in s['state']['entities'][str(original)]['abilities']
                if a['kind'] == 'hand_progress')
            if value is None:
                del ability['hand_progress']['zone']
            else:
                ability['hand_progress']['zone'] = value
            self.rehash(s)
            with self.subTest(value=value), self.assertRaises(SnapshotError):
                Game.from_snapshot(s, registry())

    def test_current_schema_accepts_and_old_or_future_schemas_reject(self):
        g = self.game()
        self.assertEqual(g.snapshot()['schema_version'], 265)
        for version in (1, 198, 217, True):
            s = g.snapshot()
            s['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot(s, registry())

    def test_player_views_hide_deck_source_candidates_and_progress_witnesses(self):
        g = self.game(board=('wait',))
        original = self.ids(g)[0]
        before = g.snapshot()
        for player in (1, 2):
            port = g.for_player(player)
            view = json.dumps((port.observe(), port.legal_actions()))
            self.assertNotIn('"card_id": "' + NATIVE + '"', view)
            for key in ('progress_keys', 'progress_units', 'ability_id', 'candidate',
                        'zone_epoch', 'resolution_frame'):
                self.assertNotIn(key, view)
        self.assertEqual(g.snapshot(), before)
        self.play(g)
        self.assertNotIn('"card_id": "' + NATIVE + '"', json.dumps(g.observe(2)))
        self.choose(g)
        self.assertIn('"card_id": "' + NATIVE + '"', json.dumps(g.observe(2)))
        self.assertIsNone(next(e for e in g.observe(1)['players'][0]['board']
            if e['card_id'] == NATIVE).get('hand_progress'))
        self.assertEqual(self.ids(g, Zone.BOARD), [original])
