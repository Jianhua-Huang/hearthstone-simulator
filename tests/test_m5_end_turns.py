"""R-143: natural end-turn bodies retain old windows, guards and clocks."""
import json
import unittest
from copy import deepcopy

from hs_sim.engine import (AddPlayerEffect, CardDefinition, CardMetadata, CardClass,
    CardType, EndTurn, EndTurnSpec, Game, GrantLimitedTrigger, HeroPowerReference,
    IllegalAction, Keyword, LaunchStarship, LimitedTriggerSpec, PlayCard,
    PlayerEffectSpec, PlayerSetup, Registry, RemovePlayerEffect, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, Freeze, GainArmor, GrantTrigger, InvokeBehavior,
    ReplaceHeroPower, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.hero_powers import RemoveHeroPower
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def fixture_registry():
    """Reconstruct the same ordinary registry, without importing a TestCase."""
    registry = Registry('end-turn-fixtures-v1')
    registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
    registry.register_card(CardDefinition('plain', 'plain', CardType.MINION,
        attack=2, health=8))
    registry.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    registry.register_behavior('raw_armor', lambda c: [GainArmor(c.player_id, 10)])
    registry.register_behavior('expire_armor', lambda c: [GainArmor(c.player_id, 99)])
    registry.register_behavior('waiting', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),
         ChoiceOption('three', 'three', (GainArmor(c.player_id, 3),))),
        source_id=c.source_id)])
    spec = EndTurnSpec()
    for name, behavior in (('end', 'armor'), ('waiting', 'waiting')):
        registry.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            triggers=(TriggerSpec('turn_ended', behavior, end_turn=spec),)))
    registry.register_card(CardDefinition('raw', 'raw', CardType.MINION, health=8,
        triggers=(TriggerSpec('turn_ended', 'raw_armor'),)))
    registry.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON,
        attack=1, durability=3, triggers=(TriggerSpec('turn_ended', 'armor', spec),)))
    registry.register_card(CardDefinition('power', 'power', CardType.HERO_POWER,
        cost=2, on_use='armor'))
    registry.register_card(CardDefinition('end_power', 'end_power', CardType.HERO_POWER,
        passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'armor', spec),)))
    registry.register_card(CardDefinition('finite', 'finite', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', uses=2,
                                             end_turn=spec),)))
    registry.register_card(CardDefinition('dormant', 'dormant', CardType.MINION,
        health=8, dormant_turns=2,
        triggers=(TriggerSpec('turn_ended', 'raw_armor', spec),),
        dormant_triggers=(TriggerSpec('turn_ended', 'armor', spec),)))
    for name, duration in (('clock', 3), ('short', 1)):
        registry.register_card(CardDefinition(name, name, CardType.SPELL,
            ongoing_effect_id=name))
        registry.register_player_effect(PlayerEffectSpec(name, name, 'objective',
            duration=duration, tick_event='turn_ended', on_expire='expire_armor',
            triggers=(TriggerSpec('turn_ended', 'armor', spec),)))
    registry.register_behavior('persistent', lambda c:
        [AddPlayerEffect(c.player_id, 'persistent', c.source_id)])
    registry.register_card(CardDefinition('persistent', 'persistent', CardType.SPELL,
        on_play='persistent'))
    registry.register_player_effect(PlayerEffectSpec('persistent', 'persistent',
        triggers=(TriggerSpec('turn_ended', 'armor', spec),)))
    return registry


class EndTurnTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()

    def game(self, board=(), enemy=(), hand=(), enemy_hand=(), weapon=None,
             power='power', rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',) * 15,
                mana=10, max_mana=10, weapon_card_id=weapon,
                hero_power_card_id=power),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('plain',) * 15,
                mana=10, max_mana=10, hero_power_card_id='power')), seed=143),
            self.r, ruleset=rules)

    def script(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL,
            on_play=name, **kwargs))

    def minion(self, name, callback=None, scope='controller', condition='always',
               **kwargs):
        behavior = name if callback is not None else 'armor'
        if callback is not None:
            self.r.register_behavior(name, callback)
        kwargs.setdefault('health', 8)
        kwargs.setdefault('triggers', (TriggerSpec('turn_ended', behavior,
            EndTurnSpec(scope, condition)),))
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kwargs))

    def raw(self, name, callback, event='turn_ended'):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            triggers=(TriggerSpec(event, name),)))

    def finite(self, name, callback, *, uses=1, condition='always'):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            limited_triggers=(LimitedTriggerSpec('turn_ended', name, uses=uses,
                end_turn=EndTurnSpec(condition_id=condition)),)))

    def body(self, game, player=1, index=0):
        return game.state.entities[game.state.players[player].board[index]]

    def armor(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].armor

    def play(self, game, name, target=None, position=None):
        player = game.state.active_player
        entity = next(i for i in game.state.players[player].hand
            if game.state.entities[i].card_id == name)
        game.apply(PlayCard(player, entity, target, position))
        return entity

    def end(self, game):
        game.apply(EndTurn(game.state.active_player))

    def choose(self, game, option='one'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def check(self, game, registry=None):
        snapshot = json.loads(json.dumps(game.snapshot()))
        registry = registry or self.r
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)

    def waiting(self, board=('waiting', 'end'), hand=()):
        game = self.game(board=board, hand=hand)
        self.end(game)
        self.assertIsNotNone(game.state.pending_choice)
        return game

    def rows(self, game):
        return game.state.end_turn_history

    def batch(self, game, index=-1):
        return game.state.end_turn_batches[index]

    def rehash(self, snapshot):
        snapshot['events_hash'] = canonical_hash(snapshot['events'])
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})

    def reject(self, snapshot):
        self.rehash(snapshot)
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def named(self, value, name):
        found = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + name):
                found.append(value)
            for child in value.values():
                found.extend(self.named(child, name))
        elif isinstance(value, list):
            for child in value:
                found.extend(self.named(child, name))
        return found

    def queue(self, snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    def test_printed_ability_has_one_natural_batch_and_actual_execution(self):
        game = self.game(board=('end',))
        ability = active_abilities(self.body(game), 'trigger')[0]
        source = self.body(game)
        self.end(game)
        batch = self.batch(game)
        row = self.rows(game)[0]
        self.assertEqual((batch.id, batch.first_id, batch.turn), (1, 1, 1))
        self.assertEqual(batch.event.kind, 'turn_ended')
        self.assertEqual((row.capture.id, row.capture.batch_id, row.capture.index), (1, 1, 0))
        self.assertEqual(row.capture.subject.ability, ability)
        self.assertEqual((row.capture.subject.source_id, row.capture.subject.card_id,
            row.capture.subject.player_id, row.capture.subject.entered_order,
            row.capture.subject.zone_epoch),
            (source.id, 'end', 1, source.entered_order, source.zone_epoch))
        self.assertEqual((row.execution_order, row.completed, row.interrupted,
            row.skipped), (1, True, False, False))
        self.assertTrue(batch.completed)
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_plain_turn_listener_is_not_an_end_turn_subject(self):
        game = self.game(board=('raw',))
        self.end(game)
        self.assertEqual(self.armor(game), 10)
        self.assertFalse(self.rows(game))
        self.assertEqual(self.batch(game).subjects, ())
        self.assertTrue(self.batch(game).completed)
        self.check(game)

    def test_empty_window_completes_and_boundary_occurs_once(self):
        game = self.game()
        self.end(game)
        self.assertEqual((game.state.active_player, game.state.turn), (2, 2))
        self.assertEqual([e.kind for e in game.events].count('turn_ended'), 1)
        self.assertEqual([e.kind for e in game.events].count('turn_started'), 1)
        self.assertEqual([e.kind for e in game.events].count('card_drawn'), 1)
        self.assertTrue(self.batch(game).completed)
        self.check(game)

    def test_controller_scope_accepts_only_ending_controllers_body(self):
        game = self.game(board=('end',), enemy=('end',))
        self.end(game)
        self.assertEqual((self.armor(game), self.armor(game, 2)), (1, 0))
        self.assertEqual([r.capture.subject.player_id for r in self.rows(game)], [1])
        self.end(game)
        self.assertEqual((self.armor(game), self.armor(game, 2)), (1, 1))
        self.check(game)

    def test_opponent_scope_has_separate_controller_and_ending_player(self):
        self.minion('opponent', scope='opponent')
        game = self.game(board=('opponent',), enemy=('opponent',))
        self.end(game)
        self.assertEqual((self.armor(game), self.armor(game, 2)), (0, 1))
        self.assertEqual(self.rows(game)[0].capture.subject.player_id, 2)
        self.assertEqual(self.batch(game).event.player_id, 1)
        self.check(game)

    def test_either_scope_preserves_active_player_first_listener_order(self):
        self.minion('either', scope='either')
        game = self.game(board=('either',), enemy=('either',))
        self.end(game)
        self.end(game)
        self.assertEqual([r.capture.subject.player_id for r in self.rows(game)], [1, 2, 2, 1])
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2, 3, 4])
        self.check(game)

    def test_condition_uses_original_boundary_and_false_has_no_subject(self):
        self.r.register_trigger_condition('damaged', lambda c: c.source.damage > 0)
        self.minion('conditional', condition='damaged')
        game = self.game(board=('conditional',))
        self.end(game)
        self.assertFalse(self.rows(game))
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_end_condition_must_return_strict_boolean_and_rolls_back(self):
        for value in (1, None, 'true'):
            with self.subTest(value=value):
                self.setUp()
                self.r.register_trigger_condition('bad', lambda c, result=value: result)
                self.minion('bad', condition='bad')
                game = self.game(board=('bad',))
                before = game.snapshot()
                with self.assertRaises(ResolutionError):
                    self.end(game)
                self.assertEqual(game.snapshot(), before)

    def test_condition_receives_detached_state(self):
        def condition(context):
            context.state.players[1].mana = 0
            context.source.damage = 7
            return True
        self.r.register_trigger_condition('detached', condition)
        self.minion('detached', condition='detached')
        game = self.game(board=('detached',))
        self.end(game)
        self.assertEqual(self.body(game).damage, 0)
        self.assertEqual(game.state.players[1].mana, 10)
        self.assertEqual(self.armor(game), 1)

    def test_invalid_scopes_and_empty_conditions_are_rejected(self):
        for kwargs in ({'turn_scope': 'friendly'}, {'turn_scope': True},
                {'condition_id': ''}, {'condition_id': None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                EndTurnSpec(**kwargs)

    def test_end_classification_rejects_other_events_and_keyword_finite_triggers(self):
        for constructor in (
                lambda: TriggerSpec('turn_started', 'armor', EndTurnSpec()),
                lambda: LimitedTriggerSpec('turn_started', 'armor', end_turn=EndTurnSpec()),
                lambda: LimitedTriggerSpec('card_played', 'armor', keyword=Keyword.SPELLBURST,
                                          end_turn=EndTurnSpec()),
                lambda: GrantTrigger(1, 'damage_dealt', 'armor', end_turn=EndTurnSpec())):
            with self.subTest(constructor=constructor), self.assertRaises(ValueError):
                constructor()

    def test_unknown_condition_fails_registry_freeze(self):
        self.minion('unknown', condition='unregistered')
        with self.assertRaises(ValueError):
            self.game(board=('unknown',))

    def test_same_behavior_instances_keep_independent_ability_identity(self):
        self.minion('multi', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),
                                      TriggerSpec('turn_ended', 'armor', EndTurnSpec())))
        game = self.game(board=('multi', 'multi'))
        self.end(game)
        self.assertEqual(self.armor(game), 4)
        self.assertEqual(len({r.capture.subject.ability.id for r in self.rows(game)}), 4)
        self.assertEqual([r.capture.index for r in self.rows(game)], list(range(4)))
        self.check(game)

    def test_classified_and_raw_callbacks_keep_original_interleaving(self):
        self.minion('mixed', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),
            TriggerSpec('turn_ended', 'raw_armor'),
            TriggerSpec('turn_ended', 'armor', EndTurnSpec())))
        game = self.game(board=('mixed', 'raw', 'end'))
        self.end(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'],
                         [1, 10, 1, 10, 1])
        self.assertEqual(len(self.rows(game)), 3)
        self.check(game)

    def test_acceptance_after_source_destroyed_keeps_ordinary_frozen_callback(self):
        self.raw('killer', lambda c: [Destroy(c.state.players[1].board[1])])
        self.minion('frozen', lambda c: [GainArmor(c.player_id, len(c.state.players[1].board))])
        game = self.game(board=('killer', 'frozen'))
        source = self.body(game, index=1).id
        self.end(game)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(self.rows(game)[0].completed)
        self.check(game)

    def test_silence_transform_bounce_and_control_after_acceptance_keep_body(self):
        operations = (lambda i: Silence(i), lambda i: Transform(i, 'plain'),
                      lambda i: ReturnToHand(i), lambda i: ChangeControl(i, 2))
        for operation in operations:
            with self.subTest(operation=operation):
                self.setUp()
                self.raw('changer', lambda c, op=operation: [op(c.state.players[1].board[1])])
                game = self.game(board=('changer', 'end'))
                self.end(game)
                self.assertEqual((self.armor(game), self.armor(game, 2)), (1, 0))
                self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'end')
                self.assertTrue(self.rows(game)[0].completed)
                self.check(game)

    def test_newly_summoned_end_body_waits_until_later_boundary(self):
        self.raw('summoner', lambda c: [Summon(c.player_id, 'end')]
            if c.event.player_id == c.player_id else [])
        game = self.game(board=('summoner',))
        self.end(game)
        self.assertFalse(self.rows(game))
        self.end(game)
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(len(self.batch(game).subjects), 1)
        self.check(game)

    def test_weapon_printed_end_body_has_weapon_identity(self):
        game = self.game(weapon='weapon')
        source = game.state.players[1].weapon_id
        self.end(game)
        self.assertEqual(self.rows(game)[0].capture.subject.source_id, source)
        self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'weapon')
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_dormant_classified_body_is_separate_from_inactive_normal_body(self):
        game = self.game(board=('dormant',))
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(self.rows(game)[0].capture.subject.ability.kind, 'dormant_trigger')
        self.assertEqual(self.body(game).dormancy.remaining_turns, 2)
        self.check(game)

    def test_accepted_dormant_body_retains_window_when_source_is_awakened(self):
        from hs_sim.engine.dormancy import AwakenMinion
        self.raw('awakener', lambda c: [AwakenMinion(c.state.players[1].board[1])])
        game = self.game(board=('awakener', 'dormant'))
        self.end(game)
        self.assertIsNone(self.body(game, index=1).dormancy)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(self.rows(game)[0].capture.subject.ability.kind, 'dormant_trigger')
        self.check(game)

    def test_finite_body_consumes_once_and_then_disappears_from_acceptance(self):
        game = self.game(board=('finite',))
        self.end(game)
        self.end(game)
        self.end(game)
        self.end(game)
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 2)
        self.assertEqual([r.capture.subject.ability.uses_remaining for r in self.rows(game)], [2, 1])
        self.assertEqual(self.body(game).abilities[-1].uses_remaining, 0)
        self.assertEqual(self.batch(game).subjects, ())
        self.check(game)

    def test_finite_callback_keeps_consumed_context_and_preconsume_identity(self):
        self.finite('context', lambda c: [GainArmor(c.player_id,
            10 * c.end_turn.subject.ability.uses_remaining + c.trigger.uses_remaining)], uses=2)
        game = self.game(board=('context',))
        self.end(game)
        self.assertEqual(self.armor(game), 21)
        self.assertEqual(self.rows(game)[0].capture.subject.ability.uses_remaining, 2)
        self.check(game)

    def test_finite_guard_source_destroyed_skips_without_actual_execution(self):
        self.raw('killer', lambda c: [Destroy(c.state.players[1].board[1])])
        game = self.game(board=('killer', 'finite'))
        source = self.body(game, index=1).id
        self.end(game)
        row = self.rows(game)[0]
        self.assertEqual((row.execution_order, row.completed, row.interrupted,
                         row.skipped), (None, False, False, True))
        self.assertEqual(game.state.entities[source].abilities[-1].uses_remaining, 2)
        self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
        self.assertEqual(activated_end_turns(game.state, 1), ())
        self.assertTrue(self.batch(game).completed)
        self.check(game)

    def test_finite_guard_silence_bounce_control_and_dormancy_skip(self):
        for operation in (lambda i: Silence(i), lambda i: ReturnToHand(i),
                lambda i: ChangeControl(i, 2), lambda i: MakeDormant(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.raw('changer', lambda c, op=operation: [op(c.state.players[1].board[1])])
                game = self.game(board=('changer', 'finite'))
                self.end(game)
                self.assertTrue(self.rows(game)[0].skipped)
                self.assertEqual(self.armor(game), 0)
                self.check(game)

    def test_limited_used_reaction_keeps_old_checkpoint_and_callback_window(self):
        self.raw('silencer', lambda c: [Silence(c.event.source_id)], event='limited_trigger_used')
        self.finite('context', lambda c: [GainArmor(c.player_id, c.trigger.uses_remaining + 1)], uses=2)
        game = self.game(board=('silencer', 'context'))
        self.end(game)
        self.assertTrue(self.body(game, index=1).silenced)
        self.assertEqual(self.armor(game), 2)
        kinds = [e.kind for e in game.events]
        self.assertLess(kinds.index('limited_trigger_used'), kinds.index('silenced'))
        self.assertLess(kinds.index('silenced'), kinds.index('armor_gained'))
        self.assertTrue(self.rows(game)[0].completed)
        self.check(game)

    def test_hero_power_end_body_is_independent_of_power_activation_history(self):
        game = self.game(power='end_power')
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'end_power')
        self.assertFalse(game.state.hero_power_history)
        self.assertFalse(game.state.hero_power_payload_history)
        self.check(game)

    def test_hero_power_guard_removal_skips_captured_body(self):
        self.raw('remove_power', lambda c: [RemoveHeroPower(1)])
        self.script('install_power', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('remove_power',), hand=('install_power',))
        self.play(game, 'install_power')
        self.end(game)
        self.assertEqual(self.armor(game), 0)
        self.assertEqual((self.rows(game)[0].execution_order, self.rows(game)[0].skipped), (None, True))
        self.assertFalse(game.state.players[1].hero_power_ids)
        self.check(game)

    def test_hero_power_replacement_does_not_reclassify_new_installation(self):
        self.raw('replace_power', lambda c: [ReplaceHeroPower(1, 'end_power')])
        self.script('install_power', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('replace_power',), hand=('install_power',))
        self.play(game, 'install_power')
        old = game.state.players[1].hero_power_id
        self.end(game)
        self.assertTrue(self.rows(game)[0].skipped)
        self.assertNotEqual(game.state.players[1].hero_power_id, old)
        self.assertEqual(self.rows(game)[0].capture.subject.source_id, old)
        self.check(game)

    def test_player_effect_body_precedes_one_owner_tick(self):
        game = self.game(hand=('clock',))
        source = self.play(game, 'clock')
        instance = game.state.players[1].player_effects[0]
        self.end(game)
        subject = self.rows(game)[0].capture.subject
        self.assertEqual((subject.source_id, subject.card_id, subject.player_effect,
                         subject.trigger_index), (source, 'clock', instance, 0))
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        kinds = [e.kind for e in game.events]
        self.assertLess(kinds.index('armor_gained'), kinds.index('player_effect_ticked'))
        self.check(game)

    def test_opponent_boundary_neither_executes_owner_body_nor_ticks_clock(self):
        game = self.game(hand=('clock',))
        self.play(game, 'clock')
        self.end(game)
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.assertEqual(self.batch(game).subjects, ())
        self.check(game)

    def test_short_player_effect_body_then_expiry_body_both_only_once(self):
        game = self.game(hand=('short',))
        self.play(game, 'short')
        self.end(game)
        self.assertEqual(self.armor(game), 100)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual(len(self.rows(game)), 1)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [1, 99])
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game)

    def test_player_effect_removal_midwindow_keeps_accepted_frozen_body(self):
        self.raw('remove_effect', lambda c: [RemovePlayerEffect(1, c.state.players[1].player_effects[0].id)])
        game = self.game(board=('remove_effect',), hand=('clock',))
        self.play(game, 'clock')
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertTrue(self.rows(game)[0].completed)
        self.assertNotIn('player_effect_ticked', [e.kind for e in game.events])
        self.check(game)

    def test_duplicate_player_effect_instances_keep_independent_subject_keys(self):
        game = self.game(hand=('persistent', 'persistent'))
        self.play(game, 'persistent')
        self.play(game, 'persistent')
        self.end(game)
        subjects = self.batch(game).subjects
        self.assertEqual(len({s.key for s in subjects}), 2)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_one_player_effect_multiple_identical_triggers_keep_tuple_positions(self):
        self.r.register_player_effect(PlayerEffectSpec('multiple', 'plain', triggers=(
            TriggerSpec('turn_ended', 'armor', EndTurnSpec()),
            TriggerSpec('turn_ended', 'armor', EndTurnSpec()))))
        self.script('install', lambda c: [AddPlayerEffect(1, 'multiple', c.source_id)])
        game = self.game(hand=('install',))
        self.play(game, 'install')
        self.end(game)
        subjects = self.batch(game).subjects
        self.assertEqual([s.trigger_index for s in subjects], [0, 1])
        self.assertEqual(len({s.player_effect.id for s in subjects}), 1)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_player_effect_source_death_keeps_its_end_turn_provenance(self):
        self.script('install', lambda c: [AddPlayerEffect(1, 'persistent',
            c.state.players[1].board[0]), Destroy(c.state.players[1].board[0])])
        game = self.game(board=('plain',), hand=('install',))
        source = self.body(game).id
        self.play(game, 'install')
        self.end(game)
        self.assertEqual(self.rows(game)[0].capture.subject.source_id, source)
        self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'plain')
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_player_effect_installed_during_boundary_waits_and_does_not_tick(self):
        self.raw('install_effect', lambda c: [AddPlayerEffect(1, 'clock', c.source_id)])
        game = self.game(board=('install_effect',))
        self.end(game)
        self.assertFalse(self.rows(game))
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_pending_choice_separates_queued_from_started_and_blocks_nextturn(self):
        game = self.waiting()
        self.assertEqual((game.state.active_player, game.state.turn), (1, 1))
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, None])
        self.assertFalse(any(r.completed for r in self.rows(game)))
        self.assertFalse(self.batch(game).completed)
        self.assertEqual(len(activated_end_turns(game.state, 1)), 1)
        self.assertNotIn('turn_started', [e.kind for e in game.events])
        self.check(game)

    def test_fresh_registry_restores_pending_and_replays_whole_natural_boundary(self):
        game = self.waiting()
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), fixture_registry())
        self.choose(game, 'three')
        self.choose(restored, 'three')
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(self.armor(game), 4)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.check(game, fixture_registry())

    def test_invalid_choice_and_end_action_leave_committed_frame_unchanged(self):
        game = self.waiting()
        before = game.snapshot()
        choice = game.state.pending_choice
        for action in (SelectChoice(choice.player_id, choice.id, ('unknown',)), EndTurn(1)):
            with self.subTest(action=action), self.assertRaises(IllegalAction):
                game.apply(action)
            self.assertEqual(game.snapshot(), before)

    def test_choice_pause_delays_player_clock_and_resume_ticks_once(self):
        game = self.game(board=('waiting',), hand=('clock',))
        self.play(game, 'clock')
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 0)
        self.check(game)
        self.choose(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 1)
        self.check(game)

    def test_several_choices_keep_positions_and_one_natural_boundary(self):
        game = self.waiting(board=('waiting', 'waiting', 'end'))
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2, None])
        self.check(game)
        self.choose(game, 'three')
        self.assertEqual(self.armor(game), 5)
        self.assertEqual([e.kind for e in game.events].count('turn_ended'), 1)
        self.check(game)

    def test_temporary_end_trigger_executes_before_attachment_expiry(self):
        self.script('grant', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, c.state.turn, EndTurnSpec())])
        game = self.game(board=('plain',), hand=('grant',))
        grantor = self.play(game, 'grant')
        self.end(game)
        ability = self.rows(game)[0].capture.subject.ability
        self.assertEqual((ability.origin, ability.source_id, ability.expires_turn), ('granted', grantor, 1))
        self.assertFalse(active_abilities(self.body(game), 'trigger'))
        self.assertEqual(self.armor(game), 1)
        self.end(game)
        self.end(game)
        self.assertEqual(len(self.rows(game)), 1)
        self.check(game)

    def test_granted_end_trigger_current_copy_keeps_it_base_copy_does_not(self):
        self.script('install', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec()),
            CopyMinion(c.state.players[1].board[0], 1),
            CopyMinion(c.state.players[1].board[0], 1, mode='base')])
        game = self.game(board=('plain',), hand=('install',))
        grantor = self.play(game, 'install')
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([r.capture.subject.ability.source_id for r in self.rows(game)], [grantor, grantor])
        self.assertEqual(len({r.capture.subject.ability.id for r in self.rows(game)}), 2)
        self.check(game)

    def test_granted_end_trigger_silence_prevents_future_acceptance(self):
        self.script('install', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec()),
            Silence(c.state.players[1].board[0])])
        game = self.game(board=('plain',), hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertFalse(self.rows(game))
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_grant_then_control_transfer_uses_current_controller_scope(self):
        self.script('install', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec()),
            ChangeControl(c.state.players[1].board[0], 2)])
        game = self.game(board=('plain',), hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertFalse(self.rows(game))
        self.end(game)
        self.assertEqual(self.armor(game, 2), 1)
        self.assertEqual(self.rows(game)[0].capture.subject.player_id, 2)
        self.check(game)

    def test_dynamic_end_trigger_supports_weapon_carrier(self):
        self.r.register_card(CardDefinition('blank_weapon', 'blank_weapon', CardType.WEAPON,
            attack=1, durability=3))
        self.script('install', lambda c: [GrantTrigger(c.state.players[1].weapon_id,
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec())])
        game = self.game(weapon='blank_weapon', hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'blank_weapon')
        self.check(game)

    def test_magnetic_end_trigger_identifies_host_and_attachment_origin(self):
        metadata = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))
        self.minion('part', keywords=(Keyword.MAGNETIC,), magnetic_tribes=('mech',), metadata=metadata)
        self.r.register_card(CardDefinition('host', 'host', CardType.MINION, health=8, metadata=metadata))
        game = self.game(board=('host',), hand=('part',))
        part = self.play(game, 'part', position=0)
        self.end(game)
        subject = self.rows(game)[0].capture.subject
        self.assertEqual((subject.card_id, subject.source_id), ('host', self.body(game).id))
        self.assertEqual((subject.ability.source_id, subject.ability.magnetic_id), (part, 1))
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_starship_building_is_inactive_then_each_component_body_has_identity(self):
        self.minion('piece', keywords=(Keyword.STARSHIP_PIECE,))
        self.r.register_card(CardDefinition('ship', 'ship', CardType.MINION,
            starship_for=(CardClass.NEUTRAL,)))
        self.script('build', lambda c: [Destroy(i) for i in c.state.players[1].board])
        game = self.game(board=('piece', 'piece'), hand=('build',))
        self.play(game, 'build')
        ship = self.body(game)
        self.assertTrue(ship.starship_building)
        self.end(game)
        self.assertFalse(self.rows(game))
        self.end(game)
        game.apply(LaunchStarship(1, ship.id))
        self.end(game)
        subjects = self.batch(game).subjects
        self.assertEqual(len(subjects), 2)
        self.assertEqual({s.source_id for s in subjects}, {ship.id})
        self.assertEqual({s.card_id for s in subjects}, {'ship'})
        self.assertEqual(len({s.ability.id for s in subjects}), 2)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_ordinary_behavior_invocation_is_not_natural_end_turn_activation(self):
        self.script('invoke', lambda c: [InvokeBehavior('armor', c.source_id, c.player_id)])
        game = self.game(hand=('invoke',))
        self.play(game, 'invoke')
        self.assertEqual(self.armor(game), 1)
        self.assertFalse(self.rows(game))
        self.assertFalse(game.state.end_turn_batches)
        self.check(game)

    def test_terminal_first_body_interrupts_started_and_queued_positions(self):
        self.minion('lethal', lambda c: [Damage(c.state.players[2].hero_id, 30, c.source_id)])
        game = self.game(board=('lethal', 'end'))
        self.end(game)
        self.assertEqual(game.state.winner, 1)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, None])
        self.assertTrue(all(r.interrupted for r in self.rows(game)))
        self.assertTrue(self.batch(game).interrupted)
        self.assertEqual((game.state.active_player, game.state.turn), (1, 1))
        self.assertNotIn('turn_started', [e.kind for e in game.events])
        self.check(game)

    def test_body_error_rolls_back_boundary_history_events_and_rng(self):
        def fail(context):
            raise ResolutionError('end-turn fixture failure')
        self.minion('fail', fail)
        game = self.game(board=('end', 'fail'))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.end(game)
        self.assertEqual(game.snapshot(), before)

    def test_resolution_budget_is_error_with_complete_action_rollback(self):
        self.minion('expansion', lambda c: [GainArmor(1, 1)] * 40)
        game = self.game(board=('expansion',), rules=Ruleset(max_resolution_steps=30))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.end(game)
        self.assertEqual(game.snapshot(), before)

    def test_no_new_end_turn_gameplay_events_or_additional_draws(self):
        game = self.game(board=('end', 'end'))
        self.end(game)
        # Host-only armor/hand-entry receipts are not additional gameplay.
        expected = ['turn_ended', 'armor_gained', 'armor_gained', 'turn_started', 'card_drawn']
        for viewer in (1, 2):
            self.assertEqual([event['kind'] for event in game.player_events(viewer)], expected)
        self.assertEqual(sum(e.kind == 'card_drawn' for e in game.events), 1)
        self.check(game)

    def test_player_observation_hides_history_captures_and_pending_controls(self):
        game = self.waiting()
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer),
                               game.for_player(viewer).legal_actions()))
            for internal in ('end_turn_history', 'end_turn_batches', 'end_turn',
                    'EndTurnCapture', 'EndTurnSubject', 'execution_order',
                    'trigger_index', 'ability_id', 'resolution_frame'):
                self.assertNotIn('"' + internal + '"', text)
        self.check(game)

    def test_host_history_filters_started_completed_player_source_and_turn(self):
        game = self.waiting()
        source = self.body(game).id
        self.assertEqual(len(activated_end_turns(game.state, 1, source_id=source,
            completed=False, turn=1)), 1)
        self.assertEqual(activated_end_turns(game.state, 2), ())
        self.assertEqual(activated_end_turns(game.state, 1, completed=True), ())
        self.choose(game)
        self.assertEqual(len(activated_end_turns(game.state, 1, completed=True)), 2)
        self.assertEqual(activated_end_turns(game.state, 1, turn=2), ())

    def test_host_history_filter_rejects_bool_ids_and_invalid_values(self):
        game = self.game()
        for player, kwargs in ((True, {}), (3, {}), (1, {'source_id': 0}),
                (1, {'source_id': True}), (1, {'completed': 1}), (1, {'turn': False}),
                (1, {'turn': 0})):
            with self.subTest(player=player, kwargs=kwargs), self.assertRaises(ValueError):
                activated_end_turns(game.state, player, **kwargs)

    def test_rehashed_missing_batch_and_record_are_rejected(self):
        game = self.waiting()
        for key in ('end_turn_batches', 'end_turn_history'):
            with self.subTest(key=key):
                snapshot = game.snapshot()
                snapshot['state'][key] = []
                self.reject(snapshot)

    def test_rehashed_capture_identity_and_execution_order_are_rejected(self):
        game = self.waiting()
        mutations = (('execution_order', 4), ('completed', True), ('skipped', True),
                     ('interrupted', True))
        for key, value in mutations:
            with self.subTest(key=key):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_history'][0][key] = value
                self.reject(snapshot)
        for key, value in (('id', 2), ('batch_id', 2), ('index', 1)):
            with self.subTest(key=key):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_history'][0]['capture'][key] = value
                self.reject(snapshot)

    def test_rehashed_batch_natural_event_and_completion_are_rejected(self):
        game = self.waiting()
        for key, value in (('turn', 2), ('first_id', 2), ('completed', True), ('interrupted', True)):
            with self.subTest(key=key):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0][key] = value
                self.reject(snapshot)
        for key, value in (('player_id', 2), ('amount', 1), ('kind', 'turn_started')):
            with self.subTest(event_key=key):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0]['event'][key] = value
                self.reject(snapshot)

    def test_rehashed_missing_subject_invoke_finish_or_window_proof_is_rejected(self):
        game = self.waiting()
        for name in ('InvokeEndTurn', 'FinishEndTurn', 'FinishEndTurnBatch'):
            with self.subTest(name=name):
                snapshot = game.snapshot()
                queue = self.queue(snapshot)
                selected = next(item for item in queue if str(item.get('type', '')).endswith('.' + name))
                queue.remove(selected)
                self.reject(snapshot)

    def test_rehashed_deleted_final_subject_with_matching_history_and_queue_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'].pop()
        snapshot['state']['end_turn_batches'][0]['subjects'].pop()
        queue = self.queue(snapshot)
        queued = next(item for item in queue if str(item.get('type', '')).endswith('.InvokeEndTurn'))
        queue.remove(queued)
        self.reject(snapshot)

    def test_rehashed_end_subject_moved_beyond_clock_completion_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        invocation = next(item for item in queue if str(item.get('type', '')).endswith('.InvokeEndTurn'))
        queue.remove(invocation)
        queue.append(invocation)
        self.reject(snapshot)

    def test_rehashed_invocation_callback_loses_end_capture_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        invocation = self.named(snapshot['resolution_frame'], 'InvokeEndTurn')[0]
        invocation['fields']['context']['fields']['end_turn'] = None
        self.reject(snapshot)

    def test_rehashed_declared_classification_removed_from_history_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        subject = snapshot['state']['end_turn_history'][0]['capture']['subject']
        subject['ability']['end_turn'] = None
        self.reject(snapshot)

    def test_rehashed_player_effect_trigger_index_and_tuple_identity_are_rejected(self):
        game = self.game(board=('waiting',), hand=('clock',))
        self.play(game, 'clock')
        self.end(game)
        for key, value in (('trigger_index', 1), ('card_id', 'plain'), ('player_id', 2)):
            with self.subTest(key=key):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_history'][1]['capture']['subject'][key] = value
                self.reject(snapshot)

    def test_rehashed_natural_event_removed_from_event_history_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['events'] = [e for e in snapshot['events'] if e['kind'] != 'turn_ended']
        self.reject(snapshot)

    def test_finite_and_power_guard_receipts_are_separate_from_ordinary_bodies(self):
        game = self.game(board=('end', 'finite'), power='end_power')
        self.end(game)
        receipt = {r.capture.subject.card_id: r.guard_passed for r in self.rows(game)}
        self.assertEqual(receipt, {'end_power': True, 'end': False, 'finite': True})
        self.check(game)

    def test_pending_finite_guard_has_no_receipt_or_consumption(self):
        game = self.waiting(board=('waiting', 'finite'))
        row = self.rows(game)[1]
        self.assertEqual((row.guard_passed, row.execution_order, row.skipped), (False, None, False))
        self.assertEqual(self.body(game, index=1).abilities[-1].uses_remaining, 2)
        self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
        self.check(game)
        self.choose(game)
        self.assertTrue(self.rows(game)[1].guard_passed)
        self.assertEqual(self.body(game, index=1).abilities[-1].uses_remaining, 1)
        self.check(game)

    def test_choice_within_finite_body_keeps_passed_guard_and_consumed_instance(self):
        self.finite('finite_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(c.player_id, c.trigger.uses_remaining),)),),
            source_id=c.source_id)], uses=2)
        game = self.game(board=('finite_wait', 'end'))
        self.end(game)
        row = self.rows(game)[0]
        self.assertEqual((row.guard_passed, row.execution_order, row.completed), (True, 1, False))
        self.assertEqual(self.body(game).abilities[-1].uses_remaining, 1)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.check(game)

    def test_finite_grant_retains_classification_and_independent_use_count(self):
        spec = LimitedTriggerSpec('turn_ended', 'armor', uses=2, end_turn=EndTurnSpec())
        self.script('grant_finite', lambda c: [GrantLimitedTrigger(c.state.players[1].board[0],
            spec, c.source_id)])
        game = self.game(board=('plain',), hand=('grant_finite',))
        grantor = self.play(game, 'grant_finite')
        self.end(game)
        subject = self.rows(game)[0].capture.subject
        self.assertEqual(subject.spec, EndTurnSpec())
        self.assertEqual((subject.ability.source_id, subject.ability.origin), (grantor, 'granted'))
        self.assertTrue(self.rows(game)[0].guard_passed)
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_finite_condition_and_end_condition_both_control_acceptance(self):
        self.r.register_trigger_condition('never', lambda c: False)
        for name, finite_condition, end_condition in (
                ('finite_never', 'never', 'always'), ('end_never', 'always', 'never')):
            self.r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
                limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', finite_condition,
                    end_turn=EndTurnSpec(condition_id=end_condition)),)))
        game = self.game(board=('finite_never', 'end_never'))
        self.end(game)
        self.assertFalse(self.rows(game))
        self.assertEqual(self.armor(game), 0)
        self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
        self.check(game)

    def test_end_body_condition_is_frozen_before_earlier_listener_changes_state(self):
        self.r.register_trigger_condition('undamaged', lambda c: c.source.damage == 0)
        self.raw('damager', lambda c: [Damage(c.state.players[1].board[1], 1)])
        self.minion('conditional', condition='undamaged')
        game = self.game(board=('damager', 'conditional'))
        self.end(game)
        self.assertEqual(self.body(game, index=1).damage, 1)
        self.assertEqual(self.armor(game), 1)
        self.assertTrue(self.rows(game)[0].completed)
        self.check(game)

    def test_end_body_choice_does_not_repeat_thaw_expiry_or_draw(self):
        self.script('prepare', lambda c: [Buff(c.state.players[1].board[0],
            2, 2, c.source_id, c.state.turn), Freeze(c.state.players[1].board[0])])
        game = self.game(board=('waiting',), hand=('prepare',))
        self.play(game, 'prepare')
        self.end(game)
        self.assertTrue(self.body(game).frozen)
        self.assertTrue(self.body(game).enchantments)
        self.choose(game)
        self.assertFalse(self.body(game).frozen)
        self.assertFalse(self.body(game).enchantments)
        kinds = [e.kind for e in game.events]
        self.assertEqual(kinds.count('turn_ended'), 1)
        self.assertEqual(kinds.count('turn_started'), 1)
        self.assertEqual(kinds.count('card_drawn'), 1)
        self.check(game)

    def test_rehashed_guard_receipt_changed_on_started_finite_is_rejected(self):
        self.finite('finite_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
        game = self.game(board=('finite_wait',))
        self.end(game)
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][0]['guard_passed'] = False
        self.reject(snapshot)

    def test_rehashed_guard_receipt_forged_on_ordinary_body_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][0]['guard_passed'] = True
        self.reject(snapshot)

    def test_rehashed_finite_check_replaced_with_invocation_is_rejected(self):
        game = self.waiting(board=('waiting', 'finite'))
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        check = next(x for x in queue if str(x.get('type', '')).endswith('.CheckLimitedTrigger'))
        context = deepcopy(check['fields']['end_turn_context'])
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_rehashed_power_check_replaced_with_invocation_is_rejected(self):
        self.script('install_power', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('waiting',), hand=('install_power',))
        self.play(game, 'install_power')
        self.end(game)
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        check = next(x for x in queue if str(x.get('type', '')).endswith('.CheckHeroPowerTrigger'))
        context = deepcopy(check['fields']['context'])
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_rehashed_finite_fake_guard_receipt_cannot_keep_preconsume_context(self):
        game = self.waiting(board=('waiting', 'finite'))
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][1]['guard_passed'] = True
        queue = self.queue(snapshot)
        check = next(x for x in queue if str(x.get('type', '')).endswith('.CheckLimitedTrigger'))
        context = deepcopy(check['fields']['end_turn_context'])
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_location_end_body_is_classified_without_becoming_a_character(self):
        self.r.register_card(CardDefinition('location', 'location', CardType.LOCATION,
            durability=2, on_use='armor', triggers=(TriggerSpec('turn_ended',
            'armor', EndTurnSpec()),)))
        game = self.game(board=('location',))
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertFalse(self.body(game).is_character)
        self.assertEqual(self.rows(game)[0].capture.subject.card_id, 'location')
        self.check(game)

    def test_player_effect_condition_gets_original_instance_and_opponent_scope(self):
        self.r.register_trigger_condition('player_instance', lambda c:
            c.player_effect is not None and c.player_effect.spec_id == 'opponent_effect')
        self.r.register_player_effect(PlayerEffectSpec('opponent_effect', 'plain',
            triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec('opponent', 'player_instance')),)))
        self.script('install', lambda c: [AddPlayerEffect(1, 'opponent_effect', c.source_id)])
        game = self.game(hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertFalse(self.rows(game))
        self.end(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(self.batch(game).event.player_id, 2)
        self.assertEqual(self.rows(game)[0].capture.subject.player_id, 1)
        self.check(game)

    def test_plain_player_clock_expiry_is_not_an_end_turn_body(self):
        self.r.register_card(CardDefinition('timer_only', 'timer_only', CardType.SPELL,
            ongoing_effect_id='timer_only'))
        self.r.register_player_effect(PlayerEffectSpec('timer_only', 'timer_only',
            'objective', duration=1, tick_event='turn_ended', on_expire='expire_armor'))
        game = self.game(hand=('timer_only',))
        self.play(game, 'timer_only')
        self.end(game)
        self.assertEqual(self.armor(game), 99)
        self.assertFalse(self.rows(game))
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(game.state.players[1].player_effects)
        self.check(game)

    def test_rehashed_completed_window_cannot_be_deleted_while_natural_event_remains(self):
        game = self.game(board=('end',))
        self.end(game)
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'] = []
        snapshot['state']['end_turn_batches'] = []
        self.reject(snapshot)

    def test_rehashed_playing_window_cannot_be_replaced_by_terminal_interruption(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][0]['interrupted'] = True
        for row in snapshot['state']['end_turn_history']:
            row['interrupted'] = True
        queue = self.queue(snapshot)
        queue[:] = [x for x in queue if not any(str(x.get('type', '')).endswith('.' + name)
            for name in ('InvokeEndTurn', 'FinishEndTurn', 'FinishEndTurnBatch'))]
        self.reject(snapshot)


if __name__ == '__main__':
    unittest.main()
