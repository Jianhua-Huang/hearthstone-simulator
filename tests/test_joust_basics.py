"""Independent actual minion/spell deck comparisons and private physical results."""
from dataclasses import replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    Game, Joust, JoustResult, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError,
    RevealCapturedHandCard, Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec,
    Zone, joust_result)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, GainArmor, RandomDamage,
    RequestChoice, Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash, event_from_dict, event_to_dict, rng_from_json
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import canonical_digest


FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/joust-basics.json'
PIN = '8f4e7d2b057c0e1f9004665b9f779cffed2a13dcd7e9d17940f95f889b05dd41'
ELEKK = 'AT_058'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete Joust evidence pin changed')
    for row in data['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Joust card changed')
    return {row['id']:row['data'] for row in data['records']}


def elekk_reward(c):
    result = joust_result(c.event)
    if not result.won:
        return []
    ref = result.own.card
    return [MoveCard(ref, c.player_id, Zone.HAND, draw=True, source_id=c.source_id),
            RevealCapturedHandCard(replace(ref, zone=Zone.HAND, zone_epoch=ref.zone_epoch+1))]


def registry(extras=()):
    r = Registry('joust-basics-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=40))
    for name, cost in (('high', 9), ('low', 1), ('middle', 5), ('zero', 0)):
        r.register_card(CardDefinition(name, name, CardType.MINION, cost=cost, attack=1, health=4))
    for name, cost in (('spell_high', 9), ('spell_low', 1)):
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost))
    r.register_behavior('report', lambda c: [GainArmor(c.player_id, 10 if joust_result(c.event).won else 1)])
    r.register_behavior('compare', lambda c: [Joust(c.player_id, 'report', c.source_id)])
    r.register_card(CardDefinition('compare', 'Compare', CardType.SPELL, on_play='compare'))
    r.register_behavior('elekk', lambda c: [Joust(c.player_id, 'elekk_reward', c.source_id)])
    r.register_behavior('elekk_reward', elekk_reward)
    raw = evidence()[ELEKK]
    tags = raw['tags']
    r.register_card(CardDefinition(ELEKK, raw['name'], CardType.MINION, cost=tags['COST'],
        attack=tags['ATK'], health=tags['HEALTH'], battlecry='elekk',
        metadata=CardMetadata(True, (CardClass.HUNTER,), Rarity.COMMON, tribes=('beast',))))
    for name, handler, event in extras:
        r.register_behavior(name, handler)
        r.register_card(CardDefinition(name, name, CardType.MINION if event else CardType.SPELL,
            attack=1 if event else 0, health=5 if event else 0,
            on_play=None if event else name, triggers=(TriggerSpec(event, name),) if event else ()))
    return r


class JoustBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []

    def script(self, name, handler):
        self.extras.append((name, handler, None))

    def watch(self, name, event, handler):
        self.extras.append((name, handler, event))

    def game(self, hand=('compare',), deck=('high',), enemy_deck=('low',), board=(), enemy_hand=(),
             active=1, rules=None, seed=13):
        self.r = registry(self.extras)
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, deck=deck, board=board,
            mana=10, max_mana=10), PlayerSetup('hero', deck=enemy_deck, hand=enemy_hand,
            mana=10, max_mana=10)), seed=seed, active_player=active), self.r, rules)

    def play(self, g, name='compare'):
        player = g.state.active_player
        entity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(player, entity))
        return entity

    def result(self, g):
        return joust_result(next(e for e in reversed(g.events) if e.kind == 'joust_resolved'))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def pause(self, c):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'OK', ()),), source_id=c.source_id)

    def choose(self, g):
        choice = g.state.pending_choice
        g.apply(SelectChoice(choice.player_id, choice.id, (choice.options[0].id,)))

    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, registry(self.extras)).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), registry(self.extras)).snapshot(), snapshot)

    def resumed(self, g):
        self.assertIsNotNone(g.state.pending_choice)
        self.check(g)
        other = Game.from_snapshot(g.snapshot(), registry(self.extras))
        self.choose(g)
        self.choose(other)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.check(g)

    def reject(self, s):
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(s, registry(self.extras))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_higher_stored_cost_wins_and_keeps_both_decks_untouched(self):
        g = self.game(deck=('spell_low', 'high'), enemy_deck=('low', 'spell_high'))
        before = {p:tuple(g.state.players[p].deck) for p in (1, 2)}
        physical = {i:g.state.entities[i] for group in before.values() for i in group}
        self.play(g)
        self.assertTrue(self.result(g).won)
        self.assertEqual(self.armor(g), 10)
        self.assertEqual({p:tuple(g.state.players[p].deck) for p in (1, 2)}, before)
        for i, entity in physical.items():
            self.assertEqual(g.state.entities[i], entity)
        self.assertEqual(g.state.draw_history, [])
        self.assertFalse(any(e.kind in ('card_drawn', 'deck_shuffled', 'card_moved_to_deck', 'fatigue') for e in g.events))
        self.check(g)

    def test_equal_or_lower_cost_never_wins(self):
        for own, enemy in (('low', 'high'), ('middle', 'middle'), ('zero', 'zero')):
            with self.subTest(own=own, enemy=enemy):
                g = self.game(deck=(own,), enemy_deck=(enemy,))
                self.play(g)
                self.assertFalse(self.result(g).won)
                self.assertEqual(self.armor(g), 1)
                self.check(g)

    def test_empty_pool_policy_including_two_empty_pools_and_no_fatigue(self):
        for own, enemy, won in ((('zero',), (), True), ((), ('high',), False), ((), (), False)):
            with self.subTest(own=own, enemy=enemy):
                g = self.game(deck=own, enemy_deck=enemy)
                self.play(g)
                result = self.result(g)
                self.assertEqual(result.won, won)
                self.assertEqual(result.own is None, not own)
                self.assertEqual(result.opponent is None, not enemy)
                self.assertEqual([g.state.players[p].fatigue for p in (1, 2)], [0, 0])
                self.assertEqual(g.state.draw_history, [])
                self.check(g)

    def test_two_empty_pools_consume_no_rng(self):
        g = self.game(deck=(), enemy_deck=())
        rng = g.snapshot()['rng_state']
        self.play(g)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.check(g)

    def test_physical_duplicates_are_independent_weights_and_rng_order_is_actor_then_opponent(self):
        g = self.game(deck=('low', 'high', 'low'), enemy_deck=('middle', 'middle', 'zero'))
        before = g.state
        expected_rng = random.Random()
        expected_rng.setstate(rng_from_json(g.snapshot()['rng_state']))
        own = before.players[1].deck[expected_rng.randrange(3)]
        other = before.players[2].deck[expected_rng.randrange(3)]
        self.play(g)
        result = self.result(g)
        self.assertEqual((result.own.card.entity_id, result.opponent.card.entity_id), (own, other))
        self.assertEqual(rng_from_json(g.snapshot()['rng_state']), expected_rng.getstate())
        self.check(g)

    def test_one_empty_pool_samples_only_the_other_physical_pool(self):
        g = self.game(deck=(), enemy_deck=('low', 'high'))
        rng = random.Random()
        rng.setstate(rng_from_json(g.snapshot()['rng_state']))
        expected = g.state.players[2].deck[rng.randrange(2)]
        self.play(g)
        self.assertEqual(self.result(g).opponent.card.entity_id, expected)
        self.assertEqual(rng_from_json(g.snapshot()['rng_state']), rng.getstate())

    def test_player_two_is_the_initiator_and_gets_its_own_result(self):
        g = self.game(hand=(), enemy_hand=('compare',), deck=('low',), enemy_deck=('high',), active=2)
        self.play(g)
        result = self.result(g)
        self.assertEqual((result.player_id, result.own.card.player_id, result.opponent.card.player_id), (2, 2, 1))
        self.assertEqual((self.armor(g, 1), self.armor(g, 2)), (0, 10))
        self.check(g)

    def test_real_spell_profile_filters_out_minions_and_returns_the_selected_spell(self):
        self.script('spells', lambda c: [Joust(c.player_id, 'report', c.source_id, kind=CardType.SPELL)])
        g = self.game(hand=('spells',), deck=('high', 'spell_high'), enemy_deck=('high', 'spell_low'))
        self.play(g, 'spells')
        result = self.result(g)
        self.assertEqual((result.kind, result.own.card.card_id, result.opponent.card.card_id),
                         (CardType.SPELL, 'spell_high', 'spell_low'))
        self.assertTrue(result.won)
        self.check(g)

    def test_stored_cost_changes_are_read_without_a_payment_or_modifier_use(self):
        self.script('discount', lambda c: [BuffStoredCard(CardReference.capture(c.state.entities[c.state.players[1].deck[0]]),
            cost=CostSpec(delta=-8, minimum=0))])
        g = self.game(hand=('discount', 'compare'), enemy_deck=('middle',))
        self.play(g, 'discount')
        before = g.state.entities[g.state.players[1].deck[0]]
        self.play(g)
        result = self.result(g)
        self.assertEqual(result.own.cost, 1)
        self.assertFalse(result.won)
        self.assertEqual(g.state.entities[before.id].enchantments, before.enchantments)
        self.check(g)

    def test_real_elekk_draws_the_selected_physical_card_and_reveals_it_in_hand(self):
        g = self.game(hand=(ELEKK,), deck=('high', 'high'), enemy_deck=('low',))
        original = set(g.state.players[1].deck)
        source = self.play(g, ELEKK)
        result = self.result(g)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (3, 2))
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertIn(result.own.card.entity_id, original)
        self.assertEqual(g.state.players[1].hand, [result.own.card.entity_id])
        self.assertEqual(g.state.draw_history[-1].entity_id, result.own.card.entity_id)
        self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'], 'high')
        self.assertEqual(len(g.state.players[2].deck), 1)
        self.check(g)

    def test_real_elekk_loss_does_not_move_cards_or_attempt_a_draw(self):
        g = self.game(hand=(ELEKK,), deck=('low',), enemy_deck=('high',))
        before = [tuple(g.state.players[p].deck) for p in (1, 2)]
        self.play(g, ELEKK)
        self.assertEqual([tuple(g.state.players[p].deck) for p in (1, 2)], before)
        self.assertEqual(g.state.players[1].hand, [])
        self.assertEqual(g.state.draw_history, [])
        self.check(g)

    def test_full_hand_at_reward_burns_the_selected_card_without_reveal_failure(self):
        self.watch('fill', 'joust_resolved', lambda c: [AddToHand(c.player_id, 'low')])
        g = self.game(hand=(ELEKK,), board=('fill',), rules=Ruleset(max_hand=1))
        self.play(g, ELEKK)
        selected = self.result(g).own.card.entity_id
        self.assertEqual(g.state.entities[selected].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.draw_history[-1].outcome, 'burned')
        self.assertFalse(any(e.kind == 'card_revealed' and e.target_id == selected for e in g.events))
        self.check(g)

    def test_joust_event_choice_preserves_pair_costs_rng_and_original_result(self):
        self.watch('pause', 'joust_resolved', lambda c: [self.pause(c)])
        g = self.game(board=('pause',))
        self.play(g)
        result, rng = self.result(g), g.snapshot()['rng_state']
        self.assertEqual(self.armor(g), 0)
        self.resumed(g)
        self.assertEqual(self.result(g), result)
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(self.armor(g), 10)

    def test_result_callback_choice_roundtrips_its_pending_draw_and_disclosure(self):
        self.extras.append(('pause_reward', lambda c: [self.pause(c), *elekk_reward(c)], None))
        self.script('delayed', lambda c: [Joust(c.player_id, 'pause_reward', c.source_id)])
        g = self.game(hand=('delayed',))
        self.play(g, 'delayed')
        selected = self.result(g).own.card.entity_id
        self.assertEqual(g.state.entities[selected].zone, Zone.DECK)
        self.resumed(g)
        self.assertEqual(g.state.players[1].hand, [selected])
        self.assertEqual(g.observe(2)['players'][0]['hand'][0]['card_id'], 'high')

    def test_pending_joust_after_choice_samples_only_when_executed(self):
        self.script('pending', lambda c: [self.pause(c), Joust(c.player_id, 'report', c.source_id)])
        g = self.game(hand=('pending',))
        before = g.snapshot()['rng_state']
        self.play(g, 'pending')
        self.assertFalse(any(e.kind == 'joust_resolved' for e in g.events))
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.resumed(g)
        self.assertTrue(self.result(g).won)

    def test_later_deck_cost_change_does_not_recalculate_the_accepted_win(self):
        self.watch('discount', 'joust_resolved', lambda c: [BuffStoredCard(joust_result(c.event).own.card,
            cost=CostSpec(set_to=0, minimum=0)), self.pause(c)])
        g = self.game(board=('discount',))
        self.play(g)
        self.assertEqual(self.result(g).own.cost, 9)
        self.resumed(g)
        self.assertEqual(self.armor(g), 10)
        self.assertEqual(g.state.entities[self.result(g).own.card.entity_id].cost, 0)

    def test_failed_result_body_rolls_back_every_reveal_sample_and_payment(self):
        self.script('broken', lambda c: [Joust(c.player_id, 'break_result', c.source_id)])
        self.extras.append(('break_result', lambda c: [RandomDamage((c.state.players[1].hero_id, c.state.players[2].hero_id), 1),
            Summon(1, 'missing')], None))
        g = self.game(hand=('broken',))
        before = g.snapshot()
        with self.assertRaisesRegex(ValueError, 'unsupported card'):
            self.play(g, 'broken')
        self.assertEqual(g.snapshot(), before)

    def test_bad_callback_or_source_is_rejected_without_accepting_a_reveal(self):
        self.script('unknown_callback', lambda c: [Joust(c.player_id, 'missing', c.source_id)])
        self.script('unknown_source', lambda c: [Joust(c.player_id, source_id=99999)])
        for name in ('unknown_callback', 'unknown_source'):
            with self.subTest(name=name):
                g = self.game(hand=(name,))
                before = g.snapshot()
                with self.assertRaises(ValueError):
                    self.play(g, name)
                self.assertEqual(g.snapshot(), before)

    def test_two_joust_requests_each_accept_a_new_physical_pair(self):
        self.script('twice', lambda c: [Joust(c.player_id, 'report', c.source_id), Joust(c.player_id, 'report', c.source_id)])
        g = self.game(hand=('twice',), deck=('high', 'low'), enemy_deck=('middle',), seed=6)
        self.play(g, 'twice')
        events = [e for e in g.events if e.kind == 'joust_resolved']
        self.assertEqual(len(events), 2)
        self.assertEqual([joust_result(e).own.card.card_id for e in events], ['high', 'low'])
        self.assertEqual(self.armor(g), 11)
        self.check(g)

    def test_public_reveal_is_face_and_cost_only_and_does_not_track_hidden_deck_cards(self):
        g = self.game(deck=('high', 'middle'), enemy_deck=('low', 'low'), enemy_hand=('spell_high',))
        self.play(g)
        for player in (1, 2):
            row = next(e['joust'] for e in g.player_events(player) if e['kind'] == 'joust_resolved')
            self.assertEqual(set(row), {'kind', 'own', 'opponent', 'won'})
            for face in (row['own'], row['opponent']):
                self.assertEqual(set(face), {'player_id', 'card_id', 'cost'})
            knowledge = g.snapshot()['information']['players'][str(player)]
            for owner in (1, 2):
                for entity in g.state.players[owner].deck:
                    self.assertNotIn(str(entity), knowledge['refs'])
                    self.assertNotIn(str(entity), knowledge['known'])
        self.assertNotIn('spell_high', json.dumps(g.observe(1)))
        self.check(g)

    def test_later_unrelated_draw_does_not_inherit_joust_face_identity(self):
        self.script('draw_one', lambda c: [MoveCard(CardReference.capture(c.state.entities[c.state.players[2].deck[0]]),
            2, Zone.HAND, draw=True, source_id=c.source_id)])
        g = self.game(hand=('compare', 'draw_one'))
        self.play(g)
        self.play(g, 'draw_one')
        self.assertIsNone(g.observe(1)['players'][1]['hand'][0]['card_id'])
        self.check(g)

    def test_captured_hand_disclosure_skips_wrong_face_epoch_or_departed_card(self):
        for ref in (CardReference(99, 1, Zone.HAND, 'high', 0),):
            self.script('reveal_stale', lambda c, ref=ref: [RevealCapturedHandCard(ref)])
        g = self.game(hand=('reveal_stale',))
        self.play(g, 'reveal_stale')
        self.assertFalse(any(e.kind == 'card_revealed' for e in g.events))
        self.check(g)
        with self.assertRaises(ValueError):
            RevealCapturedHandCard(CardReference(1, 1, Zone.DECK, 'high', 0))

    def test_joust_shapes_only_support_real_minion_and_spell_profiles(self):
        for fields in (dict(player_id=True), dict(player_id=3), dict(player_id=1, kind='minion'),
                       dict(player_id=1, kind=CardType.WEAPON), dict(player_id=1, on_result='report'),
                       dict(player_id=1, on_result='', source_id=1), dict(player_id=1, target_id=2)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                Joust(**fields)

    def test_result_reader_rejects_unknown_version_wrong_owner_cost_and_winner(self):
        g = self.game()
        self.play(g)
        event = next(e for e in g.events if e.kind == 'joust_resolved')
        saved = event_to_dict(event)
        self.assertEqual(joust_result(event_from_dict(saved)), self.result(g))
        for part, field, value in ((None, 0, True), (None, 0, 2), (3, 1, 2), (3, 2, 'hand'), (3, 5, True), (3, 5, -1)):
            row = json.loads(json.dumps(saved))
            if part is None:
                row['data']['result'][field] = value
            else:
                row['data']['result'][part][field] = value
            with self.subTest(part=part, field=field, value=value), self.assertRaises(ValueError):
                event_from_dict(row)
        row = json.loads(json.dumps(saved))
        row['amount'] = 0
        with self.assertRaises(ValueError):
            event_from_dict(row)
        self.assertIsNone(joust_result(None))

    def test_snapshot_rejects_unknown_revealed_card_and_old_schema(self):
        g = self.game()
        self.play(g)
        s = g.snapshot()
        e = next(e for e in s['events'] if e['kind'] == 'joust_resolved')
        e['data']['result'][3][0] = 99999
        self.reject(s)
        s = g.snapshot()
        self.assertEqual(s['schema_version'], 265)
        s['schema_version'] = 152
        with self.assertRaisesRegex(SnapshotError, 'schemas 1 through 264'):
            Game.from_snapshot(s, registry(self.extras))


if __name__ == '__main__':
    unittest.main()
