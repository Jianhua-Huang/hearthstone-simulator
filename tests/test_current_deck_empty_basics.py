"""Current physical-deck emptiness and one necessary native Battlecry."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    DeckCondition, DeckSpec, EndTurn, Game, IllegalAction, MatchSetup, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Scenario, SelectChoice, SnapshotError, UnknownDeckFacts,
    matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Draw, GainArmor,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'DAL_554'
TOKEN = 'DAL_554t'
CONDITION = DeckCondition('current', 'empty')
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/current-deck-empty-basics.json'
PIN = '5115bfee22352577f23664466a39fd7fcb22f7b108a311380880beed5da4e882'


def evidence():
    value = json.loads(SUPPORT.read_bytes())
    if canonical_digest(value) != PIN or [r['id'] for r in value['records']] != [NATIVE, TOKEN]:
        raise ValueError('Complete empty-deck native evidence changed')
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete native/token source changed')
    return {r['id']: r['data'] for r in value['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, CONDITION, (GainArmor(player, 3),), (GainArmor(player, 1),))


def registry():
    r = opening_registry()
    raw = evidence()
    r.register_behavior('native.empty', lambda c: (CheckDeckCondition(c.player_id,
        CONDITION, tuple(Summon(c.player_id, TOKEN) for _ in range(6))),))
    for cid in (NATIVE, TOKEN):
        card = raw[cid]
        r.register_card(CardDefinition(cid, card['name'], CardType.MINION, cost=card['cost'],
            attack=card['attack'], health=card['health'],
            battlecry='native.empty' if cid == NATIVE else None, metadata=metadata_from_record(card)))
    r.register_card(CardDefinition('class.spell', 'Known class Spell fixture', CardType.SPELL,
        metadata=metadata(CardClass.MAGE)))
    r.register_card(CardDefinition('class.minion', 'Known class Minion fixture', CardType.MINION,
        attack=1, health=3, metadata=metadata(CardClass.MAGE)))
    for cid, kind, fields in (
        ('known.no_meta.spell', CardType.SPELL, {}),
        ('known.no_meta.minion', CardType.MINION, {'health': 3}),
        ('known.no_meta.weapon', CardType.WEAPON, {'attack': 1, 'durability': 1}),
        ('known.no_meta.location', CardType.LOCATION, {'durability': 1, 'on_use': 'power'}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, **fields))
    first_deck = lambda c: CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    native_board = lambda c: next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == NATIVE)
    r.register_behavior('empty.late.fail', lambda c: (AddToHand(c.player_id, 'unknown.empty.delivery'),))
    scripts = {
        'empty.draw': lambda c: (Draw(c.player_id),),
        'empty.shuffle': lambda c: (AddToDeck(c.player_id, 'card.1'),),
        'empty.clear': lambda c: (DestroyDeckMatching(c.player_id, count=30, reveal=False),),
        'empty.face': lambda c: (TransformCapturedMinion(first_deck(c), TOKEN),),
        'empty.check': lambda c: (branch(c.player_id),),
        'empty.wait.check': lambda c: (pause(c.player_id), Draw(c.player_id), branch(c.player_id)),
        'empty.selected.yes': lambda c: (CheckDeckCondition(c.player_id, CONDITION,
            (pause(c.player_id), AddToDeck(c.player_id, 'card.1'), GainArmor(c.player_id, 3)), (GainArmor(c.player_id, 1),)),),
        'empty.selected.no': lambda c: (CheckDeckCondition(c.player_id, CONDITION, (GainArmor(c.player_id, 3),),
            (pause(c.player_id), Draw(c.player_id), GainArmor(c.player_id, 1))),),
        'empty.fail': lambda c: (branch(c.player_id), InvokeBehavior('empty.late.fail', c.source_id, c.player_id)),
        'empty.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id),
            InvokeBehavior('empty.late.fail', c.source_id, c.player_id)),
        'empty.silence': lambda c: (Silence(native_board(c)),),
        'empty.bounce': lambda c: (ReturnToHand(native_board(c)),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(CardClass.MAGE)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class CurrentDeckEmptyTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), deck=(), *, other_hand=(), other_deck=(), board=(), other_board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage.hero', hand=hand, deck=deck, board=board, hero_power_card_id='mage.power', mana=10, max_mana=10),
            PlayerSetup('warrior.hero', hand=other_hand, deck=other_deck, board=other_board,
                hero_power_card_id='warrior.power', mana=10, max_mana=10)), seed=80), registry())

    def query(self, g, player=1):
        return matches_deck_condition(g.state, g.registry, player, CONDITION)

    def play(self, g, cid=NATIVE):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('ok',)))

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def tokens(self, g, player=1):
        return [g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == TOKEN]

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(saved, registry())
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        return restored

    def nested(self, value, name):
        if isinstance(value, dict):
            if value.get('type', '').endswith('.' + name):
                return value
            values = value.values()
        elif isinstance(value, list):
            values = value
        else:
            return None
        for child in values:
            found = self.nested(child, name)
            if found is not None:
                return found

    def reject(self, saved):
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), registry())

    def test_full_raw_pin_native_identity_and_exact_six_token_text(self):
        raw = evidence()
        r = registry()
        card, token = r.card(NATIVE), r.card(TOKEN)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            (7, 6, 6, (CardClass.NEUTRAL,), Rarity.LEGENDARY, ()))
        self.assertEqual(raw[NATIVE]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'], raw[TOKEN]['dbf_id'])
        self.assertIn('six 6/6', raw[NATIVE]['text_en'])
        self.assertEqual((token.cost, token.attack, token.health, token.keywords, token.metadata.tribes), (6, 6, 6, (), ('elemental',)))
        self.assertFalse(token.metadata.collectible)
        self.assertEqual(card.metadata, metadata_from_record(raw[NATIVE]))
        self.assertEqual(token.metadata, metadata_from_record(raw[TOKEN]))

    def test_current_empty_true_nonempty_false_without_starting_inference(self):
        g = self.game()
        self.assertTrue(self.query(g))
        self.assertIsNone(g.state.opening)
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting'))
        self.assertFalse(self.query(self.game(deck=('card.1',))))
        self.check(g)

    def test_nonempty_no_minions_or_no_neutral_deck_is_not_empty(self):
        g = self.game(deck=('class.spell', 'class.spell'))
        self.assertFalse(self.query(g))
        for predicate in ('no_minions', 'no_neutral'):
            self.assertTrue(matches_deck_condition(g.state, g.registry, 1, DeckCondition('current', predicate)))
        self.assertFalse(matches_deck_condition(g.state, g.registry, 1))
        self.check(g)

    def test_physical_nonempty_is_independent_of_kind_class_and_metadata(self):
        for cid in ('known.no_meta.spell', 'known.no_meta.minion', 'known.no_meta.weapon',
                    'known.no_meta.location', TOKEN, 'class.minion', 'card.1'):
            with self.subTest(card=cid):
                g = self.game(deck=(cid,))
                self.assertFalse(self.query(g))
                self.assertEqual(len(g.state.players[1].deck), 1)
        g = self.game(deck=('known.no_meta.minion',))
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1)
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition('current', 'no_neutral'))
        self.check(g)

    def test_query_uses_requested_player_not_active_or_opponent_deck(self):
        g = self.game(other_deck=('card.2', 'card.3'))
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))
        g.apply(EndTurn(1))
        self.assertEqual(g.state.active_player, 2)
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))
        self.check(g)

    def test_cards_in_hand_board_and_graveyard_do_not_count_as_deck(self):
        g = self.game((NATIVE, 'empty.check', 'card.1'), board=('card.2',))
        self.play(g, 'empty.check')
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 3)
        self.assertTrue(g.state.players[1].hand)
        self.assertTrue(g.state.players[1].board)
        self.assertTrue(g.state.players[1].graveyard)
        self.check(g)

    def test_pure_query_preserves_rng_events_history_and_state(self):
        for deck in ((), ('known.no_meta.weapon',), ('class.spell', 'class.spell')):
            with self.subTest(deck=deck):
                g = self.game(deck=deck)
                saved = g.snapshot()
                self.query(g)
                self.assertEqual(g.snapshot(), saved)

    def test_drawing_last_physical_card_rechecks_emptiness(self):
        g = self.game(('empty.draw',), deck=('class.spell',))
        self.assertFalse(self.query(g))
        identity = g.state.players[1].deck[0]
        self.play(g, 'empty.draw')
        self.assertTrue(self.query(g))
        self.assertIn(identity, g.state.players[1].hand)
        self.check(g)

    def test_shuffling_one_card_into_empty_deck_makes_new_check_false(self):
        g = self.game(('empty.shuffle',))
        self.assertTrue(self.query(g))
        self.play(g, 'empty.shuffle')
        self.assertFalse(self.query(g))
        self.assertEqual(len(g.state.players[1].deck), 1)
        self.check(g)

    def test_destroying_remaining_deck_makes_empty_without_starting_facts(self):
        g = self.game(('empty.clear',), deck=('class.minion', 'class.spell'))
        self.play(g, 'empty.clear')
        self.assertTrue(self.query(g))
        self.assertIsNone(g.state.opening)
        self.check(g)

    def test_normal_stored_minion_transform_preserves_nonempty_identity(self):
        g = self.game(('empty.face',), deck=('class.minion',))
        identity = g.state.players[1].deck[0]
        self.play(g, 'empty.face')
        self.assertEqual(g.state.players[1].deck, [identity])
        self.assertEqual(g.state.entities[identity].card_id, TOKEN)
        self.assertFalse(self.query(g))
        self.check(g)

    def test_full_thirty_slot_constructed_opening_keeps_current_and_original_distinct(self):
        r = registry()
        own = (NATIVE,) + tuple(f'card.{i}' for i in range(1, 30))
        enemy = tuple(f'card.{i}' for i in range(1, 31))
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, enemy)), policy(r), 'coin', 80, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        self.assertFalse(self.query(g))
        self.assertEqual(len(g.state.players[1].original_deck), 30)
        self.check(g)

    def test_native_empty_deck_summons_six_independent_full_printed_tokens(self):
        g = self.game()
        identity = self.play(g)
        tokens = self.tokens(g)
        self.assertEqual(len(tokens), 6)
        self.assertEqual(len({e.id for e in tokens}), 6)
        self.assertEqual(g.state.players[1].board[0], identity)
        self.assertTrue(all((e.attack, e.health, e.controller) == (6, 6, 1) for e in tokens))
        self.assertEqual((g.state.players[1].mana, g.state.play_history[-1].cost), (3, 7))
        self.check(g)

    def test_native_nonempty_spell_deck_summons_nothing(self):
        g = self.game(deck=('class.spell',))
        self.play(g)
        self.assertEqual(self.tokens(g), [])
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(g.state.players[1].mana, 3)
        self.check(g)

    def test_native_nonempty_card_with_unknown_class_still_summons_nothing(self):
        g = self.game(deck=('known.no_meta.weapon',))
        self.play(g)
        self.assertEqual(self.tokens(g), [])
        self.assertFalse(self.query(g))
        self.check(g)

    def test_native_second_player_uses_own_deck_and_owns_tokens(self):
        g = self.game((), deck=('card.1',), other_hand=(NATIVE,))
        g.apply(EndTurn(1))
        self.play(g)
        self.assertEqual(len(self.tokens(g, 2)), 6)
        self.assertTrue(all(e.controller == 2 for e in self.tokens(g, 2)))
        self.assertEqual(g.state.players[2].mana, 3)
        self.check(g)

    def test_native_capacity_includes_original_played_body(self):
        for count, wanted in ((1, 5), (5, 1), (6, 0)):
            with self.subTest(board=count):
                g = self.game(board=('card.1',) * count)
                self.play(g)
                self.assertEqual(len(self.tokens(g)), wanted)
                self.assertEqual(len(g.state.players[1].board), 7)
                self.assertEqual(g.state.players[1].mana, 3)
                self.check(g)

    def test_native_full_board_illegal_play_rolls_back_entire_action(self):
        g = self.game(board=('card.1',) * 7)
        saved = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_native_player_command_uses_original_payment_and_legal_action(self):
        g = self.game()
        port = g.for_player(1)
        dto = port.legal_actions()
        card = next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == NATIVE)
        action = next(row for row in dto['actions'] if row.get('card') == card['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((len(self.tokens(g)), g.state.players[1].mana), (6, 3))
        self.check(g)

    def test_later_shuffle_and_silence_do_not_undo_existing_tokens(self):
        g = self.game((NATIVE, 'empty.shuffle', 'empty.silence'))
        self.play(g)
        identities = [e.id for e in self.tokens(g)]
        self.play(g, 'empty.shuffle')
        self.play(g, 'empty.silence')
        self.assertFalse(self.query(g))
        self.assertEqual([e.id for e in self.tokens(g)], identities)
        self.check(g)

    def test_bounced_native_checks_new_nonempty_deck_on_next_play(self):
        g = self.game((NATIVE, 'empty.bounce', 'empty.shuffle', 'empty.shuffle'))
        self.play(g)
        identities = [e.id for e in self.tokens(g)]
        self.play(g, 'empty.bounce')
        self.play(g, 'empty.shuffle')
        self.play(g, 'empty.shuffle')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.assertFalse(self.query(g))
        self.assertEqual(len(g.state.players[1].deck), 1)
        self.play(g)
        self.assertEqual([e.id for e in self.tokens(g)], identities)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.check(g)

    def test_unexecuted_condition_reads_deck_after_real_choice_and_draw(self):
        g = self.game(('empty.wait.check',), deck=('class.spell',))
        self.play(g, 'empty.wait.check')
        self.assertFalse(self.query(g))
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 3)
        self.check(g)

    def test_selected_match_branch_stays_selected_after_shuffle(self):
        g = self.game(('empty.selected.yes',))
        self.play(g, 'empty.selected.yes')
        restored, cloned = self.check(g), g.clone()
        self.choose(g)
        for other in (restored, cloned):
            self.choose(other)
            self.assertEqual(other.snapshot(), g.snapshot())
        self.assertFalse(self.query(g))
        self.assertEqual(self.armor(g), 3)
        self.check(g)

    def test_selected_miss_branch_stays_selected_after_last_card_draw(self):
        g = self.game(('empty.selected.no',), deck=('class.spell',))
        self.play(g, 'empty.selected.no')
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 1)
        self.check(g)

    def test_failed_waiting_continuation_restores_choice_and_original_branch(self):
        g = self.game(('empty.wait.fail',))
        self.play(g, 'empty.wait.fail')
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), saved)
        self.check(g)

    def test_branch_failure_rolls_back_action_payment_and_effect(self):
        g = self.game(('empty.fail',))
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'empty.fail')
        self.assertEqual(g.snapshot(), saved)

    def test_typed_two_field_condition_roundtrip_and_restricted_profile(self):
        g = self.game()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        wire = codec.encode(CONDITION)
        self.assertEqual(codec.decode(wire), CONDITION)
        self.assertEqual(set(wire['fields']), {'scope', 'predicate'})
        for field in ('scope', 'predicate'):
            bad = deepcopy(wire)
            del bad['fields'][field]
            with self.assertRaises(ValueError):
                codec.decode(bad)
        for make in (lambda: DeckCondition('starting', 'empty'), lambda: DeckCondition('hand', 'empty'),
                     lambda: DeckCondition('current', True), lambda: DeckCondition('current', 'not_empty')):
            with self.subTest(make=make), self.assertRaises(ValueError):
                make()

    def test_pending_restore_rejects_scope_predicate_extra_field_and_bad_player(self):
        g = self.game(('empty.wait.check',), deck=('class.spell',))
        self.play(g, 'empty.wait.check')
        for field, value in (('scope', 'starting'), ('predicate', 'always'), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCondition')['fields'][field] = value
            self.reject(saved)
        saved = g.snapshot()
        self.nested(saved['resolution_frame'], 'CheckDeckCondition')['fields']['player_id'] = True
        self.reject(saved)

    def test_unknown_card_definition_still_rejected_by_state_restoration(self):
        g = self.game(deck=('known.no_meta.weapon',))
        saved = g.snapshot()
        identity = g.state.players[1].deck[0]
        saved['state']['entities'][str(identity)]['card_id'] = 'unknown.empty.face'
        with self.assertRaisesRegex(SnapshotError, 'unsupported card definition'):
            Game.from_snapshot(rehash(saved), registry())

    def test_player_views_hide_private_predicate_and_current_deck_inventory(self):
        g = self.game(('empty.wait.check',), deck=('card.29',))
        self.play(g, 'empty.wait.check')
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for value in ('DeckCondition', 'predicate', 'on_match', 'on_miss', 'card.29'):
                self.assertNotIn(value, text)
        self.check(g)

    def test_wire_layout_unchanged_and_old_rule_handler_signatures_rejected(self):
        g = self.game()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version),
            (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v228'
        self.reject(saved)
        self.check(g)


if __name__ == '__main__':
    unittest.main()
