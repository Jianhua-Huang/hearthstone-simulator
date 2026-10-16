"""Real start/end bound death using existing finite attachment primitives."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, EndTurnSpec, Game,
    GrantLimitedTrigger, IllegalAction, LimitedTriggerSpec, PlayCard, PlayerSetup,
    QueueTurns, ResolutionError, Scenario, SelectChoice, SkipTurns, SnapshotError,
    SpellSchool, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChangeControl, ChoiceOption,
    Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

CORRUPTION = 'CS2_063'
POWER = 'EX1_316'
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/bound-minion-death-basics.json'
PIN = '5196f99a86328c4fbc5978b3f118f579b8da464c741a43bf044696e5c03c8aed'


def evidence():
    raw = json.loads(SUPPORT.read_bytes())
    if canonical_digest(raw) != PIN or [r['id'] for r in raw['records']] != [CORRUPTION, 'CS2_063e', POWER, 'EX1_316e']:
        raise ValueError('Full bound death raw changed')
    for r in raw['records']:
        if r['id'] != r['data']['id'] or canonical_digest(r['data']) != r['data_sha256']:
            raise ValueError('Full source or enchantment row changed')
    return {r['id']: r['data'] for r in raw['records']}


def kill_bound(c):
    if c.trigger is None or c.trigger.kind != 'limited_trigger' or c.trigger.source_id is None:
        raise ValueError('Bound death needs its actual consumed grant source')
    return (Destroy(c.source_id, c.trigger.source_id),)


def corrupt(c):
    return (GrantLimitedTrigger(c.target_id, LimitedTriggerSpec('turn_started', 'bound.kill',
        condition_id='bound.actor.' + str(c.player_id)), c.source_id),)


def overpower(c):
    return (Buff(c.target_id, 4, 4, c.source_id, c.state.turn),
        GrantLimitedTrigger(c.target_id, LimitedTriggerSpec('turn_ended', 'bound.kill',
            end_turn=EndTurnSpec('either')), c.source_id, c.state.turn))


def pause(c):
    return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),), c.source_id),)


def registry(scripts=(), watchers=()):
    r = opening_registry(); rows = evidence()
    r.register_behavior('bound.kill', kill_bound)
    r.register_behavior('bound.corrupt', corrupt)
    r.register_behavior('bound.power', overpower)
    # Two fixed registered policies bind the original caster without new state.
    r.register_trigger_condition('bound.actor.1', lambda c: c.event.player_id == 1)
    r.register_trigger_condition('bound.actor.2', lambda c: c.event.player_id == 2)
    for cid, relation, behavior in ((CORRUPTION, 'enemy', 'bound.corrupt'), (POWER, 'friendly', 'bound.power')):
        row = rows[cid]
        r.register_card(CardDefinition(cid, row['name'], CardType.SPELL, cost=row['cost'],
            spell_school=SpellSchool.SHADOW, on_play=behavior, metadata=metadata_from_record(row),
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation=relation)))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    for name, event, callback in watchers:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.MINION, health=5,
            triggers=(TriggerSpec(event, name),), metadata=metadata()))
    return r


class BoundMinionDeathTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.watchers = []

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def watch(self, name, event, callback):
        self.watchers.append((name, event, callback))

    def game(self, hand=(CORRUPTION,), enemy_hand=(), board=('card.1',), enemy_board=('card.2',), active=1):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=('card.30',)*8, mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=('card.31',)*8, mana=10, max_mana=10)),
            seed=89, active_player=active), registry(self.scripts, self.watchers))

    def play(self, g, card=CORRUPTION, target=None):
        p = g.state.active_player
        source = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == card)
        if target is None and card in (CORRUPTION, POWER):
            owner = 3-p if card == CORRUPTION else p
            target = g.state.players[owner].board[0]
        g.apply(PlayCard(p, source, target)); return source

    def end(self, g):
        g.apply(EndTurn(g.state.active_player))

    def choose(self, g, option='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (option,)))

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snap, registry(self.scripts, self.watchers))
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, self.watchers)).snapshot(), snap)
        return restored

    def trigger(self, g, target):
        return next(a for a in g.state.entities[target].abilities if a.kind == 'limited_trigger')

    def death(self, g, target):
        return next(d for d in g.state.death_history if d.entity_id == target)

    def assert_source_death(self, g, target, source, card):
        d = self.death(g, target)
        self.assertEqual((d.cause.kind, d.cause.source_id, d.cause.source_card_id), ('destroy', source, card))
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)

    def nodes(self, value, name):
        found = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.' + name):
                found.append(value)
            for v in value.values():
                found.extend(self.nodes(v, name))
        elif isinstance(value, list):
            for v in value:
                found.extend(self.nodes(v, name))
        return found

    def reject(self, saved):
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), registry(self.scripts, self.watchers))

    def consumed_wait(self, card=CORRUPTION):
        self.watch('used.wait', 'limited_trigger_used', pause)
        g = self.game((card,), board=('used.wait', 'card.1'))
        target = g.state.players[2 if card == CORRUPTION else 1].board[-1]
        source = self.play(g, card, target); self.end(g)
        if card == CORRUPTION:
            self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        return g, target, source

    def test_full_raw_pin_and_only_two_complete_experimental_sources(self):
        rows = evidence(); all_rows = json.loads((SUPPORT.parents[1]/'extracted/cards.json').read_bytes())
        for cid, row in rows.items():
            self.assertEqual(row, next(r for r in all_rows if r['id'] == cid))
        r = registry()
        for cid in (CORRUPTION, POWER):
            self.assertEqual((r.card(cid).cost, r.card(cid).spell_school), (1, SpellSchool.SHADOW))
        self.assertNotIn('CS2_063e', r.cards); self.assertNotIn('EX1_316e', r.cards)
        self.assertIn("corrupting player's turn", rows['CS2_063e']['text_en'])

    def test_corruption_retains_original_source_and_waits_for_caster_start(self):
        g = self.game(); target = g.state.players[2].board[0]; source = self.play(g)
        a = self.trigger(g, target)
        self.assertEqual((a.source_id, a.uses_remaining, a.limited_trigger.condition_id), (source, 1, 'bound.actor.1'))
        self.assertEqual((g.state.players[1].mana, g.state.entities[source].zone), (9, Zone.GRAVEYARD))
        self.assertEqual(len(g.state.cast_history), 1)
        self.end(g); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertEqual(self.trigger(g, target).uses_remaining, 1)
        self.end(g); self.assert_source_death(g, target, source, CORRUPTION)
        self.assertEqual(len(g.state.death_history), 1)
        self.portable(g)

    def test_second_caster_uses_second_players_start(self):
        g = self.game((), enemy_hand=(CORRUPTION,), active=2); target = g.state.players[1].board[0]
        source = self.play(g)
        self.assertEqual(self.trigger(g, target).limited_trigger.condition_id, 'bound.actor.2')
        self.end(g); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.end(g); self.assert_source_death(g, target, source, CORRUPTION); self.portable(g)

    def test_native_target_relations_reject_without_payment_or_attachment(self):
        for card, wrong_owner in ((CORRUPTION, 1), (POWER, 2)):
            g = self.game((card,)); before = g.snapshot()
            with self.subTest(card=card), self.assertRaises(IllegalAction):
                self.play(g, card, g.state.players[wrong_owner].board[0])
            self.assertEqual(g.snapshot(), before)

    def test_power_buffs_immediately_and_dies_by_original_source_at_current_end(self):
        g = self.game((POWER,)); target = g.state.players[1].board[0]; source = self.play(g, POWER)
        body = g.state.entities[target]
        self.assertEqual((body.attack, body.max_health, body.health, g.state.players[1].mana), (8, 8, 8, 9))
        self.assertEqual(self.trigger(g, target).limited_trigger.end_turn, EndTurnSpec('either'))
        self.end(g); self.assert_source_death(g, target, source, POWER)
        self.assertEqual(g.state.turn, 2); self.portable(g)

    def test_power_on_second_players_turn_uses_that_actual_end(self):
        g = self.game((), enemy_hand=(POWER,), active=2); target = g.state.players[2].board[0]
        source = self.play(g, POWER); self.end(g); self.assert_source_death(g, target, source, POWER)
        self.portable(g)

    def test_other_identical_minion_is_not_the_bound_original(self):
        g = self.game(enemy_board=('card.2', 'card.2')); target, other = g.state.players[2].board
        self.play(g, target=target); self.end(g); self.end(g)
        self.assertEqual(g.state.players[2].board, [other]); self.assertEqual(self.death(g, target).card_id, 'card.2')
        self.portable(g)

    def test_silence_removes_corruption_and_power_with_shared_lifecycle(self):
        self.script('clear', lambda c: (Silence(c.state.players[2].board[0]),))
        self.script('clear.own', lambda c: (Silence(c.state.players[1].board[0]),))
        g = self.game((CORRUPTION, 'clear')); target = g.state.players[2].board[0]
        self.play(g); self.play(g, 'clear'); self.end(g); self.end(g)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD); self.assertFalse(g.state.death_history)
        h = self.game((POWER, 'clear.own')); target = h.state.players[1].board[0]
        self.play(h, POWER); self.play(h, 'clear.own'); self.end(h)
        self.assertEqual((h.state.entities[target].attack, h.state.entities[target].max_health), (4, 4))
        self.assertEqual(h.state.entities[target].zone, Zone.BOARD); self.assertFalse(h.state.death_history)
        self.portable(g); self.portable(h)

    def test_bounce_and_replay_cannot_restore_old_corruption(self):
        self.script('bounce', lambda c: (ReturnToHand(c.state.players[2].board[0]),))
        g = self.game((CORRUPTION, 'bounce')); target = g.state.players[2].board[0]
        self.play(g); old_id = self.trigger(g, target).id; self.play(g, 'bounce'); self.end(g)
        self.play(g, 'card.2'); self.end(g)
        self.assertIn(target, g.state.players[2].board)
        self.assertFalse(any(a.id == old_id for a in g.state.entities[target].abilities))
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_transform_removes_original_bound_death(self):
        self.script('replace', lambda c: (Transform(c.state.players[2].board[0], 'card.3'),))
        g = self.game((CORRUPTION, 'replace')); target = g.state.players[2].board[0]
        self.play(g); self.play(g, 'replace'); self.end(g); self.end(g)
        self.assertEqual((g.state.entities[target].card_id, g.state.entities[target].zone), ('card.3', Zone.BOARD))
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_control_change_before_boundary_preserves_original_caster_policy(self):
        self.script('take', lambda c: (ChangeControl(c.state.players[2].board[0], 1),))
        g = self.game((CORRUPTION, 'take')); target = g.state.players[2].board[0]; source = self.play(g)
        self.play(g, 'take'); self.end(g)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.end(g); self.assert_source_death(g, target, source, CORRUPTION)
        self.assertEqual(self.death(g, target).controller, 1); self.portable(g)

    def test_power_follows_current_end_after_control_change(self):
        self.script('give', lambda c: (ChangeControl(c.state.players[1].board[0], 2),))
        g = self.game((POWER, 'give')); target = g.state.players[1].board[0]; source = self.play(g, POWER)
        self.play(g, 'give'); self.end(g)
        self.assert_source_death(g, target, source, POWER); self.assertEqual(self.death(g, target).controller, 2)
        self.portable(g)

    def test_original_target_killed_early_does_not_destroy_later_board_card(self):
        self.script('kill.early', lambda c: (Destroy(c.state.players[2].board[0], c.source_id),))
        g = self.game((CORRUPTION, 'kill.early'), enemy_board=('card.2', 'card.3'))
        target, later = g.state.players[2].board; self.play(g); self.play(g, 'kill.early'); self.end(g); self.end(g)
        self.assertEqual(g.state.players[2].board, [later]); self.assertEqual(len(g.state.death_history), 1)
        self.assertNotEqual(self.death(g, target).cause.source_card_id, CORRUPTION); self.portable(g)

    def test_two_real_corruptions_on_one_target_create_only_one_actual_death(self):
        g = self.game((CORRUPTION, CORRUPTION)); target = g.state.players[2].board[0]
        first = self.play(g); second = self.play(g)
        self.assertEqual([a.source_id for a in g.state.entities[target].abilities if a.kind == 'limited_trigger'], [first, second])
        self.end(g); self.end(g); self.assert_source_death(g, target, first, CORRUPTION)
        self.assertEqual(len(g.state.death_history), 1); self.portable(g)

    def test_actual_extra_caster_start_can_be_the_next_start(self):
        self.script('extra', lambda c: (QueueTurns((1,), c.source_id),))
        g = self.game((CORRUPTION, 'extra')); target = g.state.players[2].board[0]; source = self.play(g)
        self.play(g, 'extra'); self.end(g)
        self.assertEqual(g.state.active_player, 1); self.assert_source_death(g, target, source, CORRUPTION)
        self.portable(g)

    def test_skipped_caster_slot_is_not_a_real_start(self):
        self.script('skip', lambda c: (SkipTurns(1, 1, c.source_id),))
        g = self.game((CORRUPTION,), enemy_hand=('skip',)); target = g.state.players[2].board[0]; source = self.play(g)
        self.end(g); self.play(g, 'skip'); self.end(g)
        self.assertEqual(g.state.active_player, 2); self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.end(g); self.assert_source_death(g, target, source, CORRUPTION); self.portable(g)

    def test_wait_after_grant_preserves_full_native_acceptance_and_source(self):
        self.watch('grant.wait', 'ability_granted', pause)
        g = self.game(board=('grant.wait', 'card.1')); target = g.state.players[2].board[0]
        source = self.play(g); self.assertIsNotNone(g.state.pending_choice)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.end(g); self.end(g); self.assert_source_death(g, target, source, CORRUPTION)
        self.portable(g)

    def test_start_wait_preserves_unconsumed_original_guard(self):
        self.watch('start.wait', 'turn_started', lambda c: pause(c) if c.event.player_id == 1 else ())
        g = self.game(board=('start.wait', 'card.1')); target = g.state.players[2].board[0]; source = self.play(g)
        self.end(g); self.end(g)
        self.assertEqual(self.trigger(g, target).uses_remaining, 1)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_source_death(g, target, source, CORRUPTION)
        self.portable(g)

    def test_source_removed_before_consumption_invalidates_original_guard(self):
        self.watch('start.clear', 'turn_started', lambda c: (Silence(c.state.players[2].board[0]),)
            if c.event.player_id == 1 else ())
        g = self.game(board=('start.clear', 'card.1')); target = g.state.players[2].board[0]
        self.play(g); self.end(g); self.end(g)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind == 'limited_trigger_used' for e in g.events)); self.portable(g)

    def test_consumed_start_body_wait_restores_exact_grant_source(self):
        g, target, source = self.consumed_wait()
        a = self.trigger(g, target)
        self.assertEqual((a.consumed, a.uses_remaining, a.source_id), (True, 0, source))
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_source_death(g, target, source, CORRUPTION)
        self.portable(g)

    def test_consumed_end_body_wait_restores_one_classified_end_root(self):
        g, target, source = self.consumed_wait(POWER)
        self.assertTrue(self.trigger(g, target).consumed)
        self.assertEqual(g.state.entities[target].zone, Zone.BOARD)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_source_death(g, target, source, POWER)
        self.portable(g)

    def test_late_consumption_failure_rolls_back_complete_turn_action(self):
        self.watch('used.fault', 'limited_trigger_used', lambda c: (AddToHand(1, 'missing.bound.death'),))
        g = self.game(board=('used.fault', 'card.1')); target = g.state.players[2].board[0]
        self.play(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.bound.death'):
            self.end(g)
        self.assertEqual(g.snapshot(), before); self.assertEqual(self.trigger(g, target).uses_remaining, 1)

    def test_failed_choice_keeps_consumed_source_and_resumes_original_death(self):
        self.script('choice.fault', lambda c: (AddToHand(1, 'missing.bound.death'),))
        self.watch('used.choice', 'limited_trigger_used', lambda c: (RequestChoice(1, (
            ChoiceOption('bad', 'Fail', (InvokeBehavior('choice.fault', c.source_id, c.player_id),)),
            ChoiceOption('ok', 'Continue')), c.source_id),))
        g = self.game(board=('used.choice', 'card.1')); target = g.state.players[2].board[0]; source = self.play(g)
        self.end(g); self.end(g); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.bound.death'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before)
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assert_source_death(g, target, source, CORRUPTION)

    def test_public_projection_has_no_original_grant_or_private_conditions(self):
        g = self.game(enemy_hand=('card.29',)); self.play(g); before = g.snapshot()
        for viewer in (1, 2):
            text = json.dumps([g.observe(viewer), g.player_events(viewer), g.for_player(viewer).legal_actions()])
            for private in ('bound.actor.1', 'bound.kill', 'source_card_id', 'ability_id', 'entered_order'):
                self.assertNotIn(private, text)
        self.assertIsNone(g.observe(1)['players'][1]['hand'][0]['card_id'])
        self.assertEqual(g.observe(1)['players'][1]['board'][0]['limited_triggers'], [{'keyword': None, 'uses_remaining': 1}])
        self.assertEqual(g.snapshot(), before)

    def test_pending_consumed_context_rejects_changed_source_or_usage(self):
        g, target, source = self.consumed_wait()
        for field, value in (('source_id', target), ('uses_remaining', 1)):
            saved = g.snapshot()
            context = next(n for n in self.nodes(saved['resolution_frame'], 'RuleContext')
                if n['fields']['trigger'] is not None)
            context['fields']['trigger']['fields'][field] = value
            self.reject(saved)

    def test_existing_schema_and_full_runtime_versions_remain_unchanged(self):
        g = self.game(); self.play(g)
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = deepcopy(g.snapshot()); saved['schema_version'] = 215; self.reject(saved)
        self.portable(g)
