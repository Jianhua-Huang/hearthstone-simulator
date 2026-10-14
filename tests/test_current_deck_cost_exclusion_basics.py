"""A parameterized local deck-cost exclusion and one necessary native source."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, CheckDeckCondition,
    CostSpec, DeckCondition, DeckCostCondition, DeckSpec, EndTurn, Game, Keyword,
    MatchSetup, PlayCard, PlayerSetup, Rarity, ResolutionError, Scenario, SelectChoice,
    SnapshotError, UnknownDeckFacts, matches_deck_condition)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.costs import local_cost, quote_cost
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Draw,
    GainArmor, GrantKeyword, InvokeBehavior, ModifyCost, RequestChoice, ReturnToHand, Silence)
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.zones import AddToDeck, CardReference, DestroyDeckMatching
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata, policy, registry as opening_registry
from test_current_deck_empty_basics import rehash
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

NATIVE = 'ICC_853'
CONDITION = DeckCostCondition(4, 'local')
SUPPORT = Path(__file__).resolve().parents[1] / 'data/support/current-deck-cost-exclusion-basics.json'
PIN = '0ee74fc355c9a6bb05988d4dd091c58dd0000462c92b71e62be9388a6947043b'
KEYWORDS = (Keyword.LIFESTEAL, Keyword.TAUNT)


def evidence():
    packet = json.loads(SUPPORT.read_bytes())
    ids = ['ICC_851', 'ICC_852', 'ICC_853', 'CORE_ICC_851', 'CORE_ICC_852', 'CORE_ICC_853']
    if canonical_digest(packet) != PIN or [r['id'] for r in packet['records']] != ids:
        raise ValueError('Complete native deck-cost source changed')
    for row in packet['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original card row changed')
    return {r['id']: r['data'] for r in packet['records']}


def pause(player):
    return RequestChoice(player, (ChoiceOption('ok', 'Continue', ()),))


def branch(player):
    return CheckDeckCondition(player, CONDITION, (GainArmor(player, 3),), (GainArmor(player, 1),))


def set_first(c, amount):
    return ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(set_to=amount), source_id=c.source_id)


def registry():
    r = opening_registry()
    raw = evidence()[NATIVE]
    r.register_behavior('native.cost.exclusion', lambda c: (CheckDeckCondition(c.player_id, CONDITION,
        tuple(GrantKeyword(c.source_id, k, source_id=c.source_id) for k in KEYWORDS)),))
    r.register_card(CardDefinition(NATIVE, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry='native.cost.exclusion', metadata=metadata_from_record(raw)))
    for cid, cost in (('cost.two', 2), ('cost.three', 3), ('cost.four', 4), ('cost.large', 12)):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=cost, attack=2, health=3, metadata=metadata(CardClass.MAGE)))
    r.register_card(CardDefinition('cost.zero', 'Known zero-cost Spell', CardType.SPELL))
    for cid, kind, fields in (
        ('cost.four.spell', CardType.SPELL, {}),
        ('cost.four.weapon', CardType.WEAPON, {'attack': 1, 'durability': 1}),
        ('cost.four.location', CardType.LOCATION, {'durability': 1, 'on_use': 'power'}),
        ('cost.four.no_meta', CardType.MINION, {'health': 3}),
    ):
        r.register_card(CardDefinition(cid, cid, kind, cost=4, **fields))
    first_ref = lambda c: CardReference.capture(c.state.entities[c.state.players[c.player_id].deck[0]])
    native_board = lambda c: next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id == NATIVE)
    r.register_behavior('cost.late.fail', lambda c: (AddToHand(c.player_id, 'unknown.cost.delivery'),))
    scripts = {
        'cost.check': lambda c: (branch(c.player_id),),
        'cost.set.three': lambda c: (set_first(c, 3),),
        'cost.set.four': lambda c: (set_first(c, 4),),
        'cost.set.zero': lambda c: (set_first(c, 0),),
        'cost.reduce': lambda c: (ModifyCost(c.state.players[c.player_id].deck[0], CostSpec(delta=-2), source_id=c.source_id),),
        'cost.external': lambda c: (AddCostModifier(c.player_id, CostSpec(delta=-1), uses_remaining=1),),
        'cost.shuffle': lambda c: (AddToDeck(c.player_id, 'cost.four'),),
        'cost.shuffle.reduced': lambda c: (AddToDeck(c.player_id, 'cost.four', cost=CostSpec(set_to=3)),),
        'cost.draw': lambda c: (Draw(c.player_id),),
        'cost.clear': lambda c: (DestroyDeckMatching(c.player_id, count=30, reveal=False),),
        'cost.face': lambda c: (TransformCapturedMinion(first_ref(c), 'cost.four'),),
        'cost.wait.check': lambda c: (pause(c.player_id), set_first(c, 3), branch(c.player_id)),
        'cost.selected.yes': lambda c: (CheckDeckCondition(c.player_id, CONDITION,
            (pause(c.player_id), set_first(c, 4), GainArmor(c.player_id, 3)), (GainArmor(c.player_id, 1),)),),
        'cost.selected.no': lambda c: (CheckDeckCondition(c.player_id, CONDITION, (GainArmor(c.player_id, 3),),
            (pause(c.player_id), set_first(c, 3), GainArmor(c.player_id, 1))),),
        'cost.fail': lambda c: (branch(c.player_id), InvokeBehavior('cost.late.fail', c.source_id, c.player_id)),
        'cost.wait.fail': lambda c: (pause(c.player_id), branch(c.player_id),
            InvokeBehavior('cost.late.fail', c.source_id, c.player_id)),
        'cost.silence': lambda c: (Silence(native_board(c)),),
        'cost.bounce': lambda c: (ReturnToHand(native_board(c)),),
    }
    for cid, fn in scripts.items():
        r.register_behavior(cid, fn)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata(CardClass.MAGE)))
    return r


class CurrentDeckCostExclusionTests(unittest.TestCase):
    def game(self, hand=(NATIVE,), deck=(), *, other_hand=(), other_deck=(), board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=hand, deck=deck, board=board,
            hero_power_card_id='mage.power', mana=10, max_mana=10), PlayerSetup('warrior.hero',
            hand=other_hand, deck=other_deck, hero_power_card_id='warrior.power', mana=10, max_mana=10)), seed=81), registry())

    def query(self, g, player=1, cost=4):
        return matches_deck_condition(g.state, g.registry, player, DeckCostCondition(cost, 'local'))

    def play(self, g, cid=NATIVE):
        player = g.state.active_player
        identity = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(player, identity))
        return identity

    def native(self, g, player=1):
        return next(g.state.entities[i] for i in g.state.players[player].board if g.state.entities[i].card_id == NATIVE)

    def armor(self, g, player=1):
        return g.state.entities[g.state.players[player].hero_id].armor

    def choose(self, g):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, ('ok',)))

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

    def test_full_raw_pin_and_one_native_complete_printed_definition(self):
        raw = evidence()
        card = registry().card(NATIVE)
        self.assertEqual((card.cost, card.attack, card.health, card.metadata.classes, card.metadata.rarity, card.metadata.tribes),
            (4, 4, 4, (CardClass.NEUTRAL,), Rarity.LEGENDARY, ('undead',)))
        self.assertEqual(card.metadata, metadata_from_record(raw[NATIVE]))
        self.assertEqual(card.keywords, ())
        self.assertIn('no 4-Cost cards', raw[NATIVE]['text_en'])
        self.assertTrue(all(cid not in registry().cards for cid in raw if cid != NATIVE))

    def test_two_three_four_and_zero_large_are_parameterized_independent_values(self):
        g = self.game(deck=('cost.two', 'cost.three', 'cost.four', 'cost.large', 'cost.zero'))
        for cost in (0, 2, 3, 4, 12):
            with self.subTest(cost=cost):
                self.assertFalse(self.query(g, cost=cost))
        for cost in (1, 5, 10, 99):
            with self.subTest(cost=cost):
                self.assertTrue(self.query(g, cost=cost))
        self.check(g)

    def test_empty_current_deck_passes_without_starting_facts(self):
        g = self.game()
        self.assertTrue(self.query(g))
        self.assertIsNone(g.state.opening)
        with self.assertRaises(UnknownDeckFacts):
            matches_deck_condition(g.state, g.registry, 1, DeckCondition('starting'))
        self.check(g)

    def test_all_physical_card_types_count_without_unrelated_class_metadata(self):
        for cid in ('cost.four.spell', 'cost.four.weapon', 'cost.four.location', 'cost.four.no_meta'):
            with self.subTest(card=cid):
                g = self.game(deck=(cid,))
                self.assertFalse(self.query(g))
                self.assertTrue(self.query(g, cost=3))
        g = self.game(deck=('cost.four.no_meta',))
        for declaration in (DeckCondition(), DeckCondition('current', 'no_neutral')):
            with self.assertRaises(UnknownDeckFacts):
                matches_deck_condition(g.state, g.registry, 1, declaration)
        self.check(g)

    def test_known_matching_cost_does_not_hide_later_unknown_definition(self):
        g = self.game(deck=('cost.four', 'cost.three'))
        state = g.state
        state.entities[state.players[1].deck[1]].card_id = 'unknown.cost.face'
        with self.assertRaises(UnsupportedDefinitionError):
            matches_deck_condition(state, g.registry, 1, CONDITION)
        self.check(g)

    def test_deck_cost_is_independent_of_hand_board_and_original_deck(self):
        g = self.game((NATIVE, 'cost.four'), deck=('cost.three',), board=('cost.four',))
        self.assertTrue(self.query(g))
        self.assertTrue(g.state.players[1].hand)
        self.assertTrue(g.state.players[1].board)
        self.check(g)

    def test_query_uses_specified_player_deck(self):
        g = self.game(deck=('cost.three',), other_deck=('cost.four', 'cost.four'))
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))
        g.apply(EndTurn(1))
        self.assertTrue(self.query(g, 1))
        self.assertFalse(self.query(g, 2))
        self.check(g)

    def test_query_is_pure_and_does_not_consume_rng_or_cost_modifiers(self):
        g = self.game(('cost.external',), deck=('cost.four',))
        self.play(g, 'cost.external')
        saved = g.snapshot()
        self.assertFalse(self.query(g))
        self.assertEqual(g.snapshot(), saved)

    def test_real_local_cost_reduction_changes_match_without_printed_face_change(self):
        g = self.game(('cost.set.three',), deck=('cost.four',))
        identity = g.state.players[1].deck[0]
        self.assertFalse(self.query(g))
        self.play(g, 'cost.set.three')
        self.assertTrue(self.query(g))
        self.assertFalse(self.query(g, cost=3))
        self.assertEqual((g.state.entities[identity].card_id, g.registry.card('cost.four').cost), ('cost.four', 4))
        self.assertEqual(local_cost(g.state.entities[identity])[0], 3)
        self.check(g)

    def test_real_local_set_to_excluded_cost_changes_match(self):
        g = self.game(('cost.set.four',), deck=('cost.three',))
        self.assertTrue(self.query(g))
        self.play(g, 'cost.set.four')
        self.assertFalse(self.query(g))
        self.assertEqual(g.registry.card('cost.three').cost, 3)
        self.check(g)

    def test_local_zero_and_delta_follow_original_cost_operations(self):
        for action, target in (('cost.set.zero', 0), ('cost.reduce', 2)):
            with self.subTest(action=action):
                g = self.game((action,), deck=('cost.four',))
                self.play(g, action)
                self.assertTrue(self.query(g))
                self.assertFalse(self.query(g, cost=target))
                self.check(g)

    def test_hand_external_quote_does_not_reprice_deck_local_condition(self):
        g = self.game(('cost.external',), deck=('cost.four',))
        self.play(g, 'cost.external')
        state = g.state
        entity = state.entities[state.players[1].deck[0]]
        self.assertEqual(local_cost(entity)[0], 4)
        self.assertEqual(quote_cost(state, g.registry, entity).amount, 3)
        self.assertFalse(self.query(g))
        self.check(g)

    def test_drawing_last_excluded_cost_recomputes_current_condition(self):
        g = self.game(('cost.draw',), deck=('cost.four', 'cost.three'))
        self.assertFalse(self.query(g))
        identity = g.state.players[1].deck[0]
        self.play(g, 'cost.draw')
        self.assertTrue(self.query(g))
        self.assertIn(identity, g.state.players[1].hand)
        self.check(g)

    def test_added_stored_cost_is_used_on_original_generated_deck_entity(self):
        for action, expected in (('cost.shuffle', False), ('cost.shuffle.reduced', True)):
            with self.subTest(action=action):
                g = self.game((action,))
                self.play(g, action)
                self.assertEqual(self.query(g), expected)
                self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id, 'cost.four')
                self.check(g)

    def test_destroying_remaining_cards_rechecks_without_history_fallback(self):
        g = self.game(('cost.clear',), deck=('cost.four', 'cost.three'))
        self.play(g, 'cost.clear')
        self.assertTrue(self.query(g))
        self.assertEqual(g.state.players[1].deck, [])
        self.check(g)

    def test_normal_minion_face_change_resets_local_cost_on_same_identity(self):
        g = self.game(('cost.face',), deck=('cost.three',))
        identity = g.state.players[1].deck[0]
        self.assertTrue(self.query(g))
        self.play(g, 'cost.face')
        self.assertEqual(g.state.players[1].deck, [identity])
        self.assertFalse(self.query(g))
        self.check(g)

    def test_full_thirty_slot_experimental_constructed_opening_and_restore(self):
        r = registry()
        own = (NATIVE,) + tuple(f'card.{i}' for i in range(1, 30))
        enemy = tuple(f'card.{i}' for i in range(1, 31))
        g = Game.from_decks(MatchSetup((DeckSpec('mage.hero', 'mage.power', CardClass.MAGE, own),
            DeckSpec('warrior.hero', 'warrior.power', CardClass.WARRIOR, enemy)), policy(r), 'coin', 81, 1), r)
        while g.state.pending_choice:
            q = g.state.pending_choice
            g.apply(SelectChoice(q.player_id, q.id, ()))
        self.assertEqual(tuple(map(len, g.state.opening.original_entities)), (30, 30))
        current_ids = [g.state.entities[i].card_id for i in g.state.players[1].deck]
        self.assertEqual(self.query(g), NATIVE not in current_ids)
        self.assertIn(NATIVE, g.state.players[1].original_deck)
        self.check(g)

    def test_native_success_grants_exact_existing_keywords_and_keeps_four_four(self):
        g = self.game(deck=('cost.three',))
        self.play(g)
        native = self.native(g)
        self.assertEqual((native.attack, native.health), (4, 4))
        self.assertEqual(native.keywords, set(KEYWORDS))
        self.assertEqual((g.state.players[1].mana, g.state.play_history[-1].cost), (6, 4))
        self.check(g)

    def test_native_failure_counts_non_minion_four_cost_card(self):
        g = self.game(deck=('cost.four.spell',))
        self.play(g)
        self.assertEqual(self.native(g).keywords, set())
        self.assertEqual(g.state.players[1].mana, 6)
        self.check(g)

    def test_native_reads_changed_local_deck_cost_at_its_battlecry(self):
        g = self.game((NATIVE, 'cost.set.three'), deck=('cost.four',))
        self.play(g, 'cost.set.three')
        self.play(g)
        self.assertEqual(self.native(g).keywords, set(KEYWORDS))
        self.check(g)

    def test_native_second_player_uses_own_current_deck(self):
        g = self.game((), deck=('cost.four',), other_hand=(NATIVE,), other_deck=('cost.three', 'cost.three'))
        g.apply(EndTurn(1))
        self.play(g)
        self.assertEqual(self.native(g, 2).keywords, set(KEYWORDS))
        self.assertEqual(g.state.players[2].mana, 6)
        self.check(g)

    def test_native_player_command_pays_once_and_uses_original_branch(self):
        g = self.game(deck=('cost.three',))
        port = g.for_player(1)
        dto = port.legal_actions()
        card = next(row for row in g.observe(1)['players'][0]['hand'] if row['card_id'] == NATIVE)
        action = next(row for row in dto['actions'] if row.get('card') == card['ref'])
        self.assertTrue(port.submit({'revision': dto['revision'], 'action': action})['accepted'])
        self.assertEqual((g.state.players[1].mana, self.native(g).keywords), (6, set(KEYWORDS)))
        self.check(g)

    def test_later_deck_cost_change_keeps_already_granted_keywords(self):
        g = self.game((NATIVE, 'cost.set.four'), deck=('cost.three',))
        self.play(g)
        self.play(g, 'cost.set.four')
        self.assertFalse(self.query(g))
        self.assertEqual(self.native(g).keywords, set(KEYWORDS))
        self.check(g)

    def test_silence_and_bounce_then_new_play_use_new_deck_condition(self):
        g = self.game((NATIVE, 'cost.silence', 'cost.bounce', 'cost.shuffle', 'cost.shuffle'))
        self.play(g)
        self.play(g, 'cost.silence')
        self.assertEqual(self.native(g).keywords, set())
        self.play(g, 'cost.bounce')
        self.play(g, 'cost.shuffle')
        self.play(g, 'cost.shuffle')
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))
        self.play(g)
        self.assertEqual(self.native(g).keywords, set())
        self.check(g)

    def test_unexecuted_condition_reads_cost_change_after_actual_choice(self):
        g = self.game(('cost.wait.check',), deck=('cost.four',))
        self.play(g, 'cost.wait.check')
        restored = self.check(g)
        self.assertFalse(self.query(g))
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 3)
        self.check(g)

    def test_selected_success_branch_survives_new_excluded_cost(self):
        g = self.game(('cost.selected.yes',), deck=('cost.three',))
        self.play(g, 'cost.selected.yes')
        restored, cloned = self.check(g), g.clone()
        self.choose(g)
        for other in (restored, cloned):
            self.choose(other)
            self.assertEqual(other.snapshot(), g.snapshot())
        self.assertFalse(self.query(g))
        self.assertEqual(self.armor(g), 3)
        self.check(g)

    def test_selected_failure_branch_survives_later_matching_cost_removal(self):
        g = self.game(('cost.selected.no',), deck=('cost.four',))
        self.play(g, 'cost.selected.no')
        restored = self.check(g)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(self.query(g))
        self.assertEqual(self.armor(g), 1)
        self.check(g)

    def test_failed_waiting_continuation_restores_choice_cost_and_effects(self):
        g = self.game(('cost.wait.fail',), deck=('cost.three',))
        self.play(g, 'cost.wait.fail')
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g)
        self.assertEqual(g.snapshot(), saved)
        self.check(g)

    def test_late_failure_rolls_back_entire_original_action(self):
        g = self.game(('cost.fail',), deck=('cost.three',))
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'cost.fail')
        self.assertEqual(g.snapshot(), saved)

    def test_new_typed_three_fields_and_original_typed_two_fields_roundtrip(self):
        g = self.game()
        codec = FrameCodec(g.mechanics, g.registry, origin_state=g.state)
        for declaration, fields in ((CONDITION, {'cost', 'cost_basis', 'scope'}), (DeckCondition(), {'scope', 'predicate'})):
            wire = codec.encode(declaration)
            self.assertEqual(codec.decode(wire), declaration)
            self.assertEqual(set(wire['fields']), fields)
            for field in fields:
                bad = deepcopy(wire)
                del bad['fields'][field]
                with self.assertRaises(ValueError):
                    codec.decode(bad)

    def test_cost_scope_and_basis_are_explicit_strict_and_finite(self):
        for cost in (True, -1, 4.0, '4', None):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                DeckCostCondition(cost, 'local')
        for basis in (None, True, 'printed', 'external', ''):
            with self.subTest(basis=basis), self.assertRaises(ValueError):
                DeckCostCondition(4, basis)
        for scope in ('starting', 'hand', True, None):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                DeckCostCondition(4, 'local', scope)
        with self.assertRaises(TypeError):
            DeckCostCondition(4)
        with self.assertRaises(ValueError):
            DeckCondition('current', 'no_cost')

    def test_pending_restore_rejects_changed_basis_scope_types_and_extra_field(self):
        g = self.game(('cost.wait.check',), deck=('cost.four',))
        self.play(g, 'cost.wait.check')
        for field, value in (('scope', 'starting'), ('cost_basis', 'printed'), ('cost', True), ('cost', -1), ('invented', 1)):
            saved = g.snapshot()
            self.nested(saved['resolution_frame'], 'DeckCostCondition')['fields'][field] = value
            self.reject(saved)
        saved = g.snapshot()
        self.nested(saved['resolution_frame'], 'CheckDeckCondition')['fields']['player_id'] = True
        self.reject(saved)

    def test_player_views_hide_private_cost_condition_and_current_deck_inventory(self):
        g = self.game(('cost.wait.check',), deck=('cost.four.no_meta',))
        self.play(g, 'cost.wait.check')
        for player in (1, 2):
            text = json.dumps(g.observe(player)) + json.dumps(g.player_events(player)) + json.dumps(g.for_player(player).legal_actions())
            for value in ('DeckCostCondition', 'cost_basis', 'on_match', 'on_miss', 'cost.four.no_meta'):
                self.assertNotIn(value, text)
        self.check(g)

    def test_wire_layout_and_previous_payload_shape_remain_while_handler_advances(self):
        g = self.game()
        self.assertEqual((g.snapshot()['schema_version'], g.ruleset.id, g.mechanics.version), (266, 'prototype-v302', CORE_EFFECTS_VERSION))
        saved = g.snapshot()
        saved['mechanics_version']['version'] = 'core-effects-v229'
        self.reject(saved)
        self.check(g)


if __name__ == '__main__':
    unittest.main()
