"""Existing physical cards acquire the closed global-turn lifetime policy."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (BuffStoredCard, CardDefinition, CardType, CostSpec, EndTurn,
    Game, HandLifetime, MakeHandCardTemporary, PlayCard, PlayerSetup, Registry,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TriggerSpec, UpgradeHandCard, Zone)
from hs_sim.engine.effects import (ChoiceOption, Draw, EquipWeapon, GainArmor, ModifyCost,
    RandomDamage, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, MoveCard


def rehash(snapshot):
    snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})


class ExistingTemporaryTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('existing-temporary-v131-local')
        for definition in (
            CardDefinition('hero', 'hero', CardType.HERO, health=30),
            CardDefinition('plain', 'plain', CardType.MINION, cost=3, attack=2, health=4),
            CardDefinition('upgraded', 'upgraded', CardType.MINION, cost=4, attack=4, health=6),
        ):
            self.r.register_card(definition)

    def spell(self, name, behavior):
        self.r.register_behavior(name, behavior)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))

    def game(self, hand, board=(), enemy_hand=(), deck=('plain',)*8, enemy_deck=('plain',)*8):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, max_mana=10, mana=10),
            PlayerSetup('hero', hand=enemy_hand, deck=enemy_deck, max_mana=10, mana=10)), seed=131), self.r)

    def find(self, game, name, player=1):
        return next(i for i in game.state.players[player].hand if game.state.entities[i].card_id == name)

    def ref(self, context, name='plain', player=1):
        return CardReference.capture(next(context.state.entities[i] for i in context.state.players[player].hand
                                         if context.state.entities[i].card_id == name))

    def cast(self, game, name, player=1):
        game.apply(PlayCard(player, self.find(game, name, player)))

    def check(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.r).snapshot(), snapshot)

    def test_original_identity_modifications_and_cost_are_preserved(self):
        def modify(c):
            ref = self.ref(c)
            return [BuffStoredCard(ref, 3, 2), ModifyCost(ref.entity_id, CostSpec(delta=-2)),
                    MakeHandCardTemporary(ref, c.state.turn, source_id=c.source_id)]
        self.spell('mark', modify)
        g = self.game(('mark', 'plain'))
        ident = self.find(g, 'plain'); original = g.state.entities[ident]
        self.cast(g, 'mark'); entity = g.state.entities[ident]
        self.assertEqual((entity.id, entity.owner, entity.controller, entity.zone_epoch,
                          entity.origin_entity_id),
                         (original.id, original.owner, original.controller, original.zone_epoch,
                          original.origin_entity_id))
        self.assertEqual((entity.attack, entity.health, g.quote_cost(ident).amount), (5, 6, 1))
        self.assertEqual(len(entity.enchantments), 2)
        self.assertFalse(any(e.kind in ('card_created', 'card_drawn', 'card_added_to_hand') for e in g.events))
        self.check(g)

    def test_actual_draw_targets_both_players_without_rebuilding_cards(self):
        def after_draw(c):
            target = c.state.entities[c.event.target_id]
            return ([MakeHandCardTemporary(CardReference.capture(target), c.state.turn, source_id=c.source_id)]
                    if target.zone == Zone.HAND else [])
        self.r.register_behavior('after_draw', after_draw)
        self.r.register_card(CardDefinition('observer', 'observer', CardType.MINION, health=5,
            triggers=(TriggerSpec('card_drawn', 'after_draw'),)))
        self.spell('draw', lambda c: [Draw(1), Draw(2)])
        g = self.game(('draw',), board=('observer',))
        expected = [g.state.players[p].deck[0] for p in (1, 2)]
        self.cast(g, 'draw')
        self.assertEqual([e.target_id for e in g.events if e.kind == 'card_drawn'], expected)
        self.assertTrue(all(g.state.entities[i].hand_lifetime.expires_turn == 1 for i in expected))
        self.assertFalse(any(e.kind == 'card_created' for e in g.events))
        self.check(g)
        g.apply(EndTurn(1))
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in expected))
        self.assertFalse(g.state.death_history)
        self.assertFalse(any(e.kind == 'card_discarded' for e in g.events))
        self.check(g)

    def test_repeated_grants_never_extend_deadline_or_lower_floor(self):
        self.spell('mark', lambda c: [MakeHandCardTemporary(self.ref(c), 3, 1, c.source_id),
                                    MakeHandCardTemporary(self.ref(c), 2, 2, c.source_id),
                                    MakeHandCardTemporary(self.ref(c), 4, 0, c.source_id)])
        g = self.game(('mark', 'plain')); source = self.find(g, 'mark'); ident = self.find(g, 'plain')
        self.cast(g, 'mark')
        self.assertEqual(g.state.entities[ident].hand_lifetime, HandLifetime(source, 1, 2, 2))
        self.assertEqual(sum(e.kind == 'hand_card_made_temporary' for e in g.events), 2)
        g.apply(EndTurn(1)); self.assertIn(ident, g.state.players[1].hand)
        g.apply(EndTurn(2)); self.assertEqual(g.state.entities[ident].zone, Zone.GRAVEYARD)
        self.check(g)

    def test_current_copy_and_upgrade_keep_deadline_base_copy_is_permanent(self):
        self.spell('mark', lambda c: [MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id),
                                    CopyCard(self.ref(c), 1), CopyCard(self.ref(c), 1, mode='base'),
                                    UpgradeHandCard(self.ref(c), 'upgraded')])
        g = self.game(('mark', 'plain')); ident = self.find(g, 'plain'); self.cast(g, 'mark')
        hand = g.state.players[1].hand
        self.assertEqual(len(hand), 3)
        temporary = [i for i in hand if g.state.entities[i].hand_lifetime is not None]
        self.assertEqual(len(temporary), 2); self.assertIn(ident, temporary)
        self.assertEqual(g.state.entities[ident].card_id, 'upgraded')
        self.check(g); g.apply(EndTurn(1))
        self.assertTrue(all(g.state.entities[i].zone == Zone.GRAVEYARD for i in temporary))
        self.assertEqual(len(g.state.players[1].hand), 1); self.check(g)

    def test_other_player_hand_and_deck_keep_absolute_deadline(self):
        self.spell('mark', lambda c: [MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id),
                                    MoveCard(self.ref(c), 2, Zone.HAND)])
        self.spell('deck', lambda c: [MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id),
                                    MoveCard(self.ref(c), 1, Zone.DECK)])
        g = self.game(('mark', 'plain')); ident = self.find(g, 'plain'); self.cast(g, 'mark')
        self.assertIn(ident, g.state.players[2].hand); self.check(g)
        g.apply(EndTurn(1)); self.assertEqual(g.state.entities[ident].zone, Zone.GRAVEYARD); self.check(g)
        h = self.game(('deck', 'plain')); other = self.find(h, 'plain'); self.cast(h, 'deck')
        h.apply(EndTurn(1)); self.assertEqual(h.state.entities[other].zone, Zone.DECK)
        self.assertIsNone(h.state.entities[other].hand_lifetime); self.check(h)

    def test_played_marked_minion_survives_expiry_and_resets_on_return(self):
        self.spell('mark', lambda c: [MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id)])
        g = self.game(('mark', 'plain')); ident = self.find(g, 'plain'); self.cast(g, 'mark')
        g.apply(PlayCard(1, ident)); g.apply(EndTurn(1))
        self.assertIn(ident, g.state.players[1].board)
        self.assertIsNone(g.state.entities[ident].hand_lifetime)
        self.assertFalse(any(e.kind == 'card_expired' and e.target_id == ident for e in g.events))
        self.check(g)

    def test_known_departed_reference_restores_and_is_not_recaptured(self):
        def moved(c):
            ref = self.ref(c)
            return [MoveCard(ref, 1, Zone.DECK, position='top'), Draw(1),
                    RequestChoice(1, (ChoiceOption('ok', 'OK', (MakeHandCardTemporary(ref, 1),)),))]
        self.spell('move', moved)
        g = self.game(('move', 'plain')); ident = self.find(g, 'plain'); self.cast(g, 'move')
        self.assertIn(ident, g.state.players[1].hand); self.check(g)
        pending = g.state.pending_choice
        g = Game.from_snapshot(g.snapshot(), self.r)
        g.apply(SelectChoice(1, pending.id, ('ok',)))
        self.assertIsNone(g.state.entities[ident].hand_lifetime)
        self.assertTrue(any(e.kind == 'zone_target_skipped' and e.target_id == ident for e in g.events))
        self.check(g)

    def test_waiting_failure_rolls_back_rng_marker_and_queue(self):
        def wait(c):
            ref = self.ref(c)
            marker = MakeHandCardTemporary(ref, 1, source_id=c.source_id)
            return [RequestChoice(1, (
                ChoiceOption('bad', 'Bad', (marker, RandomDamage(tuple(c.state.players[p].hero_id for p in (1,2)), 1), EquipWeapon(1, 'plain'))),
                ChoiceOption('good', 'Good', (marker,))), source_id=c.source_id)]
        self.spell('wait', wait)
        g = self.game(('wait', 'plain')); ident = self.find(g, 'plain'); self.cast(g, 'wait')
        boundary = g.snapshot(); self.check(g); pending = g.state.pending_choice
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, pending.id, ('bad',)))
        self.assertEqual(g.snapshot(), boundary)
        self.assertIsNone(g.state.entities[ident].hand_lifetime)
        g.apply(SelectChoice(1, pending.id, ('good',)))
        self.assertEqual(g.state.entities[ident].hand_lifetime.expires_turn, 1); self.check(g)

    def test_private_event_and_visible_lifetime_do_not_leak_to_opponent(self):
        self.spell('mark', lambda c: [MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id)])
        g = self.game(('mark', 'plain')); self.cast(g, 'mark')
        own = g.observe(1); opponent = g.observe(2)
        self.assertIn('expires_turn', json.dumps(own))
        self.assertNotIn('expires_turn', json.dumps(opponent))
        self.assertEqual(sum(e['kind'] == 'hand_card_made_temporary' for e in g.player_events(1)), 1)
        self.assertFalse(any(e['kind'] == 'hand_card_made_temporary' for e in g.player_events(2)))
        self.check(g)

    def test_invalid_future_references_are_rejected_at_waiting_restore(self):
        self.spell('wait', lambda c: [RequestChoice(1, (ChoiceOption('ok', 'OK',
            (MakeHandCardTemporary(self.ref(c), 1, source_id=c.source_id),)),), source_id=c.source_id)])
        g = self.game(('wait', 'plain')); self.cast(g, 'wait'); original = g.snapshot()
        def objects(value):
            if isinstance(value, dict):
                if value.get('type') == 'hs_sim.engine.temporary_cards.MakeHandCardTemporary':
                    yield value
                for child in value.values(): yield from objects(child)
            elif isinstance(value, list):
                for child in value: yield from objects(child)
        self.assertTrue(list(objects(original['resolution_frame'])))
        for label, change in (
            ('future_entity', lambda row: row['fields']['card']['fields'].update(entity_id=999999)),
            ('future_epoch', lambda row: row['fields']['card']['fields'].update(zone_epoch=999999)),
            ('future_source', lambda row: row['fields'].update(source_id=999999)),
        ):
            with self.subTest(label=label):
                bad = deepcopy(original)
                for row in objects(bad['resolution_frame']): change(row)
                rehash(bad)
                with self.assertRaises(SnapshotError): Game.from_snapshot(bad, self.r)
        ref = CardReference.capture(g.state.entities[self.find(g, 'plain')])
        for values in ({'expires_turn': True}, {'expires_turn': 1, 'minimum_cost': True},
                       {'expires_turn': 1, 'source_id': True}):
            with self.assertRaises(ValueError): MakeHandCardTemporary(ref, **values)
        self.assertEqual(g.snapshot(), original)

