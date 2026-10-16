"""M5-13d-02l-05c: explicit effect/phase roots without natural clocks."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest
from copy import deepcopy

from hs_sim.engine import (AddPlayerEffect, CardDefinition, CardType, EndTurn,
    EndTurnSpec, Game, IllegalAction, LimitedTriggerSpec, PlayCard, PlayerEffectSpec,
    PlayerSetup, Registry, RemovePlayerEffect, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, Damage,
    Destroy, Freeze, GainArmor, GrantTrigger, ReplaceHeroPower, RequestChoice,
    ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.end_turns import TriggerEndTurnEffects, activated_end_turns
from hs_sim.engine.hero_powers import RemoveHeroPower
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (EndTurnActivationProfile, EndTurnRepeatSpec,
    EndTurnRequest, EndTurnSelector, Event)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


CARRIERS = ('minion', 'weapon', 'hero_power', 'location', 'player_effect')


def request(players=(1,), carriers=CARRIERS, profile='end_turn.effect',
            entities=(), effects=(), mode='owner'):
    return EndTurnRequest(EndTurnSelector(mode, players, carriers, entities, effects), profile)


def fixture_registry():
    r = Registry('end-turn-activation-fixtures-v1')
    r.register_end_turn_profile(EndTurnActivationProfile('effect.respect', turn_scope='respect'))
    r.register_end_turn_profile(EndTurnActivationProfile('phase.respect', kind='phase',
        turn_scope='respect', cause_events=('turn_started',)))
    r.register_end_turn_profile(EndTurnActivationProfile('effect.cause_target',
        target_policy='cause', cause_events=('armor_gained',)))
    r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=8))
    r.register_behavior('armor', lambda c: [GainArmor(c.player_id, 1)])
    r.register_behavior('ten', lambda c: [GainArmor(c.player_id, 10)])
    r.register_behavior('expire', lambda c: [GainArmor(c.player_id, 99)])
    r.register_behavior('fresh', lambda c: [GainArmor(c.player_id,
        c.state.entities[c.state.players[c.player_id].hero_id].armor + 1)])
    r.register_behavior('waiting', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('one', 'one', (GainArmor(c.player_id, 1),)),
         ChoiceOption('three', 'three', (GainArmor(c.player_id, 3),))), source_id=c.source_id)])
    r.register_trigger_condition('never', lambda c: False)
    r.register_trigger_condition('undamaged', lambda c: c.source.damage == 0)
    r.register_trigger_condition('not_bool', lambda c: 1)
    for name, scope, behavior, condition in (
            ('end', 'controller', 'armor', 'always'), ('opponent', 'opponent', 'armor', 'always'),
            ('either', 'either', 'armor', 'always'), ('waiting', 'controller', 'waiting', 'always'),
            ('fresh', 'controller', 'fresh', 'always'), ('never', 'controller', 'armor', 'never'),
            ('undamaged', 'controller', 'armor', 'undamaged'),
            ('bad_condition', 'controller', 'armor', 'not_bool')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            triggers=(TriggerSpec('turn_ended', behavior, EndTurnSpec(scope, condition)),)))
    r.register_card(CardDefinition('raw', 'raw', CardType.MINION, health=8,
        triggers=(TriggerSpec('turn_ended', 'ten'),)))
    r.register_card(CardDefinition('double', 'double', CardType.MINION, health=5,
        end_turn_repeats=(EndTurnRepeatSpec(),)))
    r.register_card(CardDefinition('finite', 'finite', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', uses=2,
            end_turn=EndTurnSpec()),)))
    r.register_card(CardDefinition('finite_never', 'finite_never', CardType.MINION, health=8,
        limited_triggers=(LimitedTriggerSpec('turn_ended', 'armor', condition_id='never',
            uses=2, end_turn=EndTurnSpec()),)))
    r.register_card(CardDefinition('dormant', 'dormant', CardType.MINION, health=8,
        dormant_turns=2, triggers=(TriggerSpec('turn_ended', 'ten', EndTurnSpec()),),
        dormant_triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=1, durability=3,
        triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('location', 'location', CardType.LOCATION, durability=2,
        on_use='armor', triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    r.register_card(CardDefinition('power', 'power', CardType.HERO_POWER, cost=2, on_use='armor'))
    r.register_card(CardDefinition('end_power', 'end_power', CardType.HERO_POWER,
        passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
    for name, duration in (('persistent', None), ('clock', 3), ('short', 1)):
        r.register_player_effect(PlayerEffectSpec(name, name,
            kind='persistent' if duration is None else 'objective', duration=duration,
            tick_event=None if duration is None else 'turn_ended',
            on_expire=None if duration is None else 'expire',
            triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
        r.register_behavior(name, lambda c, n=name: [AddPlayerEffect(c.player_id, n, c.source_id)])
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('invoke', lambda c: [TriggerEndTurnEffects(c.player_id, request(), c.source_id)])
    r.register_card(CardDefinition('invoke', 'invoke', CardType.SPELL, on_play='invoke'))
    r.register_behavior('default_source', lambda c: [TriggerEndTurnEffects(c.player_id, request())])
    r.register_card(CardDefinition('default_source', 'default_source', CardType.SPELL,
        on_play='default_source'))
    return r


class EndTurnActivationTests(unittest.TestCase):
    def setUp(self):
        self.r = fixture_registry()

    def game(self, board=('end',), enemy=(), hand=('invoke',), enemy_hand=(),
            power='power', weapon=None, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', board=board, hand=hand, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id=power, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy, hand=enemy_hand, deck=('plain',) * 20,
                mana=10, max_mana=10, hero_power_card_id='power')), seed=146), self.r, ruleset=rules)

    def script(self, name, callback):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def minion(self, name, callback, **kwargs):
        self.r.register_behavior(name, callback)
        kwargs.setdefault('health', 8)
        kwargs.setdefault('triggers', (TriggerSpec('turn_ended', name, EndTurnSpec()),))
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **kwargs))

    def raw(self, name, callback, event='turn_ended'):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.MINION, health=8,
            triggers=(TriggerSpec(event, name),)))

    def play(self, game, card='invoke'):
        owner = game.state.active_player
        entity = next(i for i in game.state.players[owner].hand
            if game.state.entities[i].card_id == card)
        game.apply(PlayCard(owner, entity))
        return entity

    def end(self, game):
        game.apply(EndTurn(game.state.active_player))

    def choose(self, game, option='one'):
        choice = game.state.pending_choice
        game.apply(SelectChoice(choice.player_id, choice.id, (option,)))

    def body(self, game, player=1, index=0):
        return game.state.entities[game.state.players[player].board[index]]

    def armor(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id].armor

    def batch(self, game, index=-1):
        return game.state.end_turn_batches[index]

    def rows(self, game):
        return game.state.end_turn_history

    def check(self, game, fresh=False):
        registry = fixture_registry() if fresh else self.r
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, registry).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), registry).snapshot(), snapshot)

    def waiting(self, board=('double', 'waiting')):
        game = self.game(board=board)
        self.play(game)
        self.assertIsNotNone(game.state.pending_choice)
        return game

    def named(self, value, name):
        result = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + name):
                result.append(value)
            for key, child in value.items():
                if key == 'fields' and value.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                    for field, operand in child.items():
                        if field != 'work':
                            result.extend(self.named(operand, name))
                else:
                    result.extend(self.named(child, name))
        elif isinstance(value, list):
            for child in value:
                result.extend(self.named(child, name))
        return result

    def queue(self, snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    def reject(self, snapshot):
        snapshot['events_hash'] = canonical_hash(snapshot['events'])
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, self.r)
        self.assertNotIn('digest mismatch', str(error.exception))

    def phase_fixture(self, profile='end_turn.phase', players=(1, 2)):
        self.raw('phase_source', lambda c: [TriggerEndTurnEffects(1,
            request(players=players, profile=profile), c.source_id, c.event)]
            if c.event.player_id == 1 else [], event='turn_started')
        game = self.game(board=('phase_source', 'end', 'opponent', 'either', 'never'),
            enemy=('end', 'opponent', 'either'), hand=())
        self.end(game)
        self.end(game)
        return game

    def nested_fixture(self, finite=False, natural=False):
        if finite:
            self.r.register_behavior('nested_finite', lambda c: [TriggerEndTurnEffects(1,
                request(mode='selected', carriers=('minion',), entities=(c.source_id,)),
                c.source_id)] if c.end_turn.subject.ability.uses_remaining == 2 else
                self.r.behavior('waiting')(c))
            self.r.register_card(CardDefinition('nested', 'nested', CardType.MINION,
                health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'nested_finite',
                    uses=2, end_turn=EndTurnSpec()),)))
            game = self.game(board=('nested',))
        else:
            self.minion('nested', lambda c: [TriggerEndTurnEffects(1,
                request(mode='selected', carriers=('minion',),
                    entities=(c.state.players[1].board[1],)), c.source_id)]
                if c.end_turn.repeat_index == 0 else [GainArmor(1, 10)])
            game = self.game(board=('nested', 'waiting'))
        if natural:
            self.end(game)
        else:
            self.play(game)
        self.assertIsNotNone(game.state.pending_choice)
        return game

    def guard_nested_fixture(self):
        self.r.register_behavior('finite_wait', lambda c: self.r.behavior('waiting')(c))
        self.r.register_card(CardDefinition('finite_wait', 'finite_wait', CardType.MINION,
            health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'finite_wait', uses=2,
                end_turn=EndTurnSpec()),)))
        self.raw('used_nested', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.event.source_id,)), c.source_id)]
            if c.event.amount == 1 else [], event='limited_trigger_used')
        game = self.game(board=('used_nested', 'finite_wait'))
        self.play(game)
        self.assertIsNotNone(game.state.pending_choice)
        return game

    def three_layer_fixture(self, warmup=False):
        self.r.register_behavior('finite_wait', lambda c: self.r.behavior('waiting')(c))
        self.r.register_card(CardDefinition('finite_wait', 'finite_wait', CardType.MINION,
            health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'finite_wait', uses=2,
                end_turn=EndTurnSpec()),)))
        self.minion('outer', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[2],)), c.source_id)])
        self.raw('used_nested', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.event.source_id,)), c.source_id)]
            if c.event.amount == 1 else [], event='limited_trigger_used')
        self.script('selected_outer', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[0],)), c.source_id)])
        self.script('warmup', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[3],)), c.source_id)])
        game = self.game(board=('outer', 'used_nested', 'finite_wait', 'end'),
            hand=('warmup', 'selected_outer') if warmup else ('selected_outer',))
        if warmup:
            self.play(game, 'warmup')
        self.play(game, 'selected_outer')
        self.assertIsNotNone(game.state.pending_choice)
        return game

    def test_effect_has_separate_root_and_no_fabricated_natural_event(self):
        game = self.game()
        issuer = self.play(game)
        batch = self.batch(game)
        origin = batch.activation
        self.assertIsNone(batch.event)
        self.assertEqual((origin.kind, origin.issuer_id, origin.issuer_card_id,
            origin.issuer_player_id, origin.action, origin.parent_id),
            ('effect', issuer, 'invoke', 1, 1, None))
        self.assertEqual(origin.request, request())
        self.assertEqual(self.armor(game), 1)
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        for kind in ('turn_ended', 'turn_started', 'card_drawn'):
            self.assertNotIn(kind, [e.kind for e in game.events])
        self.assertTrue(batch.completed)
        self.check(game, fresh=True)

    def test_omitted_issuer_uses_explicit_requesting_players_hero(self):
        game = self.game(hand=('default_source',))
        original_hero = game.state.entities[game.state.players[1].hero_id]
        self.play(game, 'default_source')
        origin = self.batch(game).activation
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual((origin.issuer_id, origin.issuer_card_id, origin.issuer_entered_order,
            origin.issuer_zone_epoch), (hero.id, 'hero', original_hero.entered_order, hero.zone_epoch))
        self.check(game, fresh=True)

    def test_owner_intersects_explicit_owners_with_carriers(self):
        self.script('enemy_minions', lambda c: [TriggerEndTurnEffects(1,
            request(players=(2,), carriers=('minion',)), c.source_id)])
        game = self.game(enemy=('end',), hand=('enemy_minions',), weapon='weapon')
        self.play(game, 'enemy_minions')
        self.assertEqual([s.player_id for s in self.batch(game).subjects], [2])
        self.assertEqual((self.armor(game, 1), self.armor(game, 2)), (0, 1))
        self.check(game)

    def test_all_five_carriers_include_player_body_and_dormant_body(self):
        game = self.game(board=('end', 'location', 'dormant'), weapon='weapon',
            power='end_power', hand=('persistent', 'invoke'))
        self.play(game, 'persistent')
        self.play(game)
        subjects = self.batch(game).subjects
        self.assertEqual(len(subjects), 6)
        self.assertEqual({s.card_id for s in subjects},
            {'end', 'location', 'dormant', 'weapon', 'end_power', 'persistent'})
        self.assertEqual(self.armor(game), 6)
        self.assertEqual(next(s for s in subjects if s.card_id == 'dormant').ability.kind, 'dormant_trigger')
        self.check(game, fresh=True)

    def test_selected_entity_freezes_all_distinct_bodies_on_that_carrier(self):
        self.r.register_card(CardDefinition('two', 'two', CardType.MINION, health=8,
            triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),
                TriggerSpec('turn_ended', 'armor', EndTurnSpec()))))
        self.script('selected', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[1],)), c.source_id)])
        game = self.game(board=('end', 'two', 'raw'), hand=('selected',))
        self.play(game, 'selected')
        self.assertEqual(len(self.batch(game).subjects), 2)
        self.assertEqual(len({s.ability.id for s in self.batch(game).subjects}), 2)
        self.assertEqual({s.card_id for s in self.batch(game).subjects}, {'two'})
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_selected_player_effect_uses_instance_identity_not_minion_source(self):
        self.script('selected_pe', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('player_effect',),
                effects=(c.state.players[1].player_effects[1].id,)), c.source_id)])
        game = self.game(hand=('persistent', 'persistent', 'selected_pe'))
        self.play(game, 'persistent')
        self.play(game, 'persistent')
        selected = game.state.players[1].player_effects[1].id
        self.play(game, 'selected_pe')
        self.assertEqual([s.player_effect.id for s in self.batch(game).subjects], [selected])
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_selected_empty_lists_are_a_real_empty_completed_root(self):
        self.script('empty', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected'), c.source_id)])
        game = self.game(hand=('empty',))
        self.play(game, 'empty')
        self.assertEqual((self.batch(game).subjects, self.batch(game).plans, self.batch(game).total), ((), (), 0))
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.rows(game))
        self.check(game)

    def test_selected_ids_do_not_override_owner_or_carrier_filter(self):
        self.script('wrong_owner', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', players=(2,), entities=(c.state.players[1].board[0],)), c.source_id)])
        game = self.game(hand=('wrong_owner',))
        self.play(game, 'wrong_owner')
        self.assertEqual(self.batch(game).total, 0)
        self.check(game)

    def test_selector_input_order_does_not_reorder_old_listener_positions(self):
        self.script('reversed', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=tuple(reversed(c.state.players[1].board))), c.source_id)])
        game = self.game(board=('end', 'end', 'end'), hand=('reversed',))
        sources = tuple(game.state.players[1].board)
        self.play(game, 'reversed')
        self.assertEqual(tuple(s.source_id for s in self.batch(game).subjects), sources)
        self.check(game)

    def test_owner_order_is_active_player_first_then_entered_order(self):
        self.script('both', lambda c: [TriggerEndTurnEffects(2,
            request(players=(2, 1)), c.source_id)])
        game = self.game(board=('end', 'end'), enemy=('end',), hand=('both',))
        self.play(game, 'both')
        self.assertEqual([s.player_id for s in self.batch(game).subjects], [1, 1, 2])
        self.assertEqual(self.batch(game).activation.issuer_player_id, 2)
        self.check(game)

    def test_effect_ignore_accepts_controller_opponent_and_either_specs(self):
        game = self.game(board=('end', 'opponent', 'either'))
        self.play(game)
        self.assertEqual([s.spec.turn_scope for s in self.batch(game).subjects],
            ['controller', 'opponent', 'either'])
        self.assertEqual(self.armor(game), 3)
        self.check(game, fresh=True)

    def test_effect_condition_kept_and_false_body_is_not_captured(self):
        game = self.game(board=('end', 'never', 'undamaged'))
        self.play(game)
        self.assertEqual([s.card_id for s in self.batch(game).subjects], ['end', 'undamaged'])
        self.assertEqual(self.armor(game), 2)
        self.check(game, fresh=True)

    def test_condition_nonbool_rejects_and_rolls_back_requesting_action(self):
        game = self.game(board=('bad_condition',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_finite_condition_remains_separate_from_end_condition(self):
        game = self.game(board=('finite_never',))
        self.play(game)
        self.assertEqual(self.batch(game).total, 0)
        self.assertEqual(self.body(game).abilities[-1].uses_remaining, 2)
        self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
        self.check(game, fresh=True)

    def test_unclassified_turn_listener_is_not_invoked_by_effect(self):
        game = self.game(board=('raw', 'end'))
        self.play(game)
        self.assertEqual((self.armor(game), self.batch(game).total), (1, 1))
        self.check(game, fresh=True)

    def test_each_classified_slot_expands_before_next_and_extra_is_fresh(self):
        game = self.game(board=('double', 'fresh', 'raw', 'fresh'))
        self.play(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [1, 2, 1, 5])
        self.assertEqual([r.capture.index for r in self.rows(game)], [0, 0, 1, 1])
        self.assertEqual(self.armor(game), 9)
        self.check(game, fresh=True)

    def test_natural_condition_not_rechecked_after_first_repeated_body(self):
        self.minion('damaging', lambda c: [Damage(c.source_id, 1), GainArmor(1, 1)],
            triggers=(TriggerSpec('turn_ended', 'damaging', EndTurnSpec(condition_id='undamaged')),))
        game = self.game(board=('double', 'damaging'))
        self.play(game)
        self.assertEqual((self.body(game, index=1).damage, self.armor(game)), (2, 2))
        self.check(game)

    def test_finite_effect_uses_one_guard_one_consumption_and_true_event(self):
        game = self.game(board=('double', 'finite'))
        self.play(game)
        self.assertEqual((self.armor(game), self.body(game, index=1).abilities[-1].uses_remaining), (2, 1))
        used = [e for e in game.events if e.kind == 'limited_trigger_used']
        self.assertEqual(len(used), 1)
        self.assertEqual([r.guard_event for r in self.rows(game)], [used[0], used[0]])
        self.assertTrue(all(r.guard_passed and r.completed for r in self.rows(game)))
        self.assertIsNone(self.batch(game).event)
        self.check(game, fresh=True)

    def test_finite_callback_receives_none_cause_and_updated_trigger(self):
        self.r.register_behavior('finite_view', lambda c: [GainArmor(1,
            10 * int(c.event is None) + c.trigger.uses_remaining)])
        self.r.register_card(CardDefinition('finite_view', 'finite_view', CardType.MINION,
            health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'finite_view', uses=2,
                end_turn=EndTurnSpec()),)))
        game = self.game(board=('double', 'finite_view'))
        self.play(game)
        self.assertEqual(self.armor(game), 22)
        self.check(game)

    def test_hp_effect_guard_does_not_create_manual_power_activation(self):
        game = self.game(board=('double',), power='end_power')
        self.play(game)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(all(r.guard_passed for r in self.rows(game)))
        self.assertFalse(game.state.hero_power_history)
        self.assertFalse(game.state.hero_power_payload_history)
        self.check(game, fresh=True)

    def test_active_work_never_ticks_or_expires_owner_player_clock(self):
        game = self.game(hand=('clock', 'invoke', 'invoke'))
        self.play(game, 'clock')
        for _ in range(2):
            self.play(game)
            self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 3)
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        self.assertNotIn('player_effect_ticked', [e.kind for e in game.events])
        self.assertNotIn('player_effect_expired', [e.kind for e in game.events])
        self.check(game, fresh=True)

    def test_effect_does_not_thaw_or_expire_turn_enchantment(self):
        self.script('prepare', lambda c: [Buff(c.state.players[1].board[0], 2, 2,
            c.source_id, expires_turn=c.state.turn), Freeze(c.state.players[1].board[0])])
        game = self.game(hand=('prepare', 'invoke'))
        self.play(game, 'prepare')
        self.play(game)
        self.assertTrue(self.body(game).frozen)
        self.assertTrue(self.body(game).enchantments)
        self.assertEqual(game.state.turn, 1)
        self.check(game)

    def test_no_eligible_bodies_still_records_empty_effect_root(self):
        game = self.game(board=('plain', 'raw'))
        self.play(game)
        self.assertEqual(self.batch(game).total, 0)
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.rows(game))
        self.check(game, fresh=True)

    def test_body_empty_effects_still_completes_all_repeat_facts(self):
        self.minion('empty', lambda c: [])
        game = self.game(board=('double', 'empty'))
        self.play(game)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2])
        self.check(game)

    def test_choice_in_each_extra_restores_clones_and_replays_fresh_registry(self):
        game = self.waiting()
        self.check(game, fresh=True)
        self.choose(game, 'three')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual([r.completed for r in self.rows(game)], [True, False])
        self.check(game, fresh=True)
        self.choose(game)
        self.assertEqual(self.armor(game), 4)
        self.assertTrue(self.batch(game).completed)
        self.check(game, fresh=True)

    def test_actual_query_excludes_unstarted_effect_repeats(self):
        game = self.waiting()
        self.assertEqual([r.capture.repeat_index for r in activated_end_turns(game.state, 1)], [0])
        self.choose(game)
        self.assertEqual([r.capture.repeat_index for r in activated_end_turns(game.state, 1)], [0, 1])
        self.choose(game)
        self.assertEqual(len(activated_end_turns(game.state, 1, completed=True)), 2)
        self.check(game, fresh=True)

    def test_unknown_profile_is_explicit_resolution_error_and_action_rollback(self):
        self.script('unknown', lambda c: [TriggerEndTurnEffects(1,
            request(profile='end_turn.unknown'), c.source_id)])
        game = self.game(hand=('unknown',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'unknown')
        self.assertEqual(game.snapshot(), before)

    def test_forged_cause_not_in_real_events_is_rejected(self):
        self.script('forged', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id,
            Event(999, c.state.action_number, 'turn_started', player_id=1))])
        game = self.game(hand=('forged',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'forged')
        self.assertEqual(game.snapshot(), before)

    def test_phase_requires_its_real_allowed_cause(self):
        self.script('bad_phase', lambda c: [TriggerEndTurnEffects(1,
            request(profile='end_turn.phase'), c.source_id)])
        game = self.game(hand=('bad_phase',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'bad_phase')
        self.assertEqual(game.snapshot(), before)

    def test_selector_strict_tuple_ids_and_owner_mode_constraints(self):
        hero = EndTurnSelector('owner', (1,), ('hero',), (), ())
        self.assertEqual(hero.carrier_kinds, ('hero',))
        invalid = (
            ('all', (1,), ('minion',), (), ()),
            ('owner', [1], ('minion',), (), ()),
            ('owner', (True,), ('minion',), (), ()),
            ('owner', (1, 1), ('minion',), (), ()),
            ('owner', (), ('minion',), (), ()),
            ('owner', (1,), (), (), ()),
            ('owner', (1,), ('secret',), (), ()),
            ('owner', (1,), ('minion', 'minion'), (), ()),
            ('owner', (1,), ('minion',), (1,), ()),
            ('selected', (1,), ('minion',), (True,), ()),
            ('selected', (1,), ('player_effect',), (), (0,)),
        )
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                EndTurnSelector(*args)

    def test_profile_registry_fingerprint_and_readonly_mapping_are_explicit(self):
        other = fixture_registry()
        baseline = self.r.fingerprint()
        other.register_end_turn_profile(EndTurnActivationProfile('another'))
        self.assertNotEqual(other.fingerprint(), baseline)
        self.assertEqual(self.r.end_turn_profile('end_turn.effect').turn_scope, 'ignore')
        self.assertEqual(self.r.end_turn_profile('end_turn.phase').cause_events, ('turn_started',))
        with self.assertRaises(TypeError):
            self.r.end_turn_profiles['new'] = EndTurnActivationProfile('new')

    def test_rehashed_missing_or_null_batch_activation_is_rejected(self):
        game = self.waiting()
        for remove in (True, False):
            with self.subTest(remove=remove):
                snapshot = game.snapshot()
                batch = snapshot['state']['end_turn_batches'][0]
                if remove:
                    del batch['activation']
                else:
                    batch['activation'] = None
                self.reject(snapshot)

    def test_rehashed_activation_kind_issuer_or_parent_corruption_rejected(self):
        game = self.waiting()
        for field, value in (('kind', 'natural'), ('issuer_id', self.body(game).id),
                ('issuer_card_id', 'plain'), ('issuer_player_id', 2), ('parent_id', 999)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0]['activation'][field] = value
                self.reject(snapshot)

    def test_rehashed_saved_selector_bool_nonlist_and_unknown_field_rejected(self):
        game = self.waiting()
        for field, value in (('player_ids', [True]), ('carrier_kinds', 'minion'),
                ('unexpected', 1), ('entity_ids', [True])):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                selector = snapshot['state']['end_turn_batches'][0]['activation']['request']['selector']
                selector[field] = value
                self.reject(snapshot)

    def test_rehashed_request_unknown_profile_is_rejected(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][0]['activation']['request']['profile_id'] = 'missing'
        self.reject(snapshot)

    def test_phase_ignore_uses_real_start_event_with_both_owners_and_all_scopes(self):
        game = self.phase_fixture()
        batch = self.batch(game)
        self.assertEqual((batch.activation.kind, batch.event.kind, batch.event.player_id),
            ('phase', 'turn_started', 1))
        self.assertEqual(len(batch.subjects), 6)
        self.assertIn(batch.event, game.events)
        self.assertEqual([e.kind for e in game.events].count('turn_ended'), 2)
        self.assertEqual([e.kind for e in game.events].count('turn_started'), 2)
        self.assertEqual((game.state.turn, game.state.active_player), (3, 1))
        self.check(game)

    def test_phase_respect_matches_controller_opponent_and_either_to_real_owner(self):
        game = self.phase_fixture('phase.respect')
        self.assertEqual([(s.player_id, s.spec.turn_scope) for s in self.batch(game).subjects],
            [(1, 'controller'), (1, 'either'), (2, 'opponent'), (2, 'either')])
        self.check(game)

    def test_respect_effect_without_real_beneficiary_rejects_and_rolls_back(self):
        self.script('respect', lambda c: [TriggerEndTurnEffects(1,
            request(profile='effect.respect'), c.source_id)])
        game = self.game(hand=('respect',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'respect')
        self.assertEqual(game.snapshot(), before)

    def test_real_cause_target_policy_keeps_callback_event_and_target_separate(self):
        for policy in ('none', 'cause'):
            with self.subTest(policy=policy):
                self.setUp()
                self.r.register_end_turn_profile(EndTurnActivationProfile('damage.profile',
                    target_policy=policy, cause_events=('damage_dealt',)))
                self.minion('reader', lambda c: [GainArmor(1, 1 if c.target_id is None else 10)])
                self.raw('react', lambda c: [TriggerEndTurnEffects(1,
                    request(carriers=('minion',), profile='damage.profile'), c.source_id, c.event)],
                    event='damage_dealt')
                self.script('damage', lambda c: [Damage(c.state.players[2].hero_id, 1, c.source_id)])
                game = self.game(board=('reader', 'react'), hand=('damage',))
                self.play(game, 'damage')
                cause = self.batch(game).event
                self.assertEqual((cause.kind, cause.target_id), ('damage_dealt', game.state.players[2].hero_id))
                self.assertIn(cause, game.events)
                self.assertEqual(self.armor(game), 1 if policy == 'none' else 10)
                self.check(game)

    def test_disallowed_real_phase_cause_rolls_back_action(self):
        self.raw('bad_cause', lambda c: [TriggerEndTurnEffects(1,
            request(profile='end_turn.phase'), c.source_id, c.event)], event='armor_gained')
        self.script('armor_cause', lambda c: [GainArmor(1, 7)])
        game = self.game(board=('bad_cause', 'end'), hand=('armor_cause',))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, 'armor_cause')
        self.assertEqual(game.snapshot(), before)

    def test_multiple_effect_roots_same_turn_have_independent_ids_and_cursors(self):
        game = self.game(hand=('invoke', 'invoke'))
        self.play(game)
        self.play(game)
        self.assertEqual([(b.id, b.first_id, b.activation.action, b.activation.parent_id)
            for b in game.state.end_turn_batches], [(1, 1, 1, None), (2, 2, 2, None)])
        self.assertLess(self.batch(game, 0).activation.event_cursor, self.batch(game, 1).activation.event_cursor)
        self.assertEqual(self.armor(game), 2)
        self.check(game, fresh=True)

    def test_nested_effect_uses_parent_capture_and_independent_complete_proofs(self):
        game = self.nested_fixture()
        outer, inner = game.state.end_turn_batches
        self.assertEqual(inner.activation.parent_id, self.rows(game)[0].capture.id)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, None, 2])
        self.assertFalse(outer.completed or inner.completed)
        self.check(game)
        self.choose(game)
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.batch(game, 0).completed)
        self.assertIsNotNone(game.state.pending_choice)
        self.check(game)
        self.choose(game)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_natural_body_can_create_effect_root_without_additional_clock(self):
        game = self.nested_fixture(natural=True)
        self.assertEqual([b.activation.kind for b in game.state.end_turn_batches], ['natural', 'effect'])
        self.assertEqual([e.kind for e in game.events].count('turn_ended'), 1)
        self.assertEqual(game.state.turn, 1)
        self.check(game)
        self.choose(game)
        self.choose(game)
        self.assertEqual((game.state.turn, game.state.active_player), (2, 2))
        self.assertEqual([e.kind for e in game.events].count('turn_started'), 1)
        self.check(game)

    def test_nested_same_finite_carrier_consumes_once_per_root_with_later_receipt(self):
        game = self.nested_fixture(finite=True)
        self.assertEqual(self.body(game).abilities[-1].uses_remaining, 0)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2])
        self.assertEqual([e.amount for e in game.events if e.kind == 'limited_trigger_used'], [1, 0])
        self.assertEqual(self.batch(game).activation.parent_id, self.rows(game)[0].capture.id)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 1)
        self.assertTrue(all(r.completed and r.guard_passed for r in self.rows(game)))
        self.check(game)

    def test_nested_finite_current_uses_without_real_later_receipt_is_rejected(self):
        self.r.register_behavior('finite_wait', lambda c: self.r.behavior('waiting')(c))
        self.r.register_card(CardDefinition('finite_wait', 'finite_wait', CardType.MINION,
            health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'finite_wait', uses=2,
                end_turn=EndTurnSpec()),)))
        game = self.game(board=('finite_wait',))
        self.play(game)
        snapshot = game.snapshot()
        source = str(self.body(game).id)
        entities = snapshot['state']['entities']
        entity = entities[source] if isinstance(entities, dict) else next(x for x in entities if x['id'] == self.body(game).id)
        entity['abilities'][-1]['uses_remaining'] = 0
        entity['abilities'][-1]['consumed'] = True
        self.reject(snapshot)

    def test_active_batch_completes_before_its_callers_next_choice(self):
        self.script('caller_tail', lambda c: [TriggerEndTurnEffects(1, request(), c.source_id),
            *self.r.behavior('waiting')(c)])
        game = self.game(hand=('caller_tail',))
        self.play(game, 'caller_tail')
        self.assertIsNotNone(game.state.pending_choice)
        self.assertTrue(self.batch(game).completed)
        self.assertTrue(self.rows(game)[0].completed)
        self.assertFalse(self.named(game.snapshot()['resolution_frame'], 'FinishEndTurnBatch'))
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.check(game)

    def test_natural_tail_choice_keeps_outer_proof_after_completed_nested_effect(self):
        self.minion('nested', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[1],)), c.source_id)])
        self.raw('tail', lambda c: self.r.behavior('waiting')(c))
        game = self.game(board=('nested', 'end', 'tail'), hand=('short',))
        self.play(game, 'short')
        self.end(game)
        self.assertTrue(self.batch(game).completed)
        self.assertFalse(self.batch(game, 0).completed)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.assertEqual(len(self.named(game.snapshot()['resolution_frame'], 'FinishEndTurnBatch')), 1)
        self.check(game)
        self.choose(game)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 0)
        self.assertEqual([e.kind for e in game.events].count('player_effect_expired'), 1)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertEqual((game.state.turn, game.state.active_player), (2, 2))
        self.check(game)

    def test_used_event_choice_pauses_before_finite_body_and_accepts_removed_attachment(self):
        self.raw('used_wait', lambda c: [RequestChoice(1,
            (ChoiceOption('one', 'one', (Silence(c.event.source_id),)),), source_id=c.source_id)],
            event='limited_trigger_used')
        game = self.game(board=('double', 'used_wait', 'finite'))
        self.play(game)
        self.assertEqual([r.execution_order for r in self.rows(game)], [None, None])
        self.assertTrue(all(r.guard_passed for r in self.rows(game)))
        self.assertEqual(self.body(game, index=2).abilities[-1].uses_remaining, 1)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(self.body(game, index=2).silenced)
        self.assertTrue(self.batch(game).completed)
        self.assertEqual([e.kind for e in game.events].count('limited_trigger_used'), 1)
        self.check(game)

    def test_active_finite_guard_rejects_changed_source_for_whole_span(self):
        for operation in (Silence, ReturnToHand, lambda i: ChangeControl(i, 2), Destroy):
            with self.subTest(operation=operation):
                self.setUp()
                self.minion('changer', lambda c, op=operation: [op(c.state.players[1].board[2])]
                    if c.end_turn.repeat_index == 0 else [])
                game = self.game(board=('double', 'changer', 'finite'))
                self.play(game)
                finite = [r for r in self.rows(game) if r.capture.subject.card_id == 'finite']
                self.assertTrue(all(r.skipped and r.execution_order is None for r in finite))
                self.assertNotIn('limited_trigger_used', [e.kind for e in game.events])
                self.assertTrue(self.batch(game).completed)
                self.check(game)

    def test_active_power_removed_before_guard_skips_whole_repeat_span(self):
        self.minion('remove', lambda c: [RemoveHeroPower(1)] if c.end_turn.repeat_index == 0 else [])
        self.script('install', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('double', 'remove'), hand=('install', 'invoke'))
        self.play(game, 'install')
        self.play(game)
        rows = [r for r in self.rows(game) if r.capture.subject.card_id == 'end_power']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r.skipped and r.execution_order is None for r in rows))
        self.assertEqual(self.armor(game), 0)
        self.check(game)

    def test_active_power_replacement_after_guard_keeps_accepted_extras(self):
        self.r.register_behavior('replace_self', lambda c: [ReplaceHeroPower(1, 'power'), GainArmor(1, 1)])
        self.r.register_card(CardDefinition('replace_power', 'replace_power', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_ended', 'replace_self', EndTurnSpec()),)))
        game = self.game(board=('double',), power='replace_power')
        original = game.state.players[1].hero_power_id
        self.play(game)
        self.assertEqual(self.armor(game), 2)
        self.assertNotEqual(game.state.players[1].hero_power_id, original)
        self.assertEqual({r.capture.subject.source_id for r in self.rows(game)}, {original})
        self.check(game)

    def test_player_effect_body_removed_by_first_repeat_keeps_frozen_extra(self):
        self.r.register_behavior('remove_body', lambda c: [RemovePlayerEffect(c.player_id,
            c.player_effect.id), GainArmor(c.player_id, 1)])
        self.r.register_player_effect(PlayerEffectSpec('removable', 'plain',
            triggers=(TriggerSpec('turn_ended', 'remove_body', EndTurnSpec()),)))
        self.script('install', lambda c: [AddPlayerEffect(1, 'removable', c.state.players[1].board[1])])
        game = self.game(board=('double', 'plain'), hand=('install', 'invoke'))
        self.play(game, 'install')
        self.play(game)
        self.assertEqual(self.armor(game), 2)
        self.assertFalse(game.state.players[1].player_effects)
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.check(game)

    def test_extra_current_source_changes_but_frozen_body_owner_is_preserved(self):
        for operation in (Destroy, Silence, lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.minion('reader', lambda c, op=operation: ([op(c.source_id)]
                    if c.end_turn.repeat_index == 0 else []) + [GainArmor(c.player_id,
                        1 if c.source.card_id == 'reader' and c.source.zone == Zone.BOARD and
                            c.source.controller == 1 and not c.source.silenced else 10)])
                game = self.game(board=('double', 'reader'))
                self.play(game)
                self.assertEqual((self.armor(game, 1), self.armor(game, 2)), (11, 0))
                self.assertTrue(all(r.completed for r in self.rows(game)))
                self.check(game)

    def test_dormant_active_body_does_not_count_wake_turns(self):
        game = self.game(board=('dormant',), hand=('invoke', 'invoke'))
        original = self.body(game).dormancy
        self.play(game)
        self.play(game)
        self.assertEqual(self.body(game).dormancy, original)
        self.assertEqual(self.armor(game), 2)
        self.assertNotIn('minion_awakened', [e.kind for e in game.events])
        self.check(game, fresh=True)

    def test_minion_repeat_scope_excludes_nonminion_and_player_body_with_minion_source(self):
        self.r.register_card(CardDefinition('minion_double', 'minion_double', CardType.MINION,
            health=5, end_turn_repeats=(EndTurnRepeatSpec(scope='minion'),)))
        self.script('install', lambda c: [AddPlayerEffect(1, 'persistent', c.state.players[1].board[1])])
        game = self.game(board=('minion_double', 'end', 'location'), weapon='weapon',
            power='end_power', hand=('install', 'invoke'))
        self.play(game, 'install')
        self.play(game)
        counts = {s.card_id: p.repetitions for s, p in zip(self.batch(game).subjects, self.batch(game).plans)
            if s.player_effect is None}
        self.assertEqual(counts, {'end': 2, 'location': 1, 'weapon': 1, 'end_power': 1})
        self.assertEqual(len(self.batch(game).subjects), 5)
        self.assertEqual(self.armor(game), 6)
        self.assertEqual(next(p.repetitions for s, p in zip(self.batch(game).subjects, self.batch(game).plans)
            if s.player_effect is not None), 1)
        self.check(game)

    def test_terminal_effect_interrupts_remaining_positions_without_turn_transition(self):
        self.minion('lethal', lambda c: [Damage(c.state.players[2].hero_id, 30)])
        game = self.game(board=('double', 'lethal', 'end'))
        self.play(game)
        self.assertTrue(self.batch(game).interrupted)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, None, None, None])
        self.assertTrue(all(r.interrupted for r in self.rows(game)))
        self.assertEqual((game.state.turn, game.state.active_player), (1, 1))
        self.assertNotIn('turn_ended', [e.kind for e in game.events])
        self.check(game)

    def test_active_repeat_expansion_obeys_shared_resolution_budget_and_rolls_back(self):
        self.r.register_card(CardDefinition('huge', 'huge', CardType.MINION, health=8,
            end_turn_repeats=(EndTurnRepeatSpec(1000),)))
        game = self.game(board=('huge', 'end'), rules=Ruleset(max_resolution_steps=50))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_extra_body_exception_rolls_back_the_entire_requesting_action(self):
        def fail(c):
            if c.end_turn.repeat_index:
                raise ValueError('synthetic active extra failure')
            return [GainArmor(1, 1)]
        self.minion('failure', fail)
        game = self.game(board=('double', 'failure'))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_active_players_observe_no_requests_origins_proofs_or_host_queries(self):
        game = self.waiting()
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer),
                game.for_player(viewer).legal_actions()))
            for key in ('end_turn_batches', 'end_turn_history', 'activation', 'request',
                    'EndTurnSelector', 'issuer_zone_epoch', 'parent_id',
                    'guard_event', 'resolution_frame', 'acceptance', 'repeat_index',
                    'end_turn_guard_id', 'end_turn_ability_id'):
                self.assertNotIn('"' + key + '"', text)
        self.check(game, fresh=True)

    def test_rehashed_activation_action_cursor_epoch_or_order_corruption_is_rejected(self):
        game = self.waiting()
        for field, value in (('action', 0), ('event_cursor', 9999),
                ('issuer_zone_epoch', 999), ('issuer_entered_order', 999)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][0]['activation'][field] = value
                self.reject(snapshot)

    def test_rehashed_finished_batch_cannot_hide_a_pending_active_body(self):
        game = self.waiting()
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][0]['completed'] = True
        self.reject(snapshot)

    def test_rehashed_extra_first_guard_alias_or_repeat_index_is_rejected(self):
        game = self.waiting()
        for field, value in (('guard_id', 2), ('repeat_index', 0)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                row = snapshot['state']['end_turn_history'][1]
                if field == 'guard_id':
                    row[field] = value
                else:
                    row['capture'][field] = value
                self.reject(snapshot)

    def test_rehashed_active_finish_proof_cannot_be_removed_during_last_extra(self):
        game = self.waiting()
        self.choose(game)
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        queue[:] = [x for x in queue if not str(x.get('type', '')).endswith('.FinishEndTurnBatch')]
        self.reject(snapshot)

    def test_manual_power_may_request_active_self_body_with_one_payment_and_manual_root(self):
        self.r.register_behavior('manual_invoke', lambda c: [TriggerEndTurnEffects(c.player_id,
            request(mode='selected', carriers=('hero_power',), entities=(c.source_id,)), c.source_id)])
        self.r.register_card(CardDefinition('hybrid_power', 'hybrid_power', CardType.HERO_POWER,
            cost=2, on_use='manual_invoke', triggers=(TriggerSpec('turn_ended', 'waiting', EndTurnSpec()),)))
        game = self.game(board=(), hand=(), power='hybrid_power')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(len(game.state.hero_power_history), 1)
        self.assertEqual(len(game.state.hero_power_payload_history), 1)
        self.assertEqual(self.batch(game).activation.issuer_id, game.state.players[1].hero_power_id)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(len(game.state.hero_power_history), 1)
        self.assertEqual(len(game.state.hero_power_payload_history), 1)
        self.check(game)

    def test_deathrattle_may_issue_active_root_from_graveyard_source(self):
        self.r.register_behavior('dr_invoke', lambda c: [TriggerEndTurnEffects(1,
            request(carriers=('minion',)), c.source_id)])
        self.r.register_card(CardDefinition('rattle', 'rattle', CardType.MINION,
            health=1, deathrattle='dr_invoke'))
        self.script('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        game = self.game(board=('rattle', 'end'), hand=('kill',))
        original = self.body(game).id
        self.play(game, 'kill')
        self.assertEqual(self.batch(game).activation.issuer_id, original)
        self.assertEqual(game.state.entities[original].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(game), 1)
        self.assertEqual(len(game.state.death_history), 1)
        self.assertEqual(len(game.state.deathrattle_history), 1)
        self.check(game)

    def test_tail_ordinary_listener_activation_tracks_unfinished_parent_batch_without_capture(self):
        self.raw('tail_active', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[0],)), c.source_id)])
        game = self.game(board=('waiting', 'tail_active'), hand=())
        self.end(game)
        self.choose(game)
        outer, inner = game.state.end_turn_batches
        self.assertIsNone(inner.activation.parent_id)
        self.assertEqual(inner.activation.parent_batch_id, outer.id)
        self.assertTrue(self.rows(game)[0].completed)
        self.assertFalse(outer.completed or inner.completed)
        self.check(game)
        self.choose(game)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.assertEqual(game.state.turn, 2)
        self.check(game)

    def test_rehashed_nested_parent_capture_and_batch_links_cannot_be_forged(self):
        game = self.nested_fixture()
        for field, value in (('parent_id', 2), ('parent_batch_id', None), ('parent_batch_id', 2)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][1]['activation'][field] = value
                self.reject(snapshot)

    def test_rehashed_frame_activation_missing_or_null_cannot_take_defaults(self):
        game = self.waiting()
        for mode in ('missing', 'null', 'extra'):
            with self.subTest(mode=mode):
                snapshot = game.snapshot()
                proof = self.named(snapshot['resolution_frame'], 'FinishEndTurnBatch')[0]
                fields = proof['fields']['batch']['fields']
                if mode == 'missing':
                    del fields['activation']
                elif mode == 'null':
                    fields['activation'] = None
                else:
                    fields['activation']['fields']['unexpected'] = 1
                self.reject(snapshot)

    def test_rehashed_effect_request_missing_or_null_cannot_recover_natural_defaults(self):
        game = self.waiting()
        for mode in ('missing', 'null'):
            with self.subTest(mode=mode):
                snapshot = game.snapshot()
                origin = snapshot['state']['end_turn_batches'][0]['activation']
                if mode == 'missing':
                    del origin['request']
                else:
                    origin['request'] = None
                self.reject(snapshot)

    def test_rehashed_active_cause_must_be_a_real_event_with_object_data(self):
        self.raw('phase', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[1],),
                profile='end_turn.phase'), c.source_id, c.event)], event='turn_started')
        game = self.game(board=('phase', 'waiting'), hand=())
        self.end(game)
        self.choose(game)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(self.batch(game).activation.kind, 'phase')
        self.check(game)
        for field, value in (('sequence', 9999), ('data', []), ('action', True), ('unexpected', 1)):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                snapshot['state']['end_turn_batches'][-1]['event'][field] = value
                self.reject(snapshot)

    def test_joint_shrink_active_last_extra_and_history_keeps_original_complete_proof(self):
        game = self.waiting()
        self.choose(game)
        snapshot = game.snapshot()
        batch = snapshot['state']['end_turn_batches'][0]
        batch['plans'][0] = {'repetitions': 1, 'contributors': []}
        snapshot['state']['end_turn_history'][0]['capture']['plan'] = deepcopy(batch['plans'][0])
        del snapshot['state']['end_turn_history'][1:]
        for plan in self.named(snapshot, 'EndTurnRepeatPlan'):
            plan['fields'] = {'repetitions': 1, 'contributors': {'tuple': []}}
        queue = self.queue(snapshot)
        queue[:] = [w for w in queue if not str(w.get('type', '')).endswith('.FinishEndTurn')]
        self.reject(snapshot)

    def test_active_finite_check_cannot_be_replaced_with_forged_guard_receipt(self):
        game = self.waiting(board=('waiting', 'finite'))
        for consumed in (False, True):
            with self.subTest(consumed=consumed):
                snapshot = game.snapshot()
                queue = self.queue(snapshot)
                check = next(w for w in queue if str(w.get('type', '')).endswith('.CheckActiveEndTurn'))
                context = deepcopy(check['fields']['context'])
                if consumed:
                    trigger = context['fields']['trigger']['fields']
                    trigger['uses_remaining'] -= 1
                snapshot['state']['end_turn_history'][1]['guard_passed'] = True
                queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
                    'fields': {'context': context, 'acceptance': deepcopy(check['fields']['acceptance'])}}
                self.reject(snapshot)

    def test_schema_97_snapshot_is_explicitly_rejected_by_new_schema(self):
        game = self.waiting()
        snapshot = game.snapshot()
        self.assertEqual(snapshot['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        snapshot['schema_version'] = 97
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.r)

    def test_owner_start_clock_ticks_once_only_on_real_owner_start_after_active_work(self):
        self.r.register_player_effect(PlayerEffectSpec('start_clock', 'plain', kind='objective',
            duration=2, tick_event='turn_started',
            triggers=(TriggerSpec('turn_ended', 'armor', EndTurnSpec()),)))
        self.script('install_start', lambda c: [AddPlayerEffect(1, 'start_clock', c.source_id)])
        game = self.game(hand=('install_start', 'invoke'))
        self.play(game, 'install_start')
        self.play(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 2)
        self.end(game)
        self.assertEqual(game.state.players[1].player_effects[0].remaining_turns, 1)
        self.assertEqual([e.kind for e in game.events].count('player_effect_ticked'), 1)
        self.assertEqual(game.state.turn, 3)
        self.check(game)

    def test_late_active_finite_guard_after_first_choice_uses_real_later_action_receipt(self):
        self.raw('used_wait', lambda c: self.r.behavior('waiting')(c), event='limited_trigger_used')
        game = self.game(board=('waiting', 'used_wait', 'finite'))
        self.play(game)
        self.assertFalse(self.rows(game)[1].guard_passed)
        self.check(game)
        self.choose(game)
        receipt = self.rows(game)[1].guard_event
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual((receipt.action, self.batch(game).activation.action), (2, 1))
        self.assertEqual(self.rows(game)[1].execution_order, None)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 3)
        self.assertTrue(self.batch(game).completed)
        self.check(game)

    def test_finite_callback_keeps_real_other_phase_cause_and_one_consumption(self):
        self.r.register_behavior('cause_reader', lambda c: [GainArmor(1,
            10 if c.event is not None and c.event.kind == 'turn_started' else 1)])
        self.r.register_card(CardDefinition('cause_finite', 'cause_finite', CardType.MINION,
            health=8, limited_triggers=(LimitedTriggerSpec('turn_ended', 'cause_reader', uses=2,
                end_turn=EndTurnSpec()),)))
        self.raw('phase', lambda c: [TriggerEndTurnEffects(1,
            request(profile='end_turn.phase', carriers=('minion',)), c.source_id, c.event)],
            event='turn_started')
        game = self.game(board=('double', 'phase', 'cause_finite'), hand=())
        self.end(game)
        self.assertEqual(self.armor(game), 22)
        self.assertEqual([e.amount for e in game.events if e.kind == 'limited_trigger_used'], [1, 0])
        self.assertEqual(self.batch(game).event.kind, 'turn_started')
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.check(game)

    def test_ordinary_source_destroyed_before_active_slot_retains_first_old_and_extra_fresh_views(self):
        self.minion('killer', lambda c: [Destroy(c.state.players[1].board[2])]
            if c.end_turn.repeat_index == 0 else [])
        self.minion('reader', lambda c: [GainArmor(1, 1 if c.source.zone == Zone.BOARD else 10)])
        game = self.game(board=('double', 'killer', 'reader'))
        self.play(game)
        self.assertEqual([e.amount for e in game.events if e.kind == 'armor_gained'], [1, 10])
        self.assertTrue(all(r.completed for r in self.rows(game)))
        self.check(game)

    def test_dynamic_classified_trigger_is_selected_with_independent_attachment_identity(self):
        self.script('grant', lambda c: [GrantTrigger(c.state.players[1].board[0],
            'turn_ended', 'armor', c.source_id, end_turn=EndTurnSpec())])
        game = self.game(board=('plain',), hand=('grant', 'invoke'))
        self.play(game, 'grant')
        attachment = active_abilities(self.body(game), 'trigger')[0]
        self.play(game)
        self.assertEqual(self.batch(game).subjects[0].ability.id, attachment.id)
        self.assertEqual(self.batch(game).subjects[0].ability.source_id, attachment.source_id)
        self.assertEqual(self.armor(game), 1)
        self.check(game)

    def test_invalid_choice_does_not_change_active_history_or_pending_continuation(self):
        game = self.waiting()
        before = game.snapshot()
        with self.assertRaises(IllegalAction) as error:
            self.choose(game, 'missing')
        self.assertIn('choice', str(error.exception).lower())
        self.assertEqual(game.snapshot(), before)
        self.check(game, fresh=True)

    def test_nested_active_work_shares_the_callers_resolution_budget(self):
        self.minion('loop', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.source_id,)), c.source_id)])
        game = self.game(board=('loop',), rules=Ruleset(max_resolution_steps=50))
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.play(game)
        self.assertEqual(game.snapshot(), before)

    def test_used_event_nested_root_runs_before_original_guarded_body_with_batch_parent(self):
        game = self.guard_nested_fixture()
        outer, inner = game.state.end_turn_batches
        self.assertIsNone(inner.activation.parent_id)
        self.assertEqual(inner.activation.parent_batch_id, outer.id)
        self.assertEqual([r.execution_order for r in self.rows(game)], [None, 1])
        self.assertEqual(self.body(game, index=1).abilities[-1].uses_remaining, 0)
        self.assertEqual([e.amount for e in game.events if e.kind == 'limited_trigger_used'], [1, 0])
        self.check(game)
        self.choose(game)
        self.assertTrue(self.batch(game).completed)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual([r.execution_order for r in self.rows(game)], [2, 1])
        self.assertEqual([r.capture.id for r in activated_end_turns(game.state, 1)], [2, 1])
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.check(game)

    def test_nested_group_proof_cannot_move_after_its_outer_finish_control(self):
        game = self.guard_nested_fixture()
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        positions = [i for i, w in enumerate(queue)
            if str(w.get('type', '')).endswith('.FinishEndTurnBatch')]
        self.assertEqual(len(positions), 2)
        left, right = positions
        queue[left], queue[right] = queue[right], queue[left]
        self.reject(snapshot)

    def test_nested_root_in_last_extra_uses_capture_id_distinct_from_batch_id(self):
        self.minion('nested_extra', lambda c: [GainArmor(1, 1)] if c.end_turn.repeat_index == 0 else
            [TriggerEndTurnEffects(1, request(mode='selected', carriers=('minion',),
                entities=(c.state.players[1].board[2],)), c.source_id)])
        self.script('selected_outer', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', carriers=('minion',), entities=(c.state.players[1].board[1],)), c.source_id)])
        game = self.game(board=('double', 'nested_extra', 'waiting'), hand=('selected_outer',))
        self.play(game, 'selected_outer')
        self.assertEqual((self.batch(game).activation.parent_id,
            self.batch(game).activation.parent_batch_id), (2, 1))
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2, 3, None])
        self.check(game)
        self.choose(game)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2, 3, 4])
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 3)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.check(game)

    def test_nested_lethal_body_interrupts_both_roots_without_natural_boundary(self):
        self.minion('outer', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[1],)), c.source_id)])
        self.minion('lethal', lambda c: [Damage(c.state.players[2].hero_id, 30)])
        self.script('selected_outer', lambda c: [TriggerEndTurnEffects(1,
            request(mode='selected', entities=(c.state.players[1].board[0],)), c.source_id)])
        game = self.game(board=('outer', 'lethal'), hand=('selected_outer',))
        self.play(game, 'selected_outer')
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 2])
        self.assertTrue(all(b.interrupted for b in game.state.end_turn_batches))
        self.assertTrue(all(r.interrupted for r in self.rows(game)))
        self.assertFalse(game.state.pending_choice)
        self.assertNotIn('turn_ended', [e.kind for e in game.events])
        self.check(game)

    def test_first_active_power_guard_cannot_be_replaced_by_forged_passed_invoke(self):
        self.script('install', lambda c: [ReplaceHeroPower(1, 'end_power')])
        game = self.game(board=('waiting',), hand=('install', 'invoke'))
        self.play(game, 'install')
        self.play(game)
        snapshot = game.snapshot()
        queue = self.queue(snapshot)
        check = next(w for w in queue if str(w.get('type', '')).endswith('.CheckActiveEndTurn'))
        context = deepcopy(check['fields']['context'])
        snapshot['state']['end_turn_history'][1]['guard_passed'] = True
        queue[queue.index(check)] = {'type': 'hs_sim.engine.end_turns.InvokeEndTurn',
            'fields': {'context': context, 'acceptance': deepcopy(context)}}
        self.reject(snapshot)

    def test_actual_active_finite_guard_receipt_and_ids_never_enter_player_events(self):
        self.raw('used_wait', lambda c: self.r.behavior('waiting')(c), event='limited_trigger_used')
        game = self.game(board=('finite', 'used_wait'))
        self.play(game)
        receipt = self.rows(game)[0].guard_event
        self.assertIn('end_turn_guard_id', dict(receipt.data))
        self.assertIn('end_turn_ability_id', dict(receipt.data))
        for viewer in (1, 2):
            text = json.dumps((game.observe(viewer), game.player_events(viewer)))
            for key in ('guard_event', 'end_turn_guard_id', 'end_turn_ability_id'):
                self.assertNotIn('"' + key + '"', text)
        self.check(game)

    def test_frame_selector_missing_explicit_ids_cannot_take_constructor_defaults(self):
        game = self.waiting()
        for field in ('entity_ids', 'player_effect_ids'):
            with self.subTest(field=field):
                snapshot = game.snapshot()
                selector = self.named(snapshot['resolution_frame'], 'EndTurnSelector')[0]
                del selector['fields'][field]
                self.reject(snapshot)

    def test_unguarded_ordinary_or_player_body_cannot_be_forged_into_active_guard(self):
        for player_body in (False, True):
            with self.subTest(player_body=player_body):
                self.setUp()
                if player_body:
                    game = self.game(board=('waiting',), hand=('persistent', 'invoke'))
                    self.play(game, 'persistent')
                    self.play(game)
                else:
                    game = self.waiting(board=('waiting', 'end'))
                snapshot = game.snapshot()
                queue = self.queue(snapshot)
                invoke = next(w for w in queue if str(w.get('type', '')).endswith('.InvokeEndTurn'))
                queue[queue.index(invoke)] = {'type': 'hs_sim.engine.end_turns.CheckActiveEndTurn',
                    'fields': {'context': deepcopy(invoke['fields']['context']),
                        'acceptance': deepcopy(invoke['fields']['acceptance'])}}
                self.reject(snapshot)

    def test_nested_finite_zero_uses_cannot_lose_consumed_flag(self):
        game = self.nested_fixture(finite=True)
        snapshot = game.snapshot()
        entity = snapshot['state']['entities'][str(self.body(game).id)]
        self.assertEqual(entity['abilities'][-1]['uses_remaining'], 0)
        self.assertTrue(entity['abilities'][-1]['consumed'])
        entity['abilities'][-1]['consumed'] = False
        self.reject(snapshot)

    def test_three_layer_guard_nested_root_has_running_capture_and_distinct_nearest_batch_parent(self):
        game = self.three_layer_fixture()
        outer, middle, inner = game.state.end_turn_batches
        self.assertEqual((middle.activation.parent_id, middle.activation.parent_batch_id), (1, 1))
        self.assertEqual((inner.activation.parent_id, inner.activation.parent_batch_id), (1, 2))
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, None, 2])
        self.assertEqual(self.body(game, index=2).abilities[-1].uses_remaining, 0)
        self.check(game)
        self.choose(game)
        self.assertEqual([r.execution_order for r in self.rows(game)], [1, 3, 2])
        self.assertIsNotNone(game.state.pending_choice)
        self.assertTrue(self.batch(game).completed)
        self.check(game)
        self.choose(game)
        self.assertEqual(self.armor(game), 2)
        self.assertTrue(all(b.completed for b in game.state.end_turn_batches))
        self.check(game)

    def test_three_layer_parent_capture_cannot_borrow_an_unrelated_completed_root(self):
        game = self.three_layer_fixture(warmup=True)
        self.assertTrue(self.rows(game)[0].completed)
        self.assertEqual((self.batch(game).activation.parent_id,
            self.batch(game).activation.parent_batch_id), (2, 3))
        snapshot = game.snapshot()
        snapshot['state']['end_turn_batches'][-1]['activation']['parent_id'] = 1
        self.reject(snapshot)


if __name__ == '__main__':
    unittest.main()
