"""Physical hidden-zone changes, guarded choices, copies and private knowledge."""
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec, Game,
    PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, ResolutionLimitExceeded,
    Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import AddToHand, ChoiceOption, Draw, GainArmor, ModifyCost, RequestChoice
from hs_sim.engine.pools import GenerateFromPool, GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import (AddToDeck, CardReference, ChooseFromZone, CopyCard, DiscardCard,
    DiscardMatching, DrawMatching, MoveCard, ReorderZone, ShuffleDeck)


class ZoneTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('zone-tests-v1')
        meta = CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=())
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30,
            metadata=replace(meta, classes=(CardClass.MAGE,))))
        self.registry.register_behavior('death', lambda c: [GainArmor(c.player_id, 20)])
        self.registry.register_card(CardDefinition('a', 'a', CardType.MINION, cost=2, attack=1, health=3,
            deathrattle='death', metadata=replace(meta, tribes=('beast',))))
        self.registry.register_card(CardDefinition('b', 'b', CardType.SPELL, cost=3, metadata=meta))
        self.registry.register_card(CardDefinition('c', 'c', CardType.SPELL, cost=1, metadata=meta))
        self.registry.register_card(CardDefinition('weapon', 'weapon', CardType.WEAPON, cost=1, attack=2, durability=2, metadata=meta))

    def script(self, callback):
        self.registry.register_behavior('script', callback)
        self.registry.register_card(CardDefinition('script', 'script', CardType.SPELL, on_play='script'))

    def game(self, hand=('script',), deck=(), enemy_hand=(), enemy_deck=(), board=(), rules=None, seed=29, context=None):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, deck=deck, board=board, max_mana=10, mana=10),
            PlayerSetup('hero', hand=enemy_hand, deck=enemy_deck)), seed=seed, generation_context=context), self.registry, rules)

    def cast(self, g):
        return g.apply(PlayCard(1, next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == 'script')))

    def choose(self, g, index=0):
        choice = g.state.pending_choice
        return g.apply(SelectChoice(choice.player_id, choice.id, (choice.options[index].id,)))

    def cards(self, g, zone, player=1):
        s = g.state
        return [s.entities[i].card_id for i in getattr(s.players[player], zone)]

    def ref(self, c, zone='hand', index=0, player=1):
        return CardReference.capture(c.state.entities[getattr(c.state.players[player], zone)[index]])

    def replay(self, g):
        self.assertEqual(replay(build_replay(g), self.registry).snapshot(), g.snapshot())

    def test_invalid_zone_payloads_are_rejected(self):
        card = CardReference(1, 1, Zone.HAND, 'a', 0)
        invalid = [lambda: CardReference(True, 1, Zone.HAND, 'a', 0), lambda: CardReference(1, 1, Zone.BOARD, 'a', 0),
            lambda: AddToDeck(1, 'a', position=True), lambda: AddToDeck(1, 'a', position=-1),
            lambda: AddToDeck(1, 'a', position='middle'), lambda: CopyCard(card, 1, mode='guess'),
            lambda: MoveCard(card, 1, Zone.HAND, draw=True), lambda: MoveCard(card, 1, Zone.BOARD),
            lambda: DiscardCard(replace(card, zone=Zone.DECK)), lambda: DiscardCard(card, reveal=1),
            lambda: ReorderZone(1, Zone.DECK, (1, 1)), lambda: ReorderZone(1, Zone.DECK, [1]),
            lambda: DrawMatching(1, PoolQuery(), 'guess'), lambda: DiscardMatching(1, count=True),
            lambda: ChooseFromZone(1, 2, Zone.DECK, operation='draw', distinct='entity'),
            lambda: ChooseFromZone(1, 1, Zone.DECK, operation='discard', distinct='entity'),
            lambda: ChooseFromZone(1, 1, Zone.HAND, operation='top', distinct='entity'),
            lambda: ChooseFromZone(1, 1, Zone.DECK, operation='take', distinct='card')]
        for fn in invalid:
            with self.subTest(fn=fn), self.assertRaises(ValueError): fn()

    def test_generated_deck_insertion_preserves_existing_order_and_has_new_ids(self):
        self.script(lambda c: [AddToDeck(1, 'c', 'top'), AddToDeck(1, 'weapon', 'bottom'), AddToDeck(1, 'a', 2)])
        g = self.game(deck=('a', 'b')); original = list(g.state.players[1].deck); self.cast(g)
        self.assertEqual(self.cards(g, 'deck'), ['c', 'a', 'a', 'b', 'weapon'])
        self.assertEqual([i for i in g.state.players[1].deck if i in original], original)
        self.assertEqual(len(set(g.state.players[1].deck)), 5); self.replay(g)

    def test_random_insertion_is_reproducible_and_not_a_full_shuffle(self):
        self.script(lambda c: [AddToDeck(1, 'c')])
        g = self.game(deck=('a', 'b', 'weapon')); twin = g.clone(); old = g.state.players[1].deck
        self.cast(g); self.cast(twin)
        self.assertEqual(g.snapshot(), twin.snapshot())
        self.assertEqual([i for i in g.state.players[1].deck if i in old], old)
        self.replay(g)

    def test_bad_insertion_unknown_card_or_hero_rolls_back_rng_and_state(self):
        for effect in (AddToDeck(1, 'a', 10), AddToDeck(1, 'missing'), AddToDeck(1, 'hero')):
            with self.subTest(effect=effect):
                self.setUp(); self.script(lambda c: [AddToDeck(1, 'a'), effect])
                g = self.game(); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.cast(g)
                self.assertEqual(g.snapshot(), before)

    def test_deck_generation_events_do_not_reveal_identity_position_or_ids(self):
        self.script(lambda c: [AddToDeck(2, 'a', 'top')])
        g = self.game(); self.cast(g)
        for player in (1, 2):
            event = next(e for e in g.player_events(player) if e['kind'] == 'card_added_to_deck')
            self.assertIsNone(event['target']); self.assertNotIn('position', event)
            self.assertEqual(g.observe(player)['players'][1]['deck_count'], 1)
            self.assertFalse(g.observe(player)['players'][1]['known_graveyard'])

    def test_generate_from_versioned_pool_can_insert_into_deck(self):
        self.registry.register_pool_card(PoolCard.from_definition(self.registry.card('a')))
        self.registry.register_pool(PoolDefinition('p', 'v1', 't', 'experimental', (PoolMember('a'),)))
        self.script(lambda c: [GenerateFromPool(1, 'p', count=2, destination='deck', position='top')])
        g = self.game(deck=('b',), context=GenerationContext('t', 'experimental')); self.cast(g)
        self.assertEqual(self.cards(g, 'deck'), ['a', 'a', 'b']); self.replay(g)

    def test_move_from_enemy_hand_keeps_id_owner_modifiers_and_changes_controller(self):
        self.script(lambda c: [ModifyCost(self.ref(c, player=2).entity_id, CostSpec(delta=-2)),
            MoveCard(self.ref(c, player=2), 1, Zone.HAND)])
        g = self.game(enemy_hand=('b',)); target = g.state.players[2].hand[0]; self.cast(g)
        entity = g.state.entities[target]
        self.assertEqual((entity.owner, entity.controller, entity.zone, entity.cost), (2, 1, Zone.HAND, 1))
        self.assertEqual(g.state.players[1].hand, [target]); self.assertFalse(g.state.players[2].hand)
        self.assertFalse(any(e.kind == 'card_drawn' for e in g.events)); self.replay(g)

    def test_hand_to_deck_move_can_preserve_or_reset_cost(self):
        for reset, expected in ((False, 1), (True, 3)):
            with self.subTest(reset=reset):
                self.setUp(); self.script(lambda c: [ModifyCost(self.ref(c).entity_id, CostSpec(delta=-2)),
                    MoveCard(self.ref(c), 1, Zone.DECK, 'top', reset=reset), Draw(1)])
                g = self.game(hand=('script', 'b')); target = g.state.players[1].hand[1]; self.cast(g)
                self.assertEqual(g.state.players[1].hand, [target]); self.assertEqual(g.state.entities[target].cost, expected)
                self.replay(g)

    def test_deck_entry_retires_old_handles_before_later_draw(self):
        self.script(lambda c: [MoveCard(self.ref(c), 1, Zone.DECK, 'top'), Draw(1)])
        g = self.game(hand=('script', 'b')); old = g.observe(1)['players'][0]['hand'][1]['ref']; self.cast(g)
        new = g.observe(1)['players'][0]['hand'][0]['ref']; self.assertNotEqual(old, new)
        self.assertIsNone(next(e for e in g.player_events(1) if e['kind'] == 'card_moved_to_deck')['target'])

    def test_move_to_full_hand_burns_original_without_death_or_corpse(self):
        self.script(lambda c: [AddToHand(1, 'c'), MoveCard(self.ref(c, 'deck'), 1, Zone.HAND, draw=True)])
        g = self.game(hand=('script',) + ('b',) * 9, deck=('a',)); target = g.state.players[1].deck[0]; self.cast(g)
        self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(len(g.state.players[1].hand), 10); self.assertFalse(g.state.death_history)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertEqual(sum(g.state.players[1].resources.values()), 0)

    def test_move_to_same_full_hand_is_noop(self):
        self.script(lambda c: [AddToHand(1, 'c'), MoveCard(self.ref(c), 1, Zone.HAND)])
        g = self.game(hand=('script',) + ('b',) * 9); target = g.state.players[1].hand[1]; self.cast(g)
        self.assertIn(target, g.state.players[1].hand)
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events))

    def test_stale_reference_cannot_follow_a_card_to_another_zone_or_controller(self):
        self.script(lambda c: [MoveCard(self.ref(c), 2, Zone.DECK), DiscardCard(self.ref(c)), CopyCard(self.ref(c), 1)])
        g = self.game(hand=('script', 'a')); self.cast(g)
        self.assertEqual(self.cards(g, 'deck', 2), ['a']); self.assertFalse(g.state.players[1].hand)
        self.assertEqual(sum(e.kind == 'zone_target_skipped' for e in g.events), 2)
        self.assertFalse(any(e['kind'] == 'zone_target_skipped' for e in g.player_events(1)))

    def test_unknown_definition_in_reference_is_an_error_not_a_stale_noop(self):
        self.script(lambda c: [CopyCard(replace(self.ref(c), card_id='missing'), 1)])
        g = self.game(hand=('script', 'a')); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'unsupported card definition'): self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_current_copy_gets_new_entity_and_attachments_base_copy_drops_modifiers(self):
        self.script(lambda c: [ModifyCost(self.ref(c).entity_id, CostSpec(delta=-2)),
            CopyCard(self.ref(c), 1), CopyCard(self.ref(c), 1, mode='base')])
        g = self.game(hand=('script', 'b')); original = g.state.players[1].hand[1]; self.cast(g)
        entities = [g.state.entities[i] for i in g.state.players[1].hand]
        self.assertEqual([e.cost for e in entities], [1, 1, 3]); self.assertEqual(len({e.id for e in entities}), 3)
        self.assertEqual([e.origin_entity_id for e in entities[1:]], [original, original])
        self.assertNotEqual(entities[0].enchantments[0].id, entities[1].enchantments[0].id)
        self.replay(g)

    def test_copy_to_enemy_deck_assigns_new_owner_and_preserves_original(self):
        self.script(lambda c: [CopyCard(self.ref(c), 2, Zone.DECK, position='top')])
        g = self.game(hand=('script', 'weapon'), enemy_deck=('b',)); original = g.state.players[1].hand[1]; self.cast(g)
        copy = g.state.entities[g.state.players[2].deck[0]]
        self.assertEqual((copy.owner, copy.controller, copy.durability), (2, 2, 2))
        self.assertNotEqual(copy.id, original); self.assertEqual(g.state.players[1].hand, [original]); self.replay(g)

    def test_copy_to_full_hand_burns_only_new_entity(self):
        self.script(lambda c: [AddToHand(1, 'c'), CopyCard(self.ref(c), 1)])
        g = self.game(hand=('script',) + ('a',) * 9); original = g.state.players[1].hand[1]; self.cast(g)
        self.assertIn(original, g.state.players[1].hand)
        burned = next(e.target_id for e in g.events if e.kind == 'card_burned')
        self.assertNotEqual(burned, original); self.assertEqual(g.state.entities[burned].origin_entity_id, original)

    def test_discard_public_and_private_visibility_and_no_death(self):
        for reveal in (True, False):
            with self.subTest(reveal=reveal):
                self.setUp(); self.script(lambda c: [DiscardCard(self.ref(c), reveal=reveal)])
                g = self.game(hand=('script', 'a')); self.cast(g)
                event = next(e for e in g.player_events(2) if e['kind'] == 'card_discarded')
                self.assertEqual(event['target']['card_id'], 'a' if reveal else None)
                self.assertEqual(next(e for e in g.player_events(1) if e['kind'] == 'card_discarded')['target']['card_id'], 'a')
                self.assertFalse(g.state.death_history); self.assertEqual(sum(g.state.players[1].resources.values()), 0)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0); self.replay(g)

    def test_filtered_draw_selects_physical_card_and_preserves_cost_modifier(self):
        self.script(lambda c: [ModifyCost(self.ref(c, 'deck', 1).entity_id, CostSpec(delta=-2)),
            DrawMatching(1, PoolQuery(kinds=(CardType.SPELL,), min_cost=3), 'skip', selection='first')])
        g = self.game(deck=('a', 'b', 'c')); target = g.state.players[1].deck[1]; self.cast(g)
        self.assertEqual(g.state.players[1].hand, [target]); self.assertEqual(g.state.entities[target].cost, 1)
        self.assertEqual(self.cards(g, 'deck'), ['a', 'c']); self.replay(g)

    def test_filtered_draw_missing_match_does_not_draw_a_fallback(self):
        self.script(lambda c: [DrawMatching(1, PoolQuery(kinds=(CardType.SPELL,)), 'fatigue', count=2)])
        g = self.game(deck=('a',)); rng = g.snapshot()['rng_state']; self.cast(g)
        self.assertEqual(self.cards(g, 'deck'), ['a']); self.assertEqual(g.state.players[1].fatigue, 0)
        self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_empty_deck_policy_is_explicit_and_zero_count_never_fatigues(self):
        for policy, count, fatigue, health in (('skip', 2, 0, 30), ('fatigue', 2, 2, 27), ('fatigue', 0, 0, 30)):
            with self.subTest(policy=policy, count=count):
                self.setUp(); self.script(lambda c: [DrawMatching(1, PoolQuery(), policy, count=count)])
                g = self.game(); self.cast(g)
                self.assertEqual(g.state.players[1].fatigue, fatigue)
                self.assertEqual(g.state.entities[g.state.players[1].hero_id].health, health); self.replay(g)

    def test_repeated_filtered_draw_requeries_after_reactions(self):
        self.registry.register_behavior('insert', lambda c: [AddToDeck(1, 'c', 'top')])
        self.registry.register_card(CardDefinition('observer', 'observer', CardType.MINION, health=2,
            triggers=(TriggerSpec('card_drawn', 'insert'),)))
        self.script(lambda c: [DrawMatching(1, PoolQuery(kinds=(CardType.SPELL,)), 'skip', count=2, selection='first')])
        g = self.game(deck=('a', 'b'), board=('observer',)); self.cast(g)
        self.assertEqual(self.cards(g, 'hand'), ['b', 'c']); self.assertEqual(self.cards(g, 'deck'), ['c', 'a'])
        self.replay(g)

    def test_random_discard_is_reproducible_and_never_discards_the_played_spell(self):
        self.script(lambda c: [DiscardMatching(1, count=2)])
        g = self.game(hand=('script', 'a', 'b', 'c')); twin = g.clone(); self.cast(g); self.cast(twin)
        self.assertEqual(g.snapshot(), twin.snapshot()); self.assertEqual(len(g.state.players[1].hand), 1)
        discarded = [g.state.entities[e.target_id].card_id for e in g.events if e.kind == 'card_discarded']
        self.assertEqual(len(discarded), 2); self.assertNotIn('script', discarded); self.replay(g)

    def test_empty_and_filtered_discard_do_not_fail_or_discard_nonmatching_card(self):
        self.script(lambda c: [DiscardMatching(1, PoolQuery(kinds=(CardType.MINION,)), count=3)])
        g = self.game(hand=('script', 'b')); rng = g.snapshot()['rng_state']; self.cast(g)
        self.assertEqual(self.cards(g, 'hand'), ['b']); self.assertEqual(g.snapshot()['rng_state'], rng)

    def test_shuffle_and_reorder_preserve_entities_and_are_private(self):
        self.script(lambda c: [ShuffleDeck(1), ReorderZone(1, Zone.DECK, tuple(reversed(c.state.players[1].deck)))])
        g = self.game(deck=('a', 'b', 'c')); original = g.state.players[1].deck; self.cast(g)
        self.assertEqual(g.state.players[1].deck, list(reversed(original)))
        self.assertEqual(self.cards(g, 'deck'), ['c', 'b', 'a'])
        self.assertTrue(all(e['target'] is None for e in g.player_events(2) if e['kind'] in ('deck_shuffled', 'deck_reordered')))
        self.replay(g)

    def test_hand_reorder_uses_existing_handles_and_exact_permutation(self):
        self.script(lambda c: [ReorderZone(1, Zone.HAND, tuple(reversed(c.state.players[1].hand)))])
        g = self.game(hand=('script', 'a', 'b')); refs = [v['ref'] for v in g.observe(1)['players'][0]['hand'][1:]]
        self.cast(g); self.assertEqual(self.cards(g, 'hand'), ['b', 'a'])
        self.assertEqual([v['ref'] for v in g.observe(1)['players'][0]['hand']], refs[::-1])
        self.replay(g)

    def test_wrong_reorder_permutation_rolls_back_earlier_randomness(self):
        self.script(lambda c: [ShuffleDeck(1), ReorderZone(1, Zone.DECK, ())])
        g = self.game(deck=('a', 'b')); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'permutation'): self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_deck_choice_copies_definition_without_removing_original_or_revealing_order(self):
        self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK, sample_size=None)])
        g = self.game(deck=('c', 'b', 'b')); old = g.state.players[1].deck; self.cast(g)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options], ['b', 'c'])
        self.assertTrue(all(o.entity_id is None for o in g.state.pending_choice.options))
        self.choose(g); self.assertEqual(g.state.players[1].deck, old); self.assertEqual(self.cards(g, 'hand'), ['b'])
        self.replay(g)

    def test_physical_choice_draws_one_copy_and_preserves_its_modifiers(self):
        self.script(lambda c: [ModifyCost(self.ref(c, 'deck').entity_id, CostSpec(delta=-2)),
            ChooseFromZone(1, 1, Zone.DECK, operation='draw', distinct='entity', sample_size=None)])
        g = self.game(deck=('b', 'b')); old = g.state.players[1].deck; self.cast(g)
        self.assertEqual(len(g.state.pending_choice.options), 2); self.choose(g)
        self.assertEqual(g.state.players[1].hand, [old[0]]); self.assertEqual(g.state.entities[old[0]].cost, 1)
        self.assertEqual(g.state.players[1].deck, [old[1]]); self.replay(g)

    def test_current_copy_choice_collapses_ids_and_preserves_selected_copy_state(self):
        self.script(lambda c: [ModifyCost(self.ref(c, 'deck').entity_id, CostSpec(delta=-2)),
            ChooseFromZone(1, 1, Zone.DECK, operation='copy_current', sample_size=None)])
        g = self.game(deck=('b', 'b')); self.cast(g)
        self.assertEqual(len(g.state.pending_choice.options), 1)
        source = g._frame.options[0].effects[0].card.entity_id
        expected = g.state.entities[source].cost; pending = g.snapshot()
        restored = Game.from_snapshot(pending, self.registry)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(len(g.state.players[1].deck), 2)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].cost, expected)
        self.assertEqual(g.snapshot()['rng_state'], pending['rng_state']); self.replay(g)

    def test_hand_choice_reveals_only_offered_faces_to_chooser(self):
        self.script(lambda c: [ChooseFromZone(1, 2, Zone.HAND, sample_size=1)])
        g = self.game(enemy_hand=('a', 'b', 'c')); self.cast(g)
        view = g.observe(1); known = [v for v in view['players'][1]['hand'] if v['card_id'] is not None]
        self.assertEqual(len(known), 1); self.assertEqual(known[0]['card_id'], view['pending_choice']['options'][0]['card_id'])
        self.assertEqual(g.observe(2)['pending_choice'], {'player_id': 1})
        self.choose(g); self.assertEqual(len(g.state.players[2].hand), 3)
        self.assertEqual(self.cards(g, 'hand'), [known[0]['card_id']]); self.replay(g)

    def test_opponent_choice_secrets_do_not_change_observation_or_revision(self):
        self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK)])
        a = self.game(deck=('b', 'b')); b = self.game(deck=('a', 'c'))
        self.cast(a); self.cast(b)
        self.assertEqual(a.for_player(2).observe(), b.for_player(2).observe())
        self.assertEqual(a.player_events(2), b.player_events(2))

    def test_nonactive_player_submits_private_zone_choice_through_player_port(self):
        self.script(lambda c: [ChooseFromZone(2, 1, Zone.DECK)])
        g = self.game(deck=('a', 'b')); self.cast(g)
        self.assertEqual(g.for_player(1).legal_actions()['actions'], [{'type': 'concede'}])
        p = g.for_player(2); available = p.legal_actions()
        self.assertTrue(p.submit({'revision': available['revision'], 'action': available['actions'][0]})['accepted'])
        self.assertEqual(len(g.state.players[2].hand), 1); self.replay(g)

    def test_departed_choice_target_is_skipped_after_request_reaction(self):
        self.registry.register_behavior('depart', lambda c: [DiscardCard(self.ref(c))])
        self.registry.register_card(CardDefinition('observer', 'observer', CardType.MINION, health=2,
            triggers=(TriggerSpec('choice_requested', 'depart'),)))
        self.script(lambda c: [ChooseFromZone(1, 1, Zone.HAND, operation='discard', distinct='entity')])
        g = self.game(hand=('script', 'a'), board=('observer',)); self.cast(g); self.choose(g)
        self.assertEqual(sum(e.kind == 'card_discarded' for e in g.events), 1)
        self.assertEqual(sum(e.kind == 'zone_target_skipped' for e in g.events), 1); self.replay(g)

    def test_choice_can_move_selected_deck_card_to_top_or_bottom(self):
        for operation, expected in (('top', ['b', 'a', 'c']), ('bottom', ['a', 'c', 'b'])):
            with self.subTest(operation=operation):
                self.setUp(); self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK,
                    operation=operation, distinct='entity', sample_size=None)])
                g = self.game(deck=('a', 'b', 'c')); self.cast(g); self.choose(g, 1)
                self.assertEqual(self.cards(g, 'deck'), expected); self.replay(g)

    def test_empty_short_and_oversized_zone_choices(self):
        self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK), GainArmor(1, 2)])
        g = self.game(); rng = g.snapshot()['rng_state']; self.cast(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(g.snapshot()['rng_state'], rng)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        g = self.game(deck=('a',)); self.cast(g); self.assertEqual(len(g.state.pending_choice.options), 1)
        self.setUp(); self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK, operation='draw', distinct='entity', sample_size=None)])
        g = self.game(deck=('a',) * 33); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_zone_effects_survive_prior_choice_continuation_and_replay(self):
        self.script(lambda c: [RequestChoice(1, (ChoiceOption('go', 'Go'),)), CopyCard(self.ref(c), 1, Zone.DECK),
            DiscardCard(self.ref(c)), DrawMatching(1, PoolQuery(), 'skip'), ChooseFromZone(1, 1, Zone.HAND)])
        g = self.game(hand=('script', 'a')); self.cast(g)
        restored = Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.registry)
        for branch in (g, restored): self.choose(branch); self.choose(branch)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.replay(g)

    def test_unknown_filter_metadata_is_not_silently_ignored(self):
        self.registry.register_card(CardDefinition('unknown', 'unknown', CardType.SPELL))
        self.script(lambda c: [ChooseFromZone(1, 1, Zone.DECK, PoolQuery(rarities=(Rarity.RARE,)))])
        g = self.game(deck=('unknown',)); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'Unknown candidate metadata'): self.cast(g)
        self.assertEqual(g.snapshot(), before)

    def test_old_snapshot_rejected_and_tampered_reference_rejected_by_frame_codec(self):
        self.script(lambda c: [RequestChoice(1, (ChoiceOption('go', 'Go'),)), CopyCard(self.ref(c), 1)])
        g = self.game(hand=('script', 'a')); self.cast(g)
        snapshot = g.snapshot(); snapshot['schema_version'] = 13
        with self.assertRaises(SnapshotError): Game.from_snapshot(snapshot, self.registry)
        from hs_sim.engine.continuations import FrameCodec
        codec = FrameCodec(g.mechanics, self.registry)
        encoded = codec.encode(CardReference(1, 1, Zone.HAND, 'a', 0)); encoded['fields']['player_id'] = 3
        with self.assertRaises(ValueError): codec.decode(encoded)

    def test_zone_counts_and_source_validation_are_bounded(self):
        for effect in (DrawMatching(1, PoolQuery(), 'skip', count=1001), DiscardMatching(1, count=1001), AddToDeck(1, 'a', source_id=9999)):
            with self.subTest(effect=effect):
                self.setUp(); self.script(lambda c: [effect]); g = self.game(); before = g.snapshot()
                with self.assertRaises(ResolutionError): self.cast(g)
                self.assertEqual(g.snapshot(), before)


