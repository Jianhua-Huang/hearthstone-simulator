"""Seat authorization, observable revisions and noninterfering legal commands."""
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError
import json
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, Keyword, PlayCard, PlayerSetup,
                          Registry, Ruleset, Scenario, SelectChoice, SnapshotError, TargetMode, TargetSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Draw, Effect, GainArmor, ModifyCost, RefreshHeroPower,
                                   RequestChoice, RevealHandCard, ShuffleIntoDeck, Summon)
from hs_sim.engine.player_api import visible_entities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics


@dataclass(frozen=True)
class PublishPair(Effect):
    pass


def publish_pair(r, effect):
    secret = r.state.entities[r.state.players[2].hand[0]].card_id
    names = ('plain', 'big') if secret == 'plain' else ('big', 'plain')
    if secret == 'big':
        r.create_entity(2, 'plain', Zone.GRAVEYARD)
        r.game._rng.random()
        r.emit('private_debug', secret='big')
    for card in names:
        r.create_entity(1, card, Zone.BOARD, ready=True)
    r.state.players[1].board.sort(key=lambda i: r.state.entities[i].card_id)
    r.emit('fixture_board_ready')


class PlayerApiTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('player-api-tests-v1')
        for card in (CardDefinition('hero', 'Hero', CardType.HERO, health=30),
                     CardDefinition('plain', 'Plain', CardType.MINION, cost=1, attack=2, health=3),
                     CardDefinition('big', 'Big', CardType.MINION, cost=6, attack=6, health=8),
                     CardDefinition('guard', 'Guard', CardType.MINION, cost=2, attack=1, health=4, keywords=(Keyword.TAUNT,))):
            self.registry.register_card(card)

    def script(self, name, fn, **kwargs):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kwargs))

    def power(self, *, use='always', **kwargs):
        self.registry.register_behavior('power', lambda c: [GainArmor(c.player_id, 1)])
        self.registry.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='power', use_rule=use, **kwargs))

    def game(self, hand=(), enemy_hand=('big',), board=(), enemy_board=(), deck=('plain', 'big'),
             enemy_deck=('big', 'plain'), power=None, seed=19, mechanics=None, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10, hero_power_card_id=power),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, deck=enemy_deck, mana=10, max_mana=10)
        ), seed=seed), self.registry, mechanics=mechanics, ruleset=rules)

    def send(self, port, action, revision=None):
        return port.submit({'revision': revision or port.observe()['revision'], 'action': action})

    def first(self, port, kind):
        result = port.legal_actions()
        self.assertIsNone(result['error'])
        return next(a for a in result['actions'] if a['type'] == kind)

    def portable(self, game):
        clones = (game.clone(), Game.from_snapshot(json.loads(json.dumps(game.snapshot())), self.registry, game.mechanics),
                  replay(build_replay(game), self.registry, game.mechanics))
        for clone in clones:
            self.assertEqual(clone.snapshot(), game.snapshot())
            for viewer in (1, 2):
                self.assertEqual(clone.for_player(viewer).legal_actions(), game.for_player(viewer).legal_actions())
        return clones[1]

    def test_ports_bind_seats_and_reject_boolean_or_unknown_viewers(self):
        game = self.game()
        for viewer in (True, 0, 3, '1', None):
            with self.assertRaises(ValueError):
                game.for_player(viewer)
        with self.assertRaises(FrozenInstanceError):
            game.for_player(1).viewer = 2
        self.assertEqual(game.for_player(2).observe()['observation']['viewer'], 2)

    def test_play_returns_only_filtered_dtos(self):
        game = self.game(hand=('plain',))
        port = game.for_player(1)
        action = self.first(port, 'play_card')
        result = self.send(port, action)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['observation']['players'][0]['board'][0]['card_id'], 'plain')
        self.assertNotEqual(result['revision'], game.state_hash())
        encoded = json.dumps(result)
        for field in ('state_hash', 'entity_id', 'target_id', 'action_number', 'rng_state', 'resolution_frame', 'modifier_ids'):
            self.assertNotIn(f'"{field}"', encoded)
        self.assertNotIn('big', encoded)
        self.assertEqual(result['events'], port.events())
        self.portable(game)

    def test_revision_and_legal_actions_depend_only_on_visible_information(self):
        self.script('hit', lambda c: [Damage(c.target_id, 1)], requires_target=True)
        a = self.game(hand=('hit',), board=('plain',), enemy_board=('guard',))
        b = self.game(hand=('hit',), board=('plain',), enemy_board=('guard',), enemy_hand=('plain',),
                      deck=('big', 'plain'), enemy_deck=('plain', 'big'), seed=99)
        self.assertNotEqual(a.state_hash(), b.state_hash())
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())

    def test_hidden_creation_ids_do_not_change_action_order_or_revision(self):
        self.script('publish', lambda c: [PublishPair()])
        self.script('hit', lambda c: [Damage(c.target_id, 1)], requires_target=True)
        mechanics = default_mechanics('publish-pair-v1').register(PublishPair, publish_pair)
        a = self.game(hand=('publish', 'hit'), enemy_hand=('plain',), mechanics=mechanics)
        b = self.game(hand=('publish', 'hit'), enemy_hand=('big',), mechanics=mechanics)
        for game in (a, b):
            game.apply(PlayCard(1, game.state.players[1].hand[0]))
        self.assertNotEqual(a.state.players[1].board, b.state.players[1].board)
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())
        self.assertEqual(a.for_player(1).events(), b.for_player(1).events())
        self.portable(b)

    def test_predicate_receives_only_detached_player_context(self):
        def friendly(context):
            self.assertFalse(hasattr(context, 'state'))
            self.assertFalse(hasattr(context, 'source_id'))
            self.assertEqual(set(context.__dict__), {'player_id', 'observation', 'source', 'target'})
            target = deepcopy(context.target)
            context.observation['players'][1]['hand'].clear()
            context.source['card_id'] = 'mutated'
            context.target['controller'] = 99
            return target['controller'] == context.player_id and target['zone'] == 'board'
        self.registry.register_target_rule('friendly', friendly, visibility='player')
        self.script('buff', lambda c: [GainArmor(1, 1)], requires_target=True, target_rule='friendly')
        game = self.game(hand=('buff',), board=('plain',), enemy_board=('big',))
        before = game.snapshot()
        port = game.for_player(1)
        actions = port.legal_actions()['actions']
        own = port.observe()['observation']['players'][0]['board'][0]['ref']
        self.assertEqual([a['target'] for a in actions if a['type'] == 'play_card'], [own])
        self.assertEqual(game.snapshot(), before)
        self.assertTrue(self.send(port, self.first(port, 'play_card'))['accepted'])

    def test_legacy_target_predicate_is_never_called_by_player_queries_or_submission(self):
        calls = []
        self.registry.register_target_rule('secret-rule', lambda c: calls.append('ran') or True)
        self.script('spell', lambda c: [], requires_target=True, target_rule='secret-rule')
        game = self.game(hand=('spell',))
        port = game.for_player(1)
        before = game.snapshot()
        result = port.legal_actions()
        self.assertEqual((result['actions'], result['error']), (None, 'unsupported_rule'))
        body = {'type': 'play_card', 'card': result['observation']['players'][0]['hand'][0]['ref'],
                'target': result['observation']['players'][1]['hero']['ref']}
        self.assertEqual(self.send(port, body)['error'], 'unsupported_rule')
        self.assertEqual(calls, [])
        self.assertEqual(game.snapshot(), before)
        self.assertTrue(game.legal_targets(game.state.players[1].hand[0]))
        self.assertTrue(calls)

    def test_unsupported_card_does_not_disable_direct_end_turn(self):
        self.registry.register_target_rule('legacy', lambda c: True)
        self.script('spell', lambda c: [], requires_target=True, target_rule='legacy')
        port = self.game(hand=('spell',)).for_player(1)
        self.assertEqual(port.legal_actions()['error'], 'unsupported_rule')
        self.assertTrue(self.send(port, {'type': 'end_turn'})['accepted'])

    def test_legacy_use_predicate_is_blocked_before_evaluation(self):
        calls = []
        self.registry.register_use_rule('private', lambda c: calls.append('ran') or True)
        self.power(use='private')
        port = self.game(power='power').for_player(1)
        self.assertEqual(port.legal_actions()['error'], 'unsupported_rule')
        power = port.observe()['observation']['players'][0]['hero_power']['ref']
        self.assertEqual(self.send(port, {'type': 'use_hero_power', 'power': power})['error'], 'unsupported_rule')
        self.assertEqual(calls, [])

    def test_player_use_predicate_and_authoritative_validation_share_context(self):
        self.registry.register_use_rule('once-ever-this-turn', lambda c: (
            c.target is None and c.observation['players'][c.player_id-1]['hero_power_uses_this_turn'] == 0), visibility='player')
        self.power(use='once-ever-this-turn')
        self.script('refresh', lambda c: [RefreshHeroPower(1)])
        game = self.game(hand=('refresh',), power='power')
        port = game.for_player(1)
        self.assertTrue(self.send(port, self.first(port, 'use_hero_power'))['accepted'])
        self.assertTrue(self.send(port, self.first(port, 'play_card'))['accepted'])
        self.assertEqual(port.observe()['observation']['players'][0]['hero_power_uses_this_turn'], 1)
        self.assertFalse(any(a['type'] == 'use_hero_power' for a in port.legal_actions()['actions']))
        self.assertFalse(any(type(a).__name__ == 'UseHeroPower' for a in game.legal_actions()))

    def test_hidden_hand_targets_use_backs_without_revealing_card_type(self):
        self.script('other-spell', lambda c: [])
        self.registry.register_target_rule('back', lambda c: c.target['zone'] == 'hand', visibility='player')
        self.script('reduce', lambda c: [ModifyCost(c.target_id, CostSpec(delta=-1))], target_rule='back',
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION, CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO), relation='enemy'))
        a = self.game(hand=('reduce',), enemy_hand=('big',))
        b = self.game(hand=('reduce',), enemy_hand=('other-spell',))
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())
        for game in (a, b):
            port = game.for_player(1)
            result = self.send(port, self.first(port, 'play_card'))
            self.assertTrue(result['accepted'])
            committed = next(e for e in result['events'] if e['kind'] == 'card_committed')
            self.assertIsNone(committed['target']['card_id'])
            self.assertEqual(committed['source']['card_id'], 'reduce')
        self.assertEqual(a.for_player(1).observe(), b.for_player(1).observe())
        self.assertEqual(a.for_player(1).events(), b.for_player(1).events())

    def test_type_filtered_enemy_hand_is_explicitly_unsupported_even_when_empty(self):
        self.script('select-minion', lambda c: [], target_rule='any_entity',
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='enemy'))
        for enemy in ((), ('big',)):
            port = self.game(hand=('select-minion',), enemy_hand=enemy).for_player(1)
            self.assertEqual(port.legal_actions()['error'], 'unsupported_target_domain')

    def test_own_hand_conditions_can_read_current_visible_cost(self):
        self.registry.register_target_rule('cheap', lambda c: c.target['cost']['amount'] == 1, visibility='player')
        self.script('select-own', lambda c: [], target_rule='cheap',
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), relation='friendly'))
        port = self.game(hand=('select-own', 'plain', 'big')).for_player(1)
        own = port.observe()['observation']['players'][0]['hand']
        targets = [a['target'] for a in port.legal_actions()['actions'] if a['type'] == 'play_card' and a['card'] == own[0]['ref']]
        self.assertEqual(targets, [own[1]['ref']])

    def test_deck_and_graveyard_domains_are_not_silently_filtered(self):
        self.script('deck', lambda c: [], target_rule='any_entity',
                    targeting=TargetSpec(zones=(Zone.DECK,), kinds=(CardType.MINION,)))
        self.script('graveyard', lambda c: [], target_rule='any_entity',
                    targeting=TargetSpec(zones=(Zone.GRAVEYARD,), kinds=(CardType.MINION,)))
        for card in ('deck', 'graveyard'):
            game = self.game(hand=(card,))
            self.assertEqual(game.for_player(1).legal_actions()['error'], 'unsupported_target_domain')

    def test_enemy_hand_cannot_be_probed_by_forging_a_play_source(self):
        self.registry.register_target_rule('secret-rule', lambda c: True)
        self.script('legacy-spell', lambda c: [], requires_target=True, target_rule='secret-rule')
        a = self.game(enemy_hand=('plain',))
        b = self.game(enemy_hand=('legacy-spell',))
        replies = []
        for game in (a, b):
            port = game.for_player(1)
            enemy = port.observe()['observation']['players'][1]['hand'][0]['ref']
            before = game.snapshot()
            replies.append(self.send(port, {'type': 'play_card', 'card': enemy}))
            self.assertEqual(game.snapshot(), before)
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(replies[0]['error'], 'invalid_action')

    def test_attack_respects_taunt_and_uses_only_visible_handles(self):
        game = self.game(board=('big',), enemy_board=('guard', 'plain'))
        port = game.for_player(1)
        guard = port.observe()['observation']['players'][1]['board'][0]['ref']
        attacks = [a for a in port.legal_actions()['actions'] if a['type'] == 'attack']
        self.assertEqual(len(attacks), 1)
        self.assertEqual(attacks[0]['defender'], guard)
        self.assertTrue(self.send(port, attacks[0])['accepted'])
        self.assertEqual(len(game.state.players[2].board), 1)

    def test_summoning_readiness_is_observable_and_still_authoritative(self):
        game = self.game(hand=('plain',))
        port = game.for_player(1)
        self.send(port, self.first(port, 'play_card'))
        self.assertTrue(port.observe()['observation']['players'][0]['board'][0]['summoned_this_turn'])
        self.assertFalse(any(a['type'] == 'attack' for a in port.legal_actions()['actions']))

    def test_inactive_seat_cannot_enumerate_or_submit_active_player_actions(self):
        game = self.game(hand=('plain',))
        port = game.for_player(2)
        self.assertEqual(port.legal_actions()['actions'], [{'type': 'concede'}])
        before = game.snapshot()
        self.assertEqual(self.send(port, {'type': 'end_turn'})['error'], 'invalid_action')
        self.assertEqual(game.snapshot(), before)

    def test_accepted_action_retires_old_observable_revision(self):
        game = self.game(hand=('plain', 'plain'))
        port = game.for_player(1)
        listing = port.legal_actions()
        command = {'revision': listing['revision'], 'action': next(a for a in listing['actions'] if a['type'] == 'play_card')}
        self.assertTrue(port.submit(command)['accepted'])
        before = game.snapshot()
        reply = port.submit(command)
        self.assertEqual(reply['error'], 'stale_observation')
        self.assertEqual(reply['events'], [])
        self.assertEqual(game.snapshot(), before)

    def test_guessed_internal_ids_unknown_fields_and_bad_values_fail_without_changes(self):
        game = self.game(hand=('plain',))
        port = game.for_player(1)
        card = port.observe()['observation']['players'][0]['hand'][0]['ref']
        bodies = [None, {}, {'type': 'play_card', 'card': 4}, {'type': 'play_card', 'entity_id': 4},
                  {'type': 'end_turn', 'player_id': 2}, {'type': 'play_card', 'card': card, 'position': True},
                  {'type': 'play_card', 'card': card, 'position': -1}, {'type': 'play_card', 'card': card, 'target': 'e99999'},
                  {'type': 'attack', 'attacker': True, 'defender': card}, {'type': 'give_mana', 'amount': 10}]
        before = game.snapshot()
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.send(port, body)['error'], 'invalid_action')
                self.assertEqual(game.snapshot(), before)
        for command in ({}, {'revision': True, 'action': {'type': 'end_turn'}},
                        {'revision': port.observe()['revision'], 'action': {'type': 'end_turn'}, 'viewer': 2}):
            self.assertEqual(port.submit(command)['error'], 'invalid_action')
        self.assertEqual(game.snapshot(), before)

    def test_washed_hand_reference_is_not_usable_even_with_fresh_revision(self):
        self.script('cycle', lambda c: [ShuffleIntoDeck(c.state.players[1].hand[-1]), Draw(1)])
        game = self.game(hand=('cycle', 'plain'), deck=())
        port = game.for_player(1)
        old = port.observe()['observation']['players'][0]['hand'][-1]['ref']
        self.send(port, self.first(port, 'play_card'))
        self.assertNotEqual(port.observe()['observation']['players'][0]['hand'][0]['ref'], old)
        self.assertEqual(self.send(port, {'type': 'play_card', 'card': old})['error'], 'invalid_action')

    def test_choices_use_seat_local_option_ids_and_can_belong_to_other_player(self):
        self.script('choose', lambda c: [RequestChoice(2, (ChoiceOption('secret-internal', 'Armor', (GainArmor(2, 4),)),))])
        game = self.game(hand=('choose',))
        self.send(game.for_player(1), self.first(game.for_player(1), 'play_card'))
        one, two = game.for_player(1), game.for_player(2)
        self.assertEqual(one.legal_actions()['actions'], [{'type': 'concede'}])
        action = self.first(two, 'select_choice')
        self.assertEqual(action, {'type': 'select_choice', 'choice': 'c1', 'options': ['o1']})
        self.assertNotIn('secret-internal', json.dumps(two.legal_actions()))
        self.assertTrue(self.send(two, action)['accepted'])
        self.assertEqual(game.state.entities[game.state.players[2].hero_id].armor, 4)
        self.portable(game)

    def test_other_players_hidden_choice_cardinality_does_not_change_api_reply(self):
        self.script('choose', lambda c: [RequestChoice(2, tuple(
            ChoiceOption(f'option-{i}', str(i)) for i in range(3 if c.state.entities[c.state.players[2].hand[0]].card_id == 'big' else 1)))])
        a, b = self.game(hand=('choose',), enemy_hand=('plain',)), self.game(hand=('choose',), enemy_hand=('big',))
        for game in (a, b):
            port = game.for_player(1)
            self.send(port, self.first(port, 'play_card'))
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())

    def test_stale_choice_and_repeated_or_internal_options_are_rejected(self):
        choice = lambda: RequestChoice(1, (ChoiceOption('inside', 'One'), ChoiceOption('other', 'Two')))
        self.script('choose', lambda c: [choice(), choice()])
        game = self.game(hand=('choose',))
        port = game.for_player(1)
        self.send(port, self.first(port, 'play_card'))
        for options in (['inside'], ['o1', 'o1'], ['o99'], [True], 'o1'):
            self.assertEqual(self.send(port, {'type': 'select_choice', 'choice': 'c1', 'options': options})['error'], 'invalid_action')
        action = self.first(port, 'select_choice')
        self.assertTrue(self.send(port, action)['accepted'])
        self.assertEqual(self.send(port, action)['error'], 'invalid_action')
        self.assertEqual(port.observe()['observation']['pending_choice']['ref'], 'c2')

    def test_choice_enumeration_limit_still_allows_direct_valid_selection(self):
        self.script('choose', lambda c: [RequestChoice(1, tuple(ChoiceOption(str(i), str(i)) for i in range(16)), min_count=8, max_count=8)])
        game = self.game(hand=('choose',))
        port = game.for_player(1)
        self.send(port, self.first(port, 'play_card'))
        self.assertEqual(port.legal_actions()['error'], 'enumeration_limit')
        self.assertTrue(self.send(port, {'type': 'select_choice', 'choice': 'c1', 'options': [f'o{i}' for i in range(1, 9)]})['accepted'])

    def test_if_available_target_rule_uses_same_observation_for_host_and_player(self):
        self.registry.register_target_rule('damaged', lambda c: c.target['health'] < c.target['max_health'], visibility='player')
        self.script('conditional', lambda c: [], target_rule='damaged', targeting=TargetSpec(mode=TargetMode.IF_AVAILABLE))
        game = self.game(hand=('conditional',))
        port = game.for_player(1)
        self.assertIsNone(self.first(port, 'play_card')['target'])
        self.assertTrue(self.send(port, self.first(port, 'play_card'))['accepted'])

    def test_error_payloads_do_not_include_private_predicate_messages(self):
        def broken(c):
            raise RuntimeError('PRIVATE-CARD-INTERNAL-ID-999')
        self.registry.register_target_rule('broken', broken, visibility='player')
        self.script('spell', lambda c: [], requires_target=True, target_rule='broken')
        game = self.game(hand=('spell',))
        port = game.for_player(1)
        before = game.snapshot()
        listing = port.legal_actions()
        self.assertEqual(listing['error'], 'rule_error')
        view = listing['observation']
        result = self.send(port, {'type': 'play_card', 'card': view['players'][0]['hand'][0]['ref'], 'target': view['players'][1]['hero']['ref']})
        self.assertEqual(result['error'], 'resolution_failed')
        self.assertNotIn('PRIVATE-CARD', json.dumps([listing, result]))
        self.assertEqual(game.snapshot(), before)

    def test_resolution_failure_rolls_back_private_reveals_and_returns_no_raw_error(self):
        self.script('fail', lambda c: [RevealHandCard(c.state.players[2].hand[0]), RevealHandCard(c.state.players[1].hero_id)])
        game = self.game(hand=('fail',))
        port = game.for_player(1)
        before = game.snapshot()
        result = self.send(port, self.first(port, 'play_card'))
        self.assertEqual(result['error'], 'resolution_failed')
        self.assertEqual(result['events'], [])
        self.assertNotIn('big', json.dumps(result))
        self.assertEqual(game.snapshot(), before)

    def test_player_choice_submission_restores_and_replays_with_same_revision(self):
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('armor', 'Armor', (GainArmor(1, 2),)),))])
        game = self.game(hand=('choose',))
        port = game.for_player(1)
        self.send(port, self.first(port, 'play_card'))
        restored = self.portable(game)
        command = {'revision': port.observe()['revision'], 'action': self.first(port, 'select_choice')}
        self.assertEqual(port.submit(command), restored.for_player(1).submit(command))
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_legal_queries_and_returned_dtos_do_not_mutate_game(self):
        game = self.game(hand=('plain',))
        port = game.for_player(1)
        before = game.snapshot()
        listing = port.legal_actions()
        listing['actions'].clear()
        listing['observation']['players'][0]['hand'].clear()
        self.assertTrue(port.legal_actions()['actions'])
        self.assertEqual(game.snapshot(), before)

    def test_registration_scope_is_fingerprinted_and_cannot_claim_builtin(self):
        a, b = Registry('same'), Registry('same')
        a.register_target_rule('target', lambda c: True)
        b.register_target_rule('target', lambda c: True, visibility='player')
        self.assertNotEqual(a.fingerprint(), b.fingerprint())
        for scope in ('builtin', 'public', True):
            with self.assertRaises(ValueError):
                self.registry.register_target_rule('bad', lambda c: True, visibility=scope)
            with self.assertRaises(ValueError):
                self.registry.register_use_rule('bad', lambda c: True, visibility=scope)

    def test_schema_eleven_is_explicitly_rejected(self):
        game = self.game()
        snapshot = game.snapshot()
        snapshot['schema_version'] = 11
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot'):
            Game.from_snapshot(snapshot, self.registry)

    def test_false_or_malformed_public_predicate_cannot_bypass_authoritative_rules(self):
        self.registry.register_target_rule('false', lambda c: False, visibility='player')
        self.registry.register_target_rule('bad-bool', lambda c: 1, visibility='player')
        self.script('refused', lambda c: [], requires_target=True, target_rule='false')
        self.script('broken', lambda c: [], requires_target=True, target_rule='bad-bool')
        for name, expected in (('refused', None), ('broken', 'rule_error')):
            port = self.game(hand=(name,)).for_player(1)
            listing = port.legal_actions()
            self.assertEqual(listing['error'], expected)
            if listing['actions'] is not None:
                self.assertFalse(any(a['type'] == 'play_card' for a in listing['actions']))

    def test_pending_choice_does_not_inspect_unrelated_legacy_hand_rules(self):
        self.registry.register_target_rule('legacy', lambda c: True)
        self.script('legacy', lambda c: [], requires_target=True, target_rule='legacy')
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('ok', 'OK'),))])
        game = self.game(hand=('choose', 'legacy'))
        port = game.for_player(1)
        card = port.observe()['observation']['players'][0]['hand'][0]['ref']
        self.assertTrue(self.send(port, {'type': 'play_card', 'card': card})['accepted'])
        self.assertIsNone(port.legal_actions()['error'])
        self.assertTrue(self.send(port, self.first(port, 'select_choice'))['accepted'])
        self.assertEqual(port.legal_actions()['error'], 'unsupported_rule')

    def test_invalid_hero_power_source_does_not_probe_enemy_private_definition(self):
        self.power()
        game = self.game(power='power')
        port = game.for_player(1)
        enemy = port.observe()['observation']['players'][1]['hand'][0]['ref']
        self.assertEqual(self.send(port, {'type': 'use_hero_power', 'power': enemy})['error'], 'invalid_action')

    def test_player_api_cannot_be_called_during_resolution(self):
        self.script('publish', lambda c: [PublishPair()])
        mechanics = default_mechanics('reentry-test-v1').register(PublishPair, lambda r, e: r.game.for_player(1).legal_actions())
        game = self.game(hand=('publish',), mechanics=mechanics)
        before = game.snapshot()
        port = game.for_player(1)
        self.assertEqual(self.send(port, self.first(port, 'play_card'))['error'], 'resolution_failed')
        self.assertEqual(game.snapshot(), before)


class PlayerMatchTests(unittest.TestCase):
    def test_complete_representative_match_needs_no_omniscient_policy_input(self):
        from examples.play_as_players import play_match
        game, traces = play_match()
        self.assertIn(game.state.status, ('finished', 'draw'))
        self.assertGreater(game.state.action_number, 10)
        for viewer, trace in traces.items():
            self.assertEqual(len(trace), game.state.action_number + 1)
            for message in trace:
                self.assertEqual(message['observation']['viewer'], viewer)
                encoded = json.dumps(message)
                for key in ('entity_id', 'choice_id', 'option_ids', 'resolution_frame', 'rng_state', 'state_hash'):
                    self.assertNotIn(f'"{key}"', encoded)
            self.assertEqual(trace[-1]['observation']['status'], game.state.status)


if __name__ == '__main__':
    unittest.main()
