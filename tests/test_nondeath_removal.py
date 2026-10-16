"""One independent removal operation and its own boundaries, no combo family."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
import unittest

from hs_sim.engine import (AuraSpec, CardClass, CardDefinition, CardType, EndTurn, Game,
    IllegalAction, Keyword, MinionReference, OpeningHook, PlayCard, PlayerSetup, RemoveFromGame,
    Rarity, ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, RequestChoice, RevealHandCard,
    ReturnToHand)
from hs_sim.engine.model import Resource
from hs_sim.engine.player_api import visible_entities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import event_from_dict, event_to_dict
from hs_sim.engine.zones import AddToDeck, CardReference, MoveCard
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, registry as opening_registry, setup


LIFE = 'MAW_013'
PIN = '397a6cd7368395bef312a605c63e4b6c11857dcf6a9d149e2756bda1630e6dd9'
FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/nondeath-removal.json'


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Complete removal raw evidence changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original removal record changed')
    return {row['id']: row['data'] for row in data['records']}


def registry(scripts=(), extra_cards=()):
    r = opening_registry()
    r.register_behavior('remove.life', lambda c: (RemoveFromGame(
        (MinionReference.capture(c.state.entities[c.target_id]),), c.source_id),))
    row = evidence()[LIFE]
    r.register_card(CardDefinition(LIFE, row['name'], CardType.SPELL, cost=row['cost'],
        on_play='remove.life', targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
        metadata=metadata(CardClass.MAGE, rarity=Rarity.RARE)))
    r.register_behavior('remove.death', lambda c: (GainArmor(c.player_id, 50),))
    r.register_card(CardDefinition('probe.unit', 'Probe', CardType.MINION, attack=2, health=3,
        deathrattle='remove.death', keywords=(Keyword.REBORN,), metadata=metadata()))
    r.register_card(CardDefinition('probe.dormant', 'Dormant', CardType.MINION,
        attack=2, health=3, dormant_turns=2, metadata=metadata()))
    r.register_card(CardDefinition('probe.aura', 'Aura', CardType.MINION, attack=2, health=3,
        auras=(AuraSpec(health=2),), metadata=metadata()))
    r.register_card(CardDefinition('probe.weapon', 'Weapon', CardType.WEAPON,
        attack=2, durability=2, metadata=metadata()))
    r.register_card(CardDefinition('probe.location', 'Location', CardType.LOCATION,
        durability=2, on_use='remove.death', metadata=metadata()))
    r.register_card(CardDefinition('probe.hero.card', 'Hero card', CardType.HERO,
        health=30, hero_card=True, initial_hero_power='mage.power', metadata=metadata(CardClass.MAGE)))
    for behavior_id, callback in scripts:
        r.register_behavior(behavior_id, callback)
        r.register_card(CardDefinition(behavior_id, behavior_id, CardType.SPELL,
            on_play=behavior_id, metadata=metadata()))
    for definition, callback in extra_cards:
        if callback is not None:
            r.register_behavior(definition.opening_hooks[0].behavior_id if definition.opening_hooks
                else definition.triggers[0].behavior_id, callback)
        r.register_card(definition)
    return r


class NondeathRemovalTests(unittest.TestCase):
    def setUp(self):
        self.scripts = []
        self.extra_cards = []

    def script(self, name, callback):
        self.scripts.append((name, callback))

    def game(self, hand=(LIFE,), board=(), deck_cards=(), enemy_board=(), enemy_hand=(), enemy_deck=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, board=board, deck=deck_cards, max_mana=10, mana=10),
            PlayerSetup('warrior.hero', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                max_mana=10, mana=10)), seed=53), registry(self.scripts, self.extra_cards))

    def play(self, g, card_id=LIFE, target=None):
        player = g.state.active_player
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == card_id)
        g.apply(PlayCard(player, source, target))
        return source

    def ref(self, c, zone=Zone.HAND, player=1, index=0):
        return CardReference.capture(c.state.entities[getattr(c.state.players[player], zone.value)[index]])

    def removal_event(self, g, viewer):
        return next(e for e in g.player_events(viewer) if e['kind'] == 'cards_removed_from_game')

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        r = registry(self.scripts, self.extra_cards)
        restored = Game.from_snapshot(snap, r)
        self.assertEqual(restored.snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry(self.scripts, self.extra_cards)).snapshot(), snap)
        return restored

    def choose(self, g):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, (pending.options[0].id,)))

    def test_full_real_evidence_and_only_one_executable_source(self):
        rows = evidence(); r = registry()
        self.assertEqual(set(rows), {LIFE, 'YOD_009', 'DMF_254'})
        self.assertEqual((r.card(LIFE).cost, r.card(LIFE).kind, r.card(LIFE).name),
            (4, CardType.SPELL, rows[LIFE]['name']))
        self.assertNotIn('YOD_009', r.cards); self.assertNotIn('DMF_254', r.cards)

    def test_real_spell_removes_enemy_and_preserves_payment_and_cast_history(self):
        g = self.game(enemy_board=('probe.unit', 'card.1'))
        target = g.state.players[2].board[0]; other = g.state.players[2].board[1]
        self.play(g, target=target)
        self.assertEqual(g.state.players[2].board, [other])
        self.assertEqual(g.state.players[2].setaside, [target])
        self.assertEqual((g.state.entities[target].zone, g.state.players[1].mana), (Zone.SETASIDE, 6))
        self.assertEqual(len(g.state.cast_history), 1)
        self.assertTrue(g.state.cast_history[0].completed)
        self.portable(g)

    def test_real_spell_can_remove_friendly_minion(self):
        g = self.game(board=('probe.unit',)); target = g.state.players[1].board[0]
        self.play(g, target=target)
        self.assertEqual(g.state.players[1].setaside, [target]); self.assertFalse(g.state.players[1].board)

    def test_removal_has_no_death_discard_destroy_reborn_or_corpse(self):
        g = self.game(enemy_board=('probe.unit',)); target = g.state.players[2].board[0]
        self.play(g, target=target)
        self.assertFalse(g.state.death_history); self.assertFalse(g.state.players[2].graveyard)
        self.assertEqual(g.state.players[2].resources[Resource.CORPSES], 0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 0)
        kinds = {e.kind for e in g.events}
        self.assertFalse(kinds & {'minion_died', 'minion_reborn', 'destroyed', 'card_discarded', 'card_destroyed_in_deck'})
        self.assertEqual(g.state.entities[target].board_presence_id, None)

    def test_simultaneous_batch_leaves_before_listener_capture(self):
        def observe(c):
            return (GainArmor(c.player_id, len(c.state.players[1].setaside) +
                len(c.state.players[2].setaside)),)
        self.extra_cards.append((CardDefinition('probe.watcher', 'Watcher', CardType.MINION,
            attack=1, health=4, triggers=(TriggerSpec('cards_removed_from_game', 'probe.watch'),),
            metadata=metadata()), observe))
        self.script('wipe', lambda c: (RemoveFromGame(tuple(MinionReference.capture(c.state.entities[i])
            for p in (1, 2) for i in c.state.players[p].board if c.state.entities[i].card_id != 'card.1'), c.source_id),))
        g = self.game(hand=('wipe',), board=('probe.aura', 'probe.watcher', 'probe.unit', 'card.1'),
            enemy_board=('probe.unit',))
        self.play(g, 'wipe')
        self.assertEqual([len(g.state.players[p].setaside) for p in (1, 2)], [3, 1])
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)
        self.assertFalse(g.state.death_history)
        event = self.removal_event(g, 1); self.assertEqual(event['amount'], 4)
        self.assertEqual(len(event['removed_cards']), 4)

    def test_remaining_listener_sees_complete_removed_batch(self):
        self.extra_cards.append((CardDefinition('probe.watcher', 'Watcher', CardType.MINION,
            attack=1, health=4, triggers=(TriggerSpec('cards_removed_from_game', 'probe.watch'),),
            metadata=metadata()), lambda c: (GainArmor(c.player_id, len(c.state.players[2].setaside)),)))
        self.script('wipe', lambda c: (RemoveFromGame(tuple(MinionReference.capture(c.state.entities[i])
            for i in c.state.players[2].board), c.source_id),))
        g = self.game(hand=('wipe',), board=('probe.watcher',), enemy_board=('probe.aura', 'probe.unit'))
        self.play(g, 'wipe'); self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertFalse(g.state.death_history)

    def test_global_removal_accepts_dormant_physical_minion(self):
        self.script('remove', lambda c: (RemoveFromGame((MinionReference.capture(
            c.state.entities[c.state.players[2].board[0]]),), c.source_id),))
        g = self.game(hand=('remove',), enemy_board=('probe.dormant',)); target = g.state.players[2].board[0]
        self.play(g, 'remove'); self.assertEqual(g.state.entities[target].zone, Zone.SETASIDE)
        self.assertIsNone(g.state.entities[target].dormancy); self.portable(g)

    def test_real_targeting_cannot_bypass_dormancy_or_target_hero(self):
        g = self.game(enemy_board=('probe.dormant',)); source = g.state.players[1].hand[0]
        for target in (g.state.players[2].board[0], g.state.players[2].hero_id):
            before = g.snapshot()
            with self.subTest(target=target), self.assertRaises(IllegalAction): g.apply(PlayCard(1, source, target))
            self.assertEqual(g.snapshot(), before)

    def test_hand_and_deck_removal_preserves_id_owner_and_other_order(self):
        self.script('remove', lambda c: (RemoveFromGame((self.ref(c), self.ref(c, Zone.DECK, 2)), c.source_id),))
        g = self.game(hand=('remove', 'probe.unit', 'card.1'), enemy_deck=('probe.unit', 'card.2'))
        hand_id = g.state.players[1].hand[1]; deck_ids = g.state.players[2].deck[:]
        self.play(g, 'remove')
        self.assertEqual(g.state.players[1].setaside, [hand_id])
        self.assertEqual(g.state.players[2].setaside, [deck_ids[0]])
        self.assertEqual(g.state.players[2].deck, deck_ids[1:])
        self.assertEqual([(g.state.entities[i].owner, g.state.entities[i].controller) for i in (hand_id, deck_ids[0])], [(1,1), (2,2)])
        self.assertFalse(g.state.death_history)

    def test_hidden_removal_never_exposes_deck_face_or_private_state(self):
        self.script('remove', lambda c: (RemoveFromGame((self.ref(c), self.ref(c, Zone.DECK, 2)), c.source_id),))
        g = self.game(hand=('remove', 'probe.unit'), enemy_deck=('card.2',)); self.play(g, 'remove')
        for viewer in (1, 2):
            event = self.removal_event(g, viewer)
            self.assertEqual(event['removed_cards'][0]['card_id'], 'probe.unit' if viewer == 1 else None)
            self.assertIsNone(event['removed_cards'][1]['card_id'])
            self.assertIsNone(event['target'])
            observation = g.observe(viewer)
            for player in observation['players']:
                self.assertNotIn('setaside', player)
                self.assertNotIn('setaside_count', player)
                self.assertFalse(player['known_graveyard'] if player['id'] == 2 else False)

    def test_revealed_deck_removal_publishes_only_bare_card_face(self):
        self.script('remove', lambda c: (RemoveFromGame((self.ref(c, Zone.DECK, 2),), c.source_id, reveal=True),))
        g = self.game(hand=('remove',), enemy_deck=('probe.unit',)); self.play(g, 'remove')
        for viewer in (1, 2):
            row = self.removal_event(g, viewer)['removed_cards'][0]
            self.assertEqual(row, dict(player_id=2, from_zone='deck', card_id='probe.unit'))
            self.assertNotIn('ref', row); self.assertNotIn('entity_id', row)
        self.portable(g)

    def test_remembered_enemy_hand_face_is_retained_only_in_event(self):
        self.script('remove', lambda c: (RevealHandCard(self.ref(c, player=2).entity_id),
            RemoveFromGame((self.ref(c, player=2),), c.source_id)))
        g = self.game(hand=('remove',), enemy_hand=('probe.unit',)); target = g.state.players[2].hand[0]
        self.play(g, 'remove')
        self.assertEqual(self.removal_event(g, 1)['removed_cards'][0]['card_id'], 'probe.unit')
        for row in g.snapshot()['information']['players'].values():
            self.assertNotIn(str(target), row['refs']); self.assertNotIn(str(target), row['known'])
        self.portable(g)

    def test_removed_board_handles_are_not_player_action_targets(self):
        g = self.game(hand=(LIFE, LIFE), enemy_board=('probe.unit',))
        old = g.observe(1)['players'][1]['board'][0]['ref']; target = g.state.players[2].board[0]
        self.play(g, target=target)
        self.assertNotIn(old, visible_entities(g.observe(1)))
        self.assertEqual(self.removal_event(g, 2)['removed_cards'][0]['card_id'], 'probe.unit')
        self.assertFalse(any(a.target_id == target for a in g.legal_actions() if isinstance(a, PlayCard)))

    def test_stale_hand_reference_cannot_follow_to_deck(self):
        self.script('remove', lambda c: (MoveCard(self.ref(c), 1, Zone.DECK), RemoveFromGame((self.ref(c),), c.source_id)))
        g = self.game(hand=('remove', 'probe.unit')); target = g.state.players[1].hand[1]
        self.play(g, 'remove')
        self.assertIn(target, g.state.players[1].deck); self.assertFalse(g.state.players[1].setaside)
        self.assertFalse(any(e.kind == 'cards_removed_from_game' for e in g.events))

    def test_stale_board_reference_cannot_follow_to_hand(self):
        def script(c):
            target = c.state.entities[c.state.players[2].board[0]]
            return (ReturnToHand(target.id), RemoveFromGame((MinionReference.capture(target),), c.source_id))
        self.script('remove', script); g = self.game(hand=('remove',), enemy_board=('probe.unit',))
        target = g.state.players[2].board[0]; self.play(g, 'remove')
        self.assertIn(target, g.state.players[2].hand); self.assertFalse(g.state.players[2].setaside)

    def test_old_reference_cannot_remove_same_card_after_reentry(self):
        def script(c):
            old = self.ref(c)
            middle = replace(old, zone=Zone.DECK, zone_epoch=old.zone_epoch + 1)
            return (MoveCard(old, 1, Zone.DECK), MoveCard(middle, 1, Zone.HAND),
                RemoveFromGame((old,), c.source_id))
        self.script('remove', script); g = self.game(hand=('remove', 'probe.unit'))
        target = g.state.players[1].hand[1]; self.play(g, 'remove')
        self.assertEqual(g.state.players[1].hand, [target]); self.assertFalse(g.state.players[1].setaside)

    def test_repeated_old_removal_is_skipped(self):
        def script(c):
            ref = self.ref(c, Zone.DECK)
            return (RemoveFromGame((ref,), c.source_id), RemoveFromGame((ref,), c.source_id))
        self.script('remove', script); g = self.game(hand=('remove',), deck_cards=('probe.unit',))
        self.play(g, 'remove')
        self.assertEqual(sum(e.kind == 'cards_removed_from_game' for e in g.events), 1)
        self.assertEqual(len(g.state.players[1].setaside), 1)

    def test_empty_removal_has_no_receipt_or_rng_use(self):
        self.script('remove', lambda c: (RemoveFromGame((), c.source_id),))
        g = self.game(hand=('remove',)); before = g.snapshot()['rng_state']; self.play(g, 'remove')
        self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertFalse(any(e.kind == 'cards_removed_from_game' for e in g.events))

    def test_invalid_duplicate_and_mutable_requests_are_rejected(self):
        ref = CardReference(10, 1, Zone.HAND, 'probe.unit', 0)
        for create in (lambda: RemoveFromGame([ref]), lambda: RemoveFromGame((ref, ref)),
                lambda: RemoveFromGame((10,)), lambda: RemoveFromGame((ref,), reveal=1),
                lambda: RemoveFromGame((ref,), source_id=True)):
            with self.subTest(create=create), self.assertRaises(ValueError): create()

    def test_unknown_definition_rolls_back_entire_action_and_rng(self):
        self.script('remove', lambda c: (AddToDeck(1, 'card.1'), RemoveFromGame((self.ref(c),
            CardReference(999, 1, Zone.DECK, 'missing', 0)), c.source_id)))
        g = self.game(hand=('remove', 'probe.unit')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'remove')
        self.assertEqual(g.snapshot(), before)

    def test_missing_source_rolls_back_without_moving_target(self):
        self.script('remove', lambda c: (RemoveFromGame((self.ref(c),), 999),))
        g = self.game(hand=('remove', 'probe.unit')); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'remove')
        self.assertEqual(g.snapshot(), before)

    def test_all_stored_playable_types_use_same_zone_operation(self):
        cards = ('probe.unit', 'coin', 'probe.weapon', 'probe.location', 'probe.hero.card')
        self.script('remove', lambda c: (RemoveFromGame(tuple(CardReference.capture(c.state.entities[i])
            for i in c.state.players[1].hand), c.source_id),))
        g = self.game(hand=('remove',) + cards); self.play(g, 'remove')
        self.assertEqual(tuple(g.state.entities[i].card_id for i in g.state.players[1].setaside), cards)
        self.assertFalse(g.state.players[1].hand); self.portable(g)

    def test_waiting_choice_carries_captured_removal_without_duplication(self):
        self.script('choose', lambda c: (RequestChoice(1, (ChoiceOption('remove', 'Remove',
            (RemoveFromGame((self.ref(c, Zone.DECK),), c.source_id),)),), source_id=c.source_id),))
        g = self.game(hand=('choose',), deck_cards=('probe.unit',)); self.play(g, 'choose')
        restored = self.portable(g)
        self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(len(g.state.players[1].setaside), 1)
        self.portable(g)

    def test_waiting_after_removal_restores_inert_zone_and_private_projection(self):
        self.script('choose', lambda c: (RemoveFromGame((self.ref(c, Zone.DECK),), c.source_id),
            RequestChoice(1, (ChoiceOption('ok', 'OK', (GainArmor(1, 1),)),), source_id=c.source_id)))
        g = self.game(hand=('choose',), deck_cards=('probe.unit',)); self.play(g, 'choose')
        restored = self.portable(g); self.choose(restored); self.choose(g)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_waiting_choice_restores_captured_board_removal(self):
        self.script('choose', lambda c: (RequestChoice(1, (ChoiceOption('remove', 'Remove',
            (RemoveFromGame((MinionReference.capture(c.state.entities[c.state.players[2].board[0]]),),
                c.source_id),)),), source_id=c.source_id),))
        g = self.game(hand=('choose',), enemy_board=('probe.unit',)); self.play(g, 'choose')
        restored = self.portable(g); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_snapshot_requires_exact_setaside_membership(self):
        g = self.game(enemy_board=('probe.unit',)); target = g.state.players[2].board[0]; self.play(g, target=target)
        good = g.snapshot()
        for kind in ('missing', 'duplicate', 'wrong_zone', 'wrong_owner', 'mutable_type'):
            bad = deepcopy(good); player = bad['state']['players']['2']
            if kind == 'missing': del player['setaside']
            elif kind == 'duplicate': player['setaside'].append(target)
            elif kind == 'wrong_zone': player['graveyard'].append(player['setaside'].pop())
            elif kind == 'wrong_owner': bad['state']['players']['1']['setaside'].append(player['setaside'].pop())
            else: player['setaside'] = {}
            with self.subTest(kind=kind), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_snapshot_rejects_retained_live_hidden_zone_handle(self):
        g = self.game(enemy_board=('probe.unit',)); target = g.state.players[2].board[0]
        old = deepcopy(g.snapshot()['information']['players']['1']); self.play(g, target=target)
        bad = g.snapshot(); k = bad['information']['players']['1']
        k['refs'][str(target)] = old['refs'][str(target)]; k['known'][str(target)] = 'probe.unit'
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_receipt_rejects_duplicate_hidden_rows_and_invalid_reveal(self):
        g = self.game(enemy_board=('probe.unit',)); self.play(g, target=g.state.players[2].board[0])
        event = next(e for e in g.events if e.kind == 'cards_removed_from_game'); good = event_to_dict(event)
        self.assertEqual(event_to_dict(event_from_dict(good)), good)
        for kind in ('duplicate', 'reveal', 'zone', 'amount'):
            bad = deepcopy(good)
            if kind == 'duplicate': bad['data']['removed'] *= 2; bad['amount'] = 2
            elif kind == 'reveal': bad['data']['reveal'] = 1
            elif kind == 'zone': bad['data']['removed'][0][2] = 'graveyard'
            else: bad['amount'] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError): event_from_dict(bad)

    def test_public_receipt_rejects_state_identity_and_wrong_board_face(self):
        g = self.game(enemy_board=('probe.unit',)); self.play(g, target=g.state.players[2].board[0])
        for kind in ('id', 'face', 'zone'):
            bad = g.snapshot(); events = bad['information']['players']['1']['events']
            row = next(e for e in events if e['kind'] == 'cards_removed_from_game')['removed_cards'][0]
            if kind == 'id': row['entity_id'] = 99
            elif kind == 'face': row['card_id'] = 'coin'
            else: row['from_zone'] = 'setaside'
            with self.subTest(kind=kind), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())

    def test_removed_entity_never_returns_via_turn_clock_or_death_candidates(self):
        g = self.game(enemy_board=('probe.unit',), deck_cards=('card.1',), enemy_deck=('card.2',))
        self.play(g, target=g.state.players[2].board[0]); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertFalse(g.state.players[2].board); self.assertFalse(g.state.death_history)
        self.assertEqual(len(g.state.players[2].setaside), 1); self.portable(g)

    def test_setaside_cannot_be_used_as_normal_stored_or_board_reference(self):
        g = self.game(enemy_board=('probe.unit',)); target = g.state.players[2].board[0]; self.play(g, target=target)
        for capture in (CardReference.capture, MinionReference.capture):
            with self.subTest(capture=capture), self.assertRaises(ValueError): capture(g.state.entities[target])

    def test_opening_removal_keeps_original_deck_facts_and_excludes_mulligan(self):
        def opening(c):
            return (RemoveFromGame((CardReference.capture(c.state.entities[c.source_id]),), c.source_id),)
        self.extra_cards.append((CardDefinition('probe.opening', 'Opening removal probe', CardType.MINION,
            attack=1, health=1, metadata=metadata(), opening_hooks=(OpeningHook('before_deal', 'probe.opening.remove'),)), opening))
        r = registry(self.scripts, self.extra_cards)
        cards = ('probe.opening',) + tuple(f'card.{i}' for i in range(1, 8))
        g = Game.from_decks(setup(r, decks=(deck(cards=cards), deck(CardClass.WARRIOR,
            cards=tuple(f'card.{i}' for i in range(8, 16)))), deck_size=8), r)
        target = g.state.players[1].setaside[0]
        self.assertEqual(g.state.players[1].original_deck, cards)
        self.assertIn(target, g.state.opening.original_entities[0])
        self.assertNotIn(target, g.state.opening.offered[0]); restored = self.portable(g)
        while g.state.pending_choice:
            pending = g.state.pending_choice
            g.apply(SelectChoice(pending.player_id, pending.id, ()))
            other = restored.state.pending_choice
            restored.apply(SelectChoice(other.player_id, other.id, ()))
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_new_schema_and_old_or_future_version_rejection(self):
        g = self.game(); self.assertEqual(g.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        for version in (1, 157, 158, 159, 160, 161, 162, 217, True):
            bad = g.snapshot(); bad['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError): Game.from_snapshot(bad, registry())