class RealZoneCardTests(unittest.TestCase):
    def game(self, hand, deck=(), enemy_hand=()):
        from hs_sim.engine.representative import build_registry
        return Game.from_scenario(Scenario((PlayerSetup('test.hero', hand=hand, deck=deck, max_mana=10, mana=10),
            PlayerSetup('test.hero', hand=enemy_hand)), seed=29), build_registry())

    def cast(self, g, target=None):
        g.apply(PlayCard(1, g.state.players[1].hand[0], target))

    def replay(self, g):
        from hs_sim.engine.representative import build_registry
        self.assertEqual(replay(build_replay(g), build_registry()).snapshot(), g.snapshot())

    def test_shadow_visions_can_copy_another_shadow_visions_in_deck(self):
        g = self.game(('UNG_029',), ('UNG_029', 'UNG_029', 'CS2_029', 'CS2_182'))
        old = g.state.players[1].deck; self.cast(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options}, {'UNG_029', 'CS2_029'})
        choice = g.state.pending_choice; option = next(o for o in choice.options if o.card_id == 'UNG_029')
        g.apply(SelectChoice(1, choice.id, (option.id,)))
        self.assertEqual(g.state.players[1].deck, old)
        self.assertEqual(g.state.entities[g.state.players[1].hand[0]].card_id, 'UNG_029'); self.replay(g)

    def test_shadow_visions_no_spells_does_not_generate_from_global_pool(self):
        g = self.game(('UNG_029',), ('CS2_182',)); self.cast(g)
        self.assertIsNone(g.state.pending_choice); self.assertFalse(g.state.players[1].hand); self.replay(g)

    def test_dead_mans_hand_copies_remaining_hand_and_keeps_originals(self):
        g = self.game(('ICC_091', 'CS2_182', 'CS2_029', 'ICC_091'), ('CS2_179',))
        hand = g.state.players[1].hand[1:]; self.cast(g)
        self.assertEqual(g.state.players[1].hand, hand)
        self.assertEqual(len(g.state.players[1].deck), 4)
        copies = [g.state.entities[i] for i in g.state.players[1].deck if g.state.entities[i].origin_entity_id is not None]
        self.assertEqual({e.origin_entity_id for e in copies}, set(hand)); self.assertEqual(len(copies), 3); self.replay(g)

    def test_soulfire_deals_damage_then_discards_another_hand_card(self):
        g = self.game(('EX1_308', 'CS2_182', 'CS2_029')); self.cast(g, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertEqual(len(g.state.players[1].hand), 1)
        kinds = [e.kind for e in g.events]; self.assertLess(kinds.index('damage_dealt'), kinds.index('card_discarded'))
        self.replay(g)

    def test_soulfire_works_with_no_other_hand_cards(self):
        g = self.game(('EX1_308',)); self.cast(g, g.state.players[2].hero_id)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 26)
        self.assertFalse(any(e.kind == 'card_discarded' for e in g.events)); self.replay(g)


if __name__ == '__main__':
    unittest.main()
