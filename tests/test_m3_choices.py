"""Committed choice boundaries, preserved continuations, and portable frames."""
from copy import deepcopy
from dataclasses import dataclass
import json
import unittest

from hs_sim.engine import (Concede, Attack, CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
                           PlayCard, PlayerSetup, Registry, ResolutionError, ResolutionLimitExceeded,
                           Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, Draw, Effect, Freeze, GainArmor,
                                   GrantKeyword, RequestChoice, Summon)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash


@dataclass(frozen=True)
class ExtraValue:
    amount: int


@dataclass(frozen=True)
class ExtraEffect(Effect):
    value: ExtraValue


@dataclass(frozen=True)
class Explode(Effect):
    pass


def rehash(snapshot):
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})


class ChoiceTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('choice-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.registry.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=3))

    def script(self, name, fn, kind=CardType.SPELL, **kwargs):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, kind, on_play=name, **kwargs))

    def choice(self, c, **kwargs):
        options = (ChoiceOption('armor', 'Armor', (GainArmor(c.player_id, 3),)),
                   ChoiceOption('draw', 'Draw', (Draw(c.player_id, 2),)))
        return RequestChoice(c.player_id, options, source_id=c.source_id, **kwargs)

    def game(self, hand=('choose',), board=(), enemy=(), rules=None, mechanics=None, power=None, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 5, max_mana=10, mana=10,
                        hero_power_card_id=power, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy, deck=('plain',) * 5)), seed=29),
            self.registry, ruleset=rules, mechanics=mechanics)

    def cast(self, g, name='choose'):
        entity = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, entity))

    def select(self, g, *ids):
        choice = g.state.pending_choice
        return g.apply(SelectChoice(choice.player_id, choice.id, ids))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snapshot, self.registry, mechanics=g.mechanics)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.registry, mechanics=g.mechanics).snapshot(), snapshot)
        return restored

    def test_cost_and_spell_zone_commit_once_before_choice_then_finish(self):
        self.script('choose', lambda c: [self.choice(c), GainArmor(1, 5)], cost=4)
        g = self.game()
        entity = g.state.players[1].hand[0]
        self.cast(g)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual(g.state.entities[entity].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(g), 0)
        self.assertNotIn('card_played', [e.kind for e in g.events])
        restored = self.portable(g)
        self.select(g, 'armor')
        self.select(restored, 'armor')
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(self.armor(g), 8)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assertEqual(g.state.entities[entity].zone, Zone.GRAVEYARD)
        self.assertEqual([e.kind for e in g.events].count('card_played'), 1)
        self.assertIsNone(g.state.pending_choice)
        self.portable(g)

    def test_normal_actions_blocked_and_invalid_selection_leaves_boundary_unchanged(self):
        self.script('choose', lambda c: [self.choice(c)])
        g = self.game(hand=('choose', 'plain'), board=('plain',))
        self.cast(g)
        before = g.snapshot()
        p = g.state.players[1]
        invalid = (EndTurn(1), PlayCard(1, p.hand[0]), Attack(1, p.board[0], g.state.players[2].hero_id),
                   SelectChoice(2, 1, ('armor',)), SelectChoice(1, 2, ('armor',)),
                   SelectChoice(1, 1, ('missing',)), SelectChoice(1, 1, ()),
                   SelectChoice(1, 1, ('draw', 'armor')))
        for action in invalid:
            with self.subTest(action=action), self.assertRaises(IllegalAction):
                g.apply(action)
            self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.legal_actions(), (Concede(1), Concede(2), SelectChoice(1, 1, ('armor',)), SelectChoice(1, 1, ('draw',))))

    def test_selection_without_pending_and_stale_selection_rejected(self):
        self.script('choose', lambda c: [self.choice(c)])
        g = self.game()
        with self.assertRaises(IllegalAction):
            g.apply(SelectChoice(1, 1, ('armor',)))
        self.cast(g)
        self.select(g, 'armor')
        with self.assertRaises(IllegalAction):
            g.apply(SelectChoice(1, 1, ('armor',)))

    def test_opponent_can_choose_during_active_players_action(self):
        self.script('choose', lambda c: [RequestChoice(2, (ChoiceOption('ok', 'OK', (GainArmor(2, 4),)),))])
        g = self.game()
        self.cast(g)
        self.assertEqual(g.state.active_player, 1)
        self.assertEqual(g.legal_actions(), (Concede(1), Concede(2), SelectChoice(2, 1, ('ok',))))
        self.select(self.portable(g), 'ok')
        self.select(g, 'ok')
        self.assertEqual(self.armor(g, 2), 4)
        self.assertEqual(g.state.active_player, 1)

    def test_clones_make_independent_choices(self):
        self.script('choose', lambda c: [self.choice(c)])
        g = self.game()
        self.cast(g)
        branch = g.clone()
        self.select(g, 'armor')
        self.select(branch, 'draw')
        self.assertEqual(self.armor(g), 3)
        self.assertEqual(self.armor(branch), 0)
        self.assertEqual(len(branch.state.players[1].hand), 2)
        self.portable(branch)

    def test_sequential_and_nested_choices_preserve_all_work(self):
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('nested', 'Nested',
            (self.choice(c), GainArmor(1, 5))),)), self.choice(c), GainArmor(1, 7)])
        g = self.game()
        self.cast(g)
        self.select(g, 'nested')
        self.assertEqual(g.state.pending_choice.id, 2)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(g.state.pending_choice.id, 3)
        self.assertEqual(self.armor(g), 8)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(self.armor(g), 18)
        self.assertEqual(g.state.next_choice_id, 4)
        self.portable(g)

    def test_multiselect_is_canonical_and_callback_sees_aggregate_before_branches(self):
        self.registry.register_behavior('selected', lambda c: [GainArmor(1, len(c.choice.selected) * 10)])
        self.script('choose', lambda c: [self.choice(c, min_count=0, max_count=2, on_select='selected')])
        g = self.game()
        self.cast(g)
        self.assertEqual(len(g.legal_actions()), 6)
        result = self.select(g, 'draw', 'armor')
        selected = next(e for e in result.events if e.kind == 'choice_selected')
        self.assertEqual(dict(selected.data)['option_ids'], ('armor', 'draw'))
        self.assertEqual(self.armor(g), 23)
        armor = [e.amount for e in result.events if e.kind == 'armor_gained']
        self.assertEqual(armor, [20, 3])
        self.portable(g)

    def test_optional_empty_submission_executes_callback_and_continuation(self):
        self.registry.register_behavior('selected', lambda c: [GainArmor(1, 2 if not c.choice.selected else 9)])
        self.script('choose', lambda c: [self.choice(c, min_count=0, on_select='selected'), GainArmor(1, 5)])
        g = self.game()
        self.cast(g)
        self.select(g)
        self.assertEqual(self.armor(g), 7)

    def test_empty_only_request_resolves_without_waiting(self):
        self.registry.register_behavior('selected', lambda c: [GainArmor(1, 4)])
        self.script('choose', lambda c: [RequestChoice(1, (), min_count=0, max_count=0, on_select='selected'), GainArmor(1, 2)])
        g = self.game()
        self.cast(g)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.next_choice_id, 2)
        self.assertEqual(self.armor(g), 6)
        self.portable(g)

    def test_sampling_is_committed_and_replay_does_not_reroll(self):
        self.script('choose', lambda c: [RequestChoice(1, tuple(
            ChoiceOption(str(i), str(i), (GainArmor(1, i),)) for i in range(10)), sample_size=3)])
        g = self.game()
        before = g.snapshot()['rng_state']
        self.cast(g)
        rng = g.snapshot()['rng_state']
        self.assertNotEqual(before, rng)
        offered = g.state.pending_choice.options
        restored = self.portable(g)
        self.assertEqual(len(offered), 3)
        self.select(g, offered[0].id)
        self.select(restored, offered[0].id)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_unsupported_candidate_is_not_filtered_out_by_sampling(self):
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('a', 'A'),
            ChoiceOption('b', 'B', card_id='missing')), sample_size=1)])
        g = self.game()
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_unregistered_work_after_pause_fails_before_boundary_commit(self):
        self.script('choose', lambda c: [self.choice(c), Explode()])
        g = self.game()
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unregistered'):
            self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_failure_after_selection_rolls_back_to_pending_boundary(self):
        def broken(r, e):
            r.game._rng.random()
            raise ValueError('deliberate failure')
        mechanics = default_mechanics('choice-failure-v1').register(Explode, broken)
        self.script('choose', lambda c: [RequestChoice(1, (
            ChoiceOption('bad', 'Bad', (GainArmor(1, 50), Explode())), ChoiceOption('good', 'Good')))], cost=4)
        g = self.game(mechanics=mechanics)
        self.cast(g)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate failure'):
            self.select(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.players[1].mana, 6)
        self.select(g, 'good')
        self.assertEqual(self.armor(g), 0)
        self.portable(g)

    def test_custom_frozen_payload_requires_registration_and_survives_restore(self):
        mechanics = default_mechanics('choice-extension-v1').register(ExtraEffect,
            lambda r, e: [GainArmor(1, e.value.amount)])
        self.script('choose', lambda c: [self.choice(c), ExtraEffect(ExtraValue(8))])
        g = self.game(mechanics=mechanics)
        with self.assertRaisesRegex(ResolutionError, 'Unregistered frame payload'):
            self.cast(g)
        supported = default_mechanics('choice-extension-v2').register_payload_type(ExtraValue).register(
            ExtraEffect, lambda r, e: [GainArmor(1, e.value.amount)])
        g = self.game(mechanics=supported)
        self.cast(g)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(self.armor(g), 11)
        self.portable(g)

    def test_choice_limit_and_enumeration_limit_do_not_truncate(self):
        self.script('choose', lambda c: [self.choice(c, min_count=0, max_count=2)])
        g = self.game(rules=Ruleset(max_choice_options=1))
        with self.assertRaises(ResolutionLimitExceeded):
            self.cast(g)
        g = self.game(rules=Ruleset(max_choice_combinations=2))
        self.cast(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            g.legal_actions()
        self.assertEqual(g.snapshot(), before)
        self.select(g, 'armor')
        self.assertEqual(self.armor(g), 3)

    def test_budget_is_cumulative_across_endless_choices(self):
        self.registry.register_behavior('again', lambda c: [self.choice(c, on_select='again')])
        self.script('choose', lambda c: [self.choice(c, on_select='again')])
        g = self.game(rules=Ruleset(max_resolution_steps=20))
        self.cast(g)
        while True:
            before = g.snapshot()
            try:
                self.select(g, 'armor')
            except ResolutionLimitExceeded:
                self.assertEqual(g.snapshot(), before)
                break
            self.assertLess(g.state.action_number, 10)
        self.portable(g)

    def test_request_triggers_then_selection_triggers_then_branch_then_continuation(self):
        self.registry.register_behavior('requested', lambda c: [GainArmor(1, 1)])
        self.registry.register_behavior('selected', lambda c: [GainArmor(1, 2)])
        self.registry.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=3,
            triggers=(TriggerSpec('choice_requested', 'requested'), TriggerSpec('choice_selected', 'selected'))))
        self.script('choose', lambda c: [self.choice(c), GainArmor(1, 4)])
        g = self.game(board=('listener',))
        self.cast(g)
        self.assertEqual(self.armor(g), 0)
        g = self.portable(g)
        result = self.select(g, 'armor')
        self.assertEqual([e.amount for e in result.events if e.kind == 'armor_gained'], [1, 2, 3, 4])
        self.portable(g)

    def test_captured_context_is_not_recreated_after_selection(self):
        self.registry.register_behavior('request', lambda c: [self.choice(c)])
        self.registry.register_behavior('remember', lambda c: [GainArmor(1,
            10 + c.state.action_number + c.state.entities[c.event.target_id].damage)])
        for name, behavior in (('first', 'request'), ('second', 'remember')):
            self.registry.register_card(CardDefinition(name, name, CardType.MINION, health=5,
                triggers=(TriggerSpec('damage_dealt', behavior),)))
        self.script('choose', lambda c: [Damage(c.state.players[2].hero_id, 2, c.source_id)])
        g = self.game(board=('first', 'second'))
        self.cast(g)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(self.armor(g), 16)  # 3 + captured (10 + action 1 + damage 2)

    def test_deathrattle_choice_preserves_other_deaths_and_reborn(self):
        self.registry.register_behavior('death_choice', lambda c: [self.choice(c)])
        self.registry.register_behavior('other_death', lambda c: [GainArmor(1, c.death.max_health)])
        self.registry.register_card(CardDefinition('dying', 'dying', CardType.MINION, health=4,
            deathrattle='death_choice', keywords=(Keyword.REBORN,)))
        self.registry.register_card(CardDefinition('other', 'other', CardType.MINION, health=6, deathrattle='other_death'))
        self.script('choose', lambda c: [DamageBatch(tuple(Damage(i, 10) for i in c.state.players[1].board))])
        g = self.game(board=('dying', 'other'))
        self.cast(g)
        self.assertEqual(len(g.state.death_history), 2)
        self.assertFalse(g.state.players[1].board)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(self.armor(g), 9)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].health, 1)

    def test_end_turn_choice_keeps_ending_context_and_starts_turn_once(self):
        self.registry.register_behavior('end_choice', lambda c: [RequestChoice(1, (
            ChoiceOption('freeze', 'Freeze', (Freeze(c.source_id),)),))])
        self.registry.register_card(CardDefinition('end', 'end', CardType.MINION, attack=2, health=3,
            triggers=(TriggerSpec('turn_ended', 'end_choice'),)))
        g = self.game(hand=(), board=('end',))
        g.apply(EndTurn(1))
        self.assertEqual(g.state.turn, 1)
        self.assertTrue(g.snapshot()['resolution_frame']['fields']['ending_turn'])
        g = self.portable(g)
        self.select(g, 'freeze')
        self.assertEqual(g.state.turn, 2)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].frozen_until_owner_turn, 2)
        self.assertEqual([e.kind for e in g.events].count('turn_started'), 1)

    def test_hero_power_choice_preserves_finish_and_usage(self):
        self.registry.register_behavior('power_choice', lambda c: [self.choice(c)])
        self.registry.register_card(CardDefinition('power', 'power', CardType.HERO_POWER, cost=2, on_use='power_choice'))
        g = self.game(hand=(), power='power')
        source = g.state.players[1].hero_power_id
        g.apply(UseHeroPower(1, source))
        self.assertEqual(g.state.players[1].mana, 8)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(g.state.entities[source].uses_this_turn, 1)
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual(self.armor(g), 3)

    def test_attack_trigger_choice_preserves_combat_and_weapon_durability(self):
        self.registry.register_behavior('attack_choice', lambda c: [self.choice(c)])
        self.registry.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=3, durability=2))
        self.registry.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=3,
            triggers=(TriggerSpec('attack_declared', 'attack_choice'),)))
        g = self.game(hand=(), board=('listener',), weapon='weapon')
        g.apply(Attack(1, g.state.players[1].hero_id, g.state.players[2].hero_id))
        self.assertIsNotNone(g.state.pending_choice)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)
        self.assertEqual(g.state.entities[g.state.players[1].weapon_id].durability, 1)
        self.portable(g)

    def test_lethal_selected_branch_discards_continuation_and_choice(self):
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('kill', 'Kill',
            (Damage(c.state.players[2].hero_id, 40),)),)), GainArmor(1, 50)])
        g = self.game()
        self.cast(g)
        self.select(g, 'kill')
        self.assertEqual(g.state.winner, 1)
        self.assertIsNone(g.state.pending_choice)
        self.assertIsNone(g.snapshot()['resolution_frame'])
        self.assertEqual(self.armor(g), 0)
        self.portable(g)

    def test_snapshot_rejects_frame_tampering_even_with_recomputed_hash(self):
        self.script('choose', lambda c: [self.choice(c), GainArmor(1, 4)])
        g = self.game()
        self.cast(g)
        changes = (
            lambda s: s.update(resolution_frame=None),
            lambda s: s['state'].update(pending_choice=None),
            lambda s: s['resolution_frame']['fields'].update(choice_id=9),
            lambda s: s['resolution_frame']['fields'].update(steps=True),
            lambda s: s['resolution_frame']['fields'].update(root_action_number=99),
            lambda s: s['resolution_frame']['fields'].update(ending_turn=1),
            lambda s: s['resolution_frame'].update(type='os.system'),
            lambda s: s['resolution_frame']['fields']['continuation']['tuple'][0]['fields'].update(amount=True),
            lambda s: s['resolution_frame']['fields']['options']['tuple'][0]['fields'].update(id='mismatch'),
            lambda s: s['resolution_frame']['fields'].update(on_select='missing'),
            lambda s: s['state']['pending_choice']['options'][0].update(card_id='missing'),
            lambda s: s['state'].update(next_choice_id=1),
            lambda s: s.update(schema_version=8),
        )
        for change in changes:
            s = deepcopy(g.snapshot())
            change(s)
            rehash(s)
            with self.subTest(change=change), self.assertRaises(SnapshotError):
                Game.from_snapshot(s, self.registry)

    def test_choice_wire_format_strict(self):
        action = SelectChoice(2, 3, ('x', 'y'))
        self.assertEqual(action_from_dict(json.loads(json.dumps(action_to_dict(action)))), action)
        for options in (['x', 'x'], [False], 'x', ('x',)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                action_from_dict({'type': 'select_choice', 'player_id': 1, 'choice_id': 1, 'option_ids': options})
        for kwargs in ({'min_count': -1}, {'min_count': 2}, {'sample_size': 0}, {'max_count': True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RequestChoice(1, (ChoiceOption('x', 'X'),), **kwargs)

    def test_captured_request_trigger_can_itself_suspend_before_selected_branch(self):
        self.registry.register_behavior('observe', lambda c: [] if c.state.pending_choice.id > 1 else [
            RequestChoice(2, (ChoiceOption('accept', 'Accept', (GainArmor(2, 5),)),))])
        self.registry.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=3,
            triggers=(TriggerSpec('choice_requested', 'observe'),)))
        self.script('choose', lambda c: [self.choice(c), GainArmor(1, 4)])
        g = self.game(board=('listener',))
        self.cast(g)
        self.select(g, 'armor')
        self.assertEqual(g.state.pending_choice.player_id, 2)
        self.assertEqual(self.armor(g), 0)
        g = self.portable(g)
        self.select(g, 'accept')
        self.assertEqual((self.armor(g), self.armor(g, 2)), (7, 5))
        self.assertEqual(sum(e.kind == 'card_played' for e in g.events), 1)

    def test_source_can_die_while_captured_request_reactions_resume(self):
        self.registry.register_behavior('kill', lambda c: [Damage(c.event.source_id, 10)])
        self.registry.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=3,
            triggers=(TriggerSpec('choice_requested', 'kill'),)))
        self.script('choose', lambda c: [self.choice(c)], kind=CardType.MINION, health=2)
        g = self.game(board=('listener',))
        source = g.state.players[1].hand[0]
        self.cast(g)
        g = self.portable(g)
        self.select(g, 'armor')
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.armor(g), 3)
        self.portable(g)

    def test_enum_branch_payload_survives_json_roundtrip(self):
        self.script('choose', lambda c: [RequestChoice(1, (ChoiceOption('keyword', 'Keyword',
            (GrantKeyword(c.state.players[1].board[0], Keyword.TAUNT, c.source_id),)),))])
        g = self.game(board=('plain',))
        self.cast(g)
        g = self.portable(g)
        self.select(g, 'keyword')
        self.assertIn(Keyword.TAUNT, g.state.entities[g.state.players[1].board[0]].keywords)

    def test_mutable_effect_cannot_be_saved_as_work(self):
        @dataclass
        class Mutable(Effect):
            amount: int
        mechanics = default_mechanics('mutable-v1').register(Mutable, lambda r, e: [])
        self.script('choose', lambda c: [self.choice(c), Mutable(1)])
        g = self.game(mechanics=mechanics)
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'frozen dataclasses'):
            self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_running_handler_cannot_clone_or_snapshot(self):
        errors = []
        def handler(r, e):
            for operation in (r.game.clone, r.game.snapshot):
                with self.assertRaises(ResolutionError):
                    operation()
                errors.append(True)
        mechanics = default_mechanics('reentry-v1').register(Explode, handler)
        self.script('choose', lambda c: [self.choice(c), Explode()])
        g = self.game(mechanics=mechanics)
        self.cast(g)
        self.select(g, 'armor')
        self.assertEqual(errors, [True, True])

    def test_registered_payload_cannot_smuggle_an_effect_without_handler(self):
        with self.assertRaisesRegex(ValueError, 'handler'):
            default_mechanics('bad-extension').register_payload_type(Explode)

    def test_unsupported_nested_branch_fails_before_random_candidates_commit(self):
        self.script('choose', lambda c: [RequestChoice(1, (
            ChoiceOption('valid', 'Valid'), ChoiceOption('invalid', 'Invalid', (Summon(1, 'missing'),))),
            sample_size=1)])
        g = self.game()
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_frame_changes_are_included_in_digest(self):
        self.script('choose', lambda c: [self.choice(c), GainArmor(1, 4)])
        g = self.game()
        self.cast(g)
        s = g.snapshot()
        s['resolution_frame']['fields']['continuation']['tuple'][0]['fields']['amount'] = 5
        with self.assertRaisesRegex(SnapshotError, 'State digest'):
            Game.from_snapshot(s, self.registry)

    def test_all_old_snapshot_schemas_rejected(self):
        g = self.game(hand=())
        for version in range(1, 10):
            s = g.snapshot()
            s['schema_version'] = version
            with self.subTest(version=version), self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot'):
                Game.from_snapshot(s, self.registry)


if __name__ == '__main__':
    unittest.main()
