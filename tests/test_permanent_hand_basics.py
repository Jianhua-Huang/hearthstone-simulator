"""One real permanent hand-copy source using existing removal and copy effects."""
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, PlayCard,
    PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, Draw,
    ModifyCost, RequestChoice, RevealHandCard)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import AddToDeck, CardReference, CopyCard, ReorderZone
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, registry as opening_registry

AZALINA = 'GIL_198'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/permanent-hand-basics.json'
PIN = '2d3aac7694d137bdbe3d4c8a52ca52097977df43b4276edd62e81d8447e488b6'


def evidence():
    raw = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(raw) != PIN:
        raise ValueError('Complete permanent hand raw changed')
    record = raw['records'][0]
    if record['id'] != AZALINA or canonical_digest(record['data']) != record['data_sha256']:
        raise ValueError('Original Azalina row changed')
    return record['data']


def replace_hand(c):
    # Capture the two ordered groups once. Each ordinary copy keeps its existing
    # reference guard and checkpoint; the complete copied group is not atomic.
    held = tuple(CardReference.capture(c.state.entities[eid])
        for eid in c.state.players[c.player_id].hand)
    other = tuple(CardReference.capture(c.state.entities[eid])
        for eid in c.state.players[3 - c.player_id].hand)
    return (RemoveFromGame(held, c.source_id),) + tuple(
        CopyCard(ref, c.player_id, source_id=c.source_id) for ref in other)


def registry(scripts=(), *, watch=None, fault=False):
    r = opening_registry()
    row = evidence()
    def azalina(c):
        work = replace_hand(c)
        return work + ((AddToDeck(c.player_id, 'card.11'),
            AddToHand(c.player_id, 'missing.permanent.hand')) if fault else ())
    r.register_behavior('azalina', azalina)
    r.register_card(CardDefinition(AZALINA, row['name'], CardType.MINION,
        cost=row['cost'], attack=row['attack'], health=row['health'], battlecry='azalina',
        metadata=metadata(rarity=Rarity.LEGENDARY, tribes=('undead',))))
    for name, callback in scripts:
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL,
            on_play=name, metadata=metadata()))
    if watch:
        event, card_id, callback = watch
        def filtered(c):
            if card_id is not None and (c.event.target_id is None or
                    c.state.entities[c.event.target_id].card_id != card_id):
                return ()
            return callback(c)
        r.register_behavior('watch', filtered)
        r.register_card(CardDefinition('watch', 'Interpreter observer', CardType.MINION,
            health=4, triggers=(TriggerSpec(event, 'watch'),), metadata=metadata()))
    return r


class PermanentHandTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.options = {}

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def game(self, hand=(AZALINA, 'card.1', 'card.2'), *,
            enemy_hand=('card.3', 'card.4'), board=(), actor=1, deck=('card.9',) * 5):
        own = PlayerSetup('mage.hero', hand=hand, deck=deck, board=board,
            mana=10, max_mana=10)
        other = PlayerSetup('warrior.hero', hand=enemy_hand, deck=('card.10',) * 5,
            mana=10, max_mana=10)
        players = (own, other) if actor == 1 else (other, own)
        return Game.from_scenario(Scenario(players, seed=79, active_player=actor),
            registry(self.scripts, **self.options))

    def play(self, g, cid=AZALINA, actor=1):
        source = next(eid for eid in g.state.players[actor].hand
            if g.state.entities[eid].card_id == cid)
        g.apply(PlayCard(actor, source))
        return source

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry(self.scripts, **self.options))
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, **self.options)).snapshot(), saved)
        return restored

    def cards(self, g, player=1):
        return [g.state.entities[eid].card_id for eid in g.state.players[player].hand]

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('ok',)))

    def watch(self, event, card=None):
        self.options['watch'] = (event, card, lambda c:
            (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue'),), c.source_id),))

    def test_real_azalina_permanently_replaces_hand_without_moving_opponent(self):
        g = self.game()
        held = tuple(g.state.players[1].hand[1:])
        other = tuple(g.state.players[2].hand)
        rng = g._rng.getstate()
        source = self.play(g)
        self.assertEqual(self.cards(g), ['card.3', 'card.4'])
        self.assertEqual(tuple(g.state.players[2].hand), other)
        self.assertEqual(tuple(g.state.entities[eid].origin_entity_id
            for eid in g.state.players[1].hand), other)
        self.assertEqual(tuple(g.state.players[1].setaside), held)
        self.assertEqual(g.state.players[1].board, [source])
        self.assertEqual(g.state.players[1].mana, 3)
        self.assertFalse(g.state.temporary_hands)
        self.assertEqual(g._rng.getstate(), rng)
        self.portable(g)

    def test_complete_raw_and_actual_battlecry_definition_are_pinned(self):
        row = evidence()
        original = next(r for r in json.loads((FIXTURE.parents[1] /
            'extracted/cards.json').read_text(encoding='utf-8')) if r['id'] == AZALINA)
        self.assertEqual(row, original)
        self.assertEqual((row['cost'], row['attack'], row['health']), (7, 3, 3))
        self.assertIn('copy of', row['text_en'])
        self.assertIn('Replace your hand', row['text_en'])
        card = registry().card(AZALINA)
        self.assertEqual(card.metadata.tribes, ('undead',))
        self.assertEqual(card.metadata.rarity, Rarity.LEGENDARY)

    def test_empty_other_hand_permanently_removes_all_remaining_originals(self):
        g = self.game(enemy_hand=())
        held = g.state.players[1].hand[1:]
        self.play(g)
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(g.state.players[1].setaside, held)
        g.apply(EndTurn(1))
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(g.state.players[1].setaside, held)
        self.portable(g)

    def test_source_is_already_played_when_remaining_hand_is_empty(self):
        g = self.game((AZALINA,))
        source = self.play(g)
        self.assertEqual(self.cards(g), ['card.3', 'card.4'])
        self.assertFalse(g.state.players[1].setaside)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertFalse(any(e.kind == 'cards_removed_from_game' for e in g.events))
        self.portable(g)

    def test_full_other_hand_fits_after_full_original_hand_is_removed(self):
        g = self.game((AZALINA,) + ('card.1',) * 9, enemy_hand=('card.3',) * 10)
        held = g.state.players[1].hand[1:]
        self.play(g)
        self.assertEqual(len(g.state.players[1].hand), 10)
        self.assertEqual(g.state.players[1].setaside, held)
        self.assertFalse(any(e.kind == 'card_burned' for e in g.events))
        self.portable(g)

    def test_identical_faces_still_have_distinct_original_and_copy_identities(self):
        g = self.game((AZALINA, 'card.1', 'card.1'), enemy_hand=('card.1', 'card.1'))
        held = g.state.players[1].hand[1:]
        other = g.state.players[2].hand
        self.play(g)
        copies = g.state.players[1].hand
        self.assertEqual(len(set(held + other + copies)), 6)
        self.assertEqual([g.state.entities[eid].origin_entity_id for eid in copies], other)
        self.assertEqual(g.state.players[1].setaside, held)
        self.portable(g)

    def test_current_opponent_hand_order_is_copied(self):
        self.script('order', lambda c: (ReorderZone(2, Zone.HAND,
            tuple(reversed(c.state.players[2].hand))),))
        g = self.game(('order', AZALINA, 'card.1'))
        self.play(g, 'order')
        other = g.state.players[2].hand
        self.play(g)
        self.assertEqual(self.cards(g), ['card.4', 'card.3'])
        self.assertEqual([g.state.entities[eid].origin_entity_id
            for eid in g.state.players[1].hand], other)
        self.portable(g)

    def test_current_cost_copy_allocates_independent_attachments(self):
        self.script('cost', lambda c: (ModifyCost(c.state.players[2].hand[0],
            CostSpec(delta=-1)),))
        g = self.game(('cost', AZALINA, 'card.1'))
        self.play(g, 'cost')
        original = g.state.players[2].hand[0]
        self.play(g)
        copied = g.state.players[1].hand[0]
        a, b = g.state.entities[original], g.state.entities[copied]
        self.assertEqual((a.cost, b.cost), (0, 0))
        self.assertEqual(len(a.enchantments), 1)
        self.assertEqual(len(b.enchantments), 1)
        self.assertNotEqual(a.enchantments[0].id, b.enchantments[0].id)
        self.portable(g)

    def test_copy_owns_new_entity_and_new_hand_acquisition(self):
        g = self.game()
        other = g.state.players[2].hand
        acquisitions = [g.state.entities[eid].hand_entry_id for eid in other]
        self.play(g)
        for eid, original in zip(g.state.players[1].hand, other):
            e = g.state.entities[eid]
            self.assertEqual((e.owner, e.controller, e.zone), (1, 1, Zone.HAND))
            self.assertNotIn(e.hand_entry_id, acquisitions)
            self.assertEqual(e.origin_entity_id, original)
        self.assertEqual([g.state.entities[eid].hand_entry_id for eid in other], acquisitions)
        self.portable(g)

    def test_spell_and_minion_copies_keep_their_normal_playable_types(self):
        g = self.game(enemy_hand=('coin', 'card.3'))
        self.play(g)
        copies = g.state.players[1].hand
        self.assertEqual([g.state.entities[eid].kind for eid in copies],
            [CardType.SPELL, CardType.MINION])
        self.play(g, 'coin')
        self.assertEqual(g.state.players[1].mana, 4)
        self.assertEqual(self.cards(g), ['card.3'])
        self.portable(g)

    def test_turns_never_restore_originals_or_expire_permanent_copies(self):
        g = self.game()
        held = g.state.players[1].hand[1:]
        self.play(g)
        copies = g.state.players[1].hand
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand, copies)
        g.apply(EndTurn(2))
        self.assertEqual(g.state.players[1].hand[:2], copies)
        self.assertEqual(g.state.players[1].setaside, held)
        self.assertFalse(g.state.temporary_hands)
        self.portable(g)

    def test_newly_drawn_card_survives_end_of_turn_without_delayed_cleanup(self):
        self.script('draw', lambda c: (Draw(c.player_id),))
        g = self.game(enemy_hand=('draw', 'card.3'))
        self.play(g)
        self.play(g, 'draw')
        current = g.state.players[1].hand
        self.assertEqual(self.cards(g), ['card.3', 'card.9'])
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].hand, current)
        self.portable(g)

    def test_played_copy_remains_on_board_with_its_original_copy_identity(self):
        g = self.game()
        self.play(g)
        body = self.play(g, 'card.3')
        origin = g.state.entities[body].origin_entity_id
        g.apply(EndTurn(1))
        self.assertIn(body, g.state.players[1].board)
        self.assertIn(origin, g.state.players[2].hand)
        self.assertEqual(self.cards(g), ['card.4'])
        self.portable(g)

    def test_source_death_does_not_restore_permanently_removed_originals(self):
        self.script('kill', lambda c: (Destroy(next(eid for eid in
            c.state.players[c.player_id].board if c.state.entities[eid].card_id == AZALINA)),))
        g = self.game(enemy_hand=('kill', 'card.3'))
        held = g.state.players[1].hand[1:]
        source = self.play(g)
        self.play(g, 'kill')
        g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.players[1].setaside, held)
        self.assertEqual(self.cards(g), ['card.3'])
        self.portable(g)

    def test_removal_is_one_complete_event_without_discard_death_draw_or_rng(self):
        g = self.game(deck=())
        held = tuple(g.state.players[1].hand[1:])
        rng = g._rng.getstate()
        self.play(g)
        removals = [e for e in g.events if e.kind == 'cards_removed_from_game']
        self.assertEqual(len(removals), 1)
        self.assertEqual(dict(removals[0].data), {'removed': tuple(
            (eid, 1, 'hand', g.state.entities[eid].card_id) for eid in held), 'reveal': False})
        self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.draw_history)
        self.assertFalse(any(e.kind in ('card_discarded', 'card_destroyed_in_deck',
            'card_burned', 'fatigue_damage') for e in g.events))
        self.assertEqual(g._rng.getstate(), rng)

    def test_removal_wait_has_complete_empty_hand_and_restores_remaining_copies_once(self):
        self.watch('cards_removed_from_game')
        g = self.game(board=('watch',))
        held = g.state.players[1].hand[1:]
        other = g.state.players[2].hand
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.players[1].hand)
        self.assertEqual(g.state.players[1].setaside, held)
        self.assertEqual(g.state.players[2].hand, other)
        restored = self.portable(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.cards(g), ['card.3', 'card.4'])
        self.assertEqual(len([e for e in g.events if e.kind == 'cards_removed_from_game']), 1)
        self.portable(g)

    def test_first_copy_wait_uses_existing_sequential_copy_checkpoints(self):
        self.watch('card_added_to_hand', 'card.3')
        g = self.game(board=('watch',))
        self.play(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.cards(g), ['card.3'])
        restored = self.portable(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.cards(g), ['card.3', 'card.4'])
        self.portable(g)

    def test_late_failure_rolls_back_payment_removal_copies_information_and_rng(self):
        self.options['fault'] = True
        g = self.game()
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'missing.permanent.hand'):
            self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_player_views_and_events_do_not_publish_private_storage_or_copy_origins(self):
        g = self.game()
        self.play(g)
        before = g.snapshot()
        self.assertIn('"card.3"', json.dumps(g.observe(1)))
        for viewer in (1, 2):
            view = json.dumps(g.observe(viewer))
            for field in ('setaside', 'SETASIDE', 'origin_entity_id', 'copied_from', 'temporary_hands'):
                self.assertNotIn(field, view)
            event = next(e for e in g.player_events(viewer) if e['kind'] == 'cards_removed_from_game')
            self.assertEqual([r['card_id'] for r in event['removed_cards']],
                ['card.1', 'card.2'] if viewer == 1 else [None, None])
            self.assertIsNone(event['target'])
            text = json.dumps(g.player_events(viewer))
            for field in ('entity_id', 'origin_entity_id', 'copied_from'):
                self.assertNotIn(field, text)
        self.assertNotIn('"card.1"', json.dumps(g.observe(2)))
        self.assertEqual(g.snapshot(), before)
        self.portable(g)

    def test_removal_retires_known_original_handle_but_keeps_knowledge_in_event(self):
        self.script('reveal', lambda c: (RevealHandCard(c.state.players[1].hand[-1]),))
        g = self.game(('reveal', AZALINA, 'card.1'))
        held = g.state.players[1].hand[-1]
        self.play(g, 'reveal')
        self.assertIn(str(held), g.snapshot()['information']['players']['2']['refs'])
        self.play(g)
        for player in g.snapshot()['information']['players'].values():
            self.assertNotIn(str(held), player['refs'])
        event = next(e for e in g.player_events(2) if e['kind'] == 'cards_removed_from_game')
        self.assertEqual(event['removed_cards'],
            [dict(player_id=1, from_zone='hand', card_id='card.1')])
        self.portable(g)

    def test_second_player_source_uses_own_remaining_hand_and_first_player_sources(self):
        g = self.game(actor=2)
        held = g.state.players[2].hand[1:]
        other = g.state.players[1].hand
        self.play(g, actor=2)
        self.assertEqual(self.cards(g, 2), ['card.3', 'card.4'])
        self.assertEqual(g.state.players[2].setaside, held)
        self.assertEqual(g.state.players[1].hand, other)
        self.assertTrue(all(g.state.entities[eid].owner == 2 for eid in g.state.players[2].hand))
        self.assertEqual(g.state.players[2].mana, 3)
        self.portable(g)

    def test_terminal_game_has_no_temporary_return_obligation(self):
        self.script('lethal', lambda c: (Damage(c.state.players[2].hero_id, 30, c.source_id),))
        g = self.game(enemy_hand=('lethal', 'card.3'))
        held = g.state.players[1].hand[1:]
        self.play(g)
        self.play(g, 'lethal')
        self.assertEqual(g.state.status, 'finished')
        self.assertEqual(g.state.players[1].setaside, held)
        self.assertEqual(self.cards(g), ['card.3'])
        self.assertFalse(g.state.temporary_hands)
        self.portable(g)


if __name__ == '__main__':
    unittest.main()
