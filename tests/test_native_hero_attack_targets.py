"""Real Glaivebound Adept and original hero completion facts in player inputs."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_hero_attack_target_cards import CARD, RULE, load_batch, register_native_hero_attack_target_cards
from hs_sim.engine import (Attack, BodyRootTargetBinding, BodyTargetBinding, BodyTargetProfile, CardDefinition, CardType,
    EndTurn, Game, GeneratedWholeTargetBinding, IllegalAction, Keyword, LimitedTriggerSpec,
    PlayCard, PlayerSetup, Registry, Scenario, SelectChoice, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Freeze, InvokeBehavior, ReplaceHero, RequestChoice)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.hero_attack_history import hero_attack_count
from hs_sim.engine.model import HeroAttackQuery
from hs_sim.engine.player_target_inputs import canonical, decode, validate_origin
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import entity_from_dict
from hs_sim.engine.generated_combo_repeats import PROFILE
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_replays import ReplayWholeCards

P = 'k180.'
HERO, NEW, FILL, SHIELD, POWER = (P+x for x in ('hero', 'new', 'filler', 'shield', 'power'))


@lru_cache(maxsize=16)
def registry(role='writer', mode='normal'):
    r = Registry('k180-' + mode)
    register_native_hero_attack_target_cards(r)
    for cid, kind, kw in (
        (HERO, CardType.HERO, dict(attack=2, health=100)),
        (NEW, CardType.HERO, dict(attack=3, health=100)),
        (FILL, CardType.MINION, dict(attack=1, health=20, keywords=(Keyword.CHARGE,))),
        (SHIELD, CardType.MINION, dict(health=20, keywords=(Keyword.DIVINE_SHIELD,))),
        (POWER, CardType.MINION, dict(health=20, spell_damage=5)),
    ):
        r.register_card(CardDefinition(cid, cid, kind, **kw))
    r.register_behavior(P+'replace', lambda c: (ReplaceHero(c.player_id, NEW),))
    r.register_card(CardDefinition(P+'replace', P+'replace', CardType.SPELL, on_play=P+'replace'))
    def fail(c):
        raise ResolutionError('k180 original reaction failure')
    r.register_behavior(P+'fail', fail)
    if mode in ('wait_commit', 'wait_hit', 'cancel', 'pre', 'post'):
        event = {'wait_commit': 'card_committed', 'wait_hit': 'damage_dealt',
                 'cancel': 'attack_declared', 'pre': 'attack_declared', 'post': 'attack_finished'}[mode]
        def condition(c):
            source = c.state.entities.get(c.event.source_id)
            return source is not None and source.controller == c.player_id and (
                source.card_id == CARD if mode.startswith('wait') else source.kind == CardType.HERO)
        def watch(c):
            if mode == 'cancel':
                return (Freeze(c.event.source_id),)
            if mode in ('pre', 'post'):
                return (ReplayWholeCards(c.player_id, c.source_id,
                    WholeCardHistoryQuery(c.player_id, len(c.state.play_history)+1, kinds=(CardType.MINION,)),
                    physical_profile=PROFILE, body_target_profile_id=P+'generated'),)
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),
                ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
        r.register_behavior(P+'watch', watch)
        r.register_trigger_condition(P+'watch', condition)
        r.register_card(CardDefinition(P+'watch', P+'watch', CardType.MINION, health=20,
            limited_triggers=(LimitedTriggerSpec(event, P+'watch', condition_id=P+'watch'),)))
    if mode in ('pre', 'post'):
        r.register_body_target_profile(BodyTargetProfile(P+'generated', 'generated_whole', 'random', 'generated_acceptance'))
        r.register_body_target_binding(BodyTargetBinding(CARD, 'battlecry', P+'generated',
            origins=('printed',), carrier_kinds=(CardType.MINION,), carrier_card_ids=(CARD,)))
        r.register_generated_whole_target_binding(GeneratedWholeTargetBinding(CARD, P+'generated', 'body_only'))
    if mode == 'paid':
        r.register_body_target_profile(BodyTargetProfile(P+'paid', 'paid_hand', 'manual', 'pre_payment'))
        r.register_body_target_binding(BodyTargetBinding(CARD, 'battlecry', P+'paid',
            origins=('printed',), carrier_kinds=(CardType.MINION,), carrier_card_ids=(CARD,)))
        r.register_body_root_target_binding(BodyRootTargetBinding(CARD, P+'paid', 'body_only'))
    r.validate()
    r.freeze()
    return r


def game(mode='normal', hand=(CARD,), board=(), enemy=()):
    if mode in ('wait_commit', 'wait_hit', 'cancel', 'pre', 'post'):
        board = (*board, P+'watch')
    return Game.from_scenario(Scenario((
        PlayerSetup(HERO, hand=hand, board=board, deck=(FILL,)*12, mana=40, max_mana=40, mana_cap=40),
        PlayerSetup(HERO, board=enemy, deck=(FILL,)*12)), seed=180), registry('writer', mode))


def play(g, cid=CARD, target=None):
    p = g.state.active_player
    e = next(g.state.entities[i] for i in g.state.players[p].hand if g.state.entities[i].card_id == cid)
    if g.registry.version == 'k180-paid' and cid == CARD:
        port = g.for_player(p)
        view = port.observe()['observation']
        ref = next(row['ref'] for row in view['players'][p-1]['hand'] if row['card_id'] == CARD)
        position = len(g.state.players[p].board)
        q = port.independent_targets(ref, position=position)
        if q['error'] is not None:
            raise AssertionError(q)
        route = q['choices'][0]
        target_ref = None if target is None else g._information.players[p].refs[str(target)]
        command = dict(type='play_card', card=route['card'], target=route['root_targets'][0],
                       position=position, body_targets=[dict(body=b['body'], target=target_ref)
                                                       for b in route['bodies']])
        reply = port.submit(dict(revision=q['revision'], action=command))
        if not reply['accepted']:
            raise AssertionError(reply)
        return e.id
    g.apply(PlayCard(p, e.id, target_id=target, position=len(g.state.players[p].board) if e.kind == CardType.MINION else None))
    return e.id


def attack(g, target=None, player=1):
    g.apply(Attack(player, g.state.players[player].hero_id, target or g.state.players[3-player].hero_id))


def own(g, player=1):
    return g.observe(player)['players'][player-1]


def select(g, key='ok'):
    q = g.state.pending_choice
    g.apply(SelectChoice(q.player_id, q.id, (key,)))


class NativeHeroAttackTargetTests(unittest.TestCase):
    def portable(self, g, mode='normal'):
        snap = g.snapshot()
        reader = registry('reader', mode)
        self.assertIsNot(reader, g.registry)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(snap)), reader).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), snap)
        for pid in (1, 2):
            visible = json.dumps(g.observe(pid)) + json.dumps(g.player_events(pid)) + json.dumps(g.for_player(pid).legal_actions())
            for key in ('original_event_cursor', 'hero_attack_history', 'physical_hero_id', 'observation_json', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"'+key+'"', visible)
            self.assertNotIn('hero_attacked_this_turn', g.observe(pid)['players'][2-pid])

    def actions(self, g):
        port = g.for_player(1)
        result = port.legal_actions()
        self.assertIsNone(result['error'])
        ref = next(x['ref'] for x in result['observation']['players'][0]['hand'] if x['card_id'] == CARD)
        return port, result, [a for a in result['actions'] if a['type'] == 'play_card' and a['card'] == ref]

    def test_01_complete_original_face_and_explicit_pure_player_rule(self):
        from tools.card_batch import check_face
        data = load_batch()
        raw = data['cards'][0]['record']
        for o in data['official_observations']:
            check_face(raw, o['face'], o['locale'])
        self.assertEqual((raw['cost'], raw['attack'], raw['health']), (5, 6, 4))
        self.assertEqual(registry().target_visibility(RULE), 'player')
        self.assertIsNotNone(registry().player_target_rule(RULE))
        self.assertIsNone(registry().card(CARD).target_condition)

    def test_02_false_condition_allows_real_paid_play_only_without_target(self):
        g = game()
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        port, result, actions = self.actions(g)
        self.assertTrue(actions)
        self.assertTrue(all(a['target'] is None for a in actions))
        eid = play(g)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].health, g.state.players[1].mana), (6, 4, 35))
        self.assertFalse(g.state.damage_history)
        self.portable(g)

    def test_03_false_condition_rejects_supplied_target_atomically(self):
        g = game()
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            play(g, target=g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(), before)

    def test_04_completed_hero_attack_enables_public_target_and_four_minion_damage(self):
        g = game(board=(POWER,))
        attack(g)
        self.assertIs(own(g)['hero_attacked_this_turn'], True)
        port, result, actions = self.actions(g)
        target = result['observation']['players'][1]['hero']['ref']
        action = next(a for a in actions if a['target'] == target)
        reply = port.submit(dict(revision=result['revision'], action=action))
        self.assertTrue(reply['accepted'], reply.get('error'))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 94)
        self.assertEqual(g.state.damage_history[-1].health_result.damage_dealt, 4)
        self.assertEqual(g.state.damage_history[-1].health_result.damage_kind, 'minion_ability')
        self.assertEqual(g.state.players[1].mana, 35)
        self.portable(g)

    def test_05_true_condition_requires_target_when_characters_exist(self):
        g = game()
        attack(g)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            play(g)
        self.assertEqual(g.snapshot(), before)

    def test_06_cancelled_declaration_does_not_count_spent_attack_opportunity(self):
        g = game('cancel')
        attack(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].attacks_this_turn, 1)
        self.assertEqual(g.state.hero_attack_history[0].terminal.outcome, 'cancelled')
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        play(g)
        self.assertFalse(g.state.damage_history)
        self.portable(g, 'cancel')

    def test_07_nonhero_attack_and_opponent_attack_do_not_enable_owner(self):
        g = game(board=(FILL,))
        g.apply(Attack(1, g.state.players[1].board[0], g.state.players[2].hero_id))
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        g.apply(EndTurn(1))
        attack(g, player=2)
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        g.apply(EndTurn(2))
        play(g)
        self.portable(g)

    def test_08_completed_shielded_exchange_still_enables_and_turn_change_resets(self):
        g = game(enemy=(SHIELD,))
        attack(g, g.state.players[2].board[0])
        self.assertIs(own(g)['hero_attacked_this_turn'], True)
        self.assertEqual(hero_attack_count(g.state, 1, HeroAttackQuery(window='owner_turn')), 1)
        g.apply(EndTurn(1))
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        g.apply(EndTurn(2))
        self.assertIs(own(g)['hero_attacked_this_turn'], False)
        play(g)
        self.portable(g)

    def test_09_new_physical_hero_does_not_erase_original_completed_fact(self):
        g = game(hand=(P+'replace', CARD))
        original = g.state.players[1].hero_id
        attack(g)
        play(g, P+'replace')
        self.assertNotEqual(g.state.players[1].hero_id, original)
        self.assertIs(own(g)['hero_attacked_this_turn'], True)
        play(g, target=g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 94)
        self.portable(g)

    def test_10_old_false_paid_origin_survives_later_real_attack(self):
        g = game('paid', hand=(CARD, CARD))
        play(g)
        proof = g.state.play_history[0].body_targets.origin.observation
        self.assertIs(json.loads(proof.observation_json)['players'][0]['hero_attacked_this_turn'], False)
        attack(g)
        play(g, target=g.state.players[2].hero_id)
        self.assertIs(own(g)['hero_attacked_this_turn'], True)
        self.assertEqual(g.state.play_history[0].body_targets.origin.observation, proof)
        self.portable(g, 'paid')

    def test_11_waiting_after_payment_retains_false_original_and_failed_choice_rolls_back(self):
        g = game('wait_commit')
        play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g, 'wait_commit')
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            select(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        select(g)
        self.assertEqual(g.state.players[1].mana, 35)
        self.assertFalse(g.state.damage_history)
        self.portable(g, 'wait_commit')

    def test_12_true_native_hit_waits_restores_and_finishes_without_repaying(self):
        g = game('wait_hit')
        attack(g)
        play(g, target=g.state.players[2].hero_id)
        self.assertIsNotNone(g.state.pending_choice)
        self.portable(g, 'wait_hit')
        reader = Game.from_snapshot(g.snapshot(), registry('reader', 'wait_hit'))
        select(g)
        select(reader)
        self.assertEqual(g.snapshot(), reader.snapshot())
        self.assertEqual(g.state.players[1].mana, 35)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 94)
        self.portable(g, 'wait_hit')

    def test_13_frozen_fact_rechecked_against_original_completion_not_current_true(self):
        g = game('paid')
        play(g)
        attack(g)
        origin = g.state.play_history[0].body_targets.origin
        source = entity_from_dict(json.loads(origin.source_json))
        value = json.loads(origin.observation.observation_json)
        value['players'][0]['hero_attacked_this_turn'] = True
        changed = replace(origin, observation=replace(origin.observation, observation_json=canonical(value)))
        with self.assertRaisesRegex(ValueError, 'actual completion window'):
            validate_origin(g.registry, changed, source, history_state=g.state)

    def test_14_private_raw_cursor_cannot_be_moved_before_a_true_original_completion(self):
        g = game('paid')
        attack(g)
        play(g, target=g.state.players[2].hero_id)
        origin = g.state.play_history[0].body_targets.origin
        source = entity_from_dict(json.loads(origin.source_json))
        changed = replace(origin, observation=replace(origin.observation, original_event_cursor=0))
        with self.assertRaisesRegex(ValueError, 'actual completion window'):
            validate_origin(g.registry, changed, source, history_state=g.state)

    def test_15_dto_rejects_nonboolean_foreign_and_missing_original_fact(self):
        g = game('paid')
        play(g)
        proof = g.state.play_history[0].body_targets.origin.observation
        for mode in ('integer', 'foreign', 'missing'):
            value = json.loads(proof.observation_json)
            if mode == 'integer':
                value['players'][0]['hero_attacked_this_turn'] = 0
            elif mode == 'foreign':
                value['players'][1]['hero_attacked_this_turn'] = False
            else:
                del value['players'][0]['hero_attacked_this_turn']
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                replace(proof, observation_json=canonical(value))
        with self.assertRaises(ValueError):
            replace(proof, original_event_cursor=True)

    def test_16_generated_body_before_same_attack_completion_retains_original_false(self):
        g = game('pre')
        play(g)
        attack(g)
        child = g.state.whole_card_replay_ledger.children[0]
        origin = child.physical.body_targets.origin
        value = json.loads(origin.observation.observation_json)
        self.assertIs(value['players'][0]['hero_attacked_this_turn'], False)
        record = g.state.hero_attack_history[0]
        self.assertEqual(record.terminal.action_number, origin.action)
        self.assertGreater(record.terminal.event_cursor, origin.observation.original_event_cursor)
        self.assertIs(own(g)['hero_attacked_this_turn'], True)
        self.assertEqual(len(g.state.damage_history), 2)
        self.portable(g, 'pre')

    def test_17_generated_body_after_same_attack_completion_has_true_original_and_four_damage(self):
        g = game('post')
        play(g)
        attack(g)
        child = g.state.whole_card_replay_ledger.children[0]
        origin = child.physical.body_targets.origin
        self.assertIs(json.loads(origin.observation.observation_json)['players'][0]['hero_attacked_this_turn'], True)
        self.assertEqual(sum(x.health_result.damage_dealt for x in g.state.damage_history
                             if x.health_result.damage_kind == 'minion_ability'), 4)
        self.portable(g, 'post')

    def test_18_previous_schema_explicitly_rejected(self):
        g = game()
        saved = g.snapshot()
        saved['schema_version'] = 383
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, registry('reader'))
