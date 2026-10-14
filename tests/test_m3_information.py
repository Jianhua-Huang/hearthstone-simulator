"""Player observations must not change when only hidden engine details change."""
from copy import deepcopy
from dataclasses import dataclass
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, PlayCard, PlayerSetup,
                          Registry, ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Draw, Effect, GainArmor, ModifyCost,
                                   RequestChoice, ReturnToHand, RevealHandCard, ShuffleIntoDeck, Summon,
                                   Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from opening_fixtures import registry as opening_registry, setup


@dataclass(frozen=True)
class PrivateWork(Effect):
    pass


def private_work(r, effect):
    hidden = r.state.entities[r.state.players[2].hand[0]]
    if hidden.card_id == 'rare':
        for _ in range(3):
            r.create_entity(2, 'plain', Zone.GRAVEYARD)
            r.game._rng.random()
            r.emit('extension_debug', target_id=hidden.id, private_card='rare', rng=r.game._rng.getstate())
    return [Summon(1, 'plain')]


def rehash(snapshot):
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})


class InformationTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('information-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        self.registry.register_card(CardDefinition('plain', 'Plain', CardType.MINION, cost=1, attack=2, health=3))
        self.registry.register_card(CardDefinition('rare', 'Rare', CardType.MINION, cost=9, attack=9, health=9))

    def script(self, name, fn):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def game(self, hand=(), enemy_hand=('rare',), deck=('plain', 'rare'), enemy_deck=('rare', 'plain'),
             board=(), enemy_board=(), mechanics=None, rules=None, seed=19):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, deck=deck, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, deck=enemy_deck, board=enemy_board, mana=10, max_mana=10)
        ), seed=seed), self.registry, mechanics=mechanics, ruleset=rules)

    def cast(self, game, name=None):
        state = game.state
        entity_id = next(i for i in state.players[1].hand if name is None or state.entities[i].card_id == name)
        return game.apply(PlayCard(1, entity_id))

    def select(self, game, options):
        choice = game.state.pending_choice
        return game.apply(SelectChoice(choice.player_id, choice.id, options))

    def portable(self, game):
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), self.registry, game.mechanics)
        clones = (restored, game.clone(), replay(build_replay(game), self.registry, game.mechanics))
        for clone in clones:
            self.assertEqual(clone.snapshot(), game.snapshot())
            for viewer in (1, 2):
                self.assertEqual(clone.observe(viewer), game.observe(viewer))
                self.assertEqual(clone.player_events(viewer), game.player_events(viewer))
        return restored

    def test_own_hand_visible_enemy_hand_back_both_decks_counts_only(self):
        game = self.game(hand=('plain',))
        own, enemy = game.observe(1)['players']
        self.assertEqual(own['hand'][0]['card_id'], 'plain')
        self.assertEqual(own['hand'][0]['cost'], {'amount': 1, 'payment': 'mana'})
        self.assertEqual(set(enemy['hand'][0]), {'ref', 'card_id'})
        self.assertIsNone(enemy['hand'][0]['card_id'])
        self.assertEqual([own['deck_count'], enemy['deck_count']], [2, 2])
        self.assertNotIn('deck', own)
        self.assertNotIn('rare', json.dumps(game.observe(1)))

    def test_hidden_cards_deck_order_and_seed_do_not_affect_observation(self):
        a = self.game(hand=('plain',))
        b = self.game(hand=('plain',), enemy_hand=('plain',), deck=('rare', 'plain'),
                      enemy_deck=('plain', 'rare'), seed=721)
        self.assertEqual(a.observe(1), b.observe(1))
        self.assertNotEqual(a.state_hash(), b.state_hash())

    def test_no_engine_ids_rng_frames_attachments_or_hashes_in_player_dto(self):
        game = self.game(hand=('plain',), board=('rare',))
        encoded = json.dumps(game.observe(1))
        for key in ('entity_id', 'rng_state', 'resolution_frame', 'next_entity_id', 'origin_entity_id',
                    'death_history', 'enchantments', 'abilities', 'state_hash', 'action_number', 'match_setup'):
            self.assertNotIn(f'"{key}"', encoded)
        self.assertIsInstance(game.observe(1)['players'][0]['hero']['ref'], str)

    def test_unknown_events_hidden_entity_creation_and_rng_work_do_not_leak(self):
        self.script('work', lambda c: [PrivateWork()])
        mechanics = default_mechanics('private-work-v1').register(PrivateWork, private_work)
        a = self.game(hand=('work',), enemy_hand=('plain',), mechanics=mechanics)
        b = self.game(hand=('work',), enemy_hand=('rare',), mechanics=mechanics)
        self.cast(a)
        self.cast(b)
        self.assertNotEqual(a.state.players[1].board, b.state.players[1].board)
        self.assertNotEqual(len(a.events), len(b.events))
        self.assertEqual(a.observe(1), b.observe(1))
        self.assertEqual(a.player_events(1), b.player_events(1))
        self.portable(b)

    def test_draw_logs_capture_identity_at_event_time(self):
        self.script('draw', lambda c: [Draw(2)])
        game = self.game(hand=('draw',), enemy_hand=(), enemy_deck=('rare',))
        self.cast(game)
        old = game.player_events(1)
        drawn = next(e for e in old if e['kind'] == 'card_drawn')
        self.assertIsNone(drawn['target']['card_id'])
        self.assertEqual(next(e for e in game.player_events(2) if e['kind'] == 'card_drawn')['target']['card_id'], 'rare')
        game.apply(EndTurn(1))
        entity_id = game.state.players[2].hand[0]
        game.apply(PlayCard(2, entity_id))
        self.assertEqual(game.player_events(1)[:len(old)], old)
        committed = next(e for e in game.player_events(1) if e['kind'] == 'card_committed' and e['player_id'] == 2)
        self.assertEqual(committed['source']['card_id'], 'rare')
        self.assertEqual(committed['source']['ref'], drawn['target']['ref'])
        self.portable(game)

    def test_public_spell_is_revealed_even_when_it_immediately_leaves_hand(self):
        self.script('spell', lambda c: [GainArmor(1, 1)])
        game = self.game(hand=('spell',))
        self.assertIsNone(game.observe(2)['players'][0]['hand'][0]['card_id'])
        self.cast(game)
        self.assertEqual(game.observe(2)['players'][0]['known_graveyard'][0]['card_id'], 'spell')
        self.assertEqual(next(e for e in game.player_events(2) if e['kind'] == 'card_committed')['source']['card_id'], 'spell')

    def test_return_remembers_identity_without_exposing_hidden_modified_cost(self):
        self.script('bounce', lambda c: [ReturnToHand(c.state.players[2].board[0])])
        self.script('discount', lambda c: [ModifyCost(c.state.players[2].hand[0], CostSpec(delta=-8))])
        game = self.game(hand=('bounce', 'discount'), enemy_hand=(), enemy_board=('rare',))
        ref = game.observe(1)['players'][1]['board'][0]['ref']
        self.cast(game, 'bounce')
        known = game.observe(1)['players'][1]['hand'][0]
        self.assertEqual(known, {'ref': ref, 'card_id': 'rare'})
        self.cast(game, 'discount')
        self.assertEqual(game.observe(1)['players'][1]['hand'][0], known)
        self.assertEqual(game.observe(2)['players'][1]['hand'][0]['cost']['amount'], 1)
        self.portable(game)

    def test_shuffle_retires_hand_handles_for_both_players_before_redraw(self):
        self.script('cycle', lambda c: [ShuffleIntoDeck(c.state.players[2].hand[0]), Draw(2)])
        game = self.game(hand=('cycle',), enemy_deck=())
        refs = [game.observe(v)['players'][1]['hand'][0]['ref'] for v in (1, 2)]
        self.cast(game)
        for viewer, old_ref in zip((1, 2), refs):
            self.assertNotEqual(game.observe(viewer)['players'][1]['hand'][0]['ref'], old_ref)
            shuffled = next(e for e in game.player_events(viewer) if e['kind'] == 'card_shuffled')
            self.assertIsNone(shuffled['target'])
            self.assertNotIn('position', json.dumps(shuffled))
        self.assertIsNone(game.observe(1)['players'][1]['hand'][0]['card_id'])
        self.portable(game)

    def test_shuffle_of_revealed_card_forgets_tracking_but_preserves_old_log(self):
        self.script('reveal', lambda c: [RevealHandCard(c.state.players[2].hand[0])])
        self.script('cycle', lambda c: [ShuffleIntoDeck(c.state.players[2].hand[0]), Draw(2)])
        game = self.game(hand=('reveal', 'cycle'), enemy_deck=())
        self.cast(game, 'reveal')
        before = game.player_events(1)
        self.cast(game, 'cycle')
        self.assertIsNone(game.observe(1)['players'][1]['hand'][0]['card_id'])
        self.assertEqual(game.player_events(1)[:len(before)], before)

    def test_public_burn_reveals_identity_without_revealing_remaining_deck(self):
        self.script('draw', lambda c: [Draw(2)])
        game = self.game(hand=('draw',), enemy_hand=('plain',), enemy_deck=('rare', 'plain'), rules=Ruleset(max_hand=1))
        self.cast(game)
        self.assertEqual(game.observe(1)['players'][1]['known_graveyard'][0]['card_id'], 'rare')
        self.assertEqual(next(e for e in game.player_events(1) if e['kind'] == 'card_burned')['target']['card_id'], 'rare')
        self.assertEqual(game.observe(1)['players'][1]['deck_count'], 1)

    def test_generated_hand_card_is_private_until_explicit_reveal(self):
        self.script('generate', lambda c: [AddToHand(2, 'rare')])
        game = self.game(hand=('generate',), enemy_hand=())
        self.cast(game)
        self.assertIsNone(game.observe(1)['players'][1]['hand'][0]['card_id'])
        self.assertNotIn('rare', json.dumps(game.player_events(1)))
        self.assertIn('rare', json.dumps(game.player_events(2)))

    def test_generated_hand_identity_can_be_explicitly_public(self):
        self.script('generate', lambda c: [AddToHand(2, 'rare', revealed_to=(1, 2))])
        game = self.game(hand=('generate',), enemy_hand=())
        self.cast(game)
        self.assertEqual(game.observe(1)['players'][1]['hand'][0]['card_id'], 'rare')
        added = next(e for e in game.player_events(1) if e['kind'] == 'card_added_to_hand')
        self.assertEqual(added['target']['card_id'], 'rare')
        self.portable(game)

    def test_generated_hand_recipients_are_validated(self):
        for viewers in ((True,), (3,), (1, 1), [1]):
            with self.assertRaises(ValueError):
                AddToHand(2, 'rare', revealed_to=viewers)

    def test_transform_updates_current_public_face_but_not_historical_face(self):
        self.script('make', lambda c: [Summon(2, 'plain')])
        self.script('change', lambda c: [Transform(c.state.players[2].board[0], 'rare')])
        game = self.game(hand=('make', 'change'), enemy_hand=())
        self.cast(game, 'make')
        old = game.player_events(1)
        old_ref = game.observe(1)['players'][1]['board'][0]['ref']
        self.cast(game, 'change')
        new = game.observe(1)['players'][1]['board'][0]
        self.assertEqual((new['ref'], new['card_id']), (old_ref, 'rare'))
        self.assertEqual(game.player_events(1)[:len(old)], old)

    def test_private_choices_hide_options_prompt_ids_and_continuation(self):
        self.script('choose', lambda c: [RequestChoice(2, (
            ChoiceOption('internal-99', 'private-label', (GainArmor(2, 7),), card_id='rare'),
        ), prompt='private-prompt'), AddToHand(2, 'rare')])
        game = self.game(hand=('choose',))
        self.cast(game)
        self.assertEqual(game.observe(1)['pending_choice'], {'player_id': 2})
        private = game.observe(2)['pending_choice']
        self.assertEqual(private['ref'], 'c1')
        self.assertEqual(private['options'][0]['ref'], 'o1')
        self.assertEqual(private['options'][0]['label'], 'private-label')
        for field in ('private-label', 'private-prompt', 'internal-99', 'rare', 'GainArmor', 'resolution_frame'):
            self.assertNotIn(field, json.dumps([game.observe(1), game.player_events(1)]))
        self.assertNotIn('internal-99', json.dumps([game.observe(2), game.player_events(2)]))
        restored = self.portable(game)
        for instance in (game, restored):
            self.select(instance, ('internal-99',))
        self.assertEqual(game.snapshot(), restored.snapshot())
        own_selected = next(e for e in game.player_events(2) if e['kind'] == 'choice_selected')
        enemy_selected = next(e for e in game.player_events(1) if e['kind'] == 'choice_selected')
        self.assertEqual(own_selected['selected'], {'ref': 'c1', 'options': ['o1']})
        self.assertIsNone(enemy_selected['selected'])

    def test_choices_dont_expose_hidden_deck_entity_references(self):
        self.script('choose', lambda c: [RequestChoice(1, (
            ChoiceOption(str(c.state.players[2].deck[0]), 'Peek option', entity_id=c.state.players[2].deck[0]),
        ))])
        game = self.game(hand=('choose',))
        self.cast(game)
        option = game.observe(1)['pending_choice']['options'][0]
        self.assertEqual(option, {'ref': 'o1', 'label': 'Peek option', 'card_id': None, 'entity': None})

    def test_opponent_hidden_option_cardinality_does_not_change_its_view(self):
        self.script('choose', lambda c: [RequestChoice(2, tuple(
            ChoiceOption(f'private-{n}', f'private-{n}', (GainArmor(2, n),))
            for n in range(1, 4 if c.state.entities[c.state.players[2].hand[0]].card_id == 'rare' else 2)
        ))])
        a = self.game(hand=('choose',), enemy_hand=('plain',))
        b = self.game(hand=('choose',), enemy_hand=('rare',))
        self.cast(a)
        self.cast(b)
        self.assertEqual(a.observe(1), b.observe(1))
        self.assertEqual(a.player_events(1), b.player_events(1))
        self.assertNotEqual(a.observe(2)['pending_choice'], b.observe(2)['pending_choice'])

    def test_reveal_only_to_specified_player(self):
        self.script('peek', lambda c: [RevealHandCard(c.state.players[2].hand[0], (1,))])
        game = self.game(hand=('peek',))
        self.cast(game)
        self.assertEqual(game.observe(1)['players'][1]['hand'][0]['card_id'], 'rare')
        self.assertIn('card_revealed', [e['kind'] for e in game.player_events(1)])
        self.assertNotIn('card_revealed', [e['kind'] for e in game.player_events(2)])
        self.portable(game)

    def test_reveal_then_failing_effect_does_not_commit_knowledge_or_logs(self):
        self.script('fail', lambda c: [RevealHandCard(c.state.players[2].hand[0]), Summon(1, 'missing')])
        game = self.game(hand=('fail',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(game)
        self.assertEqual(game.snapshot(), before)
        self.assertIsNone(game.observe(1)['players'][1]['hand'][0]['card_id'])

    def test_selection_failure_keeps_private_choice_mapping_and_logs(self):
        self.script('choose', lambda c: [RequestChoice(1, (
            ChoiceOption('fail', 'Fail', (RevealHandCard(c.state.players[2].hand[0]),
                                        RevealHandCard(c.state.players[1].hero_id))),
        ))])
        game = self.game(hand=('choose',))
        self.cast(game)
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.select(game, ('fail',))
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_projection_and_logs_are_detached_read_only_and_use_local_cursors(self):
        self.script('plain-effect', lambda c: [GainArmor(1, 1)])
        game = self.game(hand=('plain-effect',))
        self.cast(game)
        before = game.snapshot()
        view = game.observe(1)
        logs = game.player_events(1)
        view['players'][1]['hand'][0]['card_id'] = 'injected'
        logs[0]['kind'] = 'injected'
        self.assertEqual(game.snapshot(), before)
        all_logs = game.player_events(1)
        self.assertEqual([e['sequence'] for e in all_logs], list(range(1, len(all_logs) + 1)))
        self.assertEqual(game.player_events(1, after=2), all_logs[2:])
        self.assertEqual(game.player_events(1, after=game.observe(1)['event_cursor']), [])

    def test_invalid_viewers_and_cursors_fail_without_changes(self):
        game = self.game()
        before = game.snapshot()
        for viewer in (True, False, 0, 3, '1', None):
            with self.subTest(viewer=viewer):
                with self.assertRaises(ValueError):
                    game.observe(viewer)
                with self.assertRaises(ValueError):
                    game.player_events(viewer)
        for after in (True, -1, 1, '0'):
            with self.assertRaises(ValueError):
                game.player_events(1, after=after)
        self.assertEqual(game.snapshot(), before)

    def test_ended_game_does_not_automatically_reveal_hands_and_decks(self):
        self.script('finish', lambda c: [Damage(c.state.players[2].hero_id, 30)])
        game = self.game(hand=('finish',))
        self.cast(game)
        self.assertEqual(game.observe(1)['status'], 'finished')
        self.assertNotIn('rare', json.dumps([game.observe(1), game.player_events(1)]))
        self.portable(game)

    def test_rehashed_malformed_ledger_rejected(self):
        game = self.game(hand=('plain',))
        base = game.snapshot()
        mutations = (
            lambda k: k.update(next_ref=True),
            lambda k: k['refs'].update({str(game.state.players[1].deck[0]): 'e999'}),
            lambda k: k['refs'].update({'bad': 'e1'}),
            lambda k: k['known'].clear(),
            lambda k: k.update(next_choice=False),
            lambda k: k.update(pending={'internal_id': 1, 'option_ids': [], 'ref': 'c1'}),
            lambda k: k.update(events=[{'kind': 'extension_debug'}]),
        )
        for mutate in mutations:
            snapshot = deepcopy(base)
            mutate(snapshot['information']['players']['1'])
            rehash(snapshot)
            with self.subTest(snapshot=snapshot['information']['players']['1']):
                with self.assertRaises(SnapshotError):
                    Game.from_snapshot(snapshot, self.registry)

    def test_knowledge_and_filtered_logs_participate_in_state_hash(self):
        self.script('peek', lambda c: [RevealHandCard(c.state.players[2].hand[0])])
        game = self.game(hand=('peek',))
        self.cast(game)
        for field in ('known', 'events'):
            snapshot = game.snapshot()
            if field == 'known':
                snapshot['information']['players']['1']['known'].pop(str(game.state.players[2].hand[0]))
            else:
                snapshot['information']['players']['1']['events'][-1]['amount'] = 100
            with self.assertRaisesRegex(SnapshotError, 'digest mismatch'):
                Game.from_snapshot(snapshot, self.registry)

    def test_schema_ten_cannot_silently_start_without_knowledge_history(self):
        snapshot = self.game().snapshot()
        snapshot['schema_version'] = 10
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot'):
            Game.from_snapshot(snapshot, self.registry)

    def test_private_damage_source_does_not_identify_an_enemy_hand_slot(self):
        self.script('hit', lambda c: [Damage(c.state.players[1].hero_id, 1, c.state.players[2].hand[0])])
        game = self.game(hand=('hit',))
        self.cast(game)
        damage = next(e for e in game.player_events(1) if e['kind'] == 'damage_dealt')
        self.assertIsNone(damage['source'])
        self.assertIsNotNone(damage['target'])
        self.assertEqual(next(e for e in game.player_events(2) if e['kind'] == 'damage_dealt')['source']['card_id'], 'rare')

    def test_engine_diagnostic_fields_are_not_copied_into_public_damage_log(self):
        self.script('hit', lambda c: [Damage(c.state.players[2].hero_id, 2, c.source_id)])
        game = self.game(hand=('hit',))
        self.cast(game)
        damage = next(e for e in game.player_events(2) if e['kind'] == 'damage_dealt')
        self.assertEqual(damage['amount'], 2)
        self.assertEqual(set(damage), {'sequence', 'kind', 'player_id', 'amount', 'source', 'target', 'choice', 'selected'})
        self.assertTrue(dict(next(e for e in game.events if e.kind == 'damage_dealt').data))

    def test_observe_rejected_while_a_handler_is_running(self):
        self.script('work', lambda c: [PrivateWork()])
        mechanics = default_mechanics('boundary-probe-v1').register(PrivateWork, lambda r, e: r.game.observe(1))
        game = self.game(hand=('work',), mechanics=mechanics)
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'completed action boundary'):
            self.cast(game)
        self.assertEqual(game.snapshot(), before)

    def test_reveal_effect_rejects_malformed_recipients_and_non_hand_target(self):
        for viewers in ((), (True,), (3,), (1, 1), [1]):
            with self.assertRaises(ValueError):
                RevealHandCard(1, viewers)
        self.script('peek', lambda c: [RevealHandCard(c.state.players[2].deck[0])])
        game = self.game(hand=('peek',))
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'current hand card'):
            self.cast(game)
        self.assertEqual(game.snapshot(), before)


