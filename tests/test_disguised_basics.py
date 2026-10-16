"""Independent Disguised entry, actor provenance and required persistence paths."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, CounterMinion, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, Destroy, Draw,
    GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.targets import canonical_digest


FIXTURE = Path(__file__).resolve().parents[1]/'data/support/disguised-basics.json'
PIN = '87863b39651f6d62b95411870d815487700c20f4dab375466961b4f3a5495b73'
WATCHMAN = 'JAIL_455'
OPERATOR = 'CAP_004'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Disguised complete evidence pin changed')
    result = {}
    for row in data['records']:
        raw = row['data']
        if canonical_digest(raw) != row['data_sha256'] or raw['tags']['DISGUISED'] != 1:
            raise ValueError('Disguised raw face differs from its adapter')
        result[row['id']] = raw
    return result


def watchman(c):
    # Battlecry policy belongs to the actor. Its two waves use the entry side.
    return [InvokeBehavior('watchman_wave', c.source_id, c.source.controller) for _ in range(2)]


def watchman_wave(c):
    return [DamageBatch(tuple(Damage(i, 1, c.source_id)
        for i in c.state.players[c.player_id].board
        if i != c.source_id and c.state.entities[i].kind == CardType.MINION and
           c.state.entities[i].active))]


def registry(extras=()):
    r = Registry('disguised-basics-v1')
    r.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'plain', CardType.MINION, cost=1, attack=1, health=5))
    r.register_behavior('watchman', watchman)
    r.register_behavior('watchman_wave', watchman_wave)
    r.register_behavior('operator_death', lambda c: [Draw(3-c.player_id, 2, c.source_id)])
    for key, raw in evidence().items():
        tags = raw['tags']
        r.register_card(CardDefinition(key, raw['name'], CardType.MINION,
            cost=tags['COST'], attack=tags['ATK'], health=tags['HEALTH'], disguised=True,
            battlecry='watchman' if key == WATCHMAN else None,
            deathrattle='operator_death' if key == OPERATOR else None,
            keywords=(Keyword.RUSH,) if key == OPERATOR else ()))
    for kind, name, handler, event in extras:
        r.register_behavior(name, handler)
        r.register_card(CardDefinition(name, name,
            CardType.MINION if kind == 'watch' else CardType.SPELL,
            attack=1 if kind == 'watch' else 0, health=5 if kind == 'watch' else 0,
            triggers=(TriggerSpec(event, name),) if kind == 'watch' else (),
            on_play=name if kind == 'script' else None))
    return r


class DisguisedBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def watch(self, name, event, handler):
        self.extras.append(('watch', name, handler, event))

    def script(self, name, handler):
        self.extras.append(('script', name, handler, None))

    def game(self, hand=(WATCHMAN,), board=(), enemy_board=(), enemy_hand=(), mana=10):
        self.r = registry(self.extras)
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('plain',)*6, mana=mana, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, deck=('plain',)*6,
                mana=10, max_mana=10)), seed=7), self.r)

    def source(self, g, name=WATCHMAN, player=None):
        player = g.state.active_player if player is None else player
        return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)

    def play(self, g, name=WATCHMAN, *, side=None, position=None):
        i = self.source(g, name)
        g.apply(PlayCard(g.state.active_player, i, position=position, board_player_id=side))
        return i

    def choose(self, g):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (c.options[0].id,)))

    def check(self, g):
        saved = g.snapshot()
        fresh = registry(self.extras)
        self.assertIsNot(fresh, self.r)
        self.assertEqual(Game.from_snapshot(saved, fresh).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), saved)

    def wait(self, name, event):
        self.watch(name, event, lambda c: [RequestChoice(1,
            (ChoiceOption('ok', 'OK', ()),), source_id=c.source_id)]
            if c.event.source_id in c.state.entities and
               c.state.entities[c.event.source_id].card_id == WATCHMAN else [])

    def test_complete_pinned_representative_faces(self):
        r = registry()
        self.assertEqual((r.card(WATCHMAN).name, r.card(WATCHMAN).cost,
            r.card(WATCHMAN).attack, r.card(WATCHMAN).health), ('伪装的看守', 2, 2, 4))
        self.assertEqual((r.card(OPERATOR).name, r.card(OPERATOR).cost,
            r.card(OPERATOR).attack, r.card(OPERATOR).health), ('伪装的特工', 1, 4, 2))
        self.assertTrue(r.card(WATCHMAN).disguised)

    def test_declaration_requires_boolean_and_physical_minion(self):
        for value in (1, None, 'true'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Registry('negative').register_card(CardDefinition('bad', 'bad', CardType.MINION, health=2, disguised=value))
        with self.assertRaises(ValueError):
            Registry('negative').register_card(CardDefinition('bad', 'bad', CardType.SPELL, disguised=True))

    def test_ordinary_cards_cannot_select_any_explicit_board(self):
        g = self.game(hand=('plain',)); i = self.source(g, 'plain'); before = g.snapshot()
        for side in (1, 2):
            with self.subTest(side=side), self.assertRaises(IllegalAction):
                g.apply(PlayCard(1, i, board_player_id=side))
        self.assertEqual(g.snapshot(), before)

    def test_omitted_side_is_friendly_and_uses_normal_entry(self):
        g = self.game(hand=(OPERATOR,), enemy_board=('plain',)); i = self.play(g, OPERATOR)
        self.assertIn(i, g.state.players[1].board)
        self.assertEqual((g.state.entities[i].owner, g.state.entities[i].controller), (1, 1))
        self.assertIsNone(g.state.play_history[-1].board_player_id)
        self.assertIn(Attack(1, i, g.state.players[2].board[0]), g.legal_actions())
        self.assertNotIn(Attack(1, i, g.state.players[2].hero_id), g.legal_actions())
        self.check(g)

    def test_enemy_entry_retains_actor_payment_face_and_history(self):
        g = self.game(); i = self.play(g, side=2); state = g.state; p = state.play_history[-1]
        self.assertEqual((state.entities[i].owner, state.entities[i].controller), (1, 2))
        self.assertNotIn(i, state.players[1].board); self.assertIn(i, state.players[2].board)
        self.assertEqual((state.players[1].mana, state.players[2].mana), (8, 10))
        self.assertEqual((p.player_id, p.board_player_id, p.played_face.player_id,
            p.submitted_cost.quote.quote_input.player_id, p.battlecry_acceptance.player_id), (1, 2, 1, 1, 1))
        self.assertTrue(p.completed)
        self.assertEqual([e.player_id for e in g.events if e.kind == 'card_played'], [1])
        self.assertEqual([e.player_id for e in g.events if e.kind == 'minion_summoned'], [2])
        self.assertFalse(any(e.kind == 'control_changed' for e in g.events))
        self.check(g)

    def test_positions_enumerate_each_destination_without_mutation(self):
        g = self.game(board=('plain',), enemy_board=('plain',)*3); i = self.source(g); before = g.snapshot()
        actions = [a for a in g.legal_actions() if isinstance(a, PlayCard) and a.entity_id == i]
        self.assertEqual({(a.board_player_id, a.position) for a in actions},
            {(None, 0), (None, 1), (2, 0), (2, 1), (2, 2), (2, 3)})
        self.assertEqual(g.snapshot(), before)
        old = g.state.players[2].board; self.play(g, side=2, position=1)
        self.assertEqual(g.state.players[2].board, [old[0], i, *old[1:]])

    def test_position_bounds_use_selected_board(self):
        g = self.game(board=('plain',)*3); i = self.source(g); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(PlayCard(1, i, position=1, board_player_id=2))
        self.assertEqual(g.snapshot(), before)
        g.apply(PlayCard(1, i, position=3))
        self.assertEqual(g.state.players[1].board[-1], i)

    def test_capacity_uses_selected_board_only(self):
        for own, enemy, legal_side in ((7, 0, 2), (0, 7, None)):
            with self.subTest(own=own, enemy=enemy):
                g = self.game(board=('plain',)*own, enemy_board=('plain',)*enemy)
                i = self.source(g); candidates = [a for a in g.legal_actions() if isinstance(a, PlayCard)]
                self.assertEqual({a.board_player_id for a in candidates}, {legal_side})
                self.play(g, side=legal_side)
                self.assertEqual(g.state.entities[i].controller, 1 if legal_side is None else legal_side)

    def test_watchman_two_waves_hit_enemy_side_not_actor_side(self):
        g = self.game(board=('plain',), enemy_board=('plain',)*2)
        own = g.state.players[1].board[0]; enemy = g.state.players[2].board; i = self.play(g, side=2)
        self.assertEqual(g.state.entities[own].health, 5)
        self.assertEqual([g.state.entities[j].health for j in enemy], [3, 3])
        self.assertEqual(g.state.entities[i].health, 4)
        self.assertEqual([p.player_id for p in g.state.battlecry_history], [1])
        self.check(g)

    def test_watchman_friendly_side_and_first_wave_deaths(self):
        self.script('hurt', lambda c: [Damage(c.state.players[1].board[0], 4)])
        g = self.game(hand=('hurt', WATCHMAN), board=('plain',), enemy_board=('plain',))
        victim = g.state.players[1].board[0]; self.play(g, 'hurt'); self.play(g)
        self.assertEqual(g.state.entities[victim].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health, 5)
        self.assertEqual(len(g.state.death_history), 1)
        self.check(g)

    def test_controller_is_already_selected_in_entry_listener(self):
        def entered(c):
            if c.state.entities[c.event.source_id].card_id == WATCHMAN:
                if c.state.entities[c.event.source_id].controller != 2 or c.state.play_history[-1].player_id != 1:
                    raise ValueError('Entry exposed the wrong controller or actor')
                return [GainArmor(1, 3)]
            return []
        self.watch('entered', 'minion_summoned', entered)
        g = self.game(board=('entered',)); self.play(g, side=2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)

    def test_counter_cancels_entry_and_keeps_paid_actor_graveyard(self):
        self.watch('counter', 'minion_counter_check', lambda c: [CounterMinion(c.state.action_windows[-1].id)])
        g = self.game(hand=(OPERATOR,), enemy_board=('counter',)); i = self.play(g, OPERATOR, side=2)
        p = g.state.play_history[-1]
        self.assertEqual((p.player_id, p.board_player_id, p.minion_result, p.countered), (1, 2, 'countered', True))
        self.assertEqual((g.state.entities[i].zone, g.state.entities[i].controller), (Zone.GRAVEYARD, 1))
        self.assertEqual((g.state.players[1].mana, len(g.state.players[1].hand), len(g.state.players[2].hand)), (9, 0, 0))
        self.assertFalse(g.state.death_history); self.check(g)

    def test_destination_fills_after_payment_without_entry_or_fake_death(self):
        self.watch('fill', 'card_committed', lambda c: [Summon(2, 'plain') for _ in range(7)]
            if c.play is not None and c.play.card_id == WATCHMAN else [])
        g = self.game(board=('fill',)); i = self.play(g, side=2)
        self.assertEqual(g.state.play_history[-1].minion_result, 'board_full')
        self.assertEqual((g.state.entities[i].zone, g.state.entities[i].controller), (Zone.GRAVEYARD, 1))
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertFalse(g.state.battlecry_history); self.assertFalse(g.state.death_history)
        self.check(g)

    def test_waiting_before_entry_retains_actor_and_frozen_destination(self):
        self.wait('wait', 'card_committed'); g = self.game(board=('wait',), enemy_board=('plain',))
        i = self.play(g, side=2)
        self.assertEqual((g.state.entities[i].zone, g.state.entities[i].controller), (Zone.PLAY, 1))
        self.assertEqual(g.state.players[1].pending_plays, [i])
        self.assertEqual(g.observe(1)['players'][0]['pending_plays'][0]['play_side'], 'enemy')
        self.assertEqual(g.observe(2)['players'][0]['pending_plays'][0]['play_side'], 'friendly')
        self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[i].controller, 2); self.assertEqual(g.state.players[1].mana, 8)
        self.check(g)

    def test_waiting_after_entry_keeps_destination_and_pending_body(self):
        self.wait('wait', 'minion_summoned'); g = self.game(board=('wait',), enemy_board=('plain',))
        i = self.play(g, side=2); victim = g.state.players[2].board[0]
        self.assertEqual((g.state.entities[i].zone, g.state.entities[i].controller), (Zone.BOARD, 2))
        self.assertEqual(g.state.entities[victim].health, 5); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[victim].health, 3); self.check(g)

    def test_enemy_choice_between_two_actual_damage_waves_restores(self):
        self.watch('wait', 'damage_dealt', lambda c: [RequestChoice(2,
            (ChoiceOption('ok', 'OK', ()),), source_id=c.source_id)]
            if c.event.target_id == c.source_id and c.source.damage == 1 else [])
        g = self.game(enemy_board=('wait',)); i = self.play(g, side=2)
        self.assertEqual(g.state.pending_choice.player_id, 2); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.state.entities[i].controller, 2)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].damage, 2); self.check(g)

    def test_operator_death_opponent_is_relative_to_current_controller(self):
        self.script('kill', lambda c: [Destroy(next(i for i in c.state.players[2 if c.state.players[2].board else 1].board
            if c.state.entities[i].card_id == OPERATOR))])
        for side, drawing_player in ((None, 2), (2, 1)):
            with self.subTest(side=side):
                g = self.game(hand=(OPERATOR, 'kill')); i = self.play(g, OPERATOR, side=side)
                self.play(g, 'kill'); death = g.state.death_history[-1]
                self.assertEqual(death.controller, 1 if side is None else 2)
                self.assertEqual(g.state.entities[i].owner, 1)
                self.assertEqual(len(g.state.players[drawing_player].hand), 2)
                self.assertEqual(len(g.state.players[3-drawing_player].hand), 0)
                self.check(g)

    def test_return_to_hand_then_other_actor_can_choose_side(self):
        self.script('bounce', lambda c: [ReturnToHand(c.state.players[2].board[0])])
        g = self.game(hand=(OPERATOR, 'bounce')); i = self.play(g, OPERATOR, side=2)
        self.play(g, 'bounce'); self.assertIn(i, g.state.players[2].hand)
        g.apply(EndTurn(1)); g.apply(PlayCard(2, i, board_player_id=1))
        self.assertEqual((g.state.entities[i].owner, g.state.entities[i].controller), (1, 1))
        self.assertEqual((g.state.play_history[-1].player_id, g.state.play_history[-1].board_player_id), (2, 1))
        self.check(g)

    def test_current_copy_does_not_inherit_previous_destination(self):
        self.script('bounce', lambda c: [ReturnToHand(c.state.players[2].board[0])])
        self.script('copy', lambda c: [CopyCard(CardReference.capture(c.state.entities[c.state.players[2].hand[0]]), 1)])
        g = self.game(hand=(OPERATOR, 'bounce', 'copy')); original = self.play(g, OPERATOR, side=2)
        self.play(g, 'bounce')
        self.play(g, 'copy'); copied = self.source(g, OPERATOR); self.assertNotEqual(original, copied)
        self.play(g, OPERATOR)
        self.assertEqual(g.state.entities[copied].controller, 1)
        self.assertIsNone(g.state.play_history[-1].board_player_id); self.check(g)

    def test_transform_to_ordinary_face_removes_board_side_permission(self):
        self.script('replace', lambda c: [Transform(c.state.players[2].board[0], 'plain'),
            ReturnToHand(c.state.players[2].board[0])])
        g = self.game(hand=(OPERATOR, 'replace')); i = self.play(g, OPERATOR, side=2)
        self.play(g, 'replace'); g.apply(EndTurn(1)); before = g.snapshot()
        with self.assertRaises(IllegalAction): g.apply(PlayCard(2, i, board_player_id=1))
        self.assertEqual(g.snapshot(), before); self.check(g)

    def test_summon_uses_effect_destination_without_paid_play_or_battlecry(self):
        self.script('summon', lambda c: [Summon(2, WATCHMAN)])
        g = self.game(hand=('summon',), enemy_board=('plain',)); victim = g.state.players[2].board[0]
        self.play(g, 'summon'); self.assertEqual(g.state.entities[victim].health, 5)
        self.assertEqual(len(g.state.play_history), 1); self.assertFalse(g.state.battlecry_history)
        self.assertEqual(len(g.state.players[2].board), 2); self.check(g)

    def test_player_command_exposes_only_relative_side_and_public_face(self):
        for viewer in (1, 2):
            with self.subTest(viewer=viewer):
                g = self.game(hand=(OPERATOR,), enemy_hand=(OPERATOR,))
                hidden = g.observe(1)['players'][1]['hand'][0]
                self.assertIsNone(hidden['card_id']); self.assertNotIn('disguised', hidden)
                if viewer == 2: g.apply(EndTurn(1))
                port = g.for_player(viewer); offer = port.legal_actions()
                self.assertIsNone(offer['error']); self.assertEqual(offer['version'], 'player-actions-v12')
                command = next(a for a in offer['actions'] if a['type'] == 'play_card' and a.get('side') == 'enemy')
                self.assertNotIn('board_player_id', json.dumps(offer)); self.assertNotIn('source_id', json.dumps(offer))
                result = port.submit({'revision': offer['revision'], 'action': command})
                self.assertIsNone(result['error'])
                p = g.state.play_history[-1]
                self.assertEqual((p.player_id, p.board_player_id), (viewer, 3-viewer)); self.check(g)

    def test_invalid_player_side_is_rejected_without_mutation(self):
        g = self.game(hand=(OPERATOR,)); port = g.for_player(1); offer = port.legal_actions()
        command = next(a for a in offer['actions'] if a['type'] == 'play_card'); before = g.snapshot()
        for side in (None, 2, True, 'left', 'opponent'):
            with self.subTest(side=side):
                result = port.submit({'revision': offer['revision'], 'action': {**command, 'side': side}})
                self.assertIsNotNone(result['error']); self.assertEqual(g.snapshot(), before)

    def test_core_action_wire_roundtrip_and_strict_destination_type(self):
        a = PlayCard(1, 7, position=0, board_player_id=2)
        self.assertEqual(action_from_dict(action_to_dict(a)), a)
        self.assertNotIn('board_player_id', action_to_dict(PlayCard(1, 7)))
        for bad in (True, '2', 0, 3, 2.0):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                action_from_dict({**action_to_dict(a), 'board_player_id': bad})

    def test_snapshot_rejects_changed_original_destination_and_old_schema(self):
        self.wait('wait', 'card_committed'); g = self.game(board=('wait',)); self.play(g, side=2)
        saved = g.snapshot(); self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        saved['state']['play_history'][0]['board_player_id'] = 1
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.extras))
        saved = g.snapshot(); saved['schema_version'] = 150
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.extras))

    def test_entry_callback_failure_rolls_back_payment_destination_and_history(self):
        def fail(c): raise ValueError('Disguised entry fixture failure')
        self.watch('fail', 'minion_summoned', fail)
        g = self.game(board=('fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, side=2)
        self.assertEqual(g.snapshot(), before)

    def test_waiting_in_actual_counter_phase_restores_chosen_board(self):
        self.wait('wait', 'minion_counter_check'); g = self.game(board=('wait',))
        i = self.play(g, side=2); self.assertTrue(g.state.action_windows[-1].counter_phase)
        self.check(g); restored = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(g.state.entities[i].controller, 2)
        self.check(g)

    def test_snapshot_requires_destination_field_with_strict_type(self):
        self.wait('wait', 'card_committed'); g = self.game(board=('wait',)); self.play(g, side=2)
        for value in (True, '2', 3):
            with self.subTest(value=value):
                saved = g.snapshot(); saved['state']['play_history'][0]['board_player_id'] = value
                with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.extras))
        saved = g.snapshot(); del saved['state']['play_history'][0]['board_player_id']
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, registry(self.extras))

    def test_choice_failure_returns_to_already_entered_paid_boundary(self):
        def fail(c): raise ValueError('Disguised selected callback failure')
        self.script('fail_later', fail)
        self.script('first_write', lambda c: [GainArmor(1, 9), InvokeBehavior('fail_later', c.source_id, 1)])
        self.watch('wait', 'minion_summoned', lambda c: [RequestChoice(1,
            (ChoiceOption('bad', 'bad', (InvokeBehavior('first_write', c.source_id, 1),)),), source_id=c.source_id)])
        g = self.game(board=('wait',)); i = self.play(g, side=2); before = g.snapshot(); self.check(g)
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(), before); self.assertEqual(g.state.entities[i].controller, 2)
        self.assertEqual(g.state.players[1].mana, 8)


if __name__ == '__main__':
    unittest.main()
