"""M5-13d-02l-05a: per-subject counts, one guard and real owner clocks."""
import json
import unittest
from copy import deepcopy

from hs_sim.engine import (AddPlayerEffect, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, EndTurnSpec, Game, Keyword, LaunchStarship,
    LimitedTriggerSpec, PlayCard, PlayerEffectSpec, PlayerSetup, Registry,
    RemovePlayerEffect, ResolutionError, ResolutionLimitExceeded, Ruleset,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, Freeze, GainArmor, GrantTrigger, ReplaceHeroPower,
    RequestChoice, ReturnToHand, Silence, Summon, Transform, TriggerDeathrattles)
from hs_sim.engine.end_turn_repeats import GrantEndTurnRepeatAura
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.hero_powers import RemoveHeroPower
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (AbilityInstance, DeathrattleRepeatSpec,
    EndTurnRepeatContributor, EndTurnRepeatPlan, EndTurnRepeatSpec)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def fixture_registry():
    """A fresh registry has the same definitions and no mutable callback state."""
    r = Registry('end-turn-repeat-fixtures-v1')
    r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=8))
    r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('ten', lambda c: [GainArmor(c.player_id, 10)])
    r.register_behavior('expire', lambda c: [GainArmor(c.player_id, 99)])
    r.register_behavior('fresh', lambda c: [GainArmor(c.player_id,
        c.state.entities[c.state.players[c.player_id].hero_id].armor + 1)])
    r.register_behavior('waiting', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),
         ChoiceOption('three', 'three', (GainArmor(c.player_id, 3),))),
        source_id=c.source_id)])
    natural = EndTurnSpec()
    for name, behavior in (('end', 'armor'), ('waiting', 'waiting'), ('fresh', 'fresh')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            triggers=(TriggerSpec('turn_ended', behavior, natural),)))
    r.register_card(CardDefinition('raw', 'raw', CardType.MINION, health=8,
        triggers=(TriggerSpec('turn_ended', 'ten'),)))
    r.register_card(CardDefinition('power', 'power', CardType.HERO_POWER,
        cost=2, on_use='armor'))
    r.register_card(CardDefinition('end_power', 'end_power', CardType.HERO_POWER,
        passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'armor', natural),)))
    r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON,
        attack=1, durability=3, triggers=(TriggerSpec('turn_ended', 'armor', natural),)))
    r.register_card(CardDefinition('location', 'location', CardType.LOCATION,
        durability=2, on_use='armor', triggers=(TriggerSpec('turn_ended', 'armor', natural),)))
    r.register_card(CardDefinition('finite', 'finite', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', uses=2,
            end_turn=natural),)))
    r.register_card(CardDefinition('dormant', 'dormant', CardType.MINION,
        health=8, dormant_turns=2,
        dormant_triggers=(TriggerSpec('turn_ended', 'armor', natural),)))
    for name, count, scope in (('double', 2, 'all'), ('triple', 3, 'all'),
            ('minion_double', 2, 'minion')):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1,
            health=5, end_turn_repeats=(EndTurnRepeatSpec(count, scope),)))
    r.register_card(CardDefinition('multi', 'multi', CardType.MINION, health=5,
        end_turn_repeats=(EndTurnRepeatSpec(2), EndTurnRepeatSpec(3))))
    for name, scope, duration in (('persistent', 'all', None),
            ('minion_persistent', 'minion', None), ('short', 'minion', 1),
            ('clock', 'minion', 3)):
        r.register_player_effect(PlayerEffectSpec(name, name,
            kind='persistent' if duration is None else 'objective',
            duration=duration, tick_event=None if duration is None else 'turn_ended',
            on_expire=None if duration is None else 'expire',
            end_turn_repeats=(EndTurnRepeatSpec(2, scope),)))
        r.register_behavior(name, lambda c, n=name: [AddPlayerEffect(c.player_id, n, c.source_id)])
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_player_effect(PlayerEffectSpec('player_body', 'plain',
        triggers=(TriggerSpec('turn_ended', 'armor', natural),)))
    r.register_behavior('player_body', lambda c: [AddPlayerEffect(c.player_id,
        'player_body', c.state.players[c.player_id].board[0])])
    r.register_card(CardDefinition('player_body', 'player_body', CardType.SPELL,
        on_play='player_body'))
    return r


class EndTurnRepeatTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()

    def game(self, board=('double', 'end'), enemy=(), hand=(), enemy_hand=(),
            weapon=None, power='power', rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',) * 20,
                mana=10, max_mana=10, weapon_card_id=weapon, hero_power_card_id=power),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id='power')), seed=144),
            self.r, ruleset=rules)

    def script(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **kwargs))

    def minion(self, name, callback=None, scope='controller', condition='always', **kwargs):
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

    def finite(self, name, callback, uses=1):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            limited_triggers=(LimitedTriggerSpec('turn_ended', name, uses=uses,
                end_turn=EndTurnSpec()),)))

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

    def check(self, game, fresh=False):
        snapshot = json.loads(json.dumps(game.snapshot()))
        registry = fixture_registry() if fresh else self.r
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)

    def rows(self, game):
        return game.state.end_turn_history

    def batch(self, game, index=-1):
        return game.state.end_turn_batches[index]

    def counts(self, game):
        return [p.repetitions for p in self.batch(game).plans]

    def waiting(self, board=('double', 'waiting', 'end'), hand=()):
        game = self.game(board=board, hand=hand)
        self.end(game)
        self.assertIsNotNone(game.state.pending_choice)
        return game

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

    def reject(self, snapshot, rehash=True):
        if rehash:
            snapshot['events_hash'] = canonical_hash(snapshot['events'])
            snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.r)
        if rehash:
            self.assertNotIn('digest mismatch', str(error.exception))

    def test_no_policy_has_one_position_and_old_gameplay_events(self):
        game = self.game(board=('end', 'raw'))
        self.end(game)
        self.assertEqual(self.counts(game), [1])
        self.assertEqual(self.batch(game).total, 1)
        self.assertEqual([e.kind for e in game.events],
            ['turn_ended', 'armor_gained', 'armor_gained', 'turn_started', 'card_drawn'])
        self.assertEqual(self.armor(game), 11)
        self.check(game, fresh=True)

    def test_double_is_one_natural_event_and_two_distinct_actual_positions(self):
        game = self.game()
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual(self.counts(game), [2])
        self.assertEqual([(r.capture.id, r.capture.index, r.capture.repeat_index,
            r.guard_id, r.execution_order, r.completed) for r in self.rows(game)],
            [(1, 0, 0, 1, 1, True), (2, 0, 1, 1, 2, True)])
        self.assertEqual([e.kind for e in game.events].count('turn_ended'), 1)
        self.assertEqual([e.kind for e in game.events].count('turn_started'), 1)
        self.assertEqual([e.kind for e in game.events].count('card_drawn'), 1)
        self.check(game, fresh=True)

    def test_two_double_sources_set_max_and_keep_both_contributors(self):
        game = self.game(board=('double', 'double', 'end'))
        self.end(game)
        plan = self.batch(game).plans[0]
        self.assertEqual((plan.repetitions, len(plan.contributors)), (2, 2))
        self.assertEqual(len({s.key for s in plan.contributors}), 2)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_max_captures_lower_equal_and_same_carrier_declarations(self):
        game = self.game(board=('double', 'multi', 'triple', 'end'))
        self.end(game)
        plan = self.batch(game).plans[0]
        self.assertEqual(plan.repetitions, 3)
        self.assertEqual([s.spec.repetitions for s in plan.contributors], [2, 2, 3, 3])
        self.assertEqual(len({s.key for s in plan.contributors}), 4)
        self.assertTrue(all(s.spec == s.ability.end_turn_repeat for s in plan.contributors))
        self.check(game)

    def test_enemy_policy_does_not_repeat_friendly_controller_subject(self):
        game = self.game(board=('end',), enemy=('triple',))
        self.end(game)
        self.assertEqual(self.counts(game), [1])
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_all_policy_includes_every_supported_physical_and_player_carrier(self):
        game = self.game(board=('double', 'end', 'location', 'dormant'),
            weapon='weapon', power='end_power', hand=('player_body',))
        self.play(game, 'player_body')
        self.end(game)
        self.assertEqual(self.counts(game), [2] * 6)
        self.assertEqual(self.armor(game), 12)
        self.assertEqual({s.card_id for s in self.batch(game).subjects},
            {'end_power', 'weapon', 'end', 'location', 'dormant', 'double'})
        self.check(game)

    def test_minion_filter_uses_subject_carrier_even_when_player_source_is_minion(self):
        game = self.game(board=('minion_double', 'end', 'location', 'dormant'),
            weapon='weapon', power='end_power', hand=('player_body',))
        self.play(game, 'player_body')
        self.end(game)
        subjects = self.batch(game).subjects
        counts = {s.card_id: p.repetitions for s, p in zip(subjects, self.batch(game).plans)}
        self.assertEqual(counts, {'end_power': 1, 'weapon': 1, 'end': 2,
            'location': 1, 'dormant': 2, 'minion_double': 1})
        player_subject = next(s for s in subjects if s.player_effect is not None)
        self.assertEqual(game.state.entities[player_subject.source_id].kind, CardType.MINION)
        self.assertEqual(self.armor(game), 8)
        self.check(game)

    def test_all_and_minion_plans_differ_inside_same_natural_batch(self):
        self.r.register_card(CardDefinition('filtered', 'filtered', CardType.MINION,
            health=5, end_turn_repeats=(EndTurnRepeatSpec(3, 'minion'),)))
        game = self.game(board=('double', 'filtered', 'end'), weapon='weapon')
        self.end(game)
        self.assertEqual({s.card_id: p.repetitions for s, p in
            zip(self.batch(game).subjects, self.batch(game).plans)}, {'weapon': 2, 'end': 3})
        self.check(game)

    def test_opponent_and_either_subjects_use_their_owner_policy(self):
        self.minion('opponent', scope='opponent')
        self.minion('either', scope='either')
        game = self.game(board=('double', 'end', 'either'),
            enemy=('triple', 'opponent', 'either'))
        self.end(game)
        self.assertEqual(self.counts(game), [2, 2, 3, 3])
        self.assertEqual((self.armor(game, 1), self.armor(game, 2)), (4, 6))
        self.assertEqual([r.capture.subject.player_id for r in self.rows(game)], [1] * 4 + [2] * 6)
        self.check(game)

    def test_repeats_expand_each_old_listener_slot_before_next_slot(self):
        game = self.game(board=('double', 'fresh', 'raw', 'fresh'))
        self.end(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'],
            [1, 2, 10, 1, 15])
        self.assertEqual(self.armor(game), 29)
        self.assertEqual([r.capture.index for r in self.rows(game)], [0, 0, 1, 1])
        self.assertEqual([self.batch(game).position(i) for i in range(4)],
            [(0, 0), (0, 1), (1, 0), (1, 1)])
        self.check(game)

    def test_same_behavior_on_two_attachments_has_two_full_repeat_spans(self):
        self.minion('two', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),
            TriggerSpec('turn_ended', 'armor', EndTurnSpec())))
        game = self.game(board=('double', 'two'))
        self.end(game)
        self.assertEqual(self.counts(game), [2, 2])
        self.assertEqual(len({s.ability.id for s in self.batch(game).subjects}), 2)
        self.assertEqual([r.guard_id for r in self.rows(game)], [1, 1, 3, 3])
        self.assertEqual(self.armor(game), 4)
        self.check(game)

    def test_acceptance_condition_not_rechecked_after_first_body_changes_it(self):
        self.r.register_trigger_condition('undamaged', lambda c: c.source.damage == 0)
        self.minion('conditional', lambda c: [Damage(c.source_id, 1), GainArmor(c.player_id, 1)],
            condition='undamaged')
        game = self.game(board=('double', 'conditional'))
        self.end(game)
        self.assertEqual((self.body(game, index=1).damage, self.armor(game)), (2, 2))
        self.end(game)
        self.end(game)
        self.assertEqual(self.batch(game).total, 0)
        self.check(game)

    def test_first_body_retains_acceptance_extra_reads_post_ordinary_reaction(self):
        self.raw('ten_first', lambda c: [GainArmor(1, 10)])
        game = self.game(board=('double', 'ten_first', 'fresh'))
        self.end(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [10, 1, 12])
        self.check(game)

    def test_policy_disabled_before_acceptance_is_not_a_contributor(self):
        for operation in (Silence, lambda i: MakeDormant(i, 3), Destroy):
            with self.subTest(operation=operation):
                self.setUp()
                self.script('disable', lambda c, op=operation: [op(c.state.players[1].board[0])])
                game = self.game(hand=('disable',))
                self.play(game, 'disable')
                self.end(game)
                self.assertEqual(self.counts(game), [1])
                self.check(game)

    def test_policy_created_by_first_body_waits_for_next_natural_acceptance(self):
        self.minion('creator', lambda c: [Summon(c.player_id, 'double'), GainArmor(c.player_id, 1)])
        game = self.game(board=('creator', 'end'))
        self.end(game)
        self.assertEqual(self.counts(game), [1, 1])
        self.end(game)
        self.end(game)
        self.assertEqual(self.counts(game), [2, 2])
        self.check(game)

    def test_policy_lifecycle_changes_do_not_shrink_frozen_current_plan(self):
        for operation in (Destroy, Silence, ReturnToHand,
                lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.minion('changer', lambda c, op=operation: (
                    [op(c.state.players[1].board[0])] if c.end_turn.repeat_index == 0 else [])
                    + [GainArmor(c.player_id, 1)])
                game = self.game(board=('double', 'changer'))
                self.end(game)
                self.assertEqual((self.counts(game), self.armor(game)), ([2], 2))
                self.check(game)

    def test_body_lifecycle_changes_keep_frozen_owner_ability_but_extra_source_is_fresh(self):
        for operation in (Destroy, Silence, ReturnToHand,
                lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.minion('changer', lambda c, op=operation: (
                    [op(c.source_id)] if c.end_turn.repeat_index == 0 else [])
                    + [GainArmor(c.player_id, 1 if c.end_turn.repeat_index == 0 else
                        10 + int(c.trigger not in c.source.abilities) +
                        int(c.source.controller != c.player_id))])
                game = self.game(board=('double', 'changer'))
                self.end(game)
                self.assertEqual(self.counts(game), [2])
                self.assertGreaterEqual(self.armor(game), 11)
                self.assertEqual(self.armor(game, 2), 0)
                self.assertTrue(all(r.capture.subject.card_id == 'changer' for r in self.rows(game)))
                self.check(game)

    def test_new_body_created_in_repeated_work_not_added_to_current_subjects(self):
        self.minion('summoner', lambda c: [Summon(c.player_id, 'end')])
        game = self.game(board=('double', 'summoner'))
        self.end(game)
        self.assertEqual(self.counts(game), [2])
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[1].board],
            ['double', 'summoner', 'end', 'end'])
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_finite_repeats_consume_one_use_and_one_used_event_per_subject(self):
        game = self.game(board=('triple', 'finite'))
        self.end(game)
        self.assertEqual((self.armor(game), self.body(game, index=1).abilities[-1].uses_remaining), (3, 1))
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.assertEqual([r.guard_passed for r in self.rows(game)], [True] * 3)
        self.assertEqual([r.guard_id for r in self.rows(game)], [1] * 3)
        self.end(game)
        self.end(game)
        self.assertEqual((self.armor(game), self.body(game, index=1).abilities[-1].uses_remaining), (6, 0))
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 2)
        self.check(game)

    def test_finite_last_use_callback_and_extras_share_one_updated_trigger(self):
        self.finite('last', lambda c: [GainArmor(c.player_id,
            10 * c.end_turn.subject.ability.uses_remaining + c.trigger.uses_remaining)], uses=1)
        game = self.game(board=('double', 'last'))
        self.end(game)
        self.assertEqual(self.armor(game), 20)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.check(game)

    def test_failed_finite_guard_skips_whole_span_without_retry_or_use(self):
        self.raw('killer', lambda c: [Destroy(c.state.players[1].board[2])])
        game = self.game(board=('double', 'killer', 'finite'))
        source = self.body(game, index=2).id
        self.end(game)
        self.assertEqual([(r.execution_order, r.skipped, r.guard_passed) for r in self.rows(game)],
            [(None, True, False), (None, True, False)])
        self.assertEqual(game.state.entities[source].abilities[-1].uses_remaining, 2)
        self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
        self.assertTrue(self.batch(game).completed)
        self.check(game)

    def test_used_event_choice_preserves_one_receipt_before_any_actual_repeat(self):
        self.raw('used_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (Silence(c.event.source_id),)),),
            source_id=c.source_id)], event='limited_trigger_used')
        game = self.game(board=('double', 'used_wait', 'finite'))
        self.end(game)
        self.assertEqual([r.execution_order for r in self.rows(game)], [None, None])
        self.assertEqual([r.guard_passed for r in self.rows(game)], [True, True])
        receipt = self.rows(game)[0].guard_event
        self.assertEqual([r.guard_event for r in self.rows(game)], [receipt, receipt])
        self.assertIn(receipt, game.events)
        self.assertEqual(dict(receipt.data), {'end_turn_guard_id': 1,
            'end_turn_ability_id': self.rows(game)[0].capture.subject.ability.id,
            'trigger_keyword': None})
        self.assertEqual(self.body(game, index=2).abilities[-1].uses_remaining, 1)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.assertTrue(self.body(game, index=2).silenced)
        self.check(game)

    def test_finite_source_destroyed_after_success_still_runs_extra(self):
        self.finite('suicide', lambda c: [Destroy(c.source_id), GainArmor(c.player_id, 1)])
        game = self.game(board=('double', 'suicide'))
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.assertTrue(all(r.completed and r.guard_passed for r in self.rows(game)))
        self.check(game)

    def test_installed_power_guard_once_and_no_manual_power_history(self):
        game = self.game(board=('double',), power='end_power')
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertEqual([r.guard_passed for r in self.rows(game)], [True, True])
        self.assertFalse(game.state.hero_power_history)
        self.assertFalse(game.state.hero_power_payload_history)
        self.check(game)

    def test_power_removal_before_first_guard_skips_every_repeat(self):
        self.raw('remove', lambda c: [RemoveHeroPower(1)])
        self.script('install', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('double', 'remove'), hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertEqual(self.armor(game), 0)
        self.assertTrue(all(r.skipped and r.execution_order is None for r in self.rows(game)))
        self.check(game)

    def test_power_replacement_after_first_guard_keeps_accepted_extra(self):
        self.r.register_behavior('replace_self', lambda c: [ReplaceHeroPower(1, 'power'), GainArmor(1, 1)])
        self.r.register_card(CardDefinition('replace_power', 'replace_power', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'replace_self', EndTurnSpec()),)))
        game = self.game(board=('double',), power='replace_power')
        original = game.state.players[1].hero_power_id
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(all(r.capture.subject.source_id == original for r in self.rows(game)))
        self.assertNotEqual(game.state.players[1].hero_power_id, original)
        self.check(game)

    def test_persistent_policy_survives_original_card_and_owner_is_separate(self):
        self.script('install_enemy', lambda c: [AddPlayerEffect(2, 'persistent',
            c.state.players[1].board[0]), ChangeControl(c.state.players[1].board[0], 2)])
        self.minion('either', scope='either')
        game = self.game(board=('plain', 'end'), enemy=('either',), hand=('install_enemy',))
        self.play(game, 'install_enemy')
        self.end(game)
        self.assertEqual(self.counts(game), [1, 2])
        source = self.batch(game).plans[1].contributors[0]
        self.assertEqual((source.player_id, source.card_id, source.spec_index), (2, 'plain', 0))
        self.assertIsNotNone(source.player_effect)
        self.check(game)

    def test_player_body_removed_during_first_execution_keeps_extra_and_source(self):
        self.r.register_behavior('remove_body', lambda c: [RemovePlayerEffect(c.player_id,
            c.player_effect.id), GainArmor(c.player_id, 1)])
        self.r.register_player_effect(PlayerEffectSpec('removable_body', 'plain',
            triggers=(TriggerSpec('turn_ended', 'remove_body', EndTurnSpec()),)))
        self.script('install_body', lambda c: [AddPlayerEffect(1, 'removable_body',
            c.state.players[1].board[0])])
        game = self.game(board=('double',), hand=('install_body',))
        self.play(game, 'install_body')
        self.end(game)
        self.assertEqual(self.armor(game), 2)
        self.assertFalse(game.state.players[1].player_effects)
        self.check(game)

    def test_duration_three_ticks_once_per_owner_boundary_and_then_expires(self):
        game = self.game(board=('end',), hand=('clock',))
        self.play(game, 'clock')
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.assertEqual(self.armor(game), 2)
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.end(game)
        self.end(game)
        self.end(game)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual(self.armor(game), 105)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 2)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game, fresh=True)

    def test_remaining_one_policy_contributes_before_single_expiry_after_choices(self):
        game = self.game(board=('waiting',), hand=('short',))
        self.play(game, 'short')
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.check(game, fresh=True)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.choose(game)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual(self.armor(game), 101)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game, fresh=True)

    def test_opponent_scope_uses_owner_policy_without_owner_clock_tick(self):
        self.minion('opponent', scope='opponent')
        self.script('enemy_clock', lambda c: [AddPlayerEffect(2, 'clock', c.source_id)])
        game = self.game(board=(), enemy=('opponent',), hand=('enemy_clock',))
        self.play(game, 'enemy_clock')
        self.end(game)
        self.assertEqual(self.armor(game, 2), 2)
        self.assertEqual(game.state.players[2].player_effects[0].remaining_turns, 3)
        self.end(game)
        self.assertEqual(game.state.players[2].player_effects[0].remaining_turns, 2)
        self.check(game)

    def test_policy_added_during_natural_work_neither_expands_nor_ticks_immediately(self):
        self.minion('adder', lambda c: [AddPlayerEffect(c.player_id, 'clock', c.source_id)])
        game = self.game(board=('adder', 'end'))
        self.end(game)
        self.assertEqual(self.counts(game), [1, 1])
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertNotIn('player_effect_ticked', [e.kind for e in game.events])
        self.check(game)

    def test_replaced_player_instance_not_ticked_by_old_instance_clock(self):
        self.minion('replace_clock', lambda c: ([RemovePlayerEffect(1,
            c.state.players[1].player_effects[0].id), AddPlayerEffect(1, 'clock', c.source_id)]
            if c.end_turn.repeat_index == 0 else []))
        game = self.game(board=('replace_clock',), hand=('clock',))
        self.play(game, 'clock')
        old = game.state.players[1].player_effects[0].id
        self.end(game)
        new = game.state.players[1].player_effects[0]
        self.assertNotEqual(new.id, old)
        self.assertEqual(new.remaining_turns, 3)
        self.assertEqual(self.counts(game), [2])
        self.assertNotIn('player_effect_ticked', [e.kind for e in game.events])
        self.check(game)

    def test_expiry_thaw_and_enchantment_cleanup_wait_for_all_repeats_then_run_once(self):
        self.script('prepare', lambda c: [Buff(c.state.players[1].board[1], 2, 2,
            c.source_id, expires_turn=c.state.turn), Freeze(c.state.players[1].board[1])])
        game = self.game(board=('double', 'waiting'), hand=('prepare', 'short'))
        self.play(game, 'prepare')
        self.play(game, 'short')
        self.end(game)
        self.choose(game)
        self.assertTrue(self.body(game, index=1).frozen)
        self.assertTrue(self.body(game, index=1).enchantments)
        self.choose(game)
        self.assertFalse(self.body(game, index=1).frozen)
        self.assertFalse(self.body(game, index=1).enchantments)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game)

    def test_granted_policy_has_source_attachment_and_current_copy_identity(self):
        self.script('grant', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].board[0],
            EndTurnRepeatSpec(), c.source_id), CopyMinion(c.state.players[1].board[0], 1),
            CopyMinion(c.state.players[1].board[0], 1, mode='base')])
        game = self.game(board=('plain', 'end'), hand=('grant',))
        grantor = self.play(game, 'grant')
        self.end(game)
        sources = self.batch(game).plans[0].contributors
        self.assertEqual(len(sources), 2)
        self.assertEqual({s.ability.source_id for s in sources}, {grantor})
        self.assertEqual({s.ability.origin for s in sources}, {'granted'})
        self.assertEqual(len({s.ability.id for s in sources}), 2)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_granted_policy_expiry_silence_and_bounce_prevent_later_recapture(self):
        for operation in (Silence, ReturnToHand, None):
            with self.subTest(operation=operation):
                self.setUp()
                self.script('grant', lambda c: [GrantEndTurnRepeatAura(
                    c.state.players[1].board[0], source_id=c.source_id, expires_turn=c.state.turn)])
                self.script('remove', lambda c, op=operation: [] if op is None else
                    [op(c.state.players[1].board[0])])
                game = self.game(board=('plain', 'end'), hand=('grant', 'remove'))
                self.play(game, 'grant')
                if operation is not None:
                    self.play(game, 'remove')
                self.end(game)
                self.assertEqual(self.counts(game), [2] if operation is None else [1])
                self.end(game)
                self.end(game)
                self.assertEqual(self.counts(game), [1])
                self.check(game)

    def test_granted_repeat_on_nonminion_uses_existing_stale_effect_semantics(self):
        self.script('grant', lambda c: [GrantEndTurnRepeatAura(c.state.players[1].weapon_id,
            source_id=c.source_id)])
        game = self.game(board=(), hand=('grant',), weapon='weapon')
        self.play(game, 'grant')
        weapon = game.state.entities[game.state.players[1].weapon_id]
        self.assertFalse(active_abilities(weapon, 'end_turn_repeat'))
        self.end(game)
        self.assertEqual(self.counts(game), [1])
        self.check(game)

    def test_granted_minion_body_is_filtered_by_host_not_spell_grantor(self):
        self.script('grant_body', lambda c: [GrantTrigger(c.state.players[1].board[1],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec())])
        game = self.game(board=('minion_double', 'plain'), hand=('grant_body',))
        source = self.play(game, 'grant_body')
        self.end(game)
        subject = self.batch(game).subjects[0]
        self.assertEqual((subject.card_id, subject.ability.source_id), ('plain', source))
        self.assertEqual(self.counts(game), [2])
        self.check(game)

    def test_magnetic_repeat_source_retains_host_and_original_part_provenance(self):
        metadata = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('mech',))
        self.r.register_card(CardDefinition('part', 'part', CardType.MINION,
            attack=1, health=5, metadata=metadata, keywords=(Keyword.MAGNETIC,),
            magnetic_tribes=('mech',), end_turn_repeats=(EndTurnRepeatSpec(),)))
        self.minion('host', metadata=metadata)
        game = self.game(board=('host',), hand=('part',))
        origin = self.play(game, 'part', position=0)
        host = self.body(game)
        self.end(game)
        source = self.batch(game).plans[0].contributors[0]
        self.assertEqual((source.carrier_id, source.card_id, source.ability.source_id,
            source.ability.magnetic_id), (host.id, 'host', origin, 1))
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_starship_building_policy_inactive_then_component_policies_are_distinct(self):
        self.minion('piece', keywords=(Keyword.STARSHIP_PIECE,),
            end_turn_repeats=(EndTurnRepeatSpec(),))
        self.r.register_card(CardDefinition('ship', 'ship', CardType.MINION,
            starship_for=(CardClass.NEUTRAL,)))
        self.script('build', lambda c: [Destroy(i) for i in c.state.players[1].board])
        game = self.game(board=('piece', 'piece'), hand=('build',))
        self.play(game, 'build')
        ship = self.body(game)
        self.assertTrue(ship.starship_building)
        self.end(game)
        self.assertEqual(self.batch(game).total, 0)
        self.end(game)
        game.apply(LaunchStarship(1, ship.id))
        self.end(game)
        self.assertEqual(self.counts(game), [2, 2])
        plans = self.batch(game).plans
        self.assertEqual([len(p.contributors) for p in plans], [2, 2])
        self.assertEqual({s.carrier_id for p in plans for s in p.contributors}, {ship.id})
        self.assertEqual(len({s.ability.id for s in plans[0].contributors}), 2)
        self.assertEqual(self.armor(game), 4)
        self.check(game)

    def test_finite_guard_lifecycle_failure_skips_all_extras_without_used_event(self):
        for operation in (Silence, ReturnToHand, lambda i: ChangeControl(i, 2),
                lambda i: MakeDormant(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.raw('changer', lambda c, op=operation: [op(c.state.players[1].board[2])])
                game = self.game(board=('triple', 'changer', 'finite'))
                self.end(game)
                self.assertEqual(len(self.rows(game)), 3)
                self.assertTrue(all(r.skipped and r.execution_order is None for r in self.rows(game)))
                self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
                self.check(game)

    def test_ordinary_source_destroyed_before_slot_has_old_first_and_fresh_extra(self):
        self.raw('killer', lambda c: [Destroy(c.state.players[1].board[2])])
        self.minion('zone_reader', lambda c: [GainArmor(c.player_id,
            1 if c.source.zone == Zone.BOARD else 10)])
        game = self.game(board=('double', 'killer', 'zone_reader'))
        self.end(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [1, 10])
        self.assertTrue(all(r.completed and not r.skipped for r in self.rows(game)))
        self.check(game)

    def test_repeat_body_triggers_separate_deathrattle_plan_without_fake_death(self):
        self.r.register_card(CardDefinition('rattle', 'rattle', CardType.MINION,
            health=8, deathrattle='armor'))
        self.r.register_card(CardDefinition('dr_double', 'dr_double', CardType.MINION,
            health=5, deathrattle_repeats=(DeathrattleRepeatSpec(),)))
        self.minion('activator', lambda c: [TriggerDeathrattles(c.state.players[1].board[2],
            c.source_id)])
        game = self.game(board=('double', 'dr_double', 'rattle', 'activator'))
        self.end(game)
        self.assertEqual(self.armor(game), 4)
        self.assertEqual(len(game.state.deathrattle_history), 4)
        self.assertFalse(game.state.death_history)
        self.assertEqual(self.counts(game), [2])
        self.check(game)

    def test_real_death_settles_before_extra_fresh_body_without_duplicate_death(self):
        self.r.register_card(CardDefinition('rattle', 'rattle', CardType.MINION,
            health=1, deathrattle='ten'))
        self.minion('destroyer', lambda c: ([Destroy(c.state.players[1].board[1])]
            if c.end_turn.repeat_index == 0 else []) + [GainArmor(1,
                len(c.state.players[1].board))])
        game = self.game(board=('double', 'rattle', 'destroyer'))
        self.end(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [10, 3, 2])
        self.assertEqual(len(game.state.death_history), 1)
        self.check(game)

    def test_each_repeat_choice_restores_and_replays_with_fresh_registry(self):
        game = self.waiting(board=('double', 'waiting'))
        self.check(game, fresh=True)
        self.choose(game, 'three')
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2])
        self.assertEqual([r.completed for r in self.rows(game)], [True, False])
        self.check(game, fresh=True)
        self.choose(game, 'one')
        self.assertEqual(self.armor(game), 4)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.check(game, fresh=True)

    def test_trailing_ordinary_choice_keeps_complete_repeat_proof_until_timers(self):
        self.raw('raw_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(c.player_id, 10),)),), source_id=c.source_id)])
        game = self.game(board=('double', 'end', 'raw_wait'), hand=('short',))
        self.play(game, 'short')
        self.end(game)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.assertFalse(self.batch(game).completed)
        self.assertTrue(game.state.players[1].player_effects)
        self.assertTrue(self.named(game.snapshot(), 'FinishEndTurnBatch'))
        self.check(game)
        self.choose(game)
        self.assertTrue(self.batch(game).completed)
        self.assertEqual(self.armor(game), 111)
        self.check(game)

    def test_fact_query_excludes_queue_and_tracks_each_actual_execution(self):
        game = self.waiting(board=('triple', 'waiting'))
        self.assertEqual([r.capture.repeat_index for r in activated_end_turns(game.state, 1)], [0])
        self.assertEqual(activated_end_turns(game.state, 1, completed=True), ())
        self.choose(game)
        self.assertEqual([r.capture.repeat_index for r in activated_end_turns(game.state, 1)], [0, 1])
        self.choose(game)
        self.choose(game)
        source = self.rows(game)[0].capture.subject.source_id
        self.assertEqual(len(activated_end_turns(game.state, 1, source_id=source, turn=1)), 3)
        self.assertEqual(activated_end_turns(game.state, 2), ())
        self.check(game)

    def test_empty_batch_even_with_policies_has_zero_positions(self):
        game = self.game(board=('double',))
        self.end(game)
        self.assertEqual((self.batch(game).subjects, self.batch(game).plans,
            self.batch(game).total), ((), (), 0))
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.rows(game))
        self.check(game, fresh=True)

    def test_empty_behavior_still_starts_and_completes_every_repeat(self):
        self.minion('empty', lambda c: [])
        game = self.game(board=('triple', 'empty'))
        self.end(game)
        self.assertEqual(len(self.rows(game)), 3)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_lethal_first_or_intermediate_repeat_preserves_only_prior_completions(self):
        for lethal_at in (0, 1):
            with self.subTest(lethal_at=lethal_at):
                self.setUp()
                self.minion('lethal', lambda c, n=lethal_at: [Damage(c.state.players[2].hero_id,
                    30 if c.end_turn.repeat_index == n else 0, c.source_id)])
                game = self.game(board=('triple', 'lethal', 'end'), hand=('short',))
                self.play(game, 'short')
                self.end(game)
                self.assertEqual(game.state.winner, 1)
                self.assertEqual(sum(r.completed for r in self.rows(game)), lethal_at)
                self.assertEqual(sum(r.execution_order is not None for r in self.rows(game)), lethal_at + 1)
                self.assertTrue(self.batch(game).interrupted)
                self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
                self.assertEqual((game.state.active_player, game.state.turn), (1, 1))
                self.check(game)

    def test_error_in_extra_rolls_back_whole_end_action(self):
        def fail(c):
            if c.end_turn.repeat_index:
                raise ValueError('synthetic second-body error')
            return [GainArmor(c.player_id, 1)]
        self.minion('failure', fail)
        game = self.game(board=('double', 'failure'))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.end(game)
        self.assertEqual(game.snapshot(), before)

    def test_expanded_positions_share_resolution_budget_and_rollback(self):
        self.r.register_card(CardDefinition('huge', 'huge', CardType.MINION, health=8,
            end_turn_repeats=(EndTurnRepeatSpec(1000),)))
        game = self.game(board=('huge', 'end'), rules=Ruleset(max_resolution_steps=50))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.end(game)
        self.assertEqual(game.snapshot(), before)

    def test_extra_body_work_uses_shared_budget_not_new_independent_budget(self):
        self.minion('work', lambda c: [GainArmor(1, 1)] * 25)
        game = self.game(board=('triple', 'work'), rules=Ruleset(max_resolution_steps=50))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.end(game)
        self.assertEqual(game.snapshot(), before)

    def test_player_views_hide_plans_receipts_and_private_continuation(self):
        game = self.waiting()
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer),
                game.for_player(viewer).legal_actions()))
            for internal in ('end_turn_history', 'end_turn_batches', 'EndTurnRepeatPlan',
                    'contributors', 'guard_id', 'repeat_index', 'execution_order',
                    'resolution_frame', 'acceptance', 'EndTurnCapture'):
                self.assertNotIn('"' + internal + '"', text)
        self.check(game)

    def test_spec_count_scope_and_untyped_declarations_rejected(self):
        for args in ((True,), (1,), (0,), (2.0,), (2, 'friendly'), (2, None)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                EndTurnRepeatSpec(*args)
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('bad', 'bad', CardType.MINION,
                health=5, end_turn_repeats=(object(),)))
        with self.assertRaises(ValueError):
            PlayerEffectSpec('bad', 'plain', end_turn_repeats=[EndTurnRepeatSpec()])
        with self.assertRaises(ValueError):
            AbilityInstance(1, 'trigger', end_turn_repeat=EndTurnRepeatSpec())

    def test_nonminion_printed_repeat_declarations_are_rejected(self):
        for kind in (CardType.SPELL, CardType.WEAPON, CardType.LOCATION, CardType.HERO_POWER):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('bad', 'bad', kind,
                    end_turn_repeats=(EndTurnRepeatSpec(),)))

    def test_rehashed_repeat_position_and_guard_reference_corruption_rejected(self):
        game = self.waiting()
        for field, value in (('repeat_index', 0), ('index', 1), ('id', 1)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_history'][1]['capture'][field] = value
                self.reject(snapshot)
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][1]['guard_id'] = 2
        self.reject(snapshot)

    def test_rehashed_missing_extra_history_position_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        del snapshot['state']['end_turn_history'][1]
        self.reject(snapshot)

    def test_rehashed_missing_queued_extra_invocation_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        extra = next(x for x in queue if str(x.get('type', '')).endswith('.InvokeEndTurn'))
        queue.remove(extra)
        self.reject(snapshot)

    def test_rehashed_same_behavior_repeat_queue_swap_rejected(self):
        game = self.waiting(board=('double', 'waiting', 'waiting'))
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        indexes = [i for i, x in enumerate(queue) if str(x.get('type', '')).endswith('.InvokeEndTurn')]
        queue[indexes[0]], queue[indexes[-1]] = queue[indexes[-1]], queue[indexes[0]]
        self.reject(snapshot)

    def test_rehashed_plan_omitting_lower_equal_source_rejected(self):
        game = self.waiting(board=('double', 'triple', 'waiting'))
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][0]['plans'][0]['contributors'].pop(0)
        self.reject(snapshot)

    def test_rehashed_plan_max_and_scope_corruption_rejected(self):
        game = self.waiting()
        for mutate in (lambda p: p.update(repetitions=3),
                lambda p: p['contributors'][0]['spec'].update(scope='minion')):
            with self.subTest(mutate=mutate):
                snapshot = game.snapshot()
                mutate(snapshot['state']['end_turn_batches'][0]['plans'][0])
                self.reject(snapshot)

    def test_rehashed_contributor_identity_provenance_corruption_rejected(self):
        game = self.waiting()
        for field, value in (('carrier_id', self.body(game, index=1).id),
                ('card_id', 'triple'), ('player_id', 2)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0]['plans'][0]['contributors'][0][field] = value
                self.reject(snapshot)

    def test_rehashed_player_contributor_owner_instance_and_spec_index_rejected(self):
        game = self.game(board=('waiting',), hand=('persistent',))
        self.play(game, 'persistent')
        self.end(game)
        for field, value in (('player_id', 2), ('spec_index', 1), ('card_id', 'clock')):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0]['plans'][0]['contributors'][0][field] = value
                self.reject(snapshot)

    def test_rehashed_playing_batch_cannot_be_terminal_interrupted(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][0]['interrupted'] = True
        self.reject(snapshot)

    def test_rehashed_started_ordinary_record_cannot_forge_guard_receipt(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][0]['guard_passed'] = True
        self.reject(snapshot)

    def test_rehashed_successful_finite_span_cannot_drop_shared_receipt(self):
        self.finite('finite_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 1),)),), source_id=c.source_id)])
        game = self.game(board=('double', 'finite_wait'))
        self.end(game)
        snapshot = game.snapshot()
        snapshot['state']['end_turn_history'][1]['guard_passed'] = False
        self.reject(snapshot)

    def test_rehashed_natural_event_or_batch_deletion_rejected(self):
        game = self.game()
        self.end(game)
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'].clear()
        snapshot['state']['end_turn_history'].clear()
        self.reject(snapshot)
        snapshot = game.snapshot()
        snapshot['events'] = [e for e in snapshot['events'] if e['kind'] != 'turn_ended']
        self.reject(snapshot)

    def shrink_only_subject(self, snapshot):
        """Jointly change live/captured facts, while keeping original source proof."""
        batch = snapshot['state']['end_turn_batches'][0]
        batch['plans'][0] = {'repetitions': 1, 'contributors': []}
        snapshot['state']['end_turn_history'][0]['capture']['plan'] = deepcopy(batch['plans'][0])
        del snapshot['state']['end_turn_history'][1:]
        for plan in self.named(snapshot, 'EndTurnRepeatPlan'):
            plan['fields'] = {'repetitions': 1, 'contributors': {'tuple': []}}

    def test_joint_shrink_last_extra_at_choice_rejected_by_original_complete_proof(self):
        game = self.waiting(board=('double', 'waiting'))
        self.choose(game)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2])
        snapshot = game.snapshot()
        self.shrink_only_subject(snapshot)
        queue = self.queue(snapshot)
        queue[:] = [w for w in queue if not str(w.get('type', '')).endswith('.FinishEndTurn')]
        self.reject(snapshot)

    def test_joint_shrink_completed_repeats_during_tail_raw_choice_rejected(self):
        self.raw('raw_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
        game = self.game(board=('double', 'end', 'raw_wait'))
        self.end(game)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        snapshot = game.snapshot()
        self.shrink_only_subject(snapshot)
        self.reject(snapshot)

    def test_queued_extra_cannot_disguise_acceptance_as_started_fresh_context(self):
        game = self.waiting(board=('double', 'waiting'))
        snapshot = game.snapshot()
        work = next(w for w in self.queue(snapshot)
            if str(w.get('type', '')).endswith('.InvokeEndTurn'))
        for field in ('context', 'acceptance'):
            state = work['fields'][field]['fields']['state']['state']
            state['end_turn_history'][0]['completed'] = True
            state['end_turn_history'][1]['execution_order'] = 2
        self.reject(snapshot)

    def test_finite_check_cannot_be_bypassed_with_forged_span_receipt_and_original_window(self):
        game = self.waiting(board=('double', 'waiting', 'finite'))
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        work = next(w for w in queue if str(w.get('type', '')).endswith('.CheckLimitedTrigger'))
        context = deepcopy(work['fields']['end_turn_context'])
        for row in snapshot['state']['end_turn_history'][2:]:
            row['guard_passed'] = True
        queue[queue.index(work)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_guarded_extra_cannot_spend_a_second_finite_use_in_queued_context(self):
        self.finite('finite_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 1),)),), source_id=c.source_id)], uses=3)
        game = self.game(board=('double', 'finite_wait'))
        self.end(game)
        snapshot = game.snapshot()
        work = next(w for w in self.queue(snapshot)
            if str(w.get('type', '')).endswith('.InvokeEndTurn'))
        work['fields']['context']['fields']['trigger']['fields']['uses_remaining'] = 1
        self.reject(snapshot)

    def test_finite_current_uses_cannot_restore_preconsumption_or_spend_again(self):
        self.finite('finite_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 1),)),), source_id=c.source_id)], uses=3)
        game = self.game(board=('double', 'finite_wait'))
        self.end(game)
        source = self.body(game, index=1).id
        for remaining in (3, 1):
            with self.subTest(remaining=remaining):
                snapshot = game.snapshot()
                entity = snapshot['state']['entities'][str(source)]
                entity['abilities'][-1]['uses_remaining'] = remaining
                self.reject(snapshot)

    def test_frame_empty_explicit_plans_cannot_take_constructor_default(self):
        game = self.waiting(board=('double', 'waiting'))
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                snapshot = game.snapshot()
                finish = self.named(snapshot, 'FinishEndTurnBatch')[0]
                finish['fields']['batch']['fields']['plans'] = {'tuple': []}
                self.reject(snapshot, rehash=rehash)

    def test_frame_null_contributor_spec_cannot_be_derived_as_valid_wire(self):
        game = self.waiting(board=('double', 'waiting'))
        for rehash in (False, True):
            with self.subTest(rehash=rehash):
                snapshot = game.snapshot()
                contributors = self.named(snapshot, 'EndTurnRepeatContributor')
                self.assertTrue(contributors)
                for source in contributors:
                    source['fields']['spec'] = None
                self.reject(snapshot, rehash=rehash)

    def test_snapshot_schema_96_is_rejected_instead_of_defaulting_repeat_fields(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['schema_version'] = 96
        self.reject(snapshot)

    def fake_finite_invocation(self, snapshot, event, postconsume=True):
        """Forge one pending check and its whole span, without editing events."""
        queue = self.queue(snapshot)
        check = next(w for w in queue
            if str(w.get('type', '')).endswith('.CheckLimitedTrigger') and
            w['fields']['end_turn_context'] is not None)
        acceptance = deepcopy(check['fields']['end_turn_context'])
        callback = deepcopy(acceptance)
        capture = acceptance['fields']['end_turn']['fields']
        first_id = capture['id']
        count = capture['plan']['fields']['repetitions']
        for row in snapshot['state']['end_turn_history'][first_id - 1:first_id - 1 + count]:
            row['guard_passed'] = True
            row['guard_event'] = deepcopy(event)
        if postconsume:
            subject = capture['subject']['fields']
            original = subject['ability']['fields']
            updated = deepcopy(original)
            updated['uses_remaining'] -= 1
            updated['consumed'] = updated['uses_remaining'] == 0
            callback['fields']['trigger']['fields'] = deepcopy(updated)
            callback_state = callback['fields']['state']['state']
            callback_state['action_number'] = event['action']
            for row in callback_state['end_turn_history'][first_id - 1:first_id - 1 + count]:
                row['guard_passed'] = True
                row['guard_event'] = deepcopy(event)
            for state in (snapshot['state'], callback_state):
                source = state['entities'][str(subject['source_id'])]
                ability = next(a for a in source['abilities'] if a['id'] == original['id'])
                ability.update(updated)
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': callback, 'acceptance': acceptance}}
        return first_id, capture['subject']['fields']['ability']['fields']['id']

    def test_first_power_check_cannot_be_replaced_by_forged_passed_invocation(self):
        self.script('install', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('double', 'waiting'), hand=('install',))
        self.play(game, 'install')
        self.end(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.check(game)
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        check = next(w for w in queue if str(w.get('type', '')).endswith('.CheckHeroPowerTrigger'))
        context = deepcopy(check['fields']['context'])
        capture = context['fields']['end_turn']['fields']
        first = capture['id'] - 1
        for row in snapshot['state']['end_turn_history'][first:first + 2]:
            row['guard_passed'] = True
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_finite_check_forged_receipt_rejects_pre_and_postconsumption_windows(self):
        game = self.waiting(board=('double', 'waiting', 'finite'))
        for postconsume in (False, True):
            with self.subTest(postconsume=postconsume):
                snapshot = game.snapshot()
                row = snapshot['state']['end_turn_history'][2]
                subject = row['capture']['subject']
                event = {'sequence': len(snapshot['events']) + 1,
                    'action': snapshot['state']['action_number'], 'kind': 'limited_trigger_used',
                    'source_id': subject['source_id'], 'target_id': None,
                    'player_id': subject['player_id'], 'amount': 1,
                    'data': {'end_turn_guard_id': row['capture']['id'],
                        'end_turn_ability_id': subject['ability']['id'], 'trigger_keyword': None}}
                events = deepcopy(snapshot['events'])
                self.fake_finite_invocation(snapshot, event, postconsume=postconsume)
                self.assertEqual(snapshot['events'], events)
                self.reject(snapshot)

    def test_same_carrier_unclassified_used_event_cannot_supply_classified_guard(self):
        self.r.register_card(CardDefinition('mixed_finite', 'mixed_finite', CardType.MINION,
            health=8, limited_triggers=(
                LimitedTriggerSpec('turn_ended', 'waiting', uses=2),
                LimitedTriggerSpec('turn_ended', 'armor', uses=2, end_turn=EndTurnSpec()))))
        game = self.game(board=('double', 'mixed_finite'))
        self.end(game)
        self.assertIsNotNone(game.state.pending_choice)
        used = next(e for e in game.events if e.kind == 'limited_trigger_used')
        first = self.rows(game)[0]
        self.assertEqual((used.source_id, used.player_id, used.amount),
            (first.capture.subject.source_id, first.capture.subject.player_id, 1))
        self.assertEqual(dict(used.data), {'trigger_keyword': None})
        self.assertFalse(first.guard_passed)
        self.check(game)
        for insert_ids in (False, True):
            with self.subTest(insert_ids=insert_ids):
                snapshot = game.snapshot()
                event = deepcopy(next(e for e in snapshot['events'] if e['kind'] == 'limited_trigger_used'))
                if insert_ids:
                    event['data'].update(end_turn_guard_id=first.capture.id,
                        end_turn_ability_id=first.capture.subject.ability.id)
                events = deepcopy(snapshot['events'])
                self.fake_finite_invocation(snapshot, event)
                self.assertEqual(snapshot['events'], events)
                self.reject(snapshot)
        self.choose(game)
        classified = [e for e in game.events if e.kind == 'limited_trigger_used'
            and 'end_turn_guard_id' in dict(e.data)]
        self.assertEqual(len(classified), 1)
        self.assertNotEqual(classified[0].sequence, used.sequence)
        self.assertEqual([r.guard_event for r in self.rows(game)], [classified[0]] * 2)
        self.assertEqual(self.armor(game), 3)
        self.check(game)

    def test_ordinary_choice_then_late_finite_guard_and_used_choice_are_recoverable(self):
        self.raw('raw_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 1),)),), source_id=c.source_id)])
        self.raw('used_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 10),)),), source_id=c.source_id)],
            event='limited_trigger_used')
        game = self.game(board=('double', 'raw_wait', 'used_wait', 'finite'))
        self.end(game)
        natural = self.batch(game).event
        self.assertTrue(all(not r.guard_passed for r in self.rows(game)))
        self.check(game)
        self.choose(game)
        receipt = self.rows(game)[0].guard_event
        self.assertGreater(receipt.action, natural.action)
        self.assertEqual(receipt.action, game.state.action_number)
        self.assertEqual([r.execution_order for r in self.rows(game)], [None, None])
        self.assertEqual([r.guard_event for r in self.rows(game)], [receipt, receipt])
        self.assertIsNotNone(game.state.pending_choice)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 13)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.check(game)

    def test_start_clock_does_not_tick_end_body_and_expires_after_old_start_listener(self):
        self.r.register_behavior('start_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(1, 7),)),), source_id=c.source_id)]
            if c.event.player_id == c.player_id else [])
        self.r.register_player_effect(PlayerEffectSpec('start_clock', 'plain',
            'objective', 1, 'turn_started', on_expire='expire',
            triggers=(TriggerSpec('turn_started', 'start_wait'),),
            end_turn_repeats=(EndTurnRepeatSpec(2, 'minion'),)))
        self.script('install_start', lambda c: [AddPlayerEffect(1, 'start_clock', c.source_id)])
        game = self.game(board=('end',), hand=('install_start',))
        self.play(game, 'install_start')
        self.end(game)
        self.assertEqual(self.counts(game), [2])
        self.assertEqual(self.armor(game), 2)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.assertFalse(game.state.pending_choice)
        self.assertNotIn('player_effect_ticked', [e.kind for e in game.events])
        self.end(game)
        self.assertEqual((game.state.active_player, game.state.turn), (1, 3))
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.assertNotIn('player_effect_expired', [e.kind for e in game.events])
        self.check(game)
        self.choose(game)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual(self.armor(game), 108)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.check(game)
        self.end(game)
        self.assertEqual(self.counts(game), [1])
        self.assertEqual(self.armor(game), 109)
        self.check(game)

    def test_real_finite_guard_fact_and_both_internal_ids_are_private(self):
        self.raw('used_wait', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)],
            event='limited_trigger_used')
        game = self.game(board=('double', 'used_wait', 'finite'))
        self.end(game)
        receipt = self.rows(game)[0].guard_event
        self.assertIn(receipt, game.events)
        self.assertTrue({'end_turn_guard_id', 'end_turn_ability_id'} <= set(dict(receipt.data)))
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer),
                game.for_player(viewer).legal_actions()))
            for name in ('guard_event', 'end_turn_guard_id', 'end_turn_ability_id'):
                self.assertNotIn('"' + name + '"', text)
        self.check(game)


if __name__ == '__main__':
    unittest.main()