class OpeningInformationTests(unittest.TestCase):
    def test_mulligan_exposes_only_own_options_and_retires_rejected_handles(self):
        registry = opening_registry()
        game = Game.from_decks(setup(registry), registry)
        before = game.observe(1)
        self.assertEqual(len(before['pending_choice']['options']), 3)
        self.assertEqual(game.observe(2)['pending_choice'], {'player_id': 1})
        old = before['players'][0]['hand'][0]['ref']
        first = game.state.pending_choice
        game.apply(SelectChoice(1, first.id, (first.options[0].id,)))
        self.assertEqual(game.observe(1)['pending_choice'], {'player_id': 2})
        self.assertEqual(game.observe(2)['pending_choice']['ref'], 'c1')
        second = game.state.pending_choice
        game.apply(SelectChoice(2, second.id, ()))
        self.assertNotIn(old, [c['ref'] for c in game.observe(1)['players'][0]['hand']])
        for viewer in (1, 2):
            enemy_hand = game.observe(viewer)['players'][2-viewer]['hand']
            self.assertTrue(all(c['card_id'] in (None, 'coin') for c in enemy_hand))
        self.assertEqual(game.observe(1)['players'][1]['hand'][-1]['card_id'], 'coin')
        restored = replay(build_replay(game), registry)
        self.assertEqual(restored.observe(1), game.observe(1))
        self.assertEqual(restored.player_events(2), game.player_events(2))


if __name__ == '__main__':
    unittest.main()
