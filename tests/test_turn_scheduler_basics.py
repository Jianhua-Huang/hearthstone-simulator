"""Independent turn slots and the clocks directly affected by real turn starts."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, IllegalAction, Keyword, PlayCard, PlayerSetup, QueueTurns, Rarity,
    Registry, ResolutionError, ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice,
    SkipTurns, SnapshotError, TimedKeywordSpec, TriggerSpec, TurnSchedule, UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption, Damage, Freeze, GainArmor,
    GrantKeyword, RandomDamage, RequestChoice, Summon)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.actions import Concede
from hs_sim.targets import canonical_digest


FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/turn-scheduler-basics.json'
PIN = '0d8c7799e5e67072b6eb1a8bea2ef03597904369ba9236f8419874294dd9ca55'
TEMPORUS = 'LOOT_538'


def evidence():
    value = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Turn scheduling evidence pin changed')
    result = {}
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete source card changed')
        result[row['id']] = row['data']
    return result


def registry(extras=()):
    r = Registry('turn-scheduler-basics-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=80))
    r.register_card(CardDefinition('body', 'Body', CardType.MINION, attack=2, health=10))
    r.register_card(CardDefinition('cloak', 'Cloak', CardType.MINION, attack=1, health=4,
        keywords=(Keyword.STEALTH,), timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),)))
    r.register_card(CardDefinition('sleep', 'Sleep', CardType.MINION, attack=1, health=4, dormant_turns=2))
    r.register_behavior('power', lambda c: [GainArmor(c.player_id, 1)])
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='power'))
    r.register_behavior('extra', lambda c: [QueueTurns((c.player_id,), c.source_id)])
    r.register_behavior('skip_self', lambda c: [SkipTurns(c.player_id, source_id=c.source_id)])
    r.register_behavior('skip_enemy', lambda c: [SkipTurns(3-c.player_id, source_id=c.source_id)])
    r.register_behavior('freeze_own', lambda c: [Freeze(c.state.players[c.player_id].board[0], c.source_id)])
    for name in ('extra', 'skip_self', 'skip_enemy', 'freeze_own'):
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('temporus', lambda c: [QueueTurns((3-c.player_id,)*2 + (c.player_id,)*2, c.source_id)])
    raw = evidence()[TEMPORUS]
    tags = raw['tags']
    r.register_card(CardDefinition(TEMPORUS, raw['name'], CardType.MINION,
        cost=tags['COST'], attack=tags['ATK'], health=tags['HEALTH'], battlecry='temporus',
        metadata=CardMetadata(True, (CardClass.PRIEST,), Rarity.LEGENDARY, tribes=('dragon',))))
    for name, handler, event in extras:
        r.register_behavior(name, handler)
        r.register_card(CardDefinition(name, name, CardType.MINION if event else CardType.SPELL,
            attack=1 if event else 0, health=5 if event else 0,
            on_play=None if event else name, triggers=(TriggerSpec(event, name),) if event else ()))
    return r


class TurnSchedulerBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, name, handler):
        self.extras.append((name, handler, None))

    def watch(self, name, event, handler):
        self.extras.append((name, handler, event))

    def game(self, hand=(), enemy_hand=(), board=(), enemy=(), active=1, rules=None, mana=10, max_mana=10,
             overload_owed=0):
        self.r = registry(self.extras)
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('body',)*12, hero_power_card_id='power', mana=mana, max_mana=max_mana, overload_owed=overload_owed),
            PlayerSetup('hero', hand=enemy_hand, board=enemy, deck=('body',)*12,
                hero_power_card_id='power', mana=mana, max_mana=max_mana)), active_player=active, seed=19),
            self.r, rules)

    def play(self, g, name):
        player = g.state.active_player
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(player, entity))
        return entity

    def turn(self, g):
        g.apply(EndTurn(g.state.active_player))

    def choose(self, g):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (c.options[0].id,)))

    def pause(self, c):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'OK', ()),), source_id=c.source_id)

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry(self.extras)).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), saved)

    def resumed(self, g):
        self.assertIsNotNone(g.state.pending_choice)
        self.check(g)
        other = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.check(g)

    def reject(self, snapshot):
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(snapshot, registry(self.extras))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_natural_turns_and_default_schedule_remain_alternating(self):
        g = self.game()
        players = [g.state.active_player]
        for _ in range(4):
            self.turn(g)
            players.append(g.state.active_player)
        self.assertEqual(players, [1, 2, 1, 2, 1])
        self.assertEqual(g.state.turn_schedule, TurnSchedule())
        self.check(g)

    def test_extra_turn_keeps_actor_then_resumes_natural_successor(self):
        g = self.game(hand=('extra',))
        self.play(g, 'extra')
        self.assertEqual(g.state.turn_schedule, TurnSchedule((1,), 2))
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 1))
        intervals = g.state.owner_turn_history
        self.assertEqual([(v.player_id, v.owner_index, v.previous_id) for v in intervals], [(1, 1, None), (1, 2, 1)])
        self.assertTrue(intervals[0].closed)
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (3, 2))
        self.assertEqual(g.state.turn_schedule, TurnSchedule())
        self.check(g)

    def test_player_two_extra_has_its_own_natural_successor(self):
        g = self.game(enemy_hand=('extra',), active=2)
        self.play(g, 'extra')
        self.turn(g)
        self.assertEqual(g.state.active_player, 2)
        self.turn(g)
        self.assertEqual(g.state.active_player, 1)
        self.check(g)

    def test_opponent_queued_turn_does_not_replace_their_natural_turn(self):
        self.script('opponent_extra', lambda c: [QueueTurns((2,), c.source_id)])
        g = self.game(hand=('opponent_extra',))
        self.play(g, 'opponent_extra')
        sequence = []
        for _ in range(3):
            self.turn(g)
            sequence.append(g.state.active_player)
        self.assertEqual(sequence, [2, 2, 1])
        self.check(g)

    def test_real_temporus_gives_two_opponent_then_two_actor_turns(self):
        g = self.game(hand=(TEMPORUS,))
        entity = self.play(g, TEMPORUS)
        self.assertEqual((g.state.entities[entity].attack, g.state.entities[entity].max_health), (6, 6))
        self.assertEqual(g.state.players[1].mana, 3)
        self.assertEqual(g.state.turn_schedule, TurnSchedule((2, 2, 1, 1), 2))
        sequence = []
        for _ in range(6):
            self.turn(g)
            sequence.append(g.state.active_player)
        self.assertEqual(sequence, [2, 2, 1, 1, 2, 1])
        self.check(g)

    def test_repeated_temporus_sequences_append_in_acceptance_order(self):
        g = self.game(hand=(TEMPORUS,), enemy_hand=(TEMPORUS,))
        self.play(g, TEMPORUS)
        self.turn(g)
        self.play(g, TEMPORUS)
        self.assertEqual(g.state.turn_schedule.pending, (2, 1, 1, 1, 1, 2, 2))
        self.assertEqual(g.state.turn_schedule.resume_player_id, 2)
        sequence = []
        for _ in range(9):
            self.turn(g)
            sequence.append(g.state.active_player)
        self.assertEqual(sequence, [2, 1, 1, 1, 1, 2, 2, 2, 1])
        self.check(g)

    def test_skip_own_next_turn_returns_opponent_for_another_real_turn(self):
        g = self.game(hand=('skip_self',))
        self.play(g, 'skip_self')
        self.turn(g)
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (3, 2))
        self.assertEqual([(v.player_id, v.owner_index) for v in g.state.owner_turn_history], [(1, 1), (2, 1), (2, 2)])
        self.assertEqual([(e.kind, e.player_id) for e in g.events if e.kind == 'turn_skipped'], [('turn_skipped', 1)])
        self.turn(g)
        self.assertEqual(g.state.active_player, 1)
        self.check(g)

    def test_skip_opponent_next_turn_leaves_current_player_another_turn(self):
        g = self.game(hand=('skip_enemy',))
        self.play(g, 'skip_enemy')
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 1))
        self.assertFalse(any(v.player_id == 2 for v in g.state.owner_turn_history))
        self.assertEqual(g.state.turn_schedule, TurnSchedule())
        self.turn(g)
        self.assertEqual(g.state.active_player, 2)
        self.check(g)

    def test_multiple_skip_counts_consume_only_that_players_opportunities(self):
        self.script('skip_two', lambda c: [SkipTurns(1, 2, c.source_id)])
        g = self.game(hand=('skip_two',))
        self.play(g, 'skip_two')
        sequence = []
        for _ in range(4):
            self.turn(g)
            sequence.append(g.state.active_player)
        self.assertEqual(sequence, [2, 2, 2, 1])
        self.assertEqual(len([e for e in g.events if e.kind == 'turn_skipped']), 2)
        self.check(g)

    def test_both_players_skip_without_creating_phantom_turns(self):
        self.script('both_skip', lambda c: [SkipTurns(1), SkipTurns(2)])
        g = self.game(hand=('both_skip',))
        self.play(g, 'both_skip')
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 2))
        self.assertEqual([e.player_id for e in g.events if e.kind == 'turn_skipped'], [2, 1])
        self.assertEqual(len(g.state.owner_turn_history), 2)
        self.check(g)

    def test_actual_extra_start_refreshes_mana_draw_attack_and_power(self):
        g = self.game(hand=('extra',), board=('body',), mana=2, max_mana=3)
        entity = g.state.players[1].board[0]
        g.apply(Attack(1, entity, g.state.players[2].hero_id))
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id))
        self.play(g, 'extra')
        count = len(g.state.players[1].hand)
        self.turn(g)
        p = g.state.players[1]
        self.assertEqual((p.max_mana, p.mana, len(p.hand)), (4, 4, count+1))
        self.assertEqual(p.hero_power_uses_this_turn, 0)
        self.assertEqual(g.state.entities[entity].attacks_this_turn, 0)
        self.assertTrue(any(isinstance(a, Attack) and a.attacker_id == entity for a in g.legal_actions()))
        self.check(g)

    def test_skipped_player_gets_no_start_end_draw_resource_or_dormancy_tick(self):
        g = self.game(hand=('skip_enemy',), enemy=('sleep',), mana=2, max_mana=3)
        p = g.state.players[2]
        sleeping = p.board[0]
        before = (p.max_mana, p.mana, len(p.hand), g.state.entities[sleeping].dormancy)
        self.play(g, 'skip_enemy')
        self.turn(g)
        p = g.state.players[2]
        self.assertEqual((p.max_mana, p.mana, len(p.hand), g.state.entities[sleeping].dormancy), before)
        self.assertFalse(any(e.player_id == 2 and e.kind in ('turn_started', 'turn_ended', 'card_drawn') for e in g.events))
        self.check(g)

    def test_dormancy_counts_genuine_consecutive_owner_starts(self):
        g = self.game(hand=('extra', 'extra'), board=('sleep',))
        entity = g.state.players[1].board[0]
        self.play(g, 'extra')
        self.play(g, 'extra')
        self.turn(g)
        self.assertIsNotNone(g.state.entities[entity].dormancy)
        self.turn(g)
        self.assertIsNone(g.state.entities[entity].dormancy)
        self.assertEqual(g.state.active_player, 1)
        self.check(g)

    def test_timed_keyword_expires_on_consecutive_owner_start(self):
        g = self.game(hand=('extra',), board=('cloak',))
        entity = g.state.players[1].board[0]
        self.play(g, 'extra')
        self.turn(g)
        self.assertNotIn(Keyword.STEALTH, g.state.entities[entity].keywords)
        self.assertEqual((g.state.turn, g.state.owner_turn_history[-1].owner_index), (2, 2))
        self.check(g)

    def test_opponent_keyword_clock_waits_through_other_players_extra_turns(self):
        g = self.game(hand=('extra', 'extra'), enemy=('cloak',))
        entity = g.state.players[2].board[0]
        self.play(g, 'extra')
        self.play(g, 'extra')
        self.turn(g)
        self.turn(g)
        self.assertIn(Keyword.STEALTH, g.state.entities[entity].keywords)
        self.turn(g)
        self.assertNotIn(Keyword.STEALTH, g.state.entities[entity].keywords)
        self.check(g)

    def test_end_keyword_clock_uses_actual_owner_occurrences(self):
        self.script('two_ends', lambda c: [GrantKeyword(c.state.players[1].board[0], Keyword.TAUNT,
            duration=TimedKeywordSpec(Keyword.TAUNT, 'turn_ended', occurrences=2))])
        g = self.game(hand=('two_ends', 'extra'), board=('body',))
        entity = g.state.players[1].board[0]
        self.play(g, 'two_ends')
        self.play(g, 'extra')
        self.turn(g)
        self.assertIn(Keyword.TAUNT, g.state.entities[entity].keywords)
        self.turn(g)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[entity].keywords)
        self.check(g)

    def test_freeze_after_attack_thaws_after_next_actual_extra_turn(self):
        g = self.game(hand=('freeze_own', 'extra'), board=('body',))
        entity = g.state.players[1].board[0]
        g.apply(Attack(1, entity, g.state.players[2].hero_id))
        self.play(g, 'freeze_own')
        self.assertEqual(g.state.entities[entity].frozen_until_owner_turn, 2)
        self.play(g, 'extra')
        self.turn(g)
        self.assertTrue(g.state.entities[entity].frozen)
        self.turn(g)
        self.assertFalse(g.state.entities[entity].frozen)
        self.check(g)

    def test_skipping_does_not_thaw_or_expire_the_skipped_owner(self):
        self.script('freeze_enemy', lambda c: [Freeze(c.state.players[2].board[0])])
        g = self.game(hand=('freeze_enemy', 'skip_enemy'), enemy=('cloak',))
        entity = g.state.players[2].board[0]
        self.play(g, 'freeze_enemy')
        self.play(g, 'skip_enemy')
        self.turn(g)
        self.assertTrue(g.state.entities[entity].frozen)
        self.assertIn(Keyword.STEALTH, g.state.entities[entity].keywords)
        self.turn(g)
        self.assertTrue(g.state.entities[entity].frozen)
        self.assertNotIn(Keyword.STEALTH, g.state.entities[entity].keywords)
        self.turn(g)
        self.assertFalse(g.state.entities[entity].frozen)
        self.check(g)

    def test_schedule_event_choice_preserves_accepted_slots_and_fresh_restore(self):
        self.watch('pause', 'turns_scheduled', lambda c: [self.pause(c)])
        g = self.game(hand=('extra',), board=('pause',))
        self.play(g, 'extra')
        self.assertEqual(g.state.turn_schedule, TurnSchedule((1,), 2))
        self.resumed(g)
        self.turn(g)
        self.assertEqual(g.state.active_player, 1)
        self.check(g)

    def test_end_choice_does_not_consume_next_slot_early(self):
        self.watch('pause', 'turn_ended', lambda c: [self.pause(c)])
        g = self.game(hand=('extra',), board=('pause',))
        self.play(g, 'extra')
        self.turn(g)
        self.assertEqual(g.state.turn, 1)
        self.assertEqual(g.state.turn_schedule.pending, (1,))
        self.resumed(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 1))

    def test_skip_choice_keeps_ending_interval_until_actual_start(self):
        self.watch('pause', 'turn_skipped', lambda c: [self.pause(c)])
        g = self.game(hand=('skip_enemy',), board=('pause',))
        self.play(g, 'skip_enemy')
        self.turn(g)
        self.assertEqual(g.state.turn, 1)
        self.assertFalse(g.state.owner_turn_history[-1].closed)
        self.assertEqual(g.state.turn_schedule, TurnSchedule((), 1))
        self.resumed(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 1))

    def test_effects_queued_after_a_choice_roundtrip_before_acceptance(self):
        self.script('pending', lambda c: [self.pause(c), QueueTurns((c.player_id,), c.source_id)])
        g = self.game(hand=('pending',))
        self.play(g, 'pending')
        self.assertEqual(g.state.turn_schedule, TurnSchedule())
        self.resumed(g)
        self.assertEqual(g.state.turn_schedule, TurnSchedule((1,), 2))

    def test_consecutive_start_expiry_choice_precedes_real_start_and_draw(self):
        self.watch('pause', 'attachments_expired', lambda c: [self.pause(c)])
        g = self.game(hand=('extra',), board=('cloak', 'pause'))
        self.play(g, 'extra')
        count = len(g.state.players[1].hand)
        self.turn(g)
        self.assertEqual((g.state.turn, g.state.active_player), (2, 1))
        self.assertFalse(any(e.kind == 'turn_started' for e in g.events))
        self.assertEqual(len(g.state.players[1].hand), count)
        self.resumed(g)
        self.assertEqual(len(g.state.players[1].hand), count+1)

    def test_terminal_skip_reaction_starts_no_turn_or_draw(self):
        self.watch('kill', 'turn_skipped', lambda c: [Damage(c.state.players[2].hero_id, 100)])
        g = self.game(hand=('skip_enemy',), board=('kill',))
        self.play(g, 'skip_enemy')
        count = len(g.state.players[1].hand)
        self.turn(g)
        self.assertEqual((g.state.winner, g.state.turn), (1, 1))
        self.assertEqual(len(g.state.players[1].hand), count)
        self.assertFalse(any(e.kind == 'turn_started' for e in g.events))
        self.check(g)

    def test_configured_draw_closes_current_turn_without_consuming_extra(self):
        g = self.game(hand=('extra',), rules=Ruleset(draw_after_turn=1))
        self.play(g, 'extra')
        self.turn(g)
        self.assertEqual((g.state.status, g.state.turn), ('draw', 1))
        self.assertEqual(g.state.turn_schedule, TurnSchedule((1,), 2))
        self.assertTrue(g.state.owner_turn_history[-1].closed)
        self.check(g)

    def test_turn_budget_rolls_back_queue_consumption_and_natural_end(self):
        g = self.game(hand=('extra',), rules=Ruleset(max_turns=1))
        self.play(g, 'extra')
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.turn(g)
        self.assertEqual(g.snapshot(), before)
        self.check(g)

    def test_failed_body_rolls_back_schedule_events_rng_and_payment(self):
        self.script('broken', lambda c: [QueueTurns((1,), c.source_id),
            RandomDamage((c.state.players[1].hero_id, c.state.players[2].hero_id), 1), Summon(1, 'missing')])
        g = self.game(hand=('broken',))
        before = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'unsupported card'):
            self.play(g, 'broken')
        self.assertEqual(g.snapshot(), before)

    def test_queue_and_skip_engineering_admission_limits_are_transactional(self):
        self.script('too_many', lambda c: [QueueTurns((1,)*3)])
        self.script('too_many_skips', lambda c: [SkipTurns(1, 3)])
        for name in ('too_many', 'too_many_skips'):
            with self.subTest(name=name):
                g = self.game(hand=(name,), rules=Ruleset(max_turns=2))
                before = g.snapshot()
                with self.assertRaises(ResolutionLimitExceeded):
                    self.play(g, name)
                self.assertEqual(g.snapshot(), before)

    def test_source_and_effect_shapes_are_strict(self):
        for players in ([], (), (True,), (3,), ('1',)):
            with self.subTest(players=players), self.assertRaises(ValueError):
                QueueTurns(players)
        for player, count in ((True, 1), (3, 1), (1, True), (1, 0)):
            with self.subTest(player=player, count=count), self.assertRaises(ValueError):
                SkipTurns(player, count)
        self.script('bad_source', lambda c: [QueueTurns((1,), 99999)])
        g = self.game(hand=('bad_source',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'bad_source')
        self.assertEqual(g.snapshot(), before)

    def test_snapshot_rejects_malformed_schedule_and_old_schema(self):
        g = self.game(hand=('extra',))
        self.play(g, 'extra')
        for field, value in (('pending', [True]), ('pending', [3]), ('resume_player_id', None),
                             ('skip_counts', [-1, 0]), ('skip_counts', [0]), ('skip_counts', [0, True]),
                             ('pending', [1]*201)):
            with self.subTest(field=field, value=value):
                s = g.snapshot()
                s['state']['turn_schedule'][field] = value
                self.reject(s)
        for mutation in ('missing', 'unknown'):
            s = g.snapshot()
            if mutation == 'missing':
                del s['state']['turn_schedule']
            else:
                s['state']['turn_schedule']['unknown'] = 1
            self.reject(s)
        s = g.snapshot()
        self.assertEqual(s['schema_version'], 265)
        s['schema_version'] = 151
        with self.assertRaisesRegex(SnapshotError, 'schemas 1 through 264'):
            Game.from_snapshot(s, registry(self.extras))

    def test_snapshot_clock_origin_uses_actual_record_and_not_turn_parity(self):
        g = self.game(hand=('extra', 'cloak'))
        self.play(g, 'extra')
        self.turn(g)
        entity = self.play(g, 'cloak')
        expiry = g.state.entities[entity].abilities[0].keyword_expiry
        self.assertEqual((expiry.created_turn, expiry.created_owner_turn_id, expiry.owner_turn_index), (2, 2, 3))
        self.check(g)
        for name, value in (('created_owner_turn_id', 1), ('created_owner_turn_id', 999), ('created_owner_turn_id', None)):
            s = g.snapshot()
            s['state']['entities'][str(entity)]['abilities'][0]['keyword_expiry'][name] = value
            self.reject(s)

    def test_player_views_publish_scheduled_players_without_host_state(self):
        g = self.game(hand=('extra',), enemy_hand=('body',))
        self.play(g, 'extra')
        for player in (1, 2):
            view = g.observe(player)
            rows = [v for v in g.player_events(player) if v['kind'] == 'turns_scheduled']
            self.assertEqual(rows[-1]['turns'], [1])
            raw = json.dumps(view)
            for internal in ('turn_schedule', 'resume_player_id', 'skip_counts', 'created_owner_turn_id', 'owner_turn_history'):
                self.assertNotIn(internal, raw)
        self.turn(g)
        actions = g.legal_actions()
        self.assertEqual({a.player_id for a in actions if type(a) is not Concede}, {1})
        self.assertEqual({a.player_id for a in actions if type(a) is Concede}, {1, 2})
        with self.assertRaises(IllegalAction):
            g.apply(EndTurn(2))
        self.check(g)

    def test_extra_turn_uses_and_releases_overload_at_genuine_starts(self):
        g = self.game(hand=('extra', 'extra'), overload_owed=2)
        self.play(g, 'extra')
        self.play(g, 'extra')
        self.turn(g)
        p = g.state.players[1]
        self.assertEqual((p.mana, p.overload_locked, p.overload_owed), (8, 2, 0))
        self.turn(g)
        p = g.state.players[1]
        self.assertEqual((p.mana, p.overload_locked, p.overload_owed), (10, 0, 0))
        self.check(g)

    def test_many_skipped_slots_obey_step_budget_and_roll_back_the_whole_end(self):
        self.script('many_skips', lambda c: [SkipTurns(1, 30), SkipTurns(2, 30)])
        g = self.game(hand=('many_skips',), rules=Ruleset(max_resolution_steps=40))
        self.play(g, 'many_skips')
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.turn(g)
        self.assertEqual(g.snapshot(), before)

    def test_constructed_opening_cannot_hold_a_pre_first_schedule(self):
        from opening_fixtures import registry as opening_registry, setup
        r = opening_registry()
        g = Game.from_decks(setup(r), r)
        self.assertEqual(g.state.owner_turn_history, [])
        s = g.snapshot()
        s['state']['turn_schedule']['pending'] = [1]
        s['state']['turn_schedule']['resume_player_id'] = 2
        s['state_hash'] = canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'precede the first actual turn'):
            Game.from_snapshot(s, r)


if __name__ == '__main__':
    unittest.main()
